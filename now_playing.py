"""
now_playing.py - the full-screen player: big cover, seek bar, previous /
play / next, shuffle, repeat, favourite, sleep timer and the queue.
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import covers
import library as lib
import player as P
import ui_kit as K
from fonts import rich
from player_ui import _Seek
from ui_kit import text_label

SLEEP_STEPS = [0, 15, 30, 60]
_open = []                       # at most one Now Playing at a time
LIB = []                         # the app puts its Library here


def open_now_playing(library=None):
    if _open:
        return
    NowPlaying(library or (LIB[0] if LIB else None)).open()


class NowPlaying(ModalView):
    def __init__(self, library=None, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.library = library
        self.show_queue = False
        self._seen_ver = None
        self._entry_id = None
        self._sleep_i = 0
        root = BoxLayout(orientation='vertical', padding=dp(16),
                         spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        back = K.IconBtn('down', bg=K.SURFACE, size=44)
        back.bind(on_release=lambda *a: self.dismiss())
        top.add_widget(back)
        top.add_widget(text_label('Now playing', 14, K.MUTED,
                                  halign='center'))
        self.btn_queue = K.IconBtn('queue', bg=K.SURFACE, size=44)
        self.btn_queue.bind(on_release=self._toggle_queue)
        top.add_widget(self.btn_queue)
        root.add_widget(top)

        self.stage = BoxLayout()
        root.add_widget(self.stage)

        # --- the cover page
        self.page = BoxLayout(orientation='vertical', spacing=dp(8))
        holder = BoxLayout()
        self.cover = K.Cover(radius=22, size_hint=(None, None),
                             pos_hint={'center_y': .5})
        holder.add_widget(BoxLayout())
        holder.add_widget(self.cover)
        holder.add_widget(BoxLayout())
        holder.bind(size=self._fit_cover)
        self.page.add_widget(holder)
        self.title = text_label('', 20, K.TEXT, bold=True, height=56,
                                halign='center')
        self.artist = text_label('', 14, K.MUTED, height=24, halign='center')
        self.album = text_label('', 12, K.FAINT, height=22, halign='center')
        for w in (self.title, self.artist, self.album):
            self.page.add_widget(w)
        # --- the queue page
        self.qscroll = ScrollView(bar_width=dp(3))
        self.qgrid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        self.qgrid.bind(minimum_height=self.qgrid.setter('height'))
        self.qscroll.add_widget(self.qgrid)
        self.stage.add_widget(self.page)

        row = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(8))
        self.t_now = text_label('0:00', 11, K.MUTED, size_hint_x=None,
                                width=dp(44))
        self.seek = _Seek(lambda v: P.get().seek(v))
        self.t_len = text_label('', 11, K.MUTED, size_hint_x=None,
                                width=dp(44), halign='right')
        for w in (self.t_now, self.seek, self.t_len):
            row.add_widget(w)
        root.add_widget(row)

        ctl = BoxLayout(size_hint_y=None, height=dp(76), spacing=dp(6))
        self.b_shuffle = K.IconBtn('shuffle', size=48, icon_scale=.72)
        self.b_prev = K.IconBtn('prev', size=52, icon_scale=.55)
        self.b_play = K.IconBtn('play', bg=K.ACCENT, fg=K.ON_ACCENT, size=72,
                                icon_scale=.46)
        self.b_next = K.IconBtn('next', size=52, icon_scale=.55)
        self.b_repeat = K.IconBtn('repeat', size=48, icon_scale=.72)
        self.b_shuffle.bind(on_release=self._shuffle)
        self.b_prev.bind(on_release=lambda *a: P.get().previous())
        self.b_play.bind(on_release=lambda *a: P.get().toggle())
        self.b_next.bind(on_release=lambda *a: P.get().next())
        self.b_repeat.bind(on_release=self._repeat)
        for w in (self.b_shuffle, self.b_prev, self.b_play, self.b_next,
                  self.b_repeat):
            ctl.add_widget(BoxLayout())
            ctl.add_widget(w)
        ctl.add_widget(BoxLayout())
        root.add_widget(ctl)

        extra = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.b_fav = K.IconBtn('heart', bg=K.SURFACE, size=44)
        self.b_fav.bind(on_release=self._fav)
        self.b_sleep = K.Btn('Sleep timer', icon='moon', size=12)
        self.b_sleep.bind(on_release=self._sleep)
        self.b_stop = K.Btn('Stop', icon='close', size=12, size_hint_x=.4)
        self.b_stop.bind(on_release=lambda *a: (P.get().stop(),
                                                self.dismiss()))
        extra.add_widget(self.b_fav)
        extra.add_widget(self.b_sleep)
        extra.add_widget(self.b_stop)
        root.add_widget(extra)
        self.add_widget(root)
        self._tick = Clock.schedule_interval(self.refresh, 0.25)
        self.refresh()

    def on_open(self):
        _open.append(self)

    def on_dismiss(self):
        self._tick.cancel()
        if self in _open:
            _open.remove(self)

    def _fit_cover(self, holder, size):
        side = max(dp(120), min(holder.width - dp(8), holder.height - dp(4)))
        self.cover.size = (side, side)

    # ---- buttons
    def _toggle_queue(self, *a):
        self.show_queue = not self.show_queue
        self.stage.clear_widgets()
        self.stage.add_widget(self.qscroll if self.show_queue else self.page)
        self.btn_queue.set_look(bg=K.ACCENT if self.show_queue else K.SURFACE,
                                fg=K.ON_ACCENT if self.show_queue else K.TEXT)
        self._seen_ver = None
        self.refresh()

    def _shuffle(self, *a):
        pl = P.get()
        pl.set_shuffle(not pl.shuffle)

    def _repeat(self, *a):
        P.get().cycle_repeat()

    def _fav(self, *a):
        e = P.get().current
        if self.library and e and e['kind'] == 'file':
            self.library.toggle_favorite(e['path'])

    def _sleep(self, *a):
        self._sleep_i = (self._sleep_i + 1) % len(SLEEP_STEPS)
        P.get().set_sleep(SLEEP_STEPS[self._sleep_i])

    # ---- keep the screen in step with the player
    def refresh(self, *a):
        pl = P.get()
        pl.tick()
        if pl.state == 'idle':
            self.dismiss()
            return
        e = pl.current
        eid = id(e) if e else None
        if eid != self._entry_id:
            self._entry_id = eid
            covers.for_entry(e, self.cover)
        self.title.text = rich(pl.title)
        if pl.state == 'error':
            self.artist.text = rich('Could not play: ' + pl.error)
            self.artist.color = K.C(K.DANGER)
        else:
            sub = pl.subtitle if e and e['kind'] == 'item' else (
                e.get('artist', '') if e else '')
            self.artist.text = rich(sub)
            self.artist.color = K.C(K.MUTED)
        self.album.text = rich(e.get('album', '') if e and e['kind'] == 'file'
                               else '')
        playing = pl.state in ('loading', 'playing')
        self.b_play.set_kind('pause' if playing else 'play')
        self.b_shuffle.set_look(fg=K.ACCENT if pl.shuffle else K.MUTED)
        self.b_repeat.set_kind('repeat1' if pl.repeat == 'one' else 'repeat')
        self.b_repeat.set_look(fg=K.MUTED if pl.repeat == 'off' else K.ACCENT)
        fav = bool(self.library and e and e['kind'] == 'file'
                   and self.library.is_favorite(e['path']))
        self.b_fav.set_kind('heart_fill' if fav else 'heart')
        self.b_fav.set_look(fg=K.DANGER if fav else K.TEXT)
        self.b_fav.opacity = 1 if (e and e['kind'] == 'file') else .35
        mins = SLEEP_STEPS[self._sleep_i]
        if pl.sleep_at:
            left = max(0, int((pl.sleep_at - __import__('time').time()) / 60) + 1)
            self.b_sleep.text = f'Sleep in {left} min'
        else:
            self._sleep_i = 0
            self.b_sleep.text = 'Sleep timer'
        self.t_now.text = lib.fmt_time(pl.position())
        self.t_len.text = lib.fmt_time(pl.duration) if pl.duration else ''
        self.seek.set_value(pl.fraction())
        if self.show_queue and (pl.version, pl.pos) != self._seen_ver:
            self._seen_ver = (pl.version, pl.pos)
            self._draw_queue()

    # ---- the queue list
    def _draw_queue(self):
        pl = P.get()
        g = self.qgrid
        g.clear_widgets()
        head = BoxLayout(size_hint_y=None, height=dp(36))
        head.add_widget(text_label(
            f'[b]Up next[/b]  [color={K.MUTED[1:]}]{len(pl.upcoming())} '
            f'song{"s" if len(pl.upcoming()) != 1 else ""}[/color]', 13))
        clear = K.Btn('Clear', size=11, size_hint=(None, 1), width=dp(70),
                      radius=10)
        clear.bind(on_release=lambda *a: pl.clear_upcoming())
        head.add_widget(clear)
        g.add_widget(head)
        cur = pl.current
        if cur:
            g.add_widget(self._qrow(None, cur, True))
        for p, e in pl.upcoming()[:200]:
            g.add_widget(self._qrow(p, e, False))

    def _qrow(self, p, e, is_now):
        row = K.Surface(bg=K.SURFACE2 if is_now else K.SURFACE, radius=12,
                        size_hint_y=None, height=dp(52),
                        padding=(dp(12), dp(6)), spacing=dp(8))
        row.add_widget(K.Icon('music', K.ACCENT if is_now else K.FAINT,
                              pos_hint={'center_y': .5}))
        col = BoxLayout(orientation='vertical')
        t = text_label(rich(e['title']), 13, K.ACCENT if is_now else K.TEXT,
                       bold=True)
        t.shorten = True
        t.shorten_from = 'right'
        col.add_widget(t)
        col.add_widget(text_label(rich(e.get('artist', '')), 11, K.MUTED))
        row.add_widget(col)
        if not is_now:
            go = K.IconBtn('play', size=34, icon_scale=.5)
            go.bind(on_release=lambda *a, p=p: P.get().jump(p))
            rm = K.IconBtn('close', size=34, icon_scale=.45)
            rm.bind(on_release=lambda *a, p=p: P.get().remove_at(p))
            row.add_widget(go)
            row.add_widget(rm)
        return row
