"""browse_ui.py - pieces shared by the search, artist and album pages."""
import io
import threading

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

import player as PL
import ui_kit as K
from fonts import rich
from player_ui import PlayButton
from ui_kit import text_label

TAGS = {'sp': ('Spotify', K.SPOTIFY), 'ytm': ('YT Music', K.YTMUSIC)}
NAMES = {'sp': 'Spotify', 'ytm': 'YouTube Music'}


class ThumbLoader:
    """Downloads cover pictures in the background and puts them on widgets."""
    cache = {}
    gate = threading.Semaphore(4)

    @classmethod
    def load(cls, url, image):
        if not url:
            return
        if url in cls.cache:
            cls._apply(image, cls.cache[url])
            return
        threading.Thread(target=cls._fetch, args=(url, image),
                         daemon=True).start()

    @classmethod
    def _fetch(cls, url, image):
        with cls.gate:
            try:
                import requests
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                data = r.content
            except Exception:
                return
        cls.cache[url] = data
        Clock.schedule_once(lambda dt: cls._apply(image, data))

    @staticmethod
    def _apply(image, data):
        try:
            ext = 'png' if data[:4] == b'\x89PNG' else 'jpg'
            image.texture = CoreImage(io.BytesIO(data), ext=ext).texture
        except Exception:
            pass


class Tap(ButtonBehavior, BoxLayout):
    pass


class Ctx:
    """What the pages share: the searcher, how to start a download, and the
    list of open pages (so Download can close them all)."""

    def __init__(self, searcher, download, download_link):
        self.searcher = searcher
        self.download = download            # (items, title)
        self.download_link = download_link  # (link)
        self.pages = []

    def close_all(self):
        for p in list(self.pages):
            p.dismiss()
        self.pages.clear()


class Page(ModalView):
    """A full-screen page that is closed by Back (or the Android back key)."""

    def __init__(self, ctx, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.ctx = ctx

    def on_open(self):
        self.ctx.pages.append(self)

    def on_dismiss(self):
        if self in self.ctx.pages:
            self.ctx.pages.remove(self)

    def _back(self):
        self.dismiss()


def header(title, on_back, right=None):
    row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
    back = K.IconBtn('back', bg=K.SURFACE, size=44)
    back.bind(on_release=lambda *a: on_back())
    row.add_widget(back)
    lab = text_label(rich(title), 17, K.TEXT, bold=True)
    lab.shorten = True
    lab.shorten_from = 'right'
    row.add_widget(lab)
    if right is not None:
        row.add_widget(right)
    return row


def section(title, count=None):
    t = f'[b]{rich(title)}[/b]'
    if count is not None:
        t += f'  [color={K.MUTED[1:]}]{count}[/color]'
    return text_label(t, 14, K.TEXT, height=30)


def stream_entries(items, tag):
    """Queue entries that stream these items (matched to YouTube Music when
    their turn comes)."""
    return [PL.item_entry(it, (tag, i)) for i, it in enumerate(items)]


def play_items(items, tag, start=0, shuffle=False):
    if not items:
        return
    import random
    pl = PL.get()
    pl.shuffle = shuffle
    if shuffle:
        start = random.randrange(len(items))
    pl.play_entries(stream_entries(items, tag), start)


def queue_items(items, tag):
    pl = PL.get()
    for e in stream_entries(items, tag):
        pl.add(e)


def item_row(item, index, tag, selected, on_toggle, on_play, number=None):
    """One song in an album / top-songs list: tick, title, length, play."""
    row = K.Surface(bg=K.SURFACE, radius=12, size_hint_y=None, height=dp(54),
                    padding=(dp(10), dp(6)), spacing=dp(8))
    check = K.Check(active=selected, size=(dp(24), dp(24)),
                    pos_hint={'center_y': .5})
    check.bind(active=lambda w, v: on_toggle(v))
    row.add_widget(check)
    col = Tap(orientation='vertical')
    col.bind(on_release=lambda *a: setattr(check, 'active', not check.active))
    lead = f'{number}.  ' if number else ''
    t = text_label(lead + rich(item['title']), 13, K.TEXT, bold=True)
    t.shorten = True
    t.shorten_from = 'right'
    col.add_widget(t)
    sub = item.get('artist', '')
    if item.get('album') and not number:
        sub += f"  -  {item['album']}"
    col.add_widget(text_label(rich(sub), 11, K.MUTED))
    row.add_widget(col)
    row.add_widget(text_label(item.get('duration_text') or '', 11, K.FAINT,
                              size_hint_x=None, width=dp(40), halign='right'))
    row.add_widget(PlayButton((tag, index), on_play, size=36,
                              pos_hint={'center_y': .5}))
    return row, check


def play_at(items, tag, i):
    """Play item i with the rest of the list queued after it (same song again
    = pause / resume)."""
    pl = PL.get()
    if pl.key == (tag, i) and pl.state in ('playing', 'paused', 'loading',
                                           'ended'):
        return pl.toggle()
    play_items(items, tag, i)
