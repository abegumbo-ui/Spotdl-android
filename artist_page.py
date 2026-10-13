"""artist_page.py - a whole artist, like in YouTube Music: Play / Shuffle /
Download all, their top songs, and every album and single (tap one to open it)."""
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView

import album_page
import browse_ui as B
import search as srch
import ui_kit as K
from fonts import rich
from player_ui import PlayerBar
from ui_kit import text_label

TOP_SHOWN = 5


class ArtistPage(B.Page):
    def __init__(self, ctx, card, source=None, **kw):
        super().__init__(ctx, **kw)
        self.card = card
        self.source = source or ('ytm' if 'ytm' in card['sources'] else 'sp')
        self.page = None
        self.top_sel, self.album_sel = set(), set()
        self.show_all_top = False
        self.tag = ('top', self.source, card['sources'][self.source]['id'])
        src = card['sources'][self.source]
        self.busy = False

        root = BoxLayout(orientation='vertical', padding=dp(14),
                         spacing=dp(10))
        other = 'sp' if self.source == 'ytm' else 'ytm'
        right = None
        if other in card['sources']:
            right = K.Btn(f'{B.NAMES[other]}', size=11, radius=12,
                          size_hint=(None, 1), width=dp(112))
            right.bind(on_release=lambda *a: self._switch(other))
        root.add_widget(B.header('Artist', self._back, right))

        top = BoxLayout(size_hint_y=None, height=dp(104), spacing=dp(14))
        self.photo = K.Cover(radius=52, size_hint=(None, None),
                             size=(dp(100), dp(100)))
        B.ThumbLoader.load(src.get('thumb'), self.photo)
        top.add_widget(self.photo)
        col = BoxLayout(orientation='vertical', spacing=dp(2))
        col.add_widget(text_label(rich(card['name']), 20, K.TEXT, bold=True,
                                  valign='bottom'))
        self.meta = text_label(f'From {B.NAMES[self.source]}', 11.5, K.FAINT,
                               height=22)
        col.add_widget(self.meta)
        top.add_widget(col)
        root.add_widget(top)

        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.b_play = K.Btn('Play', icon='play', bg=K.ACCENT, fg=K.ON_ACCENT,
                            size=13, disabled=True)
        self.b_shuf = K.Btn('Shuffle', icon='shuffle', size=13, disabled=True)
        self.b_all = K.Btn('Download all', icon='download', size=13,
                           disabled=True)
        self.b_play.bind(on_release=lambda *a: B.play_items(
            self.page['top'], self.tag))
        self.b_shuf.bind(on_release=lambda *a: B.play_items(
            self.page['top'], self.tag, shuffle=True))
        self.b_all.bind(on_release=lambda *a: self._download(everything=True))
        for w in (self.b_play, self.b_shuf, self.b_all):
            row.add_widget(w)
        root.add_widget(row)

        self.status = text_label('Loading...', 12, K.MUTED, height=22)
        root.add_widget(self.status)
        self.scroll = ScrollView(bar_width=dp(3))
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                               padding=(0, 0, 0, dp(6)))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)
        root.add_widget(PlayerBar())
        self.b_go = K.Btn('Download selected', icon='download', bg=K.ACCENT,
                          fg=K.ON_ACCENT, size=15, size_hint_y=None,
                          height=dp(52), disabled=True)
        self.b_go.bind(on_release=lambda *a: self._download())
        root.add_widget(self.b_go)
        self.add_widget(root)
        threading.Thread(target=self._load, daemon=True).start()

    def _switch(self, other):
        self.dismiss()
        ArtistPage(self.ctx, self.card, other).open()

    # ---- loading
    def _load(self):
        src = self.card['sources'][self.source]
        try:
            page = srch.artist_page(self.ctx.searcher, self.source, src['id'],
                                    self.card['name'])
            err = ''
        except Exception as e:
            page, err = None, srch.b._clean_error(e)
        Clock.schedule_once(lambda dt: self._loaded(page, err))

    def _loaded(self, page, err):
        if page is None:
            self.status.text = rich('Could not load this artist: ' + err)
            self.status.color = K.C(K.DANGER)
            return
        self.page = page
        if page['thumb'] and not self.photo.texture:
            B.ThumbLoader.load(page['thumb'], self.photo)
        n = len(page['albums'])
        self.status.text = (f"{len(page['top'])} top songs  -  {n} "
                            f"album{'s' if n != 1 else ''} and singles")
        self.b_play.disabled = self.b_shuf.disabled = not page['top']
        self.b_all.disabled = not page['albums']
        self._render()

    # ---- drawing
    def _render(self):
        y = self.scroll.scroll_y
        g = self.grid
        g.clear_widgets()
        page = self.page
        if page['top']:
            g.add_widget(B.section('Top songs'))
            shown = page['top'] if self.show_all_top else page['top'][:TOP_SHOWN]
            for i, it in enumerate(shown):
                row, _ = B.item_row(
                    it, i, self.tag, i in self.top_sel,
                    lambda v, i=i: self._tick_top(i, v),
                    lambda i=i: B.play_at(page['top'], self.tag, i))
                g.add_widget(row)
            if len(page['top']) > TOP_SHOWN and not self.show_all_top:
                more = K.Btn(f"Show all {len(page['top'])}", size=12,
                             size_hint_y=None, height=dp(40))
                more.bind(on_release=lambda *a: self._more_top())
                g.add_widget(more)
        if page['albums']:
            g.add_widget(B.section('Albums and singles', len(page['albums'])))
            for k, al in enumerate(page['albums']):
                g.add_widget(self._album_row(k, al))
        self._count()
        self.scroll.scroll_y = y

    def _more_top(self):
        self.show_all_top = True
        self._render()

    def _album_row(self, k, al):
        row = K.Surface(bg=K.SURFACE2 if k in self.album_sel else K.SURFACE,
                        radius=14, size_hint_y=None, height=dp(66),
                        padding=(dp(10), dp(6)), spacing=dp(10))
        check = K.Check(active=k in self.album_sel, size=(dp(24), dp(24)),
                        pos_hint={'center_y': .5})
        check.bind(active=lambda w, v, k=k, row=row: self._tick_album(k, v, row))
        row.add_widget(check)
        cov = K.Cover(radius=10, size_hint=(None, None), size=(dp(50), dp(50)),
                      pos_hint={'center_y': .5})
        B.ThumbLoader.load(al.get('thumb'), cov)
        row.add_widget(cov)
        col = B.Tap(orientation='vertical')
        col.bind(on_release=lambda *a, al=al: self._open_album(al))
        t = text_label(rich(al['title']), 13.5, K.TEXT, bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        col.add_widget(t)
        sub = '  -  '.join(x for x in (al.get('kind'), al.get('year'),
                                       f"{al['total']} songs"
                                       if al.get('total') else '') if x)
        col.add_widget(text_label(rich(sub), 11, K.MUTED))
        row.add_widget(col)
        row.add_widget(K.Icon('chev', K.FAINT, pos_hint={'center_y': .5}))
        return row

    def _open_album(self, al):
        album_page.AlbumPage(self.ctx, al).open()

    # ---- ticks and downloading
    def _tick_top(self, i, v):
        (self.top_sel.add if v else self.top_sel.discard)(i)
        self._count()

    def _tick_album(self, k, v, row):
        (self.album_sel.add if v else self.album_sel.discard)(k)
        row.set_bg(K.SURFACE2 if v else K.SURFACE)
        self._count()

    def _count(self):
        n = len(self.top_sel) + len(self.album_sel)
        self.b_go.disabled = n == 0 or self.busy
        parts = []
        if self.top_sel:
            parts.append(f"{len(self.top_sel)} song"
                         f"{'s' if len(self.top_sel) != 1 else ''}")
        if self.album_sel:
            parts.append(f"{len(self.album_sel)} album"
                         f"{'s' if len(self.album_sel) != 1 else ''}")
        self.b_go.text = ('Download ' + ' + '.join(parts)) if parts \
            else 'Tick songs or albums to download'

    def _download(self, everything=False):
        if self.busy or not self.page:
            return
        self.busy = True
        self.b_go.disabled = self.b_all.disabled = True
        self.b_go.text = 'Preparing...'
        albums = (list(self.page['albums']) if everything
                  else [self.page['albums'][k] for k in sorted(self.album_sel)])
        tops = [] if everything else [self.page['top'][i]
                                      for i in sorted(self.top_sel)]
        threading.Thread(target=self._collect, args=(albums, tops),
                         daemon=True).start()

    def _collect(self, albums, tops):
        items, seen = [], set()
        try:
            for n, al in enumerate(albums, 1):
                Clock.schedule_once(lambda dt, n=n: setattr(
                    self.b_go, 'text', f'Reading album {n} of {len(albums)}...'))
                items += self.ctx.searcher.album_items(al)
            have = {(i.get('video_id'), i['title']) for i in items}
            items += [t for t in tops if (t.get('video_id'), t['title'])
                      not in have]
        except Exception as e:
            Clock.schedule_once(lambda dt: self._failed(srch.b._clean_error(e)))
            return
        name = self.page['name']
        Clock.schedule_once(lambda dt: self._finish(items, name))

    def _failed(self, msg):
        self.busy = False
        self.status.text = rich('Could not prepare the download: ' + msg)
        self.status.color = K.C(K.DANGER)
        self.b_all.disabled = False
        self._count()

    def _finish(self, items, name):
        self.busy = False
        if not items:
            return self._failed('nothing found')
        self.ctx.close_all()
        self.ctx.download(items, name)
