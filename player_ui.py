"""
player_ui.py - the player bar and the small play buttons.

PlayerBar sits at the bottom of a screen. It shows what is playing (for a
preview: the YouTube Music title, artist and album the app matched, so you can
tell at once whether it is the right song), a seek bar, and play/pause/close.
PlayButton is the round button on each song; it shows pause while its song plays.
"""
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

import player as P
import ui_kit as K
from fonts import rich


def _mmss(sec):
    sec = int(max(0, sec))
    return f'{sec // 60}:{sec % 60:02d}'


class PlayButton(ButtonBehavior, AnchorLayout):
    """Round play/pause button. Give it a `key`; it lights up while that key
    is the song in the player."""

    def __init__(self, key, on_press_play, size=40, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(size), dp(size)))
        super().__init__(anchor_x='center', anchor_y='center', **kw)
        self.key = key
        self._play = on_press_play
        with self.canvas.before:
            self._col = Color(*K.C(K.SURFACE2))
            self._disc = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)
        self.icon = K.Icon('play', K.TEXT, size=(dp(size * .5), dp(size * .5)))
        self.add_widget(self.icon)
        self._shown = None
        Clock.schedule_interval(self.refresh, 0.3)

    def _sync(self, *a):
        self._disc.pos, self._disc.size = self.pos, self.size

    def on_release(self):
        self._play()

    def refresh(self, *a):
        if not self.parent:
            return
        pl = P.get()
        mine = pl.key == self.key
        shown = (mine, pl.state if mine else None)
        if shown == self._shown:
            return
        self._shown = shown
        on = mine and pl.state in ('loading', 'playing')
        self.icon.kind = 'pause' if on else 'play'
        self.icon._draw()
        hot = mine and pl.state in ('loading', 'playing', 'paused')
        self._col.rgba = K.C(K.ACCENT if hot else K.SURFACE2)
        self.icon.set_color(K.ON_ACCENT if hot else K.TEXT)


class _Seek(Widget):
    def __init__(self, on_seek, **kw):
        super().__init__(size_hint_y=None, height=dp(20), **kw)
        self.on_seek = on_seek
        self.value = 0.0
        self.bind(pos=self._draw, size=self._draw)

    def set_value(self, v):
        self.value = v
        self._draw()

    def _draw(self, *a):
        from kivy.graphics import RoundedRectangle
        self.canvas.clear()
        h = dp(5)
        y = self.center_y - h / 2
        with self.canvas:
            Color(*K.C(K.SURFACE2))
            RoundedRectangle(pos=(self.x, y), size=(self.width, h), radius=[h / 2])
            Color(*K.C(K.ACCENT))
            w = max(h, self.width * self.value)
            RoundedRectangle(pos=(self.x, y), size=(w, h), radius=[h / 2])
            Ellipse(pos=(self.x + w - dp(7), self.center_y - dp(7)),
                    size=(dp(14), dp(14)))

    def on_touch_down(self, t):
        if self.collide_point(*t.pos):
            t.grab(self)
            self._at(t)
            return True

    def on_touch_move(self, t):
        if t.grab_current is self:
            self._at(t)
            return True

    def on_touch_up(self, t):
        if t.grab_current is self:
            t.ungrab(self)
            self._at(t, final=True)
            return True

    def _at(self, t, final=False):
        v = max(0.0, min(1.0, (t.x - self.x) / max(1, self.width)))
        self.set_value(v)
        if final:
            self.on_seek(v)


class _Tap(ButtonBehavior, BoxLayout):
    pass


class PlayerBar(K.Surface):
    """Hidden until something is loaded."""

    def __init__(self, **kw):
        super().__init__(bg=K.SURFACE, radius=16, orientation='vertical',
                         size_hint_y=None, height=0, opacity=0,
                         padding=(dp(12), dp(8)), spacing=dp(2), **kw)
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        self.toggle = PlayButton(None, lambda: P.get().toggle(), size=40,
                                 pos_hint={'center_y': .5})
        top.add_widget(self.toggle)
        col = _Tap(orientation='vertical')
        col.bind(on_release=lambda *a: self._open_full())
        self.title = K.text_label('', 13.5, K.TEXT, bold=True, height=22)
        self.title.shorten = True
        self.title.shorten_from = 'right'
        self.sub = K.text_label('', 11, K.MUTED, height=18)
        self.sub.shorten = True
        self.sub.shorten_from = 'right'
        col.add_widget(self.title)
        col.add_widget(self.sub)
        top.add_widget(col)
        nxt = K.IconBtn('next', size=40, icon_scale=.5,
                        pos_hint={'center_y': .5})
        nxt.bind(on_release=lambda *a: P.get().next())
        self.nxt = nxt
        top.add_widget(nxt)
        close = K.Btn('', icon='close', bg=K.SURFACE2, size=10,
                      size_hint=(None, None), width=dp(40), height=dp(40), radius=20,
                      pos_hint={'center_y': .5})
        close.bind(on_release=lambda *a: P.get().stop())
        top.add_widget(close)
        self.add_widget(top)
        row = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
        self.t_now = K.text_label('0:00', 10.5, K.MUTED, height=18,
                                  size_hint_x=None, width=dp(36))
        self.seek = _Seek(lambda v: P.get().seek(v))
        self.t_len = K.text_label('', 10.5, K.MUTED, height=18,
                                  size_hint_x=None, width=dp(36),
                                  halign='right')
        for w in (self.t_now, self.seek, self.t_len):
            row.add_widget(w)
        self.add_widget(row)
        self._visible = False
        Clock.schedule_interval(self.refresh, 0.25)

    def _open_full(self):
        from now_playing import open_now_playing
        open_now_playing()

    def _show(self, on):
        if on == self._visible:
            return
        self._visible = on
        self.height = dp(96) if on else 0
        self.opacity = 1 if on else 0

    def refresh(self, *a):
        pl = P.get()
        pl.tick()
        self._show(pl.state != 'idle')
        if pl.state == 'idle':
            return
        self.toggle.key = pl.key
        self.toggle.refresh()
        self.title.text = rich(pl.title)
        if pl.state == 'error':
            self.sub.text = rich('Could not play: ' + pl.error)
            self.sub.color = K.C(K.DANGER)
        else:
            self.sub.text = rich('Loading...' if pl.state == 'loading'
                                 and not pl.subtitle else pl.subtitle)
            self.sub.color = K.C(K.MUTED)
        self.nxt.opacity = 1 if pl.pos + 1 < len(pl.order) or \
            pl.repeat == 'all' else .3
        self.t_now.text = _mmss(pl.position())
        self.t_len.text = _mmss(pl.duration) if pl.duration else ''
        self.seek.set_value(pl.fraction())
