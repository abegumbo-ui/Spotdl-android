"""
search_screen.py - one search bar for everything.

Type words to search Spotify and YouTube Music together, like a normal search
bar: a top result, then Songs, Artists and Albums. Or paste a link (YouTube,
YouTube Music, Spotify) and it shows what the link is before anything is
downloaded. Tap an artist or album to open its page (play, queue, download);
tap a song's text for its card; tick songs and press Download.
"""
import threading

from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import album_page
import artist_page
import browse_ui as B
import player as PL
import search as srch
import ui_kit as K
from browse_ui import NAMES, TAGS, ThumbLoader
from fonts import rich
from player_ui import PlayButton, PlayerBar

TapBox = B.Tap
SONGS_SHOWN, ARTISTS_SHOWN, ALBUMS_SHOWN = 5, 4, 4


def _label(text='', size=13, color=K.TEXT, height=None, **kw):
    return K.text_label(text, size, color, height=height, **kw)


class SourceThumb(ButtonBehavior, FloatLayout):
    """A cover picture with a Spotify / YT Music tag. Tap to choose it."""

    def __init__(self, src, url, available=True, size=58, **kw):
        super().__init__(size_hint=(None, None), size=(dp(size), dp(size)), **kw)
        self.src = src
        self.img = K.Cover(radius=11, size_hint=(1, 1),
                           pos_hint={'x': 0, 'y': 0})
        self.add_widget(self.img)
        name, color = TAGS[src]
        self.tag = K.Chip(name, color, size=8, height=dp(15),
                          pos_hint={'x': 0.04, 'y': 0.04})
        self.tag._col.rgba = (0.02, 0.03, 0.04, 0.78)   # dark pill on the picture
        self.add_widget(self.tag)
        with self.canvas.after:
            self._edge = Color(*K.C(K.ACCENT, 0))
            self._line = Line(rounded_rectangle=(0, 0, 0, 0, dp(11)),
                              width=dp(2))
        self.bind(pos=self._sync, size=self._sync)
        if available:
            ThumbLoader.load(url, self.img)
        else:
            self.opacity = 0.22
            self.disabled = True

    def _sync(self, *a):
        self._line.rounded_rectangle = (self.x, self.y, self.width,
                                        self.height, dp(11))

    def set_chosen(self, chosen):
        self._edge.rgba = K.C(K.ACCENT, 1 if chosen else 0)


def _key(card):
    return (srch.b._norm(card['title']), srch.b._norm(card['artist']))


class SearchScreen(ModalView):
    def __init__(self, on_download, initial='', on_download_link=None,
                 auto=False, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.on_download = on_download
        self.searcher = srch.Searcher()
        self.ctx = B.Ctx(self.searcher, on_download,
                         on_download_link or (lambda link: None))
        self.result = None
        self.link = None                       # what a pasted link turned out to be
        self.song_state = {}                   # song key -> {'selected','choice'}
        self.show_all_songs = False
        self._token = 0
        self._build(initial)
        if auto and initial.strip():
            Clock.schedule_once(lambda dt: self.do_search(), 0.1)

    def on_dismiss(self):
        self.ctx.close_all()
        if len(PL.get().queue) <= 1:      # keep a queue you built playing
            PL.get().stop()

    # ------------------------------------------------------------------ layout
    def _build(self, initial):
        root = BoxLayout(orientation='vertical', padding=(dp(14), dp(14)),
                         spacing=dp(10))
        head = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))
        close = K.IconBtn('close', bg=K.SURFACE, size=48)
        close.bind(on_release=lambda *a: self.dismiss())
        box, self.query = K.make_input('Search, or paste a link', 'search',
                                       on_enter=self.do_search)
        self.query.text = initial
        go = K.Btn('Search', bg=K.ACCENT, fg=K.ON_ACCENT, size_hint=(None, 1),
                   width=dp(88), size=14)
        go.bind(on_release=lambda *a: self.do_search())
        for w in (close, box, go):
            head.add_widget(w)
        root.add_widget(head)
        self.status = _label('Search for a song, an artist or an album, or '
                             'paste a link.', 12, K.MUTED, height=34)
        root.add_widget(self.status)
        self.scroll = ScrollView(bar_width=dp(3))
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                               padding=(0, 0, 0, dp(6)))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)
        root.add_widget(PlayerBar())
        self.btn_go = K.Btn('Download', icon='download', bg=K.ACCENT,
                            fg=K.ON_ACCENT, size=15, size_hint_y=None,
                            height=dp(52), disabled=True)
        self.btn_go.bind(on_release=self._download)
        root.add_widget(self.btn_go)
        self.add_widget(root)

    # ------------------------------------------------------------------ search
    def do_search(self):
        text = self.query.text.strip()
        if not text:
            return
        self._token += 1
        token = self._token
        self.searcher.notes = []
        self.result = self.link = None
        self.show_all_songs = False
        self.grid.clear_widgets()
        self.scroll.scroll_y = 1
        self._count()
        if srch.is_link(text):
            self.status.text = 'Reading the link...'
            self.status.color = K.C(K.MUTED)
            threading.Thread(target=self._link_thread, args=(text, token),
                             daemon=True).start()
        else:
            self.status.text = 'Searching Spotify and YouTube Music...'
            self.status.color = K.C(K.MUTED)
            self.searcher.search_all(text, lambda res: Clock.schedule_once(
                lambda dt, res=res: self._got(res, token)))

    def _link_thread(self, text, token):
        try:
            info, err = srch.link_card(self.searcher, text), ''
        except Exception as e:
            info, err = None, srch.b._clean_error(e)
        Clock.schedule_once(lambda dt: self._got_link(info, err, token))

    def _got_link(self, info, err, token):
        if token != self._token:
            return
        if err:
            self.status.text = rich(err)
            self.status.color = K.C(K.DANGER)
            return
        self.link = info
        self.status.text = 'This link is:'
        self._render()

    def _got(self, result, token):
        if token != self._token:
            return
        self.result = result
        for c in result['songs']:
            self.song_state.setdefault(_key(c), {
                'selected': False,
                'choice': 'ytm' if 'ytm' in c['sources'] else 'sp'})
        total = len(result['songs']) + len(result['artists']) + \
            len(result['albums'])
        notes = ' '.join(result['notes'])
        if not result['done']:
            base = 'Searching...' if not total else \
                f'{total} results so far...'
        else:
            base = f'{total} results.' if total else 'Nothing found.'
        self.status.text = rich((base + ' ' + notes).strip())
        self.status.color = K.C(K.WARN if notes else K.MUTED)
        self._render()

    # ------------------------------------------------------------------ render
    def _render(self):
        y = self.scroll.scroll_y
        g = self.grid
        g.clear_widgets()
        if self.link:
            self._render_link(self.link)
        elif self.result:
            r = self.result
            if r['top']:
                g.add_widget(B.section('Top result'))
                g.add_widget(self._top_card(r['top']))
            songs = r['songs']
            if songs:
                g.add_widget(B.section('Songs', len(songs)))
                for card in (songs if self.show_all_songs
                             else songs[:SONGS_SHOWN]):
                    g.add_widget(self._song_row(card))
                if len(songs) > SONGS_SHOWN and not self.show_all_songs:
                    more = K.Btn(f'Show all {len(songs)} songs', size=12,
                                 size_hint_y=None, height=dp(40))
                    more.bind(on_release=lambda *a: self._more_songs())
                    g.add_widget(more)
            if r['artists']:
                g.add_widget(B.section('Artists', len(r['artists'])))
                for card in r['artists'][:ARTISTS_SHOWN]:
                    g.add_widget(self._artist_row(card))
            if r['albums']:
                g.add_widget(B.section('Albums', len(r['albums'])))
                for card in r['albums'][:ALBUMS_SHOWN]:
                    g.add_widget(self._album_row(card))
        self._count()
        self.scroll.scroll_y = y

    def _more_songs(self):
        self.show_all_songs = True
        self._render()

    # ---- the link card
    def _render_link(self, info):
        g = self.grid
        kind = info['kind']
        if kind == 'song':
            card = info['card']
            self.song_state.setdefault(_key(card), {
                'selected': True, 'choice': next(iter(card['sources']))})
            g.add_widget(self._song_row(card))
        elif kind in ('artist', 'album'):
            g.add_widget(self._top_card(info['card']))
        else:                                  # a playlist
            row = K.Surface(bg=K.SURFACE, radius=18, size_hint_y=None,
                            height=dp(150), padding=dp(14), spacing=dp(14),
                            orientation='vertical')
            top = BoxLayout(size_hint_y=None, height=dp(84), spacing=dp(14))
            cov = K.Cover(radius=14, size_hint=(None, None),
                          size=(dp(84), dp(84)))
            ThumbLoader.load(info.get('thumb'), cov)
            top.add_widget(cov)
            col = BoxLayout(orientation='vertical')
            col.add_widget(_label(rich(info['title']), 16, K.TEXT, bold=True))
            n = info.get('count')
            col.add_widget(_label(
                'Playlist' + (f'  -  {n} songs' if n else ''), 12, K.MUTED))
            top.add_widget(col)
            row.add_widget(top)
            go = K.Btn('Download this playlist', icon='download',
                       bg=K.ACCENT, fg=K.ON_ACCENT, size=14,
                       size_hint_y=None, height=dp(44))
            go.bind(on_release=lambda *a: self._download_link(info['link']))
            row.add_widget(go)
            g.add_widget(row)

    def _download_link(self, link):
        self.dismiss()
        self.ctx.download_link(link)

    # ---- cards
    def _top_card(self, card):
        kind = card['kind']
        src = card['sources'].get('ytm') or card['sources'].get('sp')
        row = B.Tap(size_hint_y=None, height=dp(104))
        surf = K.Surface(bg=K.SURFACE, radius=18, padding=dp(12),
                         spacing=dp(14))
        cov = K.Cover(radius=44 if kind == 'artist' else 14,
                      size_hint=(None, None), size=(dp(80), dp(80)),
                      pos_hint={'center_y': .5})
        ThumbLoader.load(src.get('thumb'), cov)
        surf.add_widget(cov)
        col = BoxLayout(orientation='vertical', spacing=dp(2))
        name = card['name'] if kind == 'artist' else card['title']
        t = _label(rich(name), 17, K.TEXT, bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        col.add_widget(t)
        if kind == 'artist':
            sub = 'Artist  -  tap to open, play or download'
        elif kind == 'album':
            sub = f"{card.get('kind_name') or 'Album'}  -  {card['artist']}"
            if card.get('year'):
                sub += f"  -  {card['year']}"
        else:
            sub = f"Song  -  {card['artist']}"
        col.add_widget(_label(rich(sub), 11.5, K.MUTED))
        surf.add_widget(col)
        surf.add_widget(K.Icon('chev', K.FAINT, pos_hint={'center_y': .5}))
        row.add_widget(surf)
        row.bind(on_release=lambda *a: self._open_card(card))
        return row

    def _open_card(self, card):
        kind = card['kind']
        if kind == 'artist':
            artist_page.ArtistPage(self.ctx, card).open()
        elif kind == 'album':
            src = 'ytm' if 'ytm' in card['sources'] else 'sp'
            album_page.AlbumPage(self.ctx, card['sources'][src]).open()
        else:
            self._open_detail(card)

    def _artist_row(self, card):
        src = card['sources'].get('ytm') or card['sources'].get('sp')
        row = B.Tap(size_hint_y=None, height=dp(62))
        surf = K.Surface(bg=K.SURFACE, radius=14, padding=(dp(12), dp(7)),
                         spacing=dp(12))
        cov = K.Cover(radius=24, size_hint=(None, None), size=(dp(46), dp(46)),
                      pos_hint={'center_y': .5})
        ThumbLoader.load(src.get('thumb'), cov)
        surf.add_widget(cov)
        col = BoxLayout(orientation='vertical')
        col.add_widget(_label(rich(card['name']), 14, K.TEXT, bold=True))
        have = ' + '.join(NAMES[s] for s in ('ytm', 'sp')
                          if s in card['sources'])
        col.add_widget(_label(f'Artist  -  {have}', 11, K.MUTED))
        surf.add_widget(col)
        surf.add_widget(K.Icon('chev', K.FAINT, pos_hint={'center_y': .5}))
        row.add_widget(surf)
        row.bind(on_release=lambda *a: self._open_card(card))
        return row

    def _album_row(self, card):
        src = card['sources'].get('ytm') or card['sources'].get('sp')
        row = B.Tap(size_hint_y=None, height=dp(66))
        surf = K.Surface(bg=K.SURFACE, radius=14, padding=(dp(10), dp(7)),
                         spacing=dp(12))
        cov = K.Cover(radius=10, size_hint=(None, None), size=(dp(50), dp(50)),
                      pos_hint={'center_y': .5})
        ThumbLoader.load(src.get('thumb'), cov)
        surf.add_widget(cov)
        col = BoxLayout(orientation='vertical')
        t = _label(rich(card['title']), 14, K.TEXT, bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        col.add_widget(t)
        sub = '  -  '.join(x for x in (card.get('kind_name'), card['artist'],
                                       card.get('year')) if x)
        col.add_widget(_label(rich(sub), 11, K.MUTED))
        surf.add_widget(col)
        surf.add_widget(K.Icon('chev', K.FAINT, pos_hint={'center_y': .5}))
        row.add_widget(surf)
        row.bind(on_release=lambda *a: self._open_card(card))
        return row

    # ---- songs
    def _song_row(self, card):
        st = self.song_state[_key(card)]
        key = _key(card)
        row = K.Surface(size_hint_y=None, height=dp(86), radius=16,
                        padding=(dp(10), dp(8)), spacing=dp(8))
        check = K.Check(active=st['selected'], pos_hint={'center_y': .5})
        check.bind(active=lambda w, v: self._song_selected(key, v))
        row.add_widget(check)
        thumbs = {}
        for src in ('sp', 'ytm'):
            s = card['sources'].get(src)
            th = SourceThumb(src, s['thumb'] if s else None, bool(s),
                             pos_hint={'center_y': .5})
            th.bind(on_release=lambda w, src=src: self._song_choose(
                card, row, src))
            thumbs[src] = th
            row.add_widget(th)
        row.add_widget(PlayButton(
            ('song', key), lambda: self._play_song(card),
            pos_hint={'center_y': .5}))
        info = B.Tap(orientation='vertical', spacing=dp(1))
        info.bind(on_release=lambda *a: self._open_detail(card))
        title = _label(rich(card['title']), 14, K.TEXT, bold=True)
        title.shorten = True
        title.shorten_from = 'right'
        info.add_widget(title)
        dur = srch._fmt(card['duration'])
        sub = rich(card['artist']) + (f'  -  {dur}' if dur else '')
        info.add_widget(_label(sub, 11.5, K.MUTED))
        chosen = _label('', 10.5, K.ACCENT)
        info.add_widget(chosen)
        row.add_widget(info)
        row._parts = dict(check=check, thumbs=thumbs, chosen=chosen)
        self._paint_song(card, row)
        return row

    def _paint_song(self, card, row):
        st = self.song_state[_key(card)]
        parts = row._parts
        for src, th in parts['thumbs'].items():
            th.set_chosen(src == st['choice'] and len(card['sources']) > 1)
        src = card['sources'][st['choice']]
        album = f" - {src['album']}" if src.get('album') else ''
        parts['chosen'].text = rich(f"Using {NAMES[st['choice']]} cover{album}")
        row.set_bg(K.SURFACE2 if st['selected'] else K.SURFACE)

    def _song_selected(self, key, value):
        self.song_state[key]['selected'] = value
        self._count()

    def _song_choose(self, card, row, src):
        st = self.song_state[_key(card)]
        st['choice'] = src
        self._paint_song(card, row)
        if not row._parts['check'].active:
            row._parts['check'].active = True

    def _open_detail(self, card):
        from song_detail import SongDetail
        key = _key(card)
        st = self.song_state.setdefault(key, {
            'selected': False, 'choice': next(iter(card['sources']))})

        def toggle(v):
            st['selected'] = v
            self._render()
        SongDetail(card, st['choice'], ('song', key), st['selected'], toggle,
                   ThumbLoader).open()

    def _play_song(self, card):
        st = self.song_state[_key(card)]
        PL.get().play_item(card['sources'][st['choice']]['item'],
                           ('song', _key(card)))

    # ------------------------------------------------------------------ download
    def _selected_cards(self):
        cards = []
        if self.link and self.link['kind'] == 'song':
            cards = [self.link['card']]
        elif self.result:
            cards = self.result['songs']
        return [(c, self.song_state[_key(c)]) for c in cards
                if self.song_state.get(_key(c), {}).get('selected')]

    def _count(self):
        n = len(self._selected_cards())
        self.btn_go.disabled = n == 0
        self.btn_go.text = (f"Download {n} song{'s' if n != 1 else ''}"
                            if n else 'Download')

    def _download(self, *a):
        chosen = self._selected_cards()
        if not chosen:
            return
        items = [c['sources'][s['choice']]['item'] for c, s in chosen]
        artists = {c['artist'] for c, s in chosen}
        title = artists.pop() if len(artists) == 1 else 'Selected songs'
        self.dismiss()
        self.on_download(items, title)
