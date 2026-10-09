"""
library.py - everything the app knows about the songs already downloaded.

Scans the SpotDL Downloader folder, reads each file's tags (title, artist,
album, track number, length), and keeps the things you build on top of that:
favourites, playlists, recently played and play counts. No Kivy in here.
"""
import json
import os
import threading
import time

EXTS = ('.mp3', '.m4a', '.opus', '.webm', '.ogg', '.flac', '.wav')
SKIP_DIRS = {'Reports'}


def _atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _first(v):
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ''
    return str(v).strip() if v is not None else ''


def read_tags(path):
    """Tag info for one file, with the folder names as a fallback
    (Artist/Album/Title.ext is how the app saves them)."""
    parts = os.path.normpath(path).split(os.sep)
    base = os.path.splitext(parts[-1])[0]
    album = parts[-2] if len(parts) >= 3 else ''
    artist = parts[-3] if len(parts) >= 4 else ''
    out = {'path': path, 'title': base, 'artist': artist, 'album': album,
           'album_artist': artist, 'track': 0, 'disc': 0, 'duration': 0,
           'year': ''}
    try:
        import mutagen
        mf = mutagen.File(path, easy=True)
        if mf is None:
            return out
        if mf.info is not None and getattr(mf.info, 'length', None):
            out['duration'] = int(mf.info.length)
        t = mf.tags or {}
        out['title'] = _first(t.get('title')) or out['title']
        out['artist'] = _first(t.get('artist')) or out['artist']
        out['album'] = _first(t.get('album')) or out['album']
        out['album_artist'] = (_first(t.get('albumartist'))
                               or out['artist'] or out['album_artist'])
        out['year'] = _first(t.get('date'))[:4]
        tn = _first(t.get('tracknumber')).split('/')[0]
        out['track'] = int(tn) if tn.isdigit() else 0
    except Exception:
        pass
    return out


def read_cover(path):
    """Embedded cover picture bytes (or None); falls back to cover.jpg/png in
    the album folder."""
    try:
        import mutagen
        mf = mutagen.File(path)
        tags = getattr(mf, 'tags', None)
        if tags is not None:
            if hasattr(tags, 'getall'):                  # ID3 (mp3)
                pics = tags.getall('APIC')
                if pics:
                    return pics[0].data
            if 'covr' in tags and tags['covr']:          # MP4 (m4a)
                return bytes(tags['covr'][0])
        if hasattr(mf, 'pictures') and mf.pictures:     # flac/ogg
            return mf.pictures[0].data
    except Exception:
        pass
    folder = os.path.dirname(path)
    for n in ('cover.jpg', 'cover.png', 'folder.jpg'):
        p = os.path.join(folder, n)
        if os.path.exists(p):
            try:
                with open(p, 'rb') as f:
                    return f.read()
            except OSError:
                pass
    return None


class Library:
    def __init__(self, root, data_dir):
        self.root, self.dir = root, data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.p_cache = os.path.join(data_dir, 'library_cache.json')
        self.p_user = os.path.join(data_dir, 'library_user.json')
        self.lock = threading.RLock()
        self.songs = []                       # list of tag dicts
        self.scanning = False
        self.version = 0
        user = _load(self.p_user, {})
        self.favorites = set(user.get('favorites', []))
        self.playlists = user.get('playlists', {})     # name -> [path, ...]
        self.recent = user.get('recent', [])           # newest first
        self.plays = user.get('plays', {})             # path -> count
        cache = _load(self.p_cache, {})
        self._cache = cache
        self.songs = [v['tags'] for v in cache.values()
                      if os.path.exists(v['tags']['path'])]
        self.songs.sort(key=self._sort_key)

    # ---- scanning --------------------------------------------------------
    @staticmethod
    def _sort_key(s):
        return (s['artist'].lower(), s['album'].lower(), s['track'] or 999,
                s['title'].lower())

    def scan(self, done=None):
        """Re-read the folder in the background; reuses cached tags for files
        that did not change."""
        if self.scanning:
            return
        self.scanning = True

        def work():
            found, cache = [], {}
            try:
                for d, dirs, files in os.walk(self.root):
                    dirs[:] = [x for x in dirs
                               if not x.startswith('.') and x not in SKIP_DIRS]
                    for f in files:
                        if not f.lower().endswith(EXTS):
                            continue
                        p = os.path.join(d, f)
                        try:
                            st = os.stat(p)
                        except OSError:
                            continue
                        sig = [st.st_mtime, st.st_size]
                        old = self._cache.get(p)
                        if old and old['sig'] == sig:
                            tags = old['tags']
                        else:
                            tags = read_tags(p)
                        cache[p] = {'sig': sig, 'tags': tags}
                        found.append(tags)
                found.sort(key=self._sort_key)
                with self.lock:
                    self._cache, self.songs = cache, found
                    self.version += 1
                try:
                    _atomic(self.p_cache, cache)
                except OSError:
                    pass
            finally:
                self.scanning = False
                if done:
                    done()
        threading.Thread(target=work, daemon=True).start()

    # ---- views ------------------------------------------------------------------
    def by_path(self, path):
        for s in self.songs:
            if s['path'] == path:
                return s
        return None

    def albums(self):
        d = {}
        for s in self.songs:
            d.setdefault((s['album_artist'], s['album']), []).append(s)
        out = [{'album': k[1], 'artist': k[0], 'songs': sorted(
            v, key=lambda s: (s['track'] or 999, s['title'].lower())),
            'year': next((x['year'] for x in v if x['year']), '')}
            for k, v in d.items()]
        out.sort(key=lambda a: (a['artist'].lower(), a['album'].lower()))
        return out

    def artists(self):
        d = {}
        for s in self.songs:
            d.setdefault(s['artist'] or 'Unknown artist', []).append(s)
        return [{'artist': k, 'songs': v}
                for k, v in sorted(d.items(), key=lambda kv: kv[0].lower())]

    def search(self, text, songs=None):
        words = text.lower().split()
        out = []
        for s in (self.songs if songs is None else songs):
            hay = f"{s['title']} {s['artist']} {s['album']}".lower()
            if all(w in hay for w in words):
                out.append(s)
        return out

    def sorted_songs(self, how, songs=None):
        songs = list(self.songs if songs is None else songs)
        if how == 'title':
            songs.sort(key=lambda s: s['title'].lower())
        elif how == 'recent':
            try:
                songs.sort(key=lambda s: -os.path.getmtime(s['path']))
            except OSError:
                pass
        elif how == 'plays':
            songs.sort(key=lambda s: -self.plays.get(s['path'], 0))
        return songs

    def recently_played(self, n=30):
        out = []
        for p in self.recent:
            s = self.by_path(p)
            if s:
                out.append(s)
            if len(out) >= n:
                break
        return out

    def totals(self):
        secs = sum(s['duration'] for s in self.songs)
        return {'songs': len(self.songs), 'albums': len(self.albums()),
                'artists': len(self.artists()), 'seconds': secs}

    # ---- the user's things --------------------------------------------------------
    def _save_user(self):
        try:
            _atomic(self.p_user, {'favorites': sorted(self.favorites),
                                  'playlists': self.playlists,
                                  'recent': self.recent[:200],
                                  'plays': self.plays})
        except OSError:
            pass

    def is_favorite(self, path):
        return path in self.favorites

    def toggle_favorite(self, path):
        if path in self.favorites:
            self.favorites.discard(path)
        else:
            self.favorites.add(path)
        self.version += 1
        self._save_user()
        return path in self.favorites

    def favorite_songs(self):
        return [s for s in self.songs if s['path'] in self.favorites]

    def note_played(self, path):
        self.plays[path] = self.plays.get(path, 0) + 1
        self.recent = [path] + [p for p in self.recent if p != path]
        self._save_user()

    def playlist_songs(self, name):
        out = []
        for p in self.playlists.get(name, []):
            s = self.by_path(p)
            if s:
                out.append(s)
        return out

    def create_playlist(self, name):
        name = name.strip()
        if name and name not in self.playlists:
            self.playlists[name] = []
            self._save_user()
        return name

    def delete_playlist(self, name):
        self.playlists.pop(name, None)
        self._save_user()

    def add_to_playlist(self, name, path):
        lst = self.playlists.setdefault(name, [])
        if path not in lst:
            lst.append(path)
            self._save_user()

    def remove_from_playlist(self, name, path):
        if path in self.playlists.get(name, []):
            self.playlists[name].remove(path)
            self._save_user()

    def delete_song(self, path):
        """Delete a downloaded file from the phone (and forget it)."""
        try:
            os.remove(path)
        except OSError:
            return False
        self.songs = [s for s in self.songs if s['path'] != path]
        self.favorites.discard(path)
        for l in self.playlists.values():
            if path in l:
                l.remove(path)
        self._cache.pop(path, None)
        self.version += 1
        self._save_user()
        return True


def fmt_time(sec):
    sec = int(max(0, sec or 0))
    if sec >= 3600:
        return f'{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}'
    return f'{sec // 60}:{sec % 60:02d}'


def fmt_total(sec):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f'{h} h {m} min' if h else f'{m} min'
