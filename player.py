"""
player.py - the in-app player (no screen code; see player_ui.py).

Plays one song at a time:
  * play_item(item)  - preview a search result before downloading. The song is
                       found on YouTube Music exactly the way the download
                       would find it, and its audio is streamed, so what you
                       hear is what you would get.
  * play_file(path)  - play a song that was already downloaded.

On Android this uses the phone's own MediaPlayer. Elsewhere (a computer) a
silent stand-in keeps the same behaviour so the screens can be tried out.
"""
import os
import threading
import time


class _Quiet:
    def log(self, *a, **k):
        pass


def _clean(e):
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:160]


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------
class NullBackend:
    """Pretends to play, so the player can be tested without a speaker."""

    def __init__(self):
        self._dur, self._t0, self._pos, self._on = 200.0, 0.0, 0.0, False

    def load(self, source, headers=None, duration=None):
        self._dur = duration or 200.0
        self._pos, self._on = 0.0, False

    def start(self):
        self._t0, self._on = time.time(), True

    def pause(self):
        self._pos, self._on = self.position(), False

    def seek(self, seconds):
        self._pos = max(0.0, min(self._dur, seconds))
        self._t0 = time.time()

    def position(self):
        if self._on:
            return min(self._dur, self._pos + time.time() - self._t0)
        return self._pos

    def duration(self):
        return self._dur

    def finished(self):
        return self._on and self.position() >= self._dur

    def release(self):
        self._on = False


class AndroidBackend:
    """Android's MediaPlayer through pyjnius."""

    def __init__(self):
        from jnius import autoclass
        self._MediaPlayer = autoclass('android.media.MediaPlayer')
        self._autoclass = autoclass
        self.mp = None

    def load(self, source, headers=None, duration=None):
        self.release()
        ac = self._autoclass
        mp = self._MediaPlayer()
        if str(source).startswith('http'):
            ctx = ac('org.kivy.android.PythonActivity').mActivity
            hm = ac('java.util.HashMap')()
            for k, v in (headers or {}).items():
                hm.put(str(k), str(v))
            mp.setDataSource(ctx, ac('android.net.Uri').parse(source), hm)
        else:
            mp.setDataSource(str(source))
        mp.prepare()                    # waits until enough has loaded
        self.mp = mp

    def start(self):
        self.mp.start()

    def pause(self):
        self.mp.pause()

    def seek(self, seconds):
        self.mp.seekTo(int(seconds * 1000))

    def position(self):
        return self.mp.getCurrentPosition() / 1000.0 if self.mp else 0.0

    def duration(self):
        return max(0.0, self.mp.getDuration() / 1000.0) if self.mp else 0.0

    def finished(self):
        try:
            return bool(self.mp) and not self.mp.isPlaying() and \
                self.duration() > 0 and self.position() >= self.duration() - 0.6
        except Exception:
            return False

    def release(self):
        if self.mp is not None:
            try:
                self.mp.release()
            except Exception:
                pass
            self.mp = None


def make_backend():
    if os.environ.get('ANDROID_ARGUMENT') or os.environ.get('ANDROID_PRIVATE'):
        try:
            return AndroidBackend()
        except Exception:
            pass
    return NullBackend()


# --------------------------------------------------------------------------
class Player:
    """state: idle | loading | playing | paused | ended | error"""

    def __init__(self, backend=None):
        self.backend = backend or make_backend()
        self.state = 'idle'
        self.title = self.subtitle = self.error = ''
        self.key = None                 # what is loaded (to light the right button)
        self.duration = 0.0
        self._gen = 0
        self._yt = None

    # ---- starting things -------------------------------------------------------
    def _begin(self, key, title, subtitle):
        self._gen += 1
        try:
            self.backend.release()
        except Exception:
            pass
        self.state, self.key = 'loading', key
        self.title, self.subtitle, self.error = title, subtitle, ''
        self.duration = 0.0
        return self._gen

    def play_item(self, item, key=None):
        """Preview a download item (a YouTube Music track or a Spotify entry)."""
        if key is not None and key == self.key and self.state in (
                'playing', 'paused', 'ended'):
            return self.toggle()
        gen = self._begin(key, item.get('title', ''),
                          'Finding the YouTube Music version...')
        threading.Thread(target=self._run_item, args=(gen, item),
                         daemon=True).start()

    def play_file(self, path, title='', artist='', key=None):
        if key is not None and key == self.key and self.state in (
                'playing', 'paused', 'ended'):
            return self.toggle()
        gen = self._begin(key or path, title or os.path.basename(path),
                          artist or 'Downloaded song')
        threading.Thread(target=self._run_file, args=(gen, path),
                         daemon=True).start()

    def _run_item(self, gen, item):
        try:
            import spotdl_bridge as b
            if self._yt is None:
                from ytmusicapi import YTMusic
                self._yt = YTMusic()
            track, why = b.resolve_item(self._yt, item, _Quiet(), 1)
            if track is None:
                raise RuntimeError(why)
            if gen != self._gen:
                return
            self.title = track['title']
            self.subtitle = (f"{track['artist']}  -  {track['album']}"
                             if track.get('album') else track['artist'])
            url, headers, info = b.stream_url(track['video_id'])
            if gen != self._gen:
                return
            self.backend.load(url, headers, info.get('duration'))
            self._go(gen)
        except Exception as e:
            self._fail(gen, e)

    def _run_file(self, gen, path):
        try:
            if not os.path.exists(path):
                raise RuntimeError('that file is no longer there')
            self.backend.load(path)
            self._go(gen)
        except Exception as e:
            self._fail(gen, e)

    def _go(self, gen):
        if gen != self._gen:
            self.backend.release()
            return
        self.duration = self.backend.duration()
        self.backend.start()
        self.state = 'playing'

    def _fail(self, gen, e):
        if gen == self._gen:
            self.state, self.error = 'error', _clean(e)

    # ---- controls ------------------------------------------------------------------------
    def toggle(self):
        try:
            if self.state == 'playing':
                self.backend.pause()
                self.state = 'paused'
            elif self.state == 'paused':
                self.backend.start()
                self.state = 'playing'
            elif self.state == 'ended':
                self.backend.seek(0)
                self.backend.start()
                self.state = 'playing'
        except Exception as e:
            self.state, self.error = 'error', _clean(e)

    def stop(self):
        self._gen += 1
        try:
            self.backend.release()
        except Exception:
            pass
        self.state, self.key, self.title, self.subtitle = 'idle', None, '', ''

    def seek(self, fraction):
        if self.state in ('playing', 'paused', 'ended') and self.duration:
            try:
                self.backend.seek(max(0.0, min(1.0, fraction)) * self.duration)
                if self.state == 'ended':
                    self.state = 'paused'
            except Exception:
                pass

    # ---- for the screen to read ---------------------------------------------------------
    def position(self):
        if self.state in ('playing', 'paused', 'ended'):
            try:
                return self.backend.position()
            except Exception:
                return 0.0
        return 0.0

    def fraction(self):
        return min(1.0, self.position() / self.duration) if self.duration else 0.0

    def tick(self):
        """Called a few times a second: notices when a song has finished."""
        if self.state == 'playing':
            try:
                if self.backend.finished():
                    self.state = 'ended'
            except Exception:
                pass


_player = None


def get():
    """The one shared player."""
    global _player
    if _player is None:
        _player = Player()
    return _player
