"""
ui_kit.py - the look of the app: colours and a few reusable widgets.

Everything is drawn with Kivy graphics (rounded rectangles, lines), so there
are no image or font files to ship. Icons are drawn shapes too.
"""
import math

from kivy.animation import Animation
from kivy.graphics import (Color, Ellipse, Line, RoundedRectangle, Triangle)
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

# ---- palette -----------------------------------------------------------------
BG = '#0B0E11'          # app background
SURFACE = '#141A20'     # cards
SURFACE2 = '#1C242C'    # inputs, raised parts
BORDER = '#2A3440'
TEXT = '#F2F5F8'
MUTED = '#93A0AE'
FAINT = '#5E6A77'
ACCENT = '#2EDB84'      # primary action
ACCENT_DIM = '#1E8F58'
ON_ACCENT = '#06210F'   # text on accent
DANGER = '#FF5F6D'
WARN = '#FFB347'
INFO = '#5AAEFF'
SPOTIFY = '#2EDB84'
YTMUSIC = '#FF5A6A'


def C(color, alpha=None):
    """'#RRGGBB' or an RGBA tuple -> RGBA tuple (optionally with new alpha)."""
    rgba = get_color_from_hex(color) if isinstance(color, str) else tuple(color)
    if len(rgba) == 3:
        rgba = (*rgba, 1.0)
    return rgba if alpha is None else (rgba[0], rgba[1], rgba[2], alpha)


def text_label(text='', size=13, color=TEXT, bold=False, height=None,
               halign='left', valign='middle', mono=False, **kw):
    """A left-aligned label that wraps and is vertically centred."""
    if mono:
        kw['font_name'] = 'RobotoMono-Regular'
    lbl = Label(text=text, font_size=sp(size), color=C(color), bold=bold,
                markup=True, halign=halign, valign=valign, **kw)
    if height:
        lbl.size_hint_y = None
        lbl.height = dp(height)
    lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], s[1])))
    return lbl


# ---- cards ---------------------------------------------------------------------
class Surface(BoxLayout):
    """A box with a rounded, coloured background."""

    def __init__(self, bg=SURFACE, radius=16, **kw):
        kw.setdefault('padding', dp(12))
        kw.setdefault('spacing', dp(8))
        super().__init__(**kw)
        with self.canvas.before:
            self._col = Color(*C(bg))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *a):
        self._rect.pos, self._rect.size = self.pos, self.size

    def set_bg(self, color):
        self._col.rgba = C(color)


# ---- icons -----------------------------------------------------------------------
class Icon(Widget):
    """Small line icons drawn with graphics."""

    def __init__(self, kind, color=TEXT, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(20), dp(20)))
        super().__init__(**kw)
        self.kind = kind
        self.color = C(color)
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def set_color(self, color):
        self.color = C(color)
        self._draw()

    def _draw(self, *a):
        self.canvas.clear()
        s = min(self.width, self.height)
        x = self.x + (self.width - s) / 2
        y = self.y + (self.height - s) / 2
        lw = max(dp(1.6), s * 0.1)
        P = lambda u, v: (x + u * s, y + v * s)
        line = lambda *pts, **k: Line(
            points=[c for p in pts for c in p], width=lw, cap='round',
            joint='round', **k)
        with self.canvas:
            Color(*self.color)
            k = self.kind
            if k == 'search':
                Line(circle=(*P(.43, .57), .27 * s), width=lw)
                line(P(.63, .37), P(.86, .14))
            elif k == 'download':
                line(P(.5, .82), P(.5, .30))
                line(P(.28, .50), P(.5, .28), P(.72, .50))
                line(P(.18, .12), P(.82, .12))
            elif k == 'back':
                line(P(.62, .80), P(.30, .50), P(.62, .20))
            elif k == 'close':
                line(P(.24, .24), P(.76, .76))
                line(P(.24, .76), P(.76, .24))
            elif k == 'check':
                line(P(.18, .52), P(.42, .27), P(.84, .76))
            elif k == 'plus':
                line(P(.2, .5), P(.8, .5))
                line(P(.5, .2), P(.5, .8))
            elif k == 'minus':
                line(P(.2, .5), P(.8, .5))
            elif k == 'down':
                line(P(.2, .62), P(.5, .34), P(.8, .62))
            elif k == 'up':
                line(P(.2, .38), P(.5, .66), P(.8, .38))
            elif k == 'retry':
                cx, cy, r = x + .5 * s, y + .5 * s, .30 * s
                Line(circle=(cx, cy, r, 25, 315), width=lw, cap='round')
                ang = math.radians(315)               # arc end (clockwise from top)
                ex, ey = cx + r * math.sin(ang), cy + r * math.cos(ang)
                tx, ty = math.cos(ang), -math.sin(ang)     # direction of travel
                rx, ry = math.sin(ang), math.cos(ang)      # outwards
                h = .19 * s
                Triangle(points=[ex + tx * h, ey + ty * h,
                                 ex + rx * h * .85, ey + ry * h * .85,
                                 ex - rx * h * .85, ey - ry * h * .85])
            elif k == 'paste':
                Line(rounded_rectangle=(x + .22 * s, y + .10 * s, .56 * s,
                                        .68 * s, dp(2)), width=lw)
                line(P(.38, .78), P(.38, .88), P(.62, .88), P(.62, .78))
            elif k == 'logo':          # accent disc with a download arrow
                Color(*C(ACCENT))
                Ellipse(pos=(x, y), size=(s, s))
                Color(*C(ON_ACCENT))
                lw2 = max(dp(2.2), s * 0.09)
                Line(points=[x + .5 * s, y + .70 * s, x + .5 * s, y + .36 * s],
                     width=lw2, cap='round')
                Line(points=[x + .34 * s, y + .50 * s, x + .5 * s, y + .33 * s,
                             x + .66 * s, y + .50 * s],
                     width=lw2, cap='round', joint='round')


# ---- buttons -----------------------------------------------------------------------
class Btn(ButtonBehavior, AnchorLayout):
    """A rounded button with an optional drawn icon. `text` can be changed."""

    def __init__(self, text='', icon=None, bg=SURFACE2, fg=TEXT, radius=14,
                 size=14, bold=True, **kw):
        super().__init__(anchor_x='center', anchor_y='center', **kw)
        self._bg, self._fg = C(bg), C(fg)
        with self.canvas.before:
            self._col = Color(*self._bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync, state=self._paint,
                  disabled=self._dim)
        self._inner = BoxLayout(size_hint=(None, None), spacing=dp(8),
                                height=dp(24))
        self.icon = None
        if icon:
            self.icon = Icon(icon, fg, size=(dp(18), dp(18)),
                             pos_hint={'center_y': .5})
            self._inner.add_widget(self.icon)
        self.label = Label(text=text, color=self._fg, font_size=sp(size),
                           bold=bold, size_hint=(None, 1))
        self.label.bind(texture_size=self._fit)
        self._inner.add_widget(self.label)
        self.add_widget(self._inner)
        self._fit()

    @property
    def text(self):
        return self.label.text

    @text.setter
    def text(self, value):
        self.label.text = value

    def _fit(self, *a):
        self.label.width = self.label.texture_size[0]
        self._inner.width = self.label.width + (dp(26) if self.icon else 0)

    def _sync(self, *a):
        self._rect.pos, self._rect.size = self.pos, self.size

    def _paint(self, *a):
        r, g, b, al = self._bg
        k = 0.78 if self.state == 'down' else 1.0
        self._col.rgba = (r * k, g * k, b * k, al)

    def _dim(self, w, disabled):
        self.opacity = 0.4 if disabled else 1

    def set_style(self, bg=None, fg=None):
        if bg is not None:
            self._bg = C(bg)
        if fg is not None:
            self._fg = C(fg)
            self.label.color = self._fg
            if self.icon:
                self.icon.set_color(fg)
        self._paint()


class Seg(Surface):
    """Segmented control. `text` is the selected option; `labels` can differ."""

    def __init__(self, options, selected=0, on_select=None, size=13, **kw):
        super().__init__(bg=SURFACE2, radius=14, padding=dp(4), spacing=dp(4),
                         size_hint_y=None, height=dp(44), **kw)
        self.options = list(options)
        self.labels = list(options)
        self.index = selected
        self.on_select = on_select
        self.buttons = []
        for i, name in enumerate(options):
            b = Btn(text=name, bg=(0, 0, 0, 0), fg=MUTED, radius=11, size=size)
            b.bind(on_release=lambda w, i=i: self.select(i))
            self.buttons.append(b)
            self.add_widget(b)
        self._style()

    def _style(self):
        for i, b in enumerate(self.buttons):
            on = i == self.index
            b.set_style(bg=ACCENT if on else (0, 0, 0, 0),
                        fg=ON_ACCENT if on else MUTED)

    def select(self, i, fire=True):
        self.index = i
        self._style()
        if fire and self.on_select:
            self.on_select(i, self.options[i])

    @property
    def text(self):
        return self.options[self.index]

    @text.setter
    def text(self, value):
        if value in self.options:
            self.select(self.options.index(value), fire=False)

    def set_label(self, i, text):
        self.labels[i] = text
        self.buttons[i].text = text


class Chip(Label):
    """A small coloured pill, e.g. a status."""

    def __init__(self, text='', color=ACCENT, size=11, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('height', dp(24))
        super().__init__(text=text, font_size=sp(size), bold=True, **kw)
        self.color = C(color)
        with self.canvas.before:
            self._col = Color(*C(color, 0.16))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[dp(12)])
        self.bind(texture_size=self._fit, pos=self._sync, size=self._sync)
        self._fit()

    def set_color(self, color):
        self.color = C(color)
        self._col.rgba = C(color, 0.16)

    def _fit(self, *a):
        self.width = self.texture_size[0] + dp(20)

    def _sync(self, *a):
        self._rect.pos, self._rect.size = self.pos, self.size


class PillProgress(Widget):
    """A rounded progress bar. Setting `value` (0..1) glides to the new value."""
    value = NumericProperty(0)
    shown = NumericProperty(0.0)          # what is currently drawn

    def __init__(self, color=ACCENT, track=SURFACE2, height=8, **kw):
        kw.setdefault('size_hint_y', None)
        kw.setdefault('height', dp(height))
        super().__init__(**kw)
        with self.canvas:
            Color(*C(track))
            self._track = RoundedRectangle(radius=[dp(height) / 2])
            Color(*C(color))
            self._fill = RoundedRectangle(radius=[dp(height) / 2])
        self.bind(pos=self._draw, size=self._draw, shown=self._draw,
                  value=self._glide)
        self._draw()

    def _glide(self, w, v):
        Animation.cancel_all(self, 'shown')
        Animation(shown=max(0.0, min(1.0, v)), duration=0.25,
                  t='out_quad').start(self)

    def _draw(self, *a):
        self._track.pos, self._track.size = self.pos, self.size
        w = self.width * self.shown
        self._fill.pos = self.pos
        self._fill.size = (max(w, self.height) if self.shown > 0.001 else 0,
                           self.height)


class Cover(Widget):
    """A square picture with rounded corners; assign `texture`."""
    texture = ObjectProperty(None, allownone=True)

    def __init__(self, radius=12, **kw):
        super().__init__(**kw)
        with self.canvas:
            Color(*C(SURFACE2))
            self._ph = RoundedRectangle(radius=[dp(radius)])
            Color(1, 1, 1, 1)
            self._img = RoundedRectangle(radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *a):
        self._ph.pos, self._ph.size = self.pos, self.size
        self._img.pos = self.pos
        self._img.size = self.size if self.texture else (0, 0)

    def on_texture(self, w, tex):
        self._img.texture = tex
        self._sync()


class Check(ButtonBehavior, Widget):
    """A round-cornered tick box (`active`, like Kivy's CheckBox)."""
    active = BooleanProperty(False)

    def __init__(self, active=False, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(26), dp(26)))
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, active=self._draw)
        self.active = active
        self._draw()

    def on_release(self):
        self.active = not self.active

    def _draw(self, *a):
        self.canvas.clear()
        s = min(self.width, self.height) * 0.82
        x = self.center_x - s / 2
        y = self.center_y - s / 2
        with self.canvas:
            if self.active:
                Color(*C(ACCENT))
                RoundedRectangle(pos=(x, y), size=(s, s), radius=[dp(7)])
                Color(*C(ON_ACCENT))
                Line(points=[x + .24 * s, y + .52 * s, x + .43 * s, y + .30 * s,
                             x + .78 * s, y + .72 * s],
                     width=max(dp(2), s * 0.11), cap='round', joint='round')
            else:
                Color(*C(FAINT))
                Line(rounded_rectangle=(x, y, s, s, dp(7)), width=dp(1.5))


def make_input(hint, icon='search', on_enter=None):
    """A rounded input with an icon. Returns (container, TextInput)."""
    box = Surface(bg=SURFACE2, radius=16, padding=(dp(14), 0, dp(6), 0),
                  spacing=dp(10), size_hint_y=None, height=dp(54))
    box.add_widget(Icon(icon, MUTED, size=(dp(20), dp(20)),
                        pos_hint={'center_y': .5}))
    ti = TextInput(hint_text=hint, multiline=False, font_size=sp(15),
                   background_normal='', background_active='',
                   background_disabled_normal='',
                   background_color=(0, 0, 0, 0), foreground_color=C(TEXT),
                   hint_text_color=C(FAINT), cursor_color=C(ACCENT),
                   selection_color=C(ACCENT, 0.35), padding=(0, 0),
                   write_tab=False)
    ti.bind(size=lambda *a: setattr(
        ti, 'padding_y', [max(0, (ti.height - ti.line_height) / 2), 0]))
    if on_enter:
        ti.bind(on_text_validate=lambda *a: on_enter())
    box.add_widget(ti)
    return box, ti
