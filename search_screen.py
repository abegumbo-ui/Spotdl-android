"""
search_screen.py - the search screen.

Type a song or an artist. Songs found on Spotify and YouTube Music are shown
as one card with both covers: tap a cover to choose whose title, album and
cover art to use (the audio always comes from YouTube Music), tick the songs
you want, press Download. Artists open into their albums; expand an album to
pick individual songs, or tick whole albums.
"""
import io
import threading

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import escape_markup

import search as srch

GREEN = (0.11, 0.73, 0.33, 1)
RED = (1.0, 0.25, 0.3, 1)
TAGS = {'sp': ('Spotify', GREEN), 'ytm': ('YT Music', RED)}
NAMES = {'sp': 'Spotify', 'ytm': 'YouTube Music'}


def _label(text='', size=13, color=(0.9, 0.9, 0.9, 1), height=None, **kw):
    lbl = Label(text=text, font_size=sp(size), color=color, markup=True,
                halign='left', valign='middle', **kw)
    if height:
        lbl.size_hint_y = None
        lbl.height = dp(height)
    lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], s[1])))
    return lbl


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


class SourceThumb(ButtonBehavior, FloatLayout):
    """A cover picture with a Spotify / YT Music tag. Tap to choose it."""

    def __init__(self, src, url, available=True, size=60, **kw):
        super().__init__(size_hint=(None, None), size=(dp(size), dp(size)), **kw)
        self.src = src
        self.img = Image(size_hint=(1, 1), pos_hint={'x': 0, 'y': 0},
                         allow_stretch=True, keep_ratio=True)
        self.add_widget(self.img)
        name, color = TAGS[src]
        self.tag = Label(text=name, font_size=sp(8), bold=True,
                         size_hint=(1, None), height=dp(13),
                         pos_hint={'x': 0, 'y': 0}, color=(0, 0, 0, 1))
        with self.tag.canvas.before:
            Color(*color)
            self._bg = Rectangle()
        with self.canvas.after:
            self._edge = Color(1, 1, 1, 0)
            self._line = Line(rectangle=(0, 0, 0, 0), width=dp(2))
        self.add_widget(self.tag)
        self.bind(pos=self._sync, size=self._sync)
        self.tag.bind(pos=self._sync, size=self._sync)
        if available:
            ThumbLoader.load(url, self.img)
        else:
            self.opacity = 0.2
            self.disabled = True

    def _sync(self, *a):
        self._bg.pos, self._bg.size = self.tag.pos, self.tag.size
        self._line.rectangle = (self.x, self.y, self.width, self.height)

    def set_chosen(self, chosen):
        self._edge.rgba = (1, 1, 1, 1) if chosen else (1, 1, 1, 0)


class TapBox(ButtonBehavior, BoxLayout):
    pass


class SearchScreen(ModalView):
    def __init__(self, on_download, initial='', **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=(0.05, 0.05, 0.05, 1), **kw)
        self.on_download = on_download
        self.searcher = srch.Searcher()
        self.tab = 'songs'
        self.mode = 'results'                 # or 'artist'
        self.cards = {'songs': [], 'artists': []}
        self.song_state = []
        self.artist = None
        self._token = 0                       # ignore stale search results
        self._busy = False
        self._build(initial)

    # ------------------------------------------------------------------ layout
    def _build(self, initial):
        root = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(8))
        self.header = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        root.add_widget(self.header)
        self.tabs = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        self.tab_songs = ToggleButton(text='Songs', group='stab', state='down',
                                      allow_no_selection=False)
        self.tab_artists = ToggleButton(text='Artists', group='stab',
                                        allow_no_selection=False)
        for t in (self.tab_songs, self.tab_artists):
            t.background_normal = t.background_down = ''
            t.bind(state=self._tab_style)
            self._tab_style(t, t.state)
            self.tabs.add_widget(t)
        self.tab_songs.bind(on_press=lambda *a: self._set_tab('songs'))
        self.tab_artists.bind(on_press=lambda *a: self._set_tab('artists'))
        root.add_widget(self.tabs)
        self.status = _label('Search for a song or an artist.', 12,
                             (0.6, 0.6, 0.6, 1), height=34)
        root.add_widget(self.status)
        self.scroll = ScrollView()
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.btn_all = Button(text='All', size_hint_x=0.2,
                              background_color=(0.2, 0.2, 0.2, 1))
        self.btn_none = Button(text='None', size_hint_x=0.2,
                               background_color=(0.2, 0.2, 0.2, 1))
        self.btn_go = Button(text='Download', bold=True, background_normal='',
                             background_color=GREEN, color=(0, 0, 0, 1),
                             disabled=True)
        self.btn_all.bind(on_press=lambda *a: self._select_all(True))
        self.btn_none.bind(on_press=lambda *a: self._select_all(False))
        self.btn_go.bind(on_press=self._download)
        for w in (self.btn_all, self.btn_none, self.btn_go):
            bar.add_widget(w)
        root.add_widget(bar)
        self.add_widget(root)
        self._results_header(initial)

    @staticmethod
    def _tab_style(tab, state):
        tab.background_color = GREEN if state == 'down' else (0.2, 0.2, 0.2, 1)
        tab.color = (0, 0, 0, 1) if state == 'down' else (0.8, 0.8, 0.8, 1)

    def _results_header(self, text=''):
        self.mode = 'results'
        self.header.clear_widgets()
        close = Button(text='Close', size_hint_x=0.22,
                       background_color=(0.25, 0.25, 0.25, 1))
        close.bind(on_press=lambda *a: self.dismiss())
        self.query = TextInput(text=text, hint_text='Song or artist',
                               multiline=False, font_size=sp(15),
                               background_color=(0.12, 0.12, 0.12, 1),
                               foreground_color=(0.95, 0.95, 0.95, 1),
                               hint_text_color=(0.45, 0.45, 0.45, 1),
                               cursor_color=GREEN, padding=(dp(10), dp(12)))
        self.query.bind(on_text_validate=lambda *a: self.do_search())
        go = Button(text='Search', size_hint_x=0.25, bold=True,
                    background_normal='', background_color=GREEN,
                    color=(0, 0, 0, 1))
        go.bind(on_press=lambda *a: self.do_search())
        for w in (close, self.query, go):
            self.header.add_widget(w)
        self.tabs.height = dp(38)
        self.tabs.opacity = 1

    def _artist_header(self):
        self.mode = 'artist'
        self.header.clear_widgets()
        back = Button(text='< Back', size_hint_x=0.25,
                      background_color=(0.25, 0.25, 0.25, 1))
        back.bind(on_press=lambda *a: self._back_to_results())
        name = _label(f"[b]{escape_markup(self.artist['name'])}[/b]\n"
                      f"[size=11sp][color=999999]from {NAMES[self.artist['source']]}"
                      f"[/color][/size]", 15)
        self.header.add_widget(back)
        self.header.add_widget(name)
        other = 'sp' if self.artist['source'] == 'ytm' else 'ytm'
        if other in self.artist['card']['sources']:
            sw = Button(text=f'Use {NAMES[other]}', size_hint_x=0.35,
                        font_size=sp(12), background_color=(0.2, 0.2, 0.2, 1))
            sw.bind(on_press=lambda *a: self.open_artist(self.artist['card'],
                                                         other))
            self.header.add_widget(sw)
        self.tabs.height = 0
        self.tabs.opacity = 0

    # ------------------------------------------------------------------ search
    def do_search(self):
        query = self.query.text.strip()
        if not query:
            return
        self._token += 1
        token = self._token
        self.searcher.notes = []
        self.grid.clear_widgets()
        self.song_state = []
        self.status.text = 'Searching Spotify and YouTube Music...'
        self._update_count()
        threading.Thread(target=self._search_thread, args=(query, token),
                         daemon=True).start()

    def _search_thread(self, query, token):
        songs = self.searcher.search_songs(query)
        Clock.schedule_once(lambda dt: self._got('songs', songs, token))
        artists = self.searcher.search_artists(query)
        Clock.schedule_once(lambda dt: self._got('artists', artists, token))

    def _got(self, which, cards, token):
        if token != self._token:
            return
        self.cards[which] = cards
        if which == 'songs':
            self.song_state = [
                {'selected': False,
                 'choice': 'ytm' if 'ytm' in c['sources'] else 'sp'}
                for c in cards]
        if which == self.tab and self.mode == 'results':
            self._render()
        self._note()

    def _note(self):
        notes = ' '.join(dict.fromkeys(self.searcher.notes))
        n = len(self.cards[self.tab])
        word = 'songs' if self.tab == 'songs' else 'artists'
        base = f'{n} {word} found.' if n else f'No {word} found.'
        self.status.text = (base + ' ' + notes).strip()
        self.status.color = (1, 0.6, 0.2, 1) if notes else (0.6, 0.6, 0.6, 1)

    def _set_tab(self, tab):
        self.tab = tab
        if self.mode == 'results':
            self._render()
            self._note()

    # ------------------------------------------------------------------ render
    def _render(self):
        self.grid.clear_widgets()
        if self.tab == 'songs':
            for i, card in enumerate(self.cards['songs']):
                self.grid.add_widget(self._song_row(i, card))
        else:
            for card in self.cards['artists']:
                self.grid.add_widget(self._artist_row(card))
        self.scroll.scroll_y = 1
        self._update_count()

    def _song_row(self, idx, card):
        st = self.song_state[idx]
        row = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(6))
        check = CheckBox(size_hint_x=None, width=dp(34), active=st['selected'])
        check.bind(active=lambda w, v: self._song_selected(idx, v))
        row.add_widget(check)
        thumbs = {}
        for src in ('sp', 'ytm'):
            s = card['sources'].get(src)
            th = SourceThumb(src, s['thumb'] if s else None, bool(s))
            th.bind(on_release=lambda w, src=src: self._song_choose(idx, src))
            thumbs[src] = th
            row.add_widget(th)
        info = TapBox(orientation='vertical')
        info.bind(on_release=lambda *a: setattr(check, 'active', not check.active))
        info.add_widget(_label(f"[b]{escape_markup(card['title'])}[/b]", 14))
        dur = srch._fmt(card['duration'])
        sub = escape_markup(card['artist']) + (f'  -  {dur}' if dur else '')
        info.add_widget(_label(sub, 12, (0.7, 0.7, 0.7, 1)))
        chosen = _label('', 11, (0.5, 0.8, 0.5, 1))
        info.add_widget(chosen)
        row.add_widget(info)
        st.update(check=check, thumbs=thumbs, chosen=chosen)
        self._paint_song(idx)
        return row

    def _paint_song(self, idx):
        st, card = self.song_state[idx], self.cards['songs'][idx]
        for src, th in st['thumbs'].items():
            th.set_chosen(src == st['choice'] and len(card['sources']) > 1)
        src = card['sources'][st['choice']]
        album = f" - {src['album']}" if src.get('album') else ''
        st['chosen'].text = escape_markup(
            f"Using {NAMES[st['choice']]} cover{album}")

    def _song_selected(self, idx, value):
        self.song_state[idx]['selected'] = value
        self._update_count()

    def _song_choose(self, idx, src):
        st = self.song_state[idx]
        st['choice'] = src
        self._paint_song(idx)
        if not st['check'].active:
            st['check'].active = True

    def _artist_row(self, card):
        row = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(8))
        for src in ('sp', 'ytm'):
            s = card['sources'].get(src)
            th = SourceThumb(src, s['thumb'] if s else None, bool(s))
            th.bind(on_release=lambda w, src=src, c=card: self.open_artist(c, src))
            row.add_widget(th)
        avail = ' / '.join(NAMES[s] for s in ('sp', 'ytm') if s in card['sources'])
        info = _label(f"[b]{escape_markup(card['name'])}[/b]\n"
                      f"[size=11sp][color=999999]Tap a cover to open their "
                      f"songs ({avail})[/color][/size]", 14)
        row.add_widget(info)
        return row

    # ------------------------------------------------------------------ artist
    def open_artist(self, card, src):
        ref = card['sources'][src]
        self._token += 1
        token = self._token
        self.artist = {'name': card['name'], 'card': card, 'source': src,
                       'id': ref['id'], 'albums': []}
        self._artist_header()
        self.grid.clear_widgets()
        self.status.text = f"Loading {card['name']} from {NAMES[src]}..."
        self.status.color = (0.6, 0.6, 0.6, 1)
        self._update_count()
        threading.Thread(target=self._albums_thread, args=(token,),
                         daemon=True).start()

    def _albums_thread(self, token):
        a = self.artist
        try:
            albums = self.searcher.artist_albums(a['source'], a['id'], a['name'])
            err = None
        except Exception as e:
            albums, err = [], srch.b._clean_error(e)
        Clock.schedule_once(lambda dt: self._got_albums(albums, err, token))

    def _got_albums(self, albums, err, token):
        if token != self._token or self.mode != 'artist':
            return
        for al in albums:
            al.update(selected=False, expanded=False, items=None, sel=set(),
                      loading=False, widgets=None)
        self.artist['albums'] = albums
        if err:
            self.status.text = f'Could not load this artist: {err}'
            self.status.color = (1, 0.4, 0.3, 1)
        else:
            self.status.text = (f'{len(albums)} albums and singles. Tick what '
                                'you want, or expand an album to pick songs.')
        self._render_artist()

    def _render_artist(self):
        keep = self.scroll.scroll_y
        self.grid.clear_widgets()
        for al in self.artist['albums']:
            self.grid.add_widget(self._album_row(al))
            if al['expanded']:
                if al['items'] is None:
                    self.grid.add_widget(_label('Loading songs...', 12,
                                                (0.6, 0.6, 0.6, 1), height=28))
                else:
                    al['track_checks'] = []
                    for i, it in enumerate(al['items']):
                        self.grid.add_widget(self._track_row(al, i, it))
        self.scroll.scroll_y = keep
        self._update_count()

    def _album_row(self, al):
        row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(6))
        check = CheckBox(size_hint_x=None, width=dp(34), active=al['selected'])
        check.bind(active=lambda w, v: self._album_selected(al, v))
        al['check'] = check
        row.add_widget(check)
        row.add_widget(SourceThumb(al['source'], al['thumb'], True, size=50))
        total = f"  -  {al['total']} songs" if al.get('total') else ''
        info = _label(f"[b]{escape_markup(al['title'])}[/b]\n[size=11sp]"
                      f"[color=999999]{al['kind']}  -  {al['year']}{total}"
                      f"[/color][/size]", 13)
        row.add_widget(info)
        btn = Button(text='-' if al['expanded'] else '+', size_hint_x=None,
                     width=dp(44), font_size=sp(20),
                     background_color=(0.2, 0.2, 0.2, 1))
        btn.bind(on_press=lambda *a: self._toggle_album(al))
        row.add_widget(btn)
        return row

    def _track_row(self, al, i, it):
        row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6),
                        padding=(dp(40), 0, 0, 0))
        check = CheckBox(size_hint_x=None, width=dp(30), active=i in al['sel'])
        check.bind(active=lambda w, v: self._track_selected(al, i, v))
        al['track_checks'].append(check)
        row.add_widget(check)
        n = it.get('track_number') or i + 1
        dur = it.get('duration_text') or ''
        row.add_widget(_label(f"{n}. {escape_markup(it['title'])}", 12))
        row.add_widget(_label(dur, 11, (0.6, 0.6, 0.6, 1), size_hint_x=None,
                              width=dp(44)))
        return row

    def _toggle_album(self, al):
        al['expanded'] = not al['expanded']
        if al['expanded'] and al['items'] is None and not al['loading']:
            al['loading'] = True
            threading.Thread(target=self._items_thread, args=(al,),
                             daemon=True).start()
        self._render_artist()

    def _items_thread(self, al):
        try:
            items = self.searcher.album_items(al)
        except Exception as e:
            items = []
            self.searcher.notes.append(srch.b._clean_error(e))
        Clock.schedule_once(lambda dt: self._got_items(al, items))

    def _got_items(self, al, items):
        al['items'], al['loading'] = items, False
        if al['selected']:
            al['sel'] = set(range(len(items)))
        if self.mode == 'artist':
            self._render_artist()

    def _album_selected(self, al, value):
        if self._busy:
            return
        al['selected'] = value
        if al['items'] is not None:
            al['sel'] = set(range(len(al['items']))) if value else set()
            self._busy = True
            for c in al.get('track_checks', []):
                c.active = value
            self._busy = False
        self._update_count()

    def _track_selected(self, al, i, value):
        if self._busy:
            return
        (al['sel'].add if value else al['sel'].discard)(i)
        all_on = len(al['sel']) == len(al['items'])
        al['selected'] = all_on
        self._busy = True
        al['check'].active = all_on
        self._busy = False
        self._update_count()

    def _back_to_results(self):
        self._token += 1
        self._results_header(self.query.text if hasattr(self, 'query') else '')
        self._render()
        self._note()

    # ------------------------------------------------------------------ select
    def _select_all(self, value):
        if self.mode == 'results' and self.tab == 'songs':
            for st in self.song_state:
                st['check'].active = value
        elif self.mode == 'artist':
            for al in self.artist['albums']:
                al['check'].active = value

    def _count(self):
        """(songs, unsure) currently ticked; unsure if an album's size is unknown."""
        if self.mode == 'artist' and self.artist:
            n, unsure = 0, False
            for al in self.artist['albums']:
                if al['items'] is not None:
                    n += len(al['sel'])
                elif al['selected']:
                    if al.get('total'):
                        n += al['total']
                    else:
                        unsure = True
                        n += 1
            return n, unsure
        if self.tab == 'songs':
            return sum(1 for s in self.song_state if s['selected']), False
        return 0, False

    def _update_count(self):
        n, unsure = self._count()
        self.btn_go.disabled = n == 0
        self.btn_go.text = (f"Download {n}{'+' if unsure else ''} "
                            f"song{'' if n == 1 and not unsure else 's'}"
                            if n else 'Download')

    # ------------------------------------------------------------------ go
    def _download(self, *a):
        self.btn_go.disabled = True
        self.btn_go.text = 'Preparing...'
        threading.Thread(target=self._collect_thread, daemon=True).start()

    def _collect_thread(self):
        try:
            if self.mode == 'artist':
                items, title = self._collect_artist(), self.artist['name']
            else:
                items = [c['sources'][s['choice']]['item']
                         for c, s in zip(self.cards['songs'], self.song_state)
                         if s['selected']]
                artists = {c['artist'] for c, s in
                           zip(self.cards['songs'], self.song_state)
                           if s['selected']}
                title = artists.pop() if len(artists) == 1 else 'Selected songs'
        except Exception as e:
            Clock.schedule_once(lambda dt: self._failed(srch.b._clean_error(e)))
            return
        Clock.schedule_once(lambda dt: self._finish(items, title))

    def _collect_artist(self):
        items = []
        todo = [al for al in self.artist['albums']
                if al['items'] is None and al['selected']]
        for n, al in enumerate(todo, 1):
            Clock.schedule_once(lambda dt, n=n: setattr(
                self.btn_go, 'text', f'Reading album {n} of {len(todo)}...'))
            al['items'] = self.searcher.album_items(al)
            al['sel'] = set(range(len(al['items'])))
        for al in self.artist['albums']:
            if al['items'] is not None:
                items += [al['items'][i] for i in sorted(al['sel'])]
        return items

    def _failed(self, msg):
        self.status.text = f'Could not prepare the download: {msg}'
        self.status.color = (1, 0.4, 0.3, 1)
        self._update_count()

    def _finish(self, items, title):
        if not items:
            self._failed('nothing selected')
            return
        self.dismiss()
        self.on_download(items, title)
