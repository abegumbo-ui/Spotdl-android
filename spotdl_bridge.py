"""
spotdl_bridge.py - called from main.py in a background thread.
The `ui` object has a .log(msg, kind) method that routes back to the Kivy UI.

The full `spotdl` package cannot be built for Android (it needs pydantic-core,
fastapi and an ffmpeg binary), so this module reproduces its core workflow
with pure-Python libraries that work on Android:

  * ytmusicapi - find the artist and their albums/singles on YouTube Music
  * yt-dlp     - download the audio stream (no ffmpeg conversion needed)
  * mutagen    - write title/artist/album/track tags and cover art
"""
import os
import re
import traceback

# Formats YouTube serves natively, so no ffmpeg conversion is required.
# format name -> (yt-dlp format selector, file extension)
FORMATS = {
    'm4a': ('bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]', 'm4a'),
    'opus': ('bestaudio[ext=webm]/bestaudio[acodec=opus]', 'webm'),
}

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(text):
    text = _BAD_CHARS.sub('_', str(text or '')).strip().strip('.')
    return text[:120] or 'Unknown'


def _setup_certs():
    # Android has no system CA bundle that Python can see; use certifi's.
    try:
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
    except ImportError:
        pass


def find_artist(yt, query):
    results = yt.search(query, filter='artists', limit=5)
    if not results:
        return None
    for r in results:
        if r.get('artist', '').lower() == query.lower():
            return r
    return results[0]


def collect_tracks(yt, artist_id, log):
    """Return a list of track dicts for every album and single of the artist."""
    artist = yt.get_artist(artist_id)
    releases = []
    for section in ('albums', 'singles'):
        block = artist.get(section) or {}
        items = block.get('results') or []
        if block.get('browseId') and block.get('params'):
            try:
                items = yt.get_artist_albums(block['browseId'], block['params'])
            except Exception as e:
                log(f'Could not load full {section} list ({e}), using preview.',
                    'warning')
        releases.extend(items)

    tracks, seen = [], set()
    for rel in releases:
        browse_id = rel.get('browseId')
        if not browse_id:
            continue
        try:
            album = yt.get_album(browse_id)
        except Exception as e:
            log(f"Skipping release '{rel.get('title')}': {e}", 'warning')
            continue
        thumbs = album.get('thumbnails') or []
        cover = thumbs[-1]['url'] if thumbs else None
        album_title = album.get('title') or rel.get('title') or 'Unknown'
        year = album.get('year') or ''
        album_artist = ', '.join(
            a['name'] for a in album.get('artists') or [] if a.get('name')
        ) or artist.get('name', '')
        for n, t in enumerate(album.get('tracks') or [], 1):
            vid = t.get('videoId')
            if not vid or vid in seen:
                continue
            seen.add(vid)
            tracks.append({
                'video_id': vid,
                'title': t.get('title') or 'Unknown',
                'artist': ', '.join(
                    a['name'] for a in t.get('artists') or [] if a.get('name')
                ) or album_artist,
                'album_artist': album_artist,
                'album': album_title,
                'year': str(year),
                'track_number': t.get('trackNumber') or n,
                'track_total': len(album.get('tracks') or []),
                'cover': cover,
            })
    return tracks


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
    if path.endswith('.m4a'):
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(path)
        audio['\xa9nam'] = track['title']
        audio['\xa9ART'] = track['artist']
        audio['aART'] = track['album_artist']
        audio['\xa9alb'] = track['album']
        if track['year']:
            audio['\xa9day'] = track['year']
        audio['trkn'] = [(int(track['track_number']), int(track['track_total']))]
        if cover_bytes:
            audio['covr'] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
    # .webm (opus) files are left untagged; mutagen cannot write Matroska tags.


def download_artist(artist_query, output_path, audio_format, ui):
    def log(msg, kind='info'):
        ui.log(str(msg), kind)

    try:
        _setup_certs()
        log('Loading libraries...', 'info')
        from ytmusicapi import YTMusic
        import yt_dlp

        selector, ext = FORMATS.get(audio_format, FORMATS['m4a'])
        os.makedirs(output_path, exist_ok=True)
        yt = YTMusic()

        log(f"Searching for artist: '{artist_query}'...", 'info')
        artist = find_artist(yt, artist_query)
        if not artist:
            log(f"No artist found for '{artist_query}'.", 'error')
            return
        artist_name = artist.get('artist') or artist_query
        log(f'Found artist: {artist_name}', 'success')

        log('Collecting albums and singles...', 'info')
        tracks = collect_tracks(yt, artist['browseId'], log)
        if not tracks:
            log(f"No tracks found for '{artist_name}'.", 'error')
            return

        total = len(tracks)
        log(f'Found {total} tracks. Downloading...', 'success')

        covers = {}
        done = skipped = failed = 0
        for i, t in enumerate(tracks, 1):
            if getattr(ui, 'cancel_requested', False):
                log('Cancelled.', 'warning')
                break
            folder = os.path.join(
                output_path, safe_name(t['album_artist']), safe_name(t['album'])
            )
            base = f"{int(t['track_number']):02d} - {safe_name(t['title'])}"
            final = os.path.join(folder, f'{base}.{ext}')
            log(f"[{i}/{total}] {t['artist']} - {t['title']}", 'info')
            if os.path.exists(final):
                skipped += 1
                log('  = already downloaded', 'info')
                continue
            os.makedirs(folder, exist_ok=True)
            opts = {
                'format': selector,
                'outtmpl': os.path.join(folder, base + '.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'noprogress': True,
                'noplaylist': True,
                'retries': 3,
                'logger': _QuietLogger(),
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"https://music.youtube.com/watch?v={t['video_id']}",
                        download=True,
                    )
                    saved = ydl.prepare_filename(info)
                if saved != final and os.path.exists(saved):
                    final = saved
                if t['cover'] not in covers:
                    covers[t['cover']] = _fetch_cover(t['cover'])
                try:
                    tag_file(final, t, covers[t['cover']])
                except Exception as e:
                    log(f'  ! tagging failed: {e}', 'warning')
                done += 1
                log('  + saved', 'success')
            except Exception as e:
                failed += 1
                log(f'  x {e}', 'error')

        log('-' * 30, 'info')
        log(f'Complete: {done} downloaded, {skipped} skipped, {failed} failed.',
            'success')
        log(f'Saved to: {output_path}', 'info')

    except ImportError as e:
        log(f'Import error: {e}', 'error')
        log(traceback.format_exc(), 'error')
    except Exception as e:
        log(f'Error: {e}', 'error')
        log(traceback.format_exc(), 'error')


class _QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass
