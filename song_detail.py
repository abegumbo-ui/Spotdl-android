"""
song_detail.py - the card that opens when you tap a song's text in Search.

Shows the big cover, title, artist, album, year and length of the version you
picked, and (looked up when the card opens) the YouTube Music song the app
would download, so you can see whether it is the right one. Has Play and an
Add / Remove button for the download.
"""
import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

import player as PL
import search as srch
import ui_kit as K
from fonts import rich
from player_ui import PlayButton, PlayerBar

NAMES = {'sp': 'Spotify', 'ytm': 'YouTube Music'}


class _Quiet:
    def log(self, *a, **k):
        pass


class SongDetail(ModalView):
    def __init__(self, card, choice, key, selected, on_toggle, loader, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.card, self.choice, self.key = card, choice, key
        self.selected, self.on_toggle = selected, on_toggle
        src = card['sources'][choice]
        item = src['item']
        root = BoxLayout(orientation='vertical', padding=dp(14),
                         spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(48))
        back = K.Btn('Back', icon='back', size=14, size_hint=(None, 1),
                     width=dp(110))
        back.bind(on_release=lambda *a: self.dismiss())
        top.add_widget(back)
        root.add_widget(top)

        cover = K.Cover(size_hint=(None, None), size=(dp(220), dp(220)),
                        pos_hint={'center_x': .5})
        holder = BoxLayout(size_hint_y=None, height=dp(226))
        holder.add_widget(BoxLayout())
        holder.add_widget(cover)
        holder.add_widget(BoxLayout())
        root.add_widget(holder)
        loader.load(item.get('cover') or src.get('thumb'), cover)

        self.title = K.text_label(rich(card['title']), 20, K.TEXT, bold=True,
                                  height=60, halign='center')
        root.add_widget(self.title)
        root.add_widget(K.text_label(rich(card['artist']), 14, K.MUTED,
                                     height=24, halign='center'))

        info = K.Surface(bg=K.SURFACE, radius=16, orientation='vertical',
                         padding=dp(14), spacing=dp(4), size_hint_y=None,
                         height=dp(200))
        rows = [('Album', src.get('album') or item.get('album') or '-'),
                ('Year', str(item.get('year') or '-')),
                ('Length', srch._fmt(card['duration']) or '-'),
                ('Details from', NAMES[choice])]
        if len(card['sources']) > 1:
            rows.append(('Also on', NAMES['ytm' if choice == 'sp' else 'sp']))
        for k, v in rows:
            r = BoxLayout(size_hint_y=None, height=dp(24))
            r.add_widget(K.text_label(k, 12, K.MUTED, size_hint_x=.35))
            r.add_widget(K.text_label(rich(v), 12.5, K.TEXT))
            info.add_widget(r)
        self.match = K.text_label('Looking up the YouTube Music version...',
                                  12, K.ACCENT, valign='top')
        info.add_widget(self.match)
        root.add_widget(info)
        root.add_widget(BoxLayout())          # spacer

        self.player_bar = PlayerBar()
        root.add_widget(self.player_bar)
        bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        bar.add_widget(PlayButton(
            key, lambda: PL.get().play_item(item, key),
            size=52, pos_hint={'center_y': .5}))
        self.pick = K.Btn('', icon='plus', bg=K.ACCENT, fg=K.ON_ACCENT, size=15)
        self.pick.bind(on_release=self._toggle)
        bar.add_widget(self.pick)
        root.add_widget(bar)
        self.add_widget(root)
        self._paint()
        threading.Thread(target=self._lookup, args=(item,), daemon=True).start()

    def _paint(self):
        self.pick.text = ('Remove from download' if self.selected
                          else 'Add to download')
        self.pick.set_style(bg=K.SURFACE2 if self.selected else K.ACCENT,
                            fg=K.TEXT if self.selected else K.ON_ACCENT)

    def _toggle(self, *a):
        self.selected = not self.selected
        self.on_toggle(self.selected)
        self._paint()

    def _lookup(self, item):
        try:
            import spotdl_bridge as b
            from ytmusicapi import YTMusic
            track, why = b.resolve_item(YTMusic(), item, _Quiet(), 1)
            if track is None:
                text, col = f'Would not be found: {why}', K.DANGER
            else:
                dur = srch._fmt(track.get('duration'))
                want = self.card['duration']
                off = ''
                if want and track.get('duration'):
                    d = abs(int(track['duration']) - int(want))
                    off = f', {d} s off' if d else ', same length'
                text = (f"Download will use: {track['title']} - "
                        f"{track['artist']}"
                        f"{' - ' + track['album'] if track.get('album') else ''}"
                        f" ({dur}{off})")
                col = K.ACCENT
        except Exception as e:
            text, col = f'Could not look it up: {b._clean_error(e)}', K.DANGER
        Clock.schedule_once(lambda dt: (
            setattr(self.match, 'text', rich(text)),
            setattr(self.match, 'color', K.C(col))))

    def on_dismiss(self):
        PL.get().stop()
