"""
spotdl_bridge.py - called from main.py in a background thread.

Rules this module follows:
  * Audio only. It never asks for a video stream, and only ever requests
    YouTube Music *song* ids (the audio-track versions), never music videos
    or ordinary YouTube uploads. A pasted video link is converted to its
    YouTube Music audio version, or reported as unavailable.
  * Every track ends up with a status (done / skipped / failed / not found)
    that is shown live in the app and written into a PDF report.

The `ui` object provides (all safe to call from this thread):
  log(msg, kind)  set_status(text)  set_progress(0..1)  set_overall(done, total)
  set_queue(tracks)  set_track_state(index, state, note)
  set_now(track, cover_bytes)  set_report(path)  cancel_requested
"""
import glob
import json
import os
import re
import time
import traceback

# format name -> (yt-dlp format selector, file extension)
# "bestaudio" only ever matches audio-only streams, never video.
FORMATS = {
    'm4a': ('bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]', 'm4a'),
    'opus': ('bestaudio[ext=webm]/bestaudio[acodec=opus]', 'webm'),
    # mp3 is downloaded as m4a, then converted on the phone (see to_mp3)
    'mp3': ('bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio', 'mp3'),
}
MP3_BITRATE = 192000
DURATION_TOLERANCE = 1.5  # seconds; Spotify/YouTube round differently, but a
#                           2s gap means a genuinely different cut
# Each song gets three tries. Every try asks YouTube Music for a fresh download
# address (the old one may have expired or been refused with 403 Forbidden);
# the second try uses a different player route than the first and third.
ATTEMPT_PLANS = [None, ['android_vr'], None]
AUDIO_TRACK = 'MUSIC_VIDEO_TYPE_ATV'  # YouTube Music's "song" (audio) type

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_YT_ID = re.compile(r'(?:v=|youtu\.be/|/shorts/)([\w-]{11})')
_SPOTIFY = re.compile(
    r'open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist|artist)/(\w+)')
_ANSI = re.compile(r'\x1b\[[0-9;]*m')


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


def _clean_error(e):
    msg = _ANSI.sub('', str(e)).strip()
    msg = re.sub(r'^ERROR:\s*(\[[^\]]+\]\s*[\w-]*:?\s*)?', '', msg)
    return (msg.splitlines() or ['unknown error'])[0][:220]


# --------------------------------------------------------------------------
# Covers
# --------------------------------------------------------------------------
def hires(url):
    """Ask the image host for a large square cover instead of a thumbnail."""
    if not url:
        return url
    if ('googleusercontent.com' in url or 'ggpht.com' in url) and '=' in url:
        return url.split('=')[0] + '=w1200-h1200-l90-rj'
    if 'i.scdn.co/image/' in url:
        # Spotify: 64px / 300px variants -> the 640px original
        return re.sub(r'ab67616d0000(?:4851|1e02)', 'ab67616d0000b273', url)
    return url


def image_size(data):
    """(width, height) of a JPEG or PNG, or None."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return (int.from_bytes(data[16:20], 'big'),
                    int.from_bytes(data[20:24], 'big'))
        if data[:2] == b'\xff\xd8':
            i = 2
            while i < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    return (int.from_bytes(data[i + 7:i + 9], 'big'),
                            int.from_bytes(data[i + 5:i + 7], 'big'))
                i += 2 + int.from_bytes(data[i + 2:i + 4], 'big')
    except Exception:
        pass
    return None


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


def _valid_image(data):
    return bool(data) and len(data) > 2000 and (
        data[:2] == b'\xff\xd8' or data[:8] == b'\x89PNG\r\n\x1a\n')


def cover_candidates(t):
    """Cover art sources, best first. The last ones are video-frame thumbnails
    and are only used when nothing better can be fetched."""
    urls = []
    for u in (t.get('cover'), t.get('cover_raw')):
        if u and u not in urls:
            urls.append(u)
    vid = t['video_id']
    urls += [f'https://i.ytimg.com/vi/{vid}/maxresdefault.jpg',
             f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg']
    return urls


def get_cover(t):
    """Fetch the best available cover. Returns (bytes, url, (w, h)) or None."""
    best = None
    for url in cover_candidates(t):
        data = _fetch_cover(url)
        if not _valid_image(data):
            continue
        size = image_size(data) or (0, 0)
        if min(size) >= 500:
            return data, url, size
        if best is None or min(size) > min(best[2]):
            best = (data, url, size)
    return best


# --------------------------------------------------------------------------
# Building the list of tracks
# --------------------------------------------------------------------------
def _track(video_id, title, artist, album='', album_artist='', year='',
           number=0, total=0, cover=None, duration=None, video_type=None):
    return {
        'video_id': video_id, 'title': title or 'Unknown',
        'artist': artist or 'Unknown Artist',
        'album_artist': album_artist or artist or 'Unknown Artist',
        'album': album or 'Singles', 'year': str(year or ''),
        'track_number': number or 0, 'track_total': total or 0,
        'cover': hires(cover), 'cover_raw': cover, 'duration': duration,
        'video_type': video_type,
    }


def _names(artists):
    return ', '.join(a['name'] for a in artists or [] if a.get('name'))


def _norm(text):
    return re.sub(r'[^\w]+', ' ', str(text or '').casefold()).strip()


def _same_title(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a == b or a in b or b in a))


def _thumb(thumbs):
    return thumbs[-1]['url'] if thumbs else None


def tracks_from_album(yt, browse_id, fallback_artist=''):
    album = yt.get_album(browse_id)
    cover = _thumb(album.get('thumbnails') or [])
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
            t.get('trackNumber') or n, len(items), cover,
            t.get('duration_seconds'), t.get('videoType')))
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
    return tracks, artist.get('name') or ''


def tracks_from_artist_name(yt, name, log):
    results = yt.search(name, filter='artists', limit=5)
    if not results:
        return [], name
    best = next((r for r in results
                 if r.get('artist', '').lower() == name.lower()), results[0])
    log(f"Found artist: {best.get('artist')}", 'success')
    return tracks_from_artist(yt, best['browseId'], log)


_album_cover_cache = {}


def album_cover(yt, album):
    """Square album art for a track whose own thumbnail is a video frame."""
    album_id = (album or {}).get('id')
    if not album_id:
        return None
    if album_id not in _album_cover_cache:
        try:
            _album_cover_cache[album_id] = _thumb(
                yt.get_album(album_id).get('thumbnails') or [])
        except Exception:
            _album_cover_cache[album_id] = None
    return _album_cover_cache[album_id]


def _pick_version(results, target):
    """Choose the search result whose length is closest to the original.

    Songs often exist in several cuts (album, single, radio edit, explicit)
    that differ by a couple of seconds. Taking the first search result picks
    the wrong one; matching the duration picks the right one.
    Returns (result, seconds_off); seconds_off is None when length is unknown.
    """
    results = [r for r in results if r.get('videoId')]
    if not results:
        return None, None
    if not target:
        return results[0], None
    known = [r for r in results if r.get('duration_seconds')]
    if not known:
        return results[0], None
    best = min(known, key=lambda r: abs(r['duration_seconds'] - target))
    return best, abs(best['duration_seconds'] - target)


def _song_to_track(yt, r, fallback, cover=None, duration=None):
    album = r.get('album') or {}
    return _track(
        r['videoId'], r.get('title') or fallback['title'],
        _names(r.get('artists')) or fallback['artist'],
        album.get('name') or fallback.get('album', ''),
        cover=cover or album_cover(yt, album) or _thumb(r.get('thumbnails') or []),
        duration=duration or r.get('duration_seconds'), video_type=AUDIO_TRACK)


def find_song(yt, title, artist, duration, require_title=True):
    """Search YouTube Music *songs* only. Returns (result, seconds_off)."""
    res = yt.search(f'{title} {artist}'.strip(), filter='songs', limit=8)
    if require_title:
        res = [r for r in res if _same_title(r.get('title'), title)]
    return _pick_version(res, duration)


def to_audio_track(yt, t):
    """Make sure a track points at a YouTube Music audio track, not a video.

    Returns the track, or None when only a video exists.
    """
    if t.get('video_type') in (None, AUDIO_TRACK):
        return t
    best, off = find_song(yt, t['title'], t['artist'], t.get('duration'))
    if not best or (off is not None and off > DURATION_TOLERANCE):
        return None
    fixed = _song_to_track(yt, best, t, cover=t.get('cover'),
                           duration=t.get('duration'))
    for k in ('album_artist', 'year', 'track_number', 'track_total'):
        if t.get(k) and (k != 'album_artist' or t['album'] == fixed['album']):
            fixed[k] = t[k]
    return fixed


def track_from_video_id(yt, vid):
    """Metadata for one pasted video/song id, converted to its audio track."""
    wp = yt.get_watch_playlist(vid, limit=1)
    item = (wp.get('tracks') or [{}])[0]
    if item.get('videoType') not in (None, AUDIO_TRACK):
        counterpart = item.get('counterpart')
        if counterpart and counterpart.get('videoId'):
            item = counterpart
        else:
            raise ValueError(
                'That link is a video, and no YouTube Music audio version of '
                'it exists, so nothing was downloaded.')
    album = item.get('album') or {}
    length = item.get('length') or ''
    secs = None
    if ':' in length:
        secs = 0
        for part in length.split(':'):
            secs = secs * 60 + int(part)
    return _track(
        item.get('videoId') or vid, item.get('title'),
        _names(item.get('artists')), album.get('name') or '',
        cover=album_cover(yt, album) or _thumb(item.get('thumbnail') or []),
        duration=secs, video_type=AUDIO_TRACK)


def tracks_from_youtube_url(yt, url, log):
    """Playlist / album / video links via ytmusicapi. Returns (tracks, title)."""
    m = re.search(r'/browse/(MPRE[\w-]+)', url)       # album page
    if m:
        tracks = tracks_from_album(yt, m.group(1))
        return tracks, tracks[0]['album'] if tracks else ''
    m = re.search(r'/(?:channel|browse)/(UC[\w-]{20,})', url)   # artist
    if m:
        return tracks_from_artist(yt, m.group(1), log)
    m = re.search(r'[?&]list=([\w-]+)', url)          # playlist / OLAK album
    if m and ('watch?v=' not in url or 'playlist' in url):
        pl = yt.get_playlist(m.group(1), limit=None)
        out = []
        items = pl.get('tracks') or []
        for n, t in enumerate(items, 1):
            if not t.get('videoId'):
                continue
            album = t.get('album') or {}
            out.append(_track(
                t['videoId'], t.get('title'), _names(t.get('artists')),
                album.get('name') or pl.get('title'), '', pl.get('year'),
                n, len(items),
                album_cover(yt, album) or _thumb(t.get('thumbnails') or []),
                t.get('duration_seconds'), t.get('videoType')))
        return out, pl.get('title') or ''
    m = _YT_ID.search(url)                            # single song
    if m:
        t = track_from_video_id(yt, m.group(1))
        return [t], ''
    return [], ''


# --------------------------------------------------------------------------
# Spotify links (read from Spotify's public embed page; no login needed)
# --------------------------------------------------------------------------
def _find_images(node, found):
    if isinstance(node, dict):
        url = node.get('url')
        if isinstance(url, str) and url.startswith('http') and \
                ('scdn.co' in url or 'spotifycdn' in url):
            found.append((node.get('width') or node.get('maxWidth') or 0, url))
        for v in node.values():
            _find_images(v, found)
    elif isinstance(node, list):
        for v in node:
            _find_images(v, found)


def _best_image(node):
    found = []
    _find_images(node, found)
    return max(found)[1] if found else None


def spotify_items(url, log):
    import requests
    m = _SPOTIFY.search(url)
    if not m:
        return [], ''
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
    # An album/track page has one cover for everything on it. A playlist's
    # cover is not the song's cover, so only use per-track images there.
    shared_cover = _best_image(entity) if kind in ('album', 'track') else None
    rows = [entity] if kind == 'track' else (entity.get('trackList') or [])
    out = []
    for position, row in enumerate(rows, 1):
        name = row.get('title') or row.get('name')
        artist = row.get('subtitle') or ', '.join(
            a.get('name', '') for a in row.get('artists', []) or [])
        ms = row.get('duration')
        if name:
            out.append({
                'position': position, 'title': name, 'artist': artist,
                'album': title if kind == 'album' else '',
                'duration': ms / 1000 if isinstance(ms, (int, float)) else None,
                'cover': (_best_image(row) if kind == 'playlist' else None)
                or shared_cover,
            })
    log(f"Spotify {kind}: {title or sid} ({len(out)} tracks)", 'info')
    return out, (title if kind != 'track' else '')


def match_spotify_items(yt, items, ui):
    """Match Spotify tracks to YouTube Music songs. Returns (tracks, missing)."""
    tracks, missing = [], []
    for i, it in enumerate(items, 1):
        _check_cancel(ui)
        ui.set_status(f'Matching tracks {i}/{len(items)}: {it["title"]}')
        try:
            r, off = find_song(yt, it['title'], it['artist'],
                               it.get('duration'), require_title=False)
        except Exception as e:
            missing.append({**it, 'reason': f'search failed: {_clean_error(e)}'})
            continue
        if not r:
            missing.append({**it, 'reason':
                            'no matching song on YouTube Music'})
            ui.log(f"  ! not on YouTube Music: {it['title']}", 'warning')
            continue
        if off is not None and off > DURATION_TOLERANCE:
            ui.log(f"  ! closest version of {it['title']} is {off:.0f}s off",
                   'warning')
        track = _song_to_track(
            yt, r, {'title': it['title'], 'artist': it['artist'],
                    'album': it['album']},
            cover=it.get('cover'), duration=it.get('duration'))
        track['position'] = it.get('position')
        if it['album']:       # an album: keep its real track order and numbers
            track['track_number'] = it['position']
            track['track_total'] = len(items)
        tracks.append(track)
    return tracks, missing


# --------------------------------------------------------------------------
# Tagging and conversion
# --------------------------------------------------------------------------
def _check_cancel(ui):
    if getattr(ui, 'cancel_requested', False):
        raise Cancelled()


def _is_png(data):
    return data[:8] == b'\x89PNG\r\n\x1a\n'


def tag_m4a(path, track, cover_bytes):
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
        fmt = MP4Cover.FORMAT_PNG if _is_png(cover_bytes) else MP4Cover.FORMAT_JPEG
        audio['covr'] = [MP4Cover(cover_bytes, imageformat=fmt)]
    audio.save()


def tag_mp3(path, track, cover_bytes):
    from mutagen.id3 import (ID3, ID3NoHeaderError, TIT2, TPE1, TPE2, TALB,
                             TDRC, TRCK, APIC)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=track['title']))
    tags.add(TPE1(encoding=3, text=track['artist']))
    tags.add(TPE2(encoding=3, text=track['album_artist']))
    tags.add(TALB(encoding=3, text=track['album']))
    if track['year']:
        tags.add(TDRC(encoding=3, text=track['year']))
    if track['track_number']:
        num = str(track['track_number'])
        if track['track_total']:
            num += f"/{track['track_total']}"
        tags.add(TRCK(encoding=3, text=num))
    if cover_bytes:
        mime = 'image/png' if _is_png(cover_bytes) else 'image/jpeg'
        tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover',
                      data=cover_bytes))
    tags.save(path, v2_version=3)


def tag_file(path, track, cover_bytes):
    if path.endswith('.m4a'):
        tag_m4a(path, track, cover_bytes)
    elif path.endswith('.mp3'):
        tag_mp3(path, track, cover_bytes)
    # .webm (opus): mutagen cannot write Matroska/WebM tags.


def _s16_stereo_planes(frame):
    """Convert a decoded audio frame to two s16 byte strings (left, right)
    in pure Python. Used when FFmpeg's resampler filter is unavailable."""
    from array import array
    fmt = frame.format.name
    codes = {'fltp': 'f', 'flt': 'f', 'dblp': 'd', 'dbl': 'd', 's16p': 'h',
             's16': 'h', 's32p': 'i', 's32': 'i'}
    if fmt not in codes:
        raise RuntimeError(f'unsupported sample format {fmt}')
    code = codes[fmt]
    planar = fmt.endswith('p')
    channels = len(frame.layout.channels)
    n = frame.samples
    if planar:
        chans = []
        for i in range(min(channels, 2)):
            arr = array(code)
            arr.frombytes(bytes(frame.planes[i])[:n * arr.itemsize])
            chans.append(arr)
    else:
        arr = array(code)
        arr.frombytes(bytes(frame.planes[0])[:n * channels * arr.itemsize])
        chans = [arr[i::channels] for i in range(min(channels, 2))]
    out = []
    for arr in chans:
        if code == 'h':
            out.append(arr)
        elif code == 'i':
            out.append(array('h', [x >> 16 for x in arr]))
        else:
            lo, hi = -32768, 32767
            out.append(array('h', [lo if v < -1 else hi if v > 1
                                   else int(v * 32767) for v in arr]))
    if len(out) == 1:
        out.append(out[0])
    return out[0].tobytes(), out[1].tobytes()


def _encode_mp3(src, dst, bitrate, use_filters):
    import av
    inp = av.open(src)
    rate = inp.streams.audio[0].rate
    if not use_filters and rate not in (32000, 44100, 48000):
        raise RuntimeError(f'cannot convert {rate} Hz audio without filters')
    rate = rate if rate in (32000, 44100, 48000) else 44100
    out = av.open(dst, 'w', format='mp3')
    stream = None
    for codec in ('libshine', 'libmp3lame'):
        try:
            stream = out.add_stream(codec, rate=rate)
            break
        except Exception:
            continue
    if stream is None:
        raise RuntimeError('this build has no MP3 encoder')
    stream.bit_rate = bitrate
    stream.layout = 'stereo'
    try:
        stream.format = 's16p'
    except Exception:
        pass
    resampler = (av.AudioResampler(format='s16p', layout='stereo', rate=rate)
                 if use_filters else None)
    fifo = av.AudioFifo()
    frame_size = getattr(stream.codec_context, 'frame_size', 0) or 1152

    def encode(frame):
        for packet in stream.encode(frame):
            out.mux(packet)

    def drain(flush=False):
        while fifo.samples >= frame_size or (flush and fifo.samples > 0):
            frame = fifo.read(frame_size if fifo.samples >= frame_size
                              else fifo.samples)
            if frame is None:
                break
            encode(frame)

    for frame in inp.decode(audio=0):
        frame.pts = None
        if use_filters:
            res = resampler.resample(frame)
            frames = res if isinstance(res, list) else [res]
        else:
            left, right = _s16_stereo_planes(frame)
            f = av.AudioFrame(format='s16p', layout='stereo',
                              samples=frame.samples, align=1)
            f.planes[0].update(left)
            f.planes[1].update(right)
            f.sample_rate = rate
            frames = [f]
        for f in frames:
            if f is not None:
                fifo.write(f)
        drain()
    drain(flush=True)
    encode(None)
    out.close()
    inp.close()


def to_mp3(src, dst, bitrate=MP3_BITRATE, use_filters=True):
    """Convert any audio file to MP3 using PyAV (FFmpeg built into the app).

    Tries FFmpeg's resampler first; if the build lacks it ("no filter ..."),
    falls back to converting the samples in plain Python.
    """
    try:
        _encode_mp3(src, dst, bitrate, use_filters)
    except Exception as first:
        if not use_filters:
            raise
        try:
            os.remove(dst)
        except OSError:
            pass
        try:
            _encode_mp3(src, dst, bitrate, False)
        except Exception as second:
            raise RuntimeError(f'MP3 conversion failed: {first}; '
                               f'fallback: {second}')


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------
def download_tracks(tracks, missing, output_path, audio_format, ui):
    """Download every track. Returns a list of result dicts for the report."""
    import yt_dlp
    selector, ext = FORMATS.get(audio_format, FORMATS['m4a'])
    total = len(tracks)
    ui.set_queue(tracks)
    ui.set_overall(0, total)
    covers = {}
    results = []
    claimed = set()

    for i, t in enumerate(tracks):
        _check_cancel(ui)
        n = i + 1
        label = f"{t['artist']} - {t['title']}"
        ui.set_track_state(i, 'active', '')
        ui.set_status(f'Downloading {n}/{total}: {label}')
        ui.set_progress(0)
        ui.log(f'[{n}/{total}] {label}', 'info')

        key = t.get('cover') or t['video_id']
        if key not in covers:
            found = get_cover(t)
            if found and min(found[2]) >= 300:
                covers[key] = found
            else:
                if found:
                    ui.log(f'  ! only a small cover found {found[2][0]}x'
                           f'{found[2][1]}', 'warning')
                else:
                    ui.log('  ! no cover art could be downloaded', 'warning')
                covers[key] = None if not found else found
                if not found:
                    pass
        found = covers[key]
        cover = found[0] if found else None
        if found and found[1] != getattr(ui, '_last_cover', None):
            ui.log(f'  cover art {found[2][0]}x{found[2][1]}', 'info')
            ui._last_cover = found[1]
        ui.set_now(t, cover)

        folder = os.path.join(output_path, safe_name(t['album_artist']),
                              safe_name(t['album']))
        # File names carry no track number: the order lives in the file's own
        # tags, so renaming a file never loses its place in the album.
        base = safe_name(t['title'])
        final = os.path.join(folder, f'{base}.{ext}')
        # Songs saved by earlier versions were named "01 - Title"; count them.
        legacy = (os.path.join(folder, f"{int(t['track_number']):02d} - "
                                       f"{base}.{ext}")
                  if t['track_number'] else None)
        if final in claimed:           # two songs with the same title
            base = f"{base} ({t['track_number'] or n})"
            final = os.path.join(folder, f'{base}.{ext}')
        claimed.add(final)
        if os.path.exists(final) or (legacy and os.path.exists(legacy)):
            results.append({'track': t, 'status': 'skipped',
                            'note': 'already in the folder'})
            ui.set_track_state(i, 'skipped', 'already downloaded')
            ui.log('  = already downloaded', 'info')
            ui.set_overall(n, total)
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

        def fetch(plan):
            """One download attempt. `plan` picks the YouTube player route."""
            opts = {
                'format': selector,
                'outtmpl': os.path.join(folder, base + '.%(ext)s'),
                'quiet': True, 'no_warnings': True, 'noprogress': True,
                'noplaylist': True, 'retries': 3,
                'logger': _QuietLogger(), 'progress_hooks': [hook],
            }
            if plan:
                opts['extractor_args'] = {'youtube': {'player_client': plan}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                # YouTube Music address of the audio track; audio-only format.
                info = ydl.extract_info(
                    f"https://music.youtube.com/watch?v={t['video_id']}",
                    download=True)
                return info, ydl.prepare_filename(info)

        try:
            info = saved = None
            attempts = 0
            for attempt, plan in enumerate(ATTEMPT_PLANS, 1):
                attempts = attempt
                try:
                    info, saved = fetch(plan)
                    break
                except Cancelled:
                    raise
                except Exception as e:
                    reason = _clean_error(e)
                    if attempt == len(ATTEMPT_PLANS):
                        raise RuntimeError(
                            f'{reason} (failed after {attempt} attempts)')
                    ui.log(f'  ! attempt {attempt} of {len(ATTEMPT_PLANS)} '
                           f'failed: {reason} - retrying', 'warning')
                    ui.set_track_state(
                        i, 'active', f'retry {attempt + 1} of '
                        f'{len(ATTEMPT_PLANS)}: {reason}')
                    ui.set_progress(0)
                    # Leftover partial files belong to the old download link.
                    for old in glob.glob(
                            os.path.join(glob.escape(folder),
                                         glob.escape(base) + '.*')):
                        if old != final:
                            try:
                                os.remove(old)
                            except OSError:
                                pass
                    for _ in range(attempt * 4):      # wait 4s, then 8s
                        _check_cancel(ui)
                        time.sleep(0.5)
            note = ''
            if attempts > 1:
                note = f'succeeded on attempt {attempts}'
            got = info.get('duration')
            # A second or two either way is normal (Spotify and YouTube trim
            # silence differently) and is not worth mentioning.
            if t.get('duration') and got and abs(got - t['duration']) > 5:
                note = (note + '; ' if note else '') + (
                    f"length {got:.0f}s vs expected "
                    f"{t['duration']:.0f}s (different version)")
                ui.log(f'  ! {note}', 'warning')
            if ext == 'mp3':
                ui.set_status(f'Converting {n}/{total} to MP3: {label}')
                to_mp3(saved, final)
                os.remove(saved)
            elif os.path.exists(saved):
                final = saved
            if cover:
                # Also leave the cover as a picture in the album folder, so
                # players show it even for formats that cannot embed art.
                ext_img = 'png' if _is_png(cover) else 'jpg'
                side = os.path.join(folder, f'cover.{ext_img}')
                if not os.path.exists(side):
                    with open(side, 'wb') as fh:
                        fh.write(cover)
            try:
                tag_file(final, t, cover)
            except Exception as e:
                note = (note + '; ' if note else '') + f'tagging failed: {e}'
                ui.log(f'  ! tagging failed: {e}', 'warning')
            results.append({'track': t, 'status': 'done', 'note': note,
                            'path': final})
            ui.set_track_state(i, 'done', '')
            ui.log('  + saved', 'success')
        except Cancelled:
            ui.set_track_state(i, 'pending', '')
            raise
        except Exception as e:
            reason = _clean_error(e)
            results.append({'track': t, 'status': 'failed', 'note': reason})
            ui.set_track_state(i, 'failed', reason)
            ui.log(f'  x {reason}', 'error')
        ui.set_overall(n, total)

    ui.set_now(None, None)
    return results


def make_report(title, link, audio_format, results, missing, output_path,
                cover_bytes, ui):
    from report import build_report
    stamp = time.strftime('%Y-%m-%d %H%M')
    folder = os.path.join(output_path, 'Reports')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{safe_name(title)} - {stamp}.pdf')
    build_report(path, title, link, audio_format, results, missing,
                 cover_bytes)
    return path


def download(link, output_path, audio_format, ui):
    """Entry point. `link` is a URL, or an artist name."""
    log = ui.log
    try:
        _setup_certs()
        try:
            import updater
            ui.set_status('Checking for updates...')
            updater.wait()
        except ImportError:
            pass
        ui.set_status('Starting...')
        from ytmusicapi import YTMusic
        yt = YTMusic()
        os.makedirs(output_path, exist_ok=True)
        link = link.strip()
        missing, title = [], ''

        if _SPOTIFY.search(link):
            ui.set_status('Reading Spotify link...')
            items, title = spotify_items(link, log)
            if not items:
                log('No tracks found at that Spotify link.', 'error')
                ui.set_status('No tracks found')
                return
            tracks, missing = match_spotify_items(yt, items, ui)
        elif re.match(r'https?://', link):
            ui.set_status('Reading link...')
            tracks, title = tracks_from_youtube_url(yt, link, log)
        else:
            ui.set_status(f"Searching for artist '{link}'...")
            tracks, title = tracks_from_artist_name(yt, link, log)

        # Never download a music video / ordinary upload: convert to the
        # YouTube Music audio version or report it as unavailable.
        keep = []
        for t in tracks:
            fixed = to_audio_track(yt, t) if t.get('video_type') not in \
                (None, AUDIO_TRACK) else t
            if fixed:
                keep.append(fixed)
            else:
                missing.append({'title': t['title'], 'artist': t['artist'],
                                'reason': 'only a video exists, no YouTube '
                                          'Music audio version'})
        tracks = keep

        if not tracks and not missing:
            log('Nothing to download for that link.', 'error')
            ui.set_status('Nothing found')
            return
        log(f'Found {len(tracks)} song(s)'
            + (f', {len(missing)} not available' if missing else '') + '.',
            'success')

        results = download_tracks(tracks, missing, output_path,
                                  audio_format, ui) if tracks else []

        done = sum(r['status'] == 'done' for r in results)
        skipped = sum(r['status'] == 'skipped' for r in results)
        failed = sum(r['status'] == 'failed' for r in results) + len(missing)
        ui.set_status(f'Finished: {done} downloaded, {skipped} already had, '
                      f'{failed} failed')
        log(f'Complete: {done} downloaded, {skipped} already had, '
            f'{failed} failed.', 'success' if not failed else 'warning')

        if len(tracks) + len(missing) > 1:
            if not title:
                artists = {t['album_artist'] for t in tracks}
                title = artists.pop() if len(artists) == 1 else 'Download'
            first = get_cover(tracks[0]) if tracks else None
            first_cover = first[0] if first else None
            try:
                path = make_report(title, link, audio_format, results, missing,
                                   output_path, first_cover, ui)
                log(f'Report saved: {path}', 'info')
                ui.set_report(path)
            except Exception as e:
                log(f'Could not create the PDF report: {e}', 'warning')

    except Cancelled:
        log('Cancelled.', 'warning')
        ui.set_status('Cancelled')
    except Exception as e:
        log(f'Error: {_clean_error(e)}', 'error')
        log(traceback.format_exc(), 'error')
        ui.set_status('Failed - see log')
