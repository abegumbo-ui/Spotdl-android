"""settings_screen.py - Settings: songs at once, updates, fixing and redoing
downloads, and past downloads."""
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import settings as S
import ui_kit as K
import updater
from fonts import rich
from ui_kit import text_label


def _card(title):
    c = K.Surface(bg=K.SURFACE, radius=18, orientation='vertical',
                  padding=dp(14), spacing=dp(8), size_hint_y=None)
    c.add_widget(text_label(f'[b]{rich(title)}[/b]', 14.5, K.TEXT, height=26))
    c._h = dp(26 + 28)
    return c


def _put(card, widget, h):
    card.add_widget(widget)
    card._h += dp(h) + dp(8)
    card.height = card._h


class SettingsScreen(ModalView):
    def __init__(self, data_dir, get_library, on_redo, on_history, **kw):
        """on_redo(items, title) starts a redo job; on_history() opens the
        past-downloads page."""
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background='',
                         background_color=K.C(K.BG), **kw)
        self.dir = data_dir
        self.get_library = get_library
        self.on_redo = on_redo
        self.on_history = on_history
        self.conf = S.load(data_dir)
        self.broken = []
        root = BoxLayout(orientation='vertical', padding=dp(14),
                         spacing=dp(10))
        head = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        back = K.IconBtn('back', bg=K.SURFACE, size=44)
        back.bind(on_release=lambda *a: self.dismiss())
        head.add_widget(back)
        head.add_widget(text_label('[b]Settings[/b]', 22, K.TEXT))
        root.add_widget(head)
        sc = ScrollView(bar_width=dp(3))
        self.col = GridLayout(cols=1, size_hint_y=None, spacing=dp(12),
                              padding=(0, 0, 0, dp(20)))
        self.col.bind(minimum_height=self.col.setter('height'))
        sc.add_widget(self.col)
        root.add_widget(sc)
        self.add_widget(root)
        self._downloads()
        self._updates()
        self._repair()

    # ---- downloads
    def _downloads(self):
        c = _card('Downloads')
        _put(c, text_label(
            'Songs downloaded at the same time. More is faster, but '
            'uses more battery and YouTube may slow you down. 3 is a good '
            'balance.', 11.5, K.MUTED, height=50, valign='top'), 50)
        seg = K.Seg(['1', '2', '3', '4', '5'],
                    selected=self.conf['workers'] - 1,
                    on_select=lambda i, n: self._set(workers=i + 1))
        _put(c, seg, 44)
        self.col.add_widget(c)

    def _set(self, **kw):
        self.conf = S.save(self.dir, **kw)

    # ---- updates
    def _updates(self):
        c = _card('Updates')
        self.versions = text_label('', 12, K.MUTED, height=40, valign='top')
        _put(c, self.versions, 40)
        self.auto = K.Btn('', size=13, size_hint_y=None, height=dp(44))
        self.auto.bind(on_release=self._toggle_auto)
        _put(c, self.auto, 44)
        self.upd_btn = K.Btn('Check for updates now', icon='retry', size=13,
                             size_hint_y=None, height=dp(44))
        self.upd_btn.bind(on_release=self._check_now)
        _put(c, self.upd_btn, 44)
        self.upd_status = text_label('', 11.5, K.MUTED, height=34,
                                     valign='top')
        _put(c, self.upd_status, 34)
        self.col.add_widget(c)
        self._paint_updates()

    def _paint_updates(self):
        v = updater.versions(self.dir)
        last = self.conf['last_update_check']
        when = time.strftime('%d %b, %H:%M', time.localtime(last)) if last \
            else 'never'
        self.versions.text = (f"yt-dlp {v['yt-dlp']}    ytmusicapi "
                              f"{v['ytmusicapi']}\nLast checked: {when}")
        on = self.conf['auto_update']
        self.auto.text = ('Automatic check once a day: ON' if on
                          else 'Automatic check once a day: OFF')
        self.auto.set_style(bg=K.ACCENT if on else K.SURFACE2,
                            fg=K.ON_ACCENT if on else K.TEXT)

    def _toggle_auto(self, *a):
        self._set(auto_update=not self.conf['auto_update'])
        self._paint_updates()

    def _check_now(self, *a):
        self.upd_btn.disabled = True
        self.upd_status.text = 'Checking...'
        self.upd_status.color = K.C(K.MUTED)
        lines = []

        def log(msg, kind='info'):
            lines.append(str(msg))

        def work():
            updater.check_and_update(self.dir, log, force=True)
            Clock.schedule_once(lambda dt: self._checked(lines))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, lines):
        self.conf = S.load(self.dir)
        self.upd_btn.disabled = False
        bad = [l for l in lines if l.startswith('Could not')]
        self.upd_status.text = rich(' '.join(lines[-2:]) or 'Done.')
        self.upd_status.color = K.C(K.WARN if bad else K.ACCENT)
        self._paint_updates()

    # ---- repair, redo, history
    def _repair(self):
        c = _card('Fix and redo')
        hist = K.Btn('Past downloads  (fill gaps / redo)', icon='queue',
                     size=13, size_hint_y=None, height=dp(44))
        hist.bind(on_release=lambda *a: (self.dismiss(), self.on_history()))
        _put(c, hist, 44)
        scan = K.Btn('Check my library for broken songs', icon='search',
                     size=13, size_hint_y=None, height=dp(44))
        scan.bind(on_release=self._scan)
        _put(c, scan, 44)
        self.scan_status = text_label('', 11.5, K.MUTED, height=34,
                                      valign='top')
        _put(c, self.scan_status, 34)
        self.redo_btn = K.Btn('', icon='download', bg=K.ACCENT,
                              fg=K.ON_ACCENT, size=13, size_hint_y=None,
                              height=0, opacity=0, disabled=True)
        self.redo_btn.bind(on_release=self._redo_broken)
        c.add_widget(self.redo_btn)
        self._redo_card = c
        self.upg = K.Btn('', size=13, size_hint_y=None, height=dp(44))
        self.upg.bind(on_release=self._toggle_upgrade)
        _put(c, self.upg, 44)
        _put(c, text_label(
            'Upgrade mode: when you download something you already have, '
            'also redo songs that have no cover art or were saved in a '
            'different format than the one selected now.', 11, K.FAINT,
            height=62, valign='top'), 62)
        self.col.add_widget(c)
        self._paint_upgrade()

    def _paint_upgrade(self):
        on = self.conf['upgrade_mode']
        self.upg.text = f"Upgrade mode: {'ON' if on else 'OFF'}"
        self.upg.set_style(bg=K.ACCENT if on else K.SURFACE2,
                           fg=K.ON_ACCENT if on else K.TEXT)

    def _toggle_upgrade(self, *a):
        self._set(upgrade_mode=not self.conf['upgrade_mode'])
        self._paint_upgrade()

    def _scan(self, *a):
        lib = self.get_library()
        self.scan_status.text = 'Reading your songs...'
        self.scan_status.color = K.C(K.MUTED)

        def done():
            Clock.schedule_once(lambda dt: self._scanned(lib))
        lib.scan(done)

    def _scanned(self, lib):
        self.broken = lib.find_broken()
        n = len(self.broken)
        total = len(lib.songs)
        if not n:
            self.scan_status.text = f'All {total} songs look complete.'
            self.scan_status.color = K.C(K.ACCENT)
            self.redo_btn.height, self.redo_btn.opacity = 0, 0
            self.redo_btn.disabled = True
            return
        self.scan_status.text = (f'{n} of {total} songs look broken '
                                 '(empty, very short or unreadable).')
        self.scan_status.color = K.C(K.WARN)
        self.redo_btn.text = f"Redo {n} broken song{'s' if n != 1 else ''}"
        self.redo_btn.height, self.redo_btn.opacity = dp(44), 1
        self.redo_btn.disabled = False

    def _redo_broken(self, *a):
        items = self.get_library().repair_items(self.broken)
        self.dismiss()
        self.on_redo(items, 'Repair broken songs')
