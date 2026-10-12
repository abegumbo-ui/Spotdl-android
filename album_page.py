"""album_page.py - one album: cover, details, Play / Shuffle / Queue, every
song with a tick and a play button, and Download."""
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView

import browse_ui as B
import search as srch
import ui_kit as K
from fonts import rich
from player_ui import PlayerBar
from ui_kit import text_label


class AlbumPage(B.Page):
    def __init__(self, ctx, album, **kw):
        super().__init__(ctx, **kw)
        self.album = album
        self.items = None
        self.sel = set()
        self.tag = ('album', album['source'], album['id'])
        root = BoxLayout(orientation='vertical', padding=dp(14),
                         spacing=dp(10))
        root.add_widget(B.header(album.get('kind') or 'Album', self._back))

        top = BoxLayout(size_hint_y=None, height=dp(124), spacing=dp(14))
        self.cover = K.Cover(radius=16, size_hint=(None, None),
                             size=(dp(124), dp(124)))
        B.ThumbLoader.load(album.get('thumb'), self.cover)
        top.add_widget(self.cover)
        col = BoxLayout(orientation='vertical', spacing=dp(2))
        self.title = text_label(rich(album['title']), 17, K.TEXT, bold=True,
                                valign='top')
        col.add_widget(self.title)
        col.add_widget(text_label(rich(album.get('artist', '')), 13, K.MUTED,
                                  height=22))
        self.meta = text_label(self._meta(), 11.5, K.FAINT, height=20)
        col.add_widget(self.meta)
        top.add_widget(col)
        root.add_widget(top)

        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.b_play = K.Btn('Play', icon='play', bg=K.ACCENT, fg=K.ON_ACCENT,
                            size=13, disabled=True)
        self.b_shuf = K.Btn('Shuffle', icon='shuffle', size=13, disabled=True)
        self.b_queue = K.Btn('Queue', icon='queue', size=13, disabled=True)
        self.b_play.bind(on_release=lambda *a: B.play_items(
            self.items, self.tag))
        self.b_shuf.bind(on_release=lambda *a: B.play_items(
            self.items, self.tag, shuffle=True))
        self.b_queue.bind(on_release=lambda *a: B.queue_items(
            self.items, self.tag))
        for w in (self.b_play, self.b_shuf, self.b_queue):
            row.add_widget(w)
        root.add_widget(row)

        self.status = text_label('Loading songs...', 12, K.MUTED, height=22)
        root.add_widget(self.status)
        self.scroll = ScrollView(bar_width=dp(3))
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                               padding=(0, 0, 0, dp(6)))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)
        root.add_widget(PlayerBar())
        bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.b_all = K.Btn('All', size=13, size_hint_x=.2)
        self.b_none = K.Btn('None', size=13, size_hint_x=.2)
        self.b_go = K.Btn('Download album', icon='download', bg=K.ACCENT,
                          fg=K.ON_ACCENT, size=15, disabled=True)
        self.b_all.bind(on_release=lambda *a: self._select(True))
        self.b_none.bind(on_release=lambda *a: self._select(False))
        self.b_go.bind(on_release=self._download)
        for w in (self.b_all, self.b_none, self.b_go):
            bar.add_widget(w)
        root.add_widget(bar)
        self.add_widget(root)
        threading.Thread(target=self._load, daemon=True).start()

    def _meta(self):
        a = self.album
        bits = [x for x in (a.get('year'),
                            f"{a['total']} songs" if a.get('total') else '')
                if x]
        return '  -  '.join(bits)

    def _load(self):
        try:
            items = self.ctx.searcher.album_items(self.album)
            err = ''
        except Exception as e:
            items, err = [], srch.b._clean_error(e)
        Clock.schedule_once(lambda dt: self._loaded(items, err))

    def _loaded(self, items, err):
        self.items = items
        if err or not items:
            self.status.text = rich('Could not load this album: ' + err
                                    if err else 'No songs found.')
            self.status.color = K.C(K.DANGER)
            return
        total = sum(i.get('duration') or 0 for i in items)
        self.status.text = f'{len(items)} songs  -  {srch._fmt(total)}'
        if items[0].get('cover') and not self.cover.texture:
            B.ThumbLoader.load(items[0]['cover'], self.cover)
        for i, it in enumerate(items):
            row, check = B.item_row(
                it, i, self.tag, False,
                lambda v, i=i: self._ticked(i, v),
                lambda i=i: B.play_at(self.items, self.tag, i),
                number=it.get('track_number') or i + 1)
            self.grid.add_widget(row)
        for b in (self.b_play, self.b_shuf, self.b_queue):
            b.disabled = False
        self._count()

    def _ticked(self, i, v):
        (self.sel.add if v else self.sel.discard)(i)
        self._count()

    def _select(self, v):
        if not self.items:
            return
        for row in self.grid.children:
            for w in row.children:
                if isinstance(w, K.Check):
                    w.active = v
        self.sel = set(range(len(self.items))) if v else set()
        self._count()

    def _count(self):
        n = len(self.sel)
        self.b_go.disabled = not self.items
        self.b_go.text = (f"Download {n} song{'s' if n != 1 else ''}" if n
                          else 'Download album')

    def _download(self, *a):
        if not self.items:
            return
        picked = [self.items[i] for i in sorted(self.sel)] or self.items
        self.ctx.close_all()
        self.ctx.download(picked, self.album['title'])
