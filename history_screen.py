"""history_screen.py - past downloads, each with Fill gaps and Redo all."""
import time

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import history
import ui_kit as K
from fonts import rich
from sheets import ActionSheet, Confirm
from ui_kit import text_label


class HistoryScreen(ModalView):
    def __init__(self, data_dir, on_run, **kw):
        """on_run(spec, mode): start the job again; mode is 'fill' or 'redo'."""
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.dir, self.on_run = data_dir, on_run
        root = BoxLayout(orientation='vertical', padding=dp(14),
                         spacing=dp(10))
        head = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        back = K.IconBtn('back', bg=K.SURFACE, size=44)
        back.bind(on_release=lambda *a: self.dismiss())
        head.add_widget(back)
        head.add_widget(text_label('[b]Past downloads[/b]', 20, K.TEXT))
        root.add_widget(head)
        sc = ScrollView(bar_width=dp(3))
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(8),
                               padding=(0, 0, 0, dp(10)))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        sc.add_widget(self.grid)
        root.add_widget(sc)
        self.add_widget(root)
        self._render()

    def _render(self):
        self.grid.clear_widgets()
        entries = history.entries(self.dir)
        if not entries:
            self.grid.add_widget(text_label(
                'Nothing yet. Finished downloads show up here.', 13, K.MUTED,
                height=60, halign='center'))
            return
        for e in entries:
            self.grid.add_widget(self._row(e))

    def _row(self, e):
        c = e['counts']
        total = c['done'] + c['skipped'] + c['failed']
        have = c['done'] + c['skipped']
        row = K.Surface(bg=K.SURFACE, radius=16, orientation='vertical',
                        size_hint_y=None, height=dp(122),
                        padding=dp(12), spacing=dp(6))
        t = text_label(rich(e['title']), 14.5, K.TEXT, bold=True, height=24)
        t.shorten = True
        t.shorten_from = 'right'
        row.add_widget(t)
        when = time.strftime('%d %b %Y, %H:%M', time.localtime(e['time']))
        line = f"{have} of {total} downloaded"
        if c['failed']:
            line += f"  -  {c['failed']} failed"
        row.add_widget(text_label(f'{line}\n{when}', 11.5, K.MUTED, height=36,
                                  valign='top'))
        btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        fill = K.Btn('Fill gaps', icon='download', bg=K.ACCENT,
                     fg=K.ON_ACCENT, size=12, radius=12)
        fill.bind(on_release=lambda *a, e=e: self._go(e, 'fill'))
        redo = K.Btn('Redo all', icon='retry', size=12, radius=12)
        redo.bind(on_release=lambda *a, e=e: Confirm(
            'Redo everything?',
            f"All {total} songs download again. This can take a long time. "
            'Your current files are only replaced when the new copy is '
            'complete.', lambda: self._go(e, 'redo'),
            yes_label='Redo all').open())
        rm = K.IconBtn('trash', bg=K.SURFACE2, fg=K.DANGER, size=40,
                       icon_scale=.5)
        rm.bind(on_release=lambda *a, e=e: (history.remove(self.dir, e['id']),
                                            self._render()))
        for w in (fill, redo, rm):
            btns.add_widget(w)
        row.add_widget(btns)
        return row

    def _go(self, entry, mode):
        self.dismiss()
        self.on_run(history.spec(entry), mode)
