"""sheets.py - small pop-up pieces: an action list, a text question, a confirm."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

import ui_kit as K
from fonts import rich


class _Base(ModalView):
    def __init__(self, title, subtitle='', **kw):
        super().__init__(size_hint=(.92, None), auto_dismiss=True,
                         background='', background_color=(0, 0, 0, .55), **kw)
        self.card = K.Surface(bg=K.SURFACE, radius=20, orientation='vertical',
                              padding=dp(14), spacing=dp(8),
                              size_hint_y=None)
        self.card.add_widget(K.text_label(rich(title), 16, K.TEXT, bold=True,
                                          height=28))
        if subtitle:
            self.card.add_widget(K.text_label(rich(subtitle), 12, K.MUTED,
                                              height=22))
        self._h = dp(28 + 28) + (dp(22) if subtitle else 0)
        self.add_widget(self.card)

    def _add(self, w, h):
        self.card.add_widget(w)
        self._h += h + dp(8)
        self.card.height = self._h
        self.height = self._h


class ActionSheet(_Base):
    def __init__(self, title, actions, subtitle='', **kw):
        """actions: [(label, icon, callback, colour or None)]"""
        super().__init__(title, subtitle, **kw)
        for label, icon, fn, color in actions:
            b = K.Btn(label, icon=icon, bg=K.SURFACE2,
                      fg=color or K.TEXT, size=14, size_hint_y=None,
                      height=dp(46))
            b.bind(on_release=lambda w, fn=fn: (self.dismiss(), fn()))
            self._add(b, dp(46))


class AskText(_Base):
    def __init__(self, title, hint, on_ok, ok_label='Create', **kw):
        super().__init__(title, **kw)
        box, self.input = K.make_input(hint, 'plus')
        box.size_hint_y = None
        box.height = dp(48)
        self._add(box, dp(48))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        cancel = K.Btn('Cancel', size=13)
        cancel.bind(on_release=lambda *a: self.dismiss())
        ok = K.Btn(ok_label, bg=K.ACCENT, fg=K.ON_ACCENT, size=13)
        ok.bind(on_release=lambda *a: (self.dismiss(),
                                       on_ok(self.input.text.strip())))
        row.add_widget(cancel)
        row.add_widget(ok)
        self._add(row, dp(46))
        self.pos_hint = {'center_y': .62}


class Confirm(_Base):
    def __init__(self, title, message, on_yes, yes_label='Delete', **kw):
        super().__init__(title, **kw)
        self._add(K.text_label(rich(message), 12.5, K.MUTED, height=44,
                               valign='top'), dp(44))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        no = K.Btn('Cancel', size=13)
        no.bind(on_release=lambda *a: self.dismiss())
        yes = K.Btn(yes_label, bg=K.DANGER, fg='#2B0408', size=13)
        yes.bind(on_release=lambda *a: (self.dismiss(), on_yes()))
        row.add_widget(no)
        row.add_widget(yes)
        self._add(row, dp(46))
