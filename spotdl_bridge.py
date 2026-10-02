"""
spotdl_bridge.py - called from main.py in a background thread.

The `ui` object provides:
  ui.log(msg, kind)                 - append a line to the log
  ui.set_status(text)               - the "where am I up to" line
  ui.set_progress(fraction 0..1)    - progress of the current track
  ui.set_overall(done, total)       - progress through the whole link

Supported input:
  * YouTube / YouTube Music links: video, playlist, album, artist/channel
  * Spotify links: track, album, playlist (matched to YouTube Music audio)
  * Anything that is not a link is treated as an artist name to search for

Everything is pure Python (yt-dlp, ytmusicapi, mutagen, requests) because the
real `spotdl` package and ffmpeg cannot be built for Android.
"""
import json
import os
import re
import traceback

# format name -> (yt-dlp format selector, file extension)
FORMATS = {
    'm4a': ('bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]', 'm4a'),
    'opus': ('bestaudio[ext=webm]/bestaudio[acodec=opus]', 'webm'),
}

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_YT_ID = re.compile(r'(?:v=|youtu\.be/|/shorts/)([\w-]{11})')
_SPOTIFY = re.compile(
    r'open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist|artist)/(\w+)')


def safe_name(text):
    text = _BAD_CHARS.sub('_', str(text or '')).strip().strip('.')
    return text[:120] or 'Unknown'


def _setup_certs():
    # Android has no CA bundle Python can see; use certifi's.
    try:
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
    except ImportError:
        pass


class Cancelled(Exception):
    pass


class _QuietLogger:
    def debug(self, msg):
        pass

    info = warning = error = debug


# --------------------------------------------------------------------------
# Building the list of tracks
# --------------------------------------------------------------------------
def _track(video_id, title, artist, album='', album_artist='', year='',
           number=0, total=0, cover=None):
    return {
        'video_id': video_id, 'title': title or 'Unknown',
        'artist': artist or 'Unknown Artist',
        'album_artist': album_artist or artist or 'Unknown Artist',
        'album': album or 'Singles', 'year': str(year or ''),
        'track_number': number or 0, 'track_total': total or 0,
        'cover': cover,
    }


def _names(artists):
    return ', '.join(a['name'] for a in artists or [] if a.get('name'))


def tracks_from_album(yt, browse_id, fallback_artist=''):
    album = yt.get_album(browse_id)
    thumbs = album.get('thumbnails') or []
    cover = thumbs[-1]['url'] if thumbs else None
    album_artist = _names(album.get('artists')) or fallback_artist
    items = album.get('tracks') or []
    out = []
    for n, t in enumerate(items, 1):
        if not t.get('videoId'):
            continue
        out.append(_track(
            t['videoId'], t.get('title'),
            _names(t.get('artists')) or album_artist,
            album.get('title'), album_artist, album.get('year'),
            t.get('trackNumber') or n, len(items), cover))
    return out


def tracks_from_artist(yt, channel_id, log):
    artist = yt.get_artist(channel_id)
    releases = []
    for section in ('albums', 'singles'):
        block = artist.get(section) or {}
        items = block.get('results') or []
        if block.get('browseId') and block.get('params'):
            try:
                items = yt.get_artist_albums(block['browseId'], block['params'])
            except Exception as e:
                log(f'Could not load full {section} list ({e}); using preview.',
                    'warning')
        releases.extend(items)
    tracks, seen = [], set()
    for rel in releases:
        if not rel.get('browseId'):
            continue
        try:
            for t in tracks_from_album(yt, rel['browseId'], artist.get('name')):
                if t['video_id'] not in seen:
                    seen.add(t['video_id'])
                    tracks.append(t)
        except Exception as e:
            log(f"Skipping '{rel.get('title')}': {e}", 'warning')
    return tracks


def tracks_from_artist_name(yt, name, log):
    results = yt.search(name, filter='artists', limit=5)
    if not results:
        return []
    best = next((r for r in results
                 if r.get('artist', '').lower() == name.lower()), results[0])
    log(f"Found artist: {best.get('artist')}", 'success')
    return tracks_from_artist(yt, best['browseId'], log)


def tracks_from_youtube_url(yt, url, log):
    """Playlist / album / video links via ytmusicapi, falling back to yt-dlp."""
    # Album pages: music.youtube.com/browse/MPREb...
    m = re.search(r'/browse/(MPRE[\w-]+)', url)
    if m:
        return tracks_from_album(yt, m.group(1))
    # Artist / channel pages
    m = re.search(r'/(?:channel|browse)/(UC[\w-]{20,})', url)
    if m:
        return tracks_from_artist(yt, m.group(1), log)
    # Playlists (including album playlists, OLAK...)
    m = re.search(r'[?&]list=([\w-]+)', url)
    if m and 'watch?v=' not in url or (m and 'playlist' in url):
        pl = yt.get_playlist(m.group(1), limit=None)
        out = []
        items = pl.get('tracks') or []
        for n, t in enumerate(items, 1):
            if not t.get('videoId'):
                continue
            alb = (t.get('album') or {}).get('name') or pl.get('title')
            thumbs = t.get('thumbnails') or []
            out.append(_track(
                t['videoId'], t.get('title'), _names(t.get('artists')), alb,
                '', pl.get('year'), n, len(items),
                thumbs[-1]['url'] if thumbs else None))
        return out
    # Single video
    m = _YT_ID.search(url)
    if m:
        vid = m.group(1)
        info = yt.get_song(vid).get('videoDetails', {})
        thumbs = (info.get('thumbnail') or {}).get('thumbnails') or []
        return [_track(vid, info.get('title'), info.get('author'),
                       cover=thumbs[-1]['url'] if thumbs else None)]
    return []


def spotify_items(url, log):
    """Read track names from Spotify's public embed page (no login needed)."""
    import requests
    m = _SPOTIFY.search(url)
    if not m:
        return []
    kind, sid = m.groups()
    if kind == 'artist':
        raise ValueError('Spotify artist links are not supported. Paste an '
                         'album, playlist or track link, or type the artist '
                         'name instead.')
    r = requests.get(f'https://open.spotify.com/embed/{kind}/{sid}',
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise ValueError('Could not read this Spotify page.')
    data = json.loads(m.group(1))
    entity = (data.get('props', {}).get('pageProps', {})
              .get('state', {}).get('data', {}).get('entity', {}))
    title = entity.get('name') or entity.get('title') or ''
    if kind == 'track':
        rows = [entity]
    else:
        rows = entity.get('trackList') or []
    out = []
    for row in rows:
        name = row.get('title') or row.get('name')
        artist = row.get('subtitle') or ', '.join(
            a.get('name', '') for a in row.get('artists', []) or [])
        if name:
            out.append({'title': name, 'artist': artist,
                        'album': title if kind == 'album' else ''})
    log(f"Spotify {kind}: {title or sid} ({len(out)} tracks)", 'info')
    return out


def match_spotify_items(yt, items, ui):
    tracks = []
    for i, it in enumerate(items, 1):
        _check_cancel(ui)
        ui.set_status(f'Matching tracks {i}/{len(items)}: {it["title"]}')
        q = f"{it['title']} {it['artist']}".strip()
        try:
            res = yt.search(q, filter='songs', limit=1)
        except Exception as e:
            ui.log(f'  ! search failed for {q}: {e}', 'warning')
            continue
        if not res:
            ui.log(f'  ! no match for {q}', 'warning')
            continue
        r = res[0]
        thumbs = r.get('thumbnails') or []
        alb = (r.get('album') or {}).get('name') or it['album']
        tracks.append(_track(
            r['videoId'], r.get('title') or it['title'],
            _names(r.get('artists')) or it['artist'], alb,
            cover=thumbs[-1]['url'] if thumbs else None))
    return tracks


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------
def _check_cancel(ui):
    if getattr(ui, 'cancel_requested', False):
        raise Cancelled()


def _fetch_cover(url):
    if not url:
        return None
    try:
        import requests
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def tag_file(path, track, cover_bytes):
    if not path.endswith('.m4a'):
        return  # mutagen cannot write Matroska/WebM tags
    from mutagen.mp4 import MP4, MP4Cover
    audio = MP4(path)
    audio['\xa9nam'] = track['title']
    audio['\xa9ART'] = track['artist']
    audio['aART'] = track['album_artist']
    audio['\xa9alb'] = track['album']
    if track['year']:
        audio['\xa9day'] = track['year']
    if track['track_number']:
        audio['trkn'] = [(int(track['track_number']),
                          int(track['track_total'] or 0))]
    if cover_bytes:
        audio['covr'] = [MP4Cover(cover_bytes,
                                  imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def download_tracks(tracks, output_path, audio_format, ui):
    import yt_dlp
    selector, ext = FORMATS.get(audio_format, FORMATS['m4a'])
    total = len(tracks)
    ui.set_overall(0, total)
    covers = {}
    done = skipped = failed = 0

    for i, t in enumerate(tracks, 1):
        _check_cancel(ui)
        label = f"{t['artist']} - {t['title']}"
        ui.set_status(f'Downloading {i}/{total}: {label}')
        ui.set_progress(0)
        ui.log(f'[{i}/{total}] {label}', 'info')

        folder = os.path.join(output_path, safe_name(t['album_artist']),
                              safe_name(t['album']))
        prefix = f"{int(t['track_number']):02d} - " if t['track_number'] else ''
        base = f"{prefix}{safe_name(t['title'])}"
        final = os.path.join(folder, f'{base}.{ext}')
        if os.path.exists(final):
            skipped += 1
            ui.log('  = already downloaded', 'info')
            ui.set_overall(i, total)
            continue
        os.makedirs(folder, exist_ok=True)

        def hook(d):
            _check_cancel(ui)
            if d.get('status') == 'downloading':
                size = d.get('total_bytes') or d.get('total_bytes_estimate')
                if size:
                    ui.set_progress(d.get('downloaded_bytes', 0) / size)
            elif d.get('status') == 'finished':
                ui.set_progress(1)

        opts = {
            'format': selector,
            'outtmpl': os.path.join(folder, base + '.%(ext)s'),
            'quiet': True, 'no_warnings': True, 'noprogress': True,
            'noplaylist': True, 'retries': 3,
            'logger': _QuietLogger(), 'progress_hooks': [hook],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://music.youtube.com/watch?v={t['video_id']}",
                    download=True)
                saved = ydl.prepare_filename(info)
            if os.path.exists(saved):
                final = saved
            if t['cover'] not in covers:
                covers[t['cover']] = _fetch_cover(t['cover'])
            try:
                tag_file(final, t, covers[t['cover']])
            except Exception as e:
                ui.log(f'  ! tagging failed: {e}', 'warning')
            done += 1
            ui.log('  + saved', 'success')
        except Cancelled:
            raise
        except Exception as e:
            failed += 1
            ui.log(f'  x {e}', 'error')
        ui.set_overall(i, total)

    ui.set_status(f'Finished: {done} downloaded, {skipped} skipped, '
                  f'{failed} failed')
    ui.log(f'Complete: {done} downloaded, {skipped} skipped, {failed} failed.',
           'success')
    ui.log(f'Saved to: {output_path}', 'info')


def download(link, output_path, audio_format, ui):
    """Entry point. `link` is a URL, or an artist name."""
    log = ui.log
    try:
        _setup_certs()
        ui.set_status('Starting...')
        from ytmusicapi import YTMusic
        yt = YTMusic()
        os.makedirs(output_path, exist_ok=True)
        link = link.strip()

        if _SPOTIFY.search(link):
            ui.set_status('Reading Spotify link...')
            items = spotify_items(link, log)
            if not items:
                log('No tracks found at that Spotify link.', 'error')
                ui.set_status('No tracks found')
                return
            tracks = match_spotify_items(yt, items, ui)
        elif re.match(r'https?://', link):
            ui.set_status('Reading link...')
            tracks = tracks_from_youtube_url(yt, link, log)
        else:
            ui.set_status(f"Searching for artist '{link}'...")
            tracks = tracks_from_artist_name(yt, link, log)

        if not tracks:
            log('Nothing to download for that link.', 'error')
            ui.set_status('Nothing found')
            return
        log(f'Found {len(tracks)} track(s).', 'success')
        download_tracks(tracks, output_path, audio_format, ui)

    except Cancelled:
        log('Cancelled.', 'warning')
        ui.set_status('Cancelled')
    except Exception as e:
        log(f'Error: {e}', 'error')
        log(traceback.format_exc(), 'error')
        ui.set_status('Failed - see log')
