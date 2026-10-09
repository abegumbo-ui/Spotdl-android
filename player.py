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
        try:                            # keep playing with the screen off
            mp.setWakeMode(ac('org.kivy.android.PythonActivity').mActivity, 1)
        except Exception:
            pass
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
def file_entry(path, title='', artist='', album='', duration=0):
    return {'kind': 'file', 'path': path, 'key': ('file', path),
            'title': title or os.path.splitext(os.path.basename(path))[0],
            'artist': artist, 'album': album, 'duration': duration}


def item_entry(item, key=None):
    return {'kind': 'item', 'item': item, 'key': key or ('item', id(item)),
            'title': item.get('title', ''), 'artist': item.get('artist', ''),
            'album': item.get('album', ''),
            'duration': item.get('duration') or 0}


class Player:
    """A queue of songs. state: idle | loading | playing | paused | ended | error

    Songs are either files on the phone or search results (streamed).
    repeat: 'off' | 'all' | 'one'.  Shuffle plays the rest of the queue in a
    random order without losing the order you built.
    """

    def __init__(self, backend=None):
        self.backend = backend or make_backend()
        self.state = 'idle'
        self.title = self.subtitle = self.error = ''
        self.key = None                 # key of the song that is loaded
        self.duration = 0.0
        self.queue = []                 # entries, in the order you built
        self.order = []                 # indexes into queue, in play order
        self.pos = -1                   # position inside `order`
        self.shuffle = False
        self.repeat = 'off'
        self.sleep_at = None            # time.time() when music should stop
        self.version = 0                # bumped whenever the queue changes
        self.on_play = None             # called with a file path when it starts
        self._gen = 0
        self._yt = None
        self._rng = __import__('random').Random()

    # ---- the queue --------------------------------------------------------
    @property
    def current(self):
        if 0 <= self.pos < len(self.order):
            return self.queue[self.order[self.pos]]
        return None

    def _reorder(self, keep_current=True):
        cur = self.order[self.pos] if 0 <= self.pos < len(self.order) else None
        self.order = list(range(len(self.queue)))
        if self.shuffle:
            self._rng.shuffle(self.order)
            if cur is not None:
                self.order.remove(cur)
                self.order.insert(0, cur)
        self.pos = self.order.index(cur) if cur is not None else -1
        self.version += 1

    def play_entries(self, entries, start=0):
        """Replace the queue and start playing entries[start]."""
        self.queue = list(entries)
        self.order = list(range(len(self.queue)))
        self.pos = start
        if self.shuffle and self.queue:
            self._rng.shuffle(self.order)
            self.order.remove(start)
            self.order.insert(0, start)
            self.pos = 0
        self.version += 1
        self._start_current()

    def add(self, entry, next_up=False):
        """Add a song to the end of the queue, or right after the current one."""
        if not self.queue or self.state == 'idle':
            return self.play_entries([entry])
        self.queue.append(entry)
        n = len(self.queue) - 1
        if next_up:
            self.order.insert(self.pos + 1, n)
        else:
            self.order.append(n)
        self.version += 1

    def remove_at(self, order_pos):
        if not 0 <= order_pos < len(self.order) or order_pos == self.pos:
            return
        qi = self.order.pop(order_pos)
        self.queue.pop(qi)
        self.order = [i - 1 if i > qi else i for i in self.order]
        if order_pos < self.pos:
            self.pos -= 1
        self.version += 1

    def jump(self, order_pos):
        if 0 <= order_pos < len(self.order):
            self.pos = order_pos
            self._start_current()

    def clear_upcoming(self):
        keep = self.order[:self.pos + 1]
        self.queue = [self.queue[i] for i in keep]
        self.order = list(range(len(self.queue)))
        self.pos = len(self.queue) - 1
        self.version += 1

    def upcoming(self):
        return [(p, self.queue[self.order[p]])
                for p in range(self.pos + 1, len(self.order))]

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self._reorder()

    def cycle_repeat(self):
        self.repeat = {'off': 'all', 'all': 'one', 'one': 'off'}[self.repeat]

    def next(self, auto=False):
        if not self.order:
            return
        if auto and self.repeat == 'one':
            return self._start_current()
        if self.pos + 1 < len(self.order):
            self.pos += 1
        elif self.repeat == 'all':
            self.pos = 0
            if self.shuffle:
                self._reorder_keep_first_random()
        else:
            if auto:
                self.state = 'ended'
            return
        self._start_current()

    def _reorder_keep_first_random(self):
        self._rng.shuffle(self.order)

    def previous(self):
        """Restart the song if it has played a few seconds, else go back."""
        if self.position() > 3 or self.pos <= 0:
            if self.state != 'idle':
                self.seek(0)
                if self.state in ('paused', 'ended'):
                    self.toggle()
            return
        self.pos -= 1
        self._start_current()

    # ---- starting things ----------------------------------------------------------
    def _begin(self, entry):
        self._gen += 1
        try:
            self.backend.release()
        except Exception:
            pass
        self.state, self.key = 'loading', entry.get('key')
        self.title = entry.get('title', '')
        self.subtitle = (entry.get('artist', '') if entry['kind'] == 'file'
                         else 'Finding the YouTube Music version...')
        self.error = ''
        self.duration = float(entry.get('duration') or 0)
        return self._gen

    def _start_current(self):
        entry = self.current
        if entry is None:
            return
        gen = self._begin(entry)
        target = self._run_item if entry['kind'] == 'item' else self._run_file
        threading.Thread(target=target, args=(gen, entry), daemon=True).start()

    def play_item(self, item, key=None):
        """Preview one search result (same button again = pause/resume)."""
        if key is not None and key == self.key and self.state in (
                'playing', 'paused', 'ended', 'loading'):
            return self.toggle()
        self.play_entries([item_entry(item, key)])

    def play_file(self, path, title='', artist='', key=None):
        if key is not None and key == self.key and self.state in (
                'playing', 'paused', 'ended', 'loading'):
            return self.toggle()
        e = file_entry(path, title, artist)
        if key is not None:
            e['key'] = key
        self.play_entries([e])

    def _run_item(self, gen, entry):
        try:
            import spotdl_bridge as b
            if self._yt is None:
                from ytmusicapi import YTMusic
                self._yt = YTMusic()
            track, why = b.resolve_item(self._yt, entry['item'], _Quiet(), 1)
            if track is None:
                raise RuntimeError(why)
            if gen != self._gen:
                return
            self.title = track['title']
            self.subtitle = (f"{track['artist']}  -  {track['album']}"
                             if track.get('album') else track['artist'])
            entry['matched'] = {k: track.get(k) for k in
                                ('title', 'artist', 'album', 'cover')}
            url, headers, info = b.stream_url(track['video_id'])
            if gen != self._gen:
                return
            self.backend.load(url, headers, info.get('duration'))
            self._go(gen)
        except Exception as e:
            self._fail(gen, e)

    def _run_file(self, gen, entry):
        try:
            path = entry['path']
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
        self.duration = self.backend.duration() or self.duration
        self.backend.start()
        self.state = 'playing'
        e = self.current
        if self.on_play and e and e['kind'] == 'file':
            try:
                self.on_play(e['path'])
            except Exception:
                pass

    def _fail(self, gen, e):
        if gen == self._gen:
            self.state, self.error = 'error', _clean(e)
            self._skip_at = time.time() + 2.5      # move on after a moment

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
            elif self.state == 'error':
                self._start_current()
        except Exception as e:
            self.state, self.error = 'error', _clean(e)

    def stop(self):
        self._gen += 1
        try:
            self.backend.release()
        except Exception:
            pass
        self.state, self.key, self.title, self.subtitle = 'idle', None, '', ''
        self.queue, self.order, self.pos = [], [], -1
        self.sleep_at = None
        self.version += 1

    def seek(self, fraction):
        if self.state in ('playing', 'paused', 'ended') and self.duration:
            try:
                self.backend.seek(max(0.0, min(1.0, fraction)) * self.duration)
                if self.state == 'ended':
                    self.state = 'paused'
            except Exception:
                pass

    def set_sleep(self, minutes):
        self.sleep_at = time.time() + minutes * 60 if minutes else None

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
        """Called a few times a second: moves to the next song, honours the
        sleep timer."""
        if self.sleep_at and time.time() >= self.sleep_at:
            self.sleep_at = None
            if self.state == 'playing':
                self.toggle()
        if self.state == 'playing':
            try:
                if self.backend.finished():
                    self.state = 'ended'
            except Exception:
                pass
        if self.state == 'ended' and self.order:
            self.next(auto=True)
        elif self.state == 'error' and getattr(self, '_skip_at', 0) and \
                time.time() >= self._skip_at and self.pos + 1 < len(self.order):
            self._skip_at = 0
            self.next()


_player = None


def get():
    """The one shared player."""
    global _player
    if _player is None:
        _player = Player()
    return _player
