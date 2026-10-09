"""
library_screen.py - the music library: every downloaded song, browsable by
song, album, artist, playlist and favourites, with search, sorting, queueing
and a mini player.
"""
import os

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import covers
import library as lib
import player as P
import ui_kit as K
from fonts import rich
from player_ui import PlayButton, PlayerBar
from sheets import ActionSheet, AskText, Confirm
from ui_kit import text_label

PAGE = 80
SORTS = [('artist', 'Artist'), ('title', 'Title'), ('recent', 'Newest'),
         ('plays', 'Most played')]
TABS = ['Songs', 'Albums', 'Artists', 'Lists', 'Favorites']


class Tap(ButtonBehavior, BoxLayout):
    pass


def entries_for(songs):
    return [P.file_entry(s['path'], s['title'], s['artist'], s['album'],
                         s['duration']) for s in songs]


def play_list(songs, start=0, shuffle=False):
    if not songs:
        return
    pl = P.get()
    pl.shuffle = shuffle
    if shuffle:
        import random
        start = random.randrange(len(songs))
    pl.play_entries(entries_for(songs), start)


class LibraryScreen(ModalView):
    def __init__(self, library, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.lib = library
        self.tab = 0
        self.sort = 0
        self.drill = None            # ('album', dict) | ('artist', dict) | ...
        self.shown = PAGE
        self._seen = None
        self._build()
        self.lib.scan()
        self._poll = Clock.schedule_interval(self._watch, 1.0)
        self._render()

    def on_dismiss(self):
        self._poll.cancel()

    # ------------------------------------------------------------ layout
    def _build(self):
        root = BoxLayout(orientation='vertical', padding=(dp(14), dp(14)),
                         spacing=dp(10))
        head = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.back = K.IconBtn('back', bg=K.SURFACE, size=44)
        self.back.bind(on_release=self._back)
        head.add_widget(self.back)
        self.title = text_label('Library', 22, K.TEXT, bold=True)
        head.add_widget(self.title)
        self.shuffle_all = K.Btn('Shuffle', icon='shuffle', bg=K.ACCENT,
                                 fg=K.ON_ACCENT, size=12, size_hint=(None, 1),
                                 width=dp(110), radius=22)
        self.shuffle_all.bind(on_release=self._shuffle_all)
        head.add_widget(self.shuffle_all)
        root.add_widget(head)

        self.stats = text_label('', 11.5, K.MUTED, height=20)
        root.add_widget(self.stats)
        box, self.query = K.make_input('Search your songs', 'search')
        box.height = dp(46)
        self.query.bind(text=lambda *a: self._typed())
        root.add_widget(box)
        self.tabs = K.Seg(TABS, size=12, on_select=self._on_tab)
        root.add_widget(self.tabs)
        self.tools = BoxLayout(size_hint_y=None, height=dp(0), spacing=dp(8))
        root.add_widget(self.tools)
        self.scroll = ScrollView(bar_width=dp(3))
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                               padding=(0, 0, 0, dp(6)))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)
        self.player_bar = PlayerBar()
        root.add_widget(self.player_bar)
        self.add_widget(root)

    # ------------------------------------------------------------ events
    def _watch(self, dt):
        key = (self.lib.version, self.lib.scanning)
        if key != self._seen:
            self._render()

    def _typed(self):
        self.shown = PAGE
        Clock.unschedule(self._render)
        Clock.schedule_once(lambda dt: self._render(), 0.25)

    def _on_tab(self, i, name):
        self.tab, self.drill, self.shown = i, None, PAGE
        self.query.text = ''
        self.scroll.scroll_y = 1
        self._render()

    def _back(self, *a):
        if self.drill:
            self.drill, self.shown = None, PAGE
            self.scroll.scroll_y = 1
            self._render()
        else:
            self.dismiss()

    def _shuffle_all(self, *a):
        play_list(self._current_songs() or self.lib.songs, shuffle=True)

    # ------------------------------------------------------------ what to show
    def _current_songs(self):
        """The songs on screen right now (used by Shuffle and Play all)."""
        d = self.drill
        if d:
            return self._drill_songs()
        if self.tab == 0:
            return self._filtered(self.lib.sorted_songs(SORTS[self.sort][0]))
        if self.tab == 4:
            return self._filtered(self.lib.favorite_songs())
        return []

    def _filtered(self, songs):
        q = self.query.text.strip()
        return self.lib.search(q, songs) if q else songs

    def _drill_songs(self):
        kind, data = self.drill
        if kind in ('album', 'artist'):
            return self._filtered(data['songs'])
        if kind == 'recent':
            return self._filtered(self.lib.recently_played())
        if kind == 'plays':
            return self._filtered([s for s in self.lib.sorted_songs('plays')
                                   if self.lib.plays.get(s['path'])][:100])
        if kind == 'new':
            return self._filtered(self.lib.sorted_songs('recent')[:100])
        if kind == 'playlist':
            return self._filtered(self.lib.playlist_songs(data))
        return []

    # ------------------------------------------------------------ drawing
    def _render(self, *a):
        self._seen = (self.lib.version, self.lib.scanning)
        t = self.lib.totals()
        self.stats.text = (
            f"{t['songs']} songs  -  {t['albums']} albums  -  "
            f"{t['artists']} artists  -  {lib.fmt_total(t['seconds'])}"
            + ('   (reading files...)' if self.lib.scanning else ''))
        self.grid.clear_widgets()
        self.tools.clear_widgets()
        self.tools.height = 0
        self.back.opacity = 1
        self.title.text = '[b]Library[/b]'
        if self.drill:
            self._draw_drill()
        elif self.tab == 0:
            self._draw_songs()
        elif self.tab == 1:
            self._draw_albums()
        elif self.tab == 2:
            self._draw_artists()
        elif self.tab == 3:
            self._draw_lists()
        else:
            self._draw_songs(self._filtered(self.lib.favorite_songs()),
                             empty='Tap the heart on a song to keep it here.')

    def _empty(self, text):
        self.grid.add_widget(text_label(rich(text), 13, K.MUTED, height=70,
                                        halign='center'))

    def _tool_row(self, widgets):
        self.tools.height = dp(40)
        for w in widgets:
            self.tools.add_widget(w)

    def _draw_songs(self, songs=None, empty=None, context=None):
        if songs is None:
            self._tool_row([self._sort_btn()])
            songs = self._filtered(self.lib.sorted_songs(SORTS[self.sort][0]))
        if not songs:
            self._empty(empty or (
                'No songs found.' if self.query.text.strip() else
                'No downloaded songs yet.\nDownload some from the main screen '
                'and they show up here.'))
            return
        for i, s in enumerate(songs[:self.shown]):
            self.grid.add_widget(self._song_row(songs, i, context))
        if len(songs) > self.shown:
            more = K.Btn(f'Show more ({len(songs) - self.shown} left)',
                         size=13, size_hint_y=None, height=dp(44))
            more.bind(on_release=lambda *a: self._more())
            self.grid.add_widget(more)

    def _more(self):
        self.shown += PAGE
        y = self.scroll.scroll_y
        self._render()
        self.scroll.scroll_y = y

    def _sort_btn(self):
        b = K.Btn(f'Sort: {SORTS[self.sort][1]}', size=12, radius=12)
        b.bind(on_release=self._next_sort)
        return b

    def _next_sort(self, *a):
        self.sort = (self.sort + 1) % len(SORTS)
        self._render()

    def _song_row(self, songs, i, context=None):
        s = songs[i]
        fav = self.lib.is_favorite(s['path'])
        row = K.Surface(bg=K.SURFACE, radius=14, size_hint_y=None,
                        height=dp(60), padding=(dp(10), dp(6)), spacing=dp(8))
        row.add_widget(PlayButton(
            ('file', s['path']), lambda: self._play_here(songs, i), size=40,
            pos_hint={'center_y': .5}))
        col = Tap(orientation='vertical')
        col.bind(on_release=lambda *a: self._play_here(songs, i))
        t = text_label(rich(s['title']), 13.5, K.TEXT, bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        sub = s['artist'] + (f"  -  {s['album']}" if s['album'] else '')
        u = text_label(rich(sub), 11, K.MUTED)
        u.shorten = True
        u.shorten_from = 'right'
        col.add_widget(t)
        col.add_widget(u)
        row.add_widget(col)
        row.add_widget(text_label(lib.fmt_time(s['duration']), 11, K.FAINT,
                                  size_hint_x=None, width=dp(38),
                                  halign='right'))
        heart = K.IconBtn('heart_fill' if fav else 'heart', size=36,
                          fg=K.DANGER if fav else K.MUTED, icon_scale=.5,
                          pos_hint={'center_y': .5})
        heart.bind(on_release=lambda *a: self._fav(s))
        dots = K.IconBtn('dots', size=36, fg=K.MUTED, icon_scale=.45,
                         pos_hint={'center_y': .5})
        dots.bind(on_release=lambda *a: self._menu(s, context))
        row.add_widget(heart)
        row.add_widget(dots)
        return row

    def _play_here(self, songs, i):
        pl = P.get()
        key = ('file', songs[i]['path'])
        if pl.key == key and pl.state in ('playing', 'paused', 'loading'):
            pl.toggle()
        else:
            play_list(songs, i)

    def _fav(self, s):
        self.lib.toggle_favorite(s['path'])
        y = self.scroll.scroll_y
        self._render()
        self.scroll.scroll_y = y

    # ---- the per-song menu
    def _menu(self, s, context=None):
        e = P.file_entry(s['path'], s['title'], s['artist'], s['album'],
                         s['duration'])
        acts = [
            ('Play next', 'next', lambda: P.get().add(dict(e), True), None),
            ('Add to queue', 'queue', lambda: P.get().add(dict(e)), None),
            ('Add to playlist', 'plus', lambda: self._pick_playlist(s), None),
            ('Remove from favorites' if self.lib.is_favorite(s['path'])
             else 'Add to favorites', 'heart',
             lambda: self._fav(s), None),
            ('Song info', 'music', lambda: self._info(s), None),
        ]
        if context and context[0] == 'playlist':
            acts.append(('Remove from this playlist', 'minus',
                         lambda: self._remove_from(context[1], s), K.WARN))
        acts.append(('Delete from phone', 'trash',
                     lambda: self._confirm_delete(s), K.DANGER))
        ActionSheet(s['title'], acts, subtitle=s['artist']).open()

    def _info(self, s):
        rows = [('Title', s['title']), ('Artist', s['artist']),
                ('Album', s['album']), ('Year', s['year'] or '-'),
                ('Track', str(s['track'] or '-')),
                ('Length', lib.fmt_time(s['duration'])),
                ('File', os.path.basename(s['path']))]
        ActionSheet('Song info', [
            (f'{k}:  {v}', None, lambda: None, K.MUTED) for k, v in rows]
        ).open()

    def _confirm_delete(self, s):
        Confirm('Delete this song?',
                f"{s['title']} will be deleted from your phone.",
                lambda: (self._stop_if_playing(s['path']),
                         self.lib.delete_song(s['path']))).open()

    def _stop_if_playing(self, path):
        pl = P.get()
        if pl.key == ('file', path):
            pl.stop()

    def _pick_playlist(self, s):
        acts = [(f'{n}  ({len(v)})', 'music',
                 lambda n=n: self.lib.add_to_playlist(n, s['path']), None)
                for n, v in sorted(self.lib.playlists.items())]
        acts.append(('New playlist...', 'plus',
                     lambda: self._new_playlist(s['path']), K.ACCENT))
        ActionSheet('Add to playlist', acts).open()

    def _new_playlist(self, add_path=None):
        def made(name):
            if not name:
                return
            self.lib.create_playlist(name)
            if add_path:
                self.lib.add_to_playlist(name, add_path)
            self._render()
        AskText('New playlist', 'Playlist name', made).open()

    def _remove_from(self, name, s):
        self.lib.remove_from_playlist(name, s['path'])
        self._render()

    # ---- albums / artists / lists
    def _draw_albums(self):
        q = self.query.text.strip().lower()
        albums = [a for a in self.lib.albums()
                  if not q or q in f"{a['album']} {a['artist']}".lower()]
        if not albums:
            return self._empty('No albums found.')
        for a in albums[:self.shown]:
            self.grid.add_widget(self._album_row(a))
        if len(albums) > self.shown:
            more = K.Btn('Show more', size=13, size_hint_y=None, height=dp(44))
            more.bind(on_release=lambda *a: self._more())
            self.grid.add_widget(more)

    def _album_row(self, a):
        row = Tap(size_hint_y=None, height=dp(68))
        card = K.Surface(bg=K.SURFACE, radius=14, padding=(dp(10), dp(8)),
                         spacing=dp(12))
        cov = K.Cover(radius=10, size_hint=(None, None),
                      size=(dp(52), dp(52)), pos_hint={'center_y': .5})
        covers.for_file(a['songs'][0]['path'], cov)
        card.add_widget(cov)
        col = BoxLayout(orientation='vertical')
        t = text_label(rich(a['album'] or 'Unknown album'), 14, K.TEXT,
                       bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        n = len(a['songs'])
        sub = f"{a['artist']}  -  {n} song{'s' if n != 1 else ''}"
        if a['year']:
            sub += f"  -  {a['year']}"
        col.add_widget(t)
        col.add_widget(text_label(rich(sub), 11, K.MUTED))
        card.add_widget(col)
        card.add_widget(K.Icon('next', K.FAINT, pos_hint={'center_y': .5}))
        row.add_widget(card)
        row.bind(on_release=lambda *a_: self._open('album', a))
        return row

    def _draw_artists(self):
        q = self.query.text.strip().lower()
        arts = [a for a in self.lib.artists()
                if not q or q in a['artist'].lower()]
        if not arts:
            return self._empty('No artists found.')
        for a in arts[:self.shown]:
            row = Tap(size_hint_y=None, height=dp(60))
            card = K.Surface(bg=K.SURFACE, radius=14,
                             padding=(dp(12), dp(8)), spacing=dp(12))
            cov = K.Cover(radius=24, size_hint=(None, None),
                          size=(dp(44), dp(44)), pos_hint={'center_y': .5})
            covers.for_file(a['songs'][0]['path'], cov)
            card.add_widget(cov)
            col = BoxLayout(orientation='vertical')
            col.add_widget(text_label(rich(a['artist']), 14, K.TEXT,
                                      bold=True))
            n = len(a['songs'])
            col.add_widget(text_label(f"{n} song{'s' if n != 1 else ''}", 11,
                                      K.MUTED))
            card.add_widget(col)
            card.add_widget(K.Icon('next', K.FAINT, pos_hint={'center_y': .5}))
            row.add_widget(card)
            row.bind(on_release=lambda w, a=a: self._open('artist', a))
            self.grid.add_widget(row)
        if len(arts) > self.shown:
            more = K.Btn('Show more', size=13, size_hint_y=None, height=dp(44))
            more.bind(on_release=lambda *a: self._more())
            self.grid.add_widget(more)

    def _draw_lists(self):
        new = K.Btn('New playlist', icon='plus', bg=K.ACCENT, fg=K.ON_ACCENT,
                    size=13, radius=12)
        new.bind(on_release=lambda *a: self._new_playlist())
        self._tool_row([new])
        smart = [('recent', 'Recently played', len(self.lib.recently_played())),
                 ('plays', 'Most played', len([p for p in self.lib.plays
                                               if self.lib.by_path(p)])),
                 ('new', 'Recently added', min(100, len(self.lib.songs)))]
        for kind, name, n in smart:
            self.grid.add_widget(self._list_row(name, n, 'queue',
                                                lambda k=kind: self._open(k, None)))
        for name in sorted(self.lib.playlists):
            n = len(self.lib.playlist_songs(name))
            self.grid.add_widget(self._list_row(
                name, n, 'music', lambda nm=name: self._open('playlist', nm)))
        if not self.lib.playlists:
            self.grid.add_widget(text_label(
                'Make playlists with "New playlist", then use the ... menu '
                'on any song.', 12, K.FAINT, height=50, valign='top'))

    def _list_row(self, name, n, icon, fn):
        row = Tap(size_hint_y=None, height=dp(58))
        card = K.Surface(bg=K.SURFACE, radius=14, padding=(dp(14), dp(8)),
                         spacing=dp(12))
        card.add_widget(K.Icon(icon, K.ACCENT, pos_hint={'center_y': .5}))
        col = BoxLayout(orientation='vertical')
        col.add_widget(text_label(rich(name), 14, K.TEXT, bold=True))
        col.add_widget(text_label(f"{n} song{'s' if n != 1 else ''}", 11,
                                  K.MUTED))
        card.add_widget(col)
        card.add_widget(K.Icon('next', K.FAINT, pos_hint={'center_y': .5}))
        row.add_widget(card)
        row.bind(on_release=lambda *a: fn())
        return row

    # ---- one album / artist / list opened
    def _open(self, kind, data):
        self.drill, self.shown = (kind, data), PAGE
        self.query.text = ''
        self.scroll.scroll_y = 1
        self._render()

    def _draw_drill(self):
        kind, data = self.drill
        names = {'recent': 'Recently played', 'plays': 'Most played',
                 'new': 'Recently added'}
        if kind == 'album':
            name = data['album'] or 'Unknown album'
        elif kind == 'artist':
            name = data['artist']
        elif kind == 'playlist':
            name = data
        else:
            name = names[kind]
        self.title.text = f'[b]{rich(name)}[/b]'
        songs = self._drill_songs()
        play = K.Btn('Play all', icon='play', bg=K.ACCENT, fg=K.ON_ACCENT,
                     size=12, radius=12)
        play.bind(on_release=lambda *a: play_list(songs))
        addq = K.Btn('Add to queue', icon='queue', size=12, radius=12)
        addq.bind(on_release=lambda *a: [P.get().add(e)
                                         for e in entries_for(songs)])
        tools = [play, addq]
        if kind == 'playlist':
            rm = K.Btn('Delete', icon='trash', fg=K.DANGER, size=12,
                       radius=12, size_hint_x=.6)
            rm.bind(on_release=lambda *a: Confirm(
                'Delete playlist?', f'"{data}" will be removed (the songs '
                'stay on your phone).', lambda: (
                    self.lib.delete_playlist(data), self._back()),
            ).open())
            tools.append(rm)
        self._tool_row(tools)
        context = ('playlist', data) if kind == 'playlist' else None
        self._draw_songs(songs, empty='Nothing here yet.', context=context)
