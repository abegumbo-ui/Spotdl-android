"""
SpotDL Downloader - Kivy UI
Paste a link, press Go, watch every song download.
"""
import io
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import platform, escape_markup

Window.clearcolor = (0.05, 0.05, 0.05, 1)

FOLDER_NAME = 'SpotDL Downloader'
MAX_LOG_LINES = 300
GREEN = (0.11, 0.73, 0.33, 1)

# state -> (label, hex colour)
STATES = {
    'pending': ('waiting', '777777'),
    'active': ('downloading', '1DB954'),
    'done': ('done', '1DB954'),
    'skipped': ('had it', '999999'),
    'failed': ('FAILED', 'F44336'),
}


def _text_label(text, size, color, height, **kw):
    lbl = Label(text=text, font_size=sp(size), color=color, size_hint_y=None,
                height=dp(height), halign='left', valign='middle', **kw)
    lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
    return lbl


# --------------------------------------------------------------------------
# Storage: create "SpotDL Downloader" in internal storage
# --------------------------------------------------------------------------
def has_all_files_access():
    """True when Android 11+ 'All files access' is granted (or not needed)."""
    if platform != 'android':
        return True
    try:
        from jnius import autoclass
        Build = autoclass('android.os.Build$VERSION')
        if Build.SDK_INT < 30:
            return True
        Environment = autoclass('android.os.Environment')
        return bool(Environment.isExternalStorageManager())
    except Exception:
        return False


def open_all_files_settings():
    try:
        from jnius import autoclass
        Intent = autoclass('android.content.Intent')
        Settings = autoclass('android.provider.Settings')
        Uri = autoclass('android.net.Uri')
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        intent = Intent(
            Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
            Uri.parse('package:' + activity.getPackageName()))
        activity.startActivity(intent)
    except Exception:
        pass


def internal_storage_root():
    if platform == 'android':
        try:
            from android.storage import primary_external_storage_path
            return primary_external_storage_path()
        except Exception:
            return '/storage/emulated/0'
    return os.path.expanduser('~')


def _writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, '.write_test')
        with open(probe, 'w') as f:
            f.write('ok')
        os.remove(probe)
        return True
    except Exception:
        return False


class SpotDLLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', padding=dp(16),
                         spacing=dp(8), **kwargs)
        self.log_lines = []
        self.cancel_requested = False
        self.running = False
        self.output_path = None
        self.queue_rows = []        # [(label, track)]
        self._done = 0
        self._total = 0
        self._frac = 0.0
        self._build_ui()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        self.add_widget(_text_label(
            '[b][color=1DB954]SpotDL[/color][/b]  Downloader', 22,
            (1, 1, 1, 1), 40, markup=True))

        self.link_input = TextInput(
            hint_text='Paste a link (YouTube, YouTube Music, Spotify)',
            multiline=False, size_hint_y=None, height=dp(48),
            background_color=(0.12, 0.12, 0.12, 1),
            foreground_color=(0.95, 0.95, 0.95, 1),
            hint_text_color=(0.45, 0.45, 0.45, 1),
            cursor_color=GREEN, font_size=sp(15),
            padding=(dp(12), dp(13)), write_tab=False)
        self.link_input.bind(on_text_validate=self.on_go)
        self.add_widget(self.link_input)

        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.format_spinner = Spinner(
            text='mp3', values=['mp3', 'm4a', 'opus'], size_hint_x=0.3,
            background_color=(0.2, 0.2, 0.2, 1), font_size=sp(15))
        self.go_btn = Button(
            text='Go', bold=True, font_size=sp(18),
            background_normal='', background_color=GREEN,
            color=(0, 0, 0, 1))
        self.go_btn.bind(on_press=self.on_go)
        row.add_widget(self.format_spinner)
        row.add_widget(self.go_btn)
        self.add_widget(row)

        self.path_label = _text_label('', 11, (0.5, 0.5, 0.5, 1), 30)
        self.add_widget(self.path_label)

        # "Now downloading" card: cover art + details
        card = BoxLayout(size_hint_y=None, height=dp(104), spacing=dp(12))
        self.cover = Image(size_hint=(None, 1), width=dp(104),
                           allow_stretch=True, keep_ratio=True)
        card.add_widget(self.cover)
        info = BoxLayout(orientation='vertical')
        self.now_title = _text_label('', 16, (1, 1, 1, 1), 30, bold=True)
        self.now_artist = _text_label('', 13, (0.75, 0.75, 0.75, 1), 24)
        self.now_album = _text_label('', 12, (0.5, 0.5, 0.5, 1), 22)
        self.status_label = _text_label('Ready', 13, GREEN, 28)
        for w in (self.now_title, self.now_artist, self.now_album,
                  self.status_label):
            info.add_widget(w)
        card.add_widget(info)
        self.add_widget(card)

        self.track_bar = ProgressBar(max=1, value=0, size_hint_y=None,
                                     height=dp(8))
        self.add_widget(self.track_bar)

        self.overall_label = _text_label('', 13, (0.9, 0.9, 0.9, 1), 24)
        self.add_widget(self.overall_label)
        self.overall_bar = ProgressBar(max=1, value=0, size_hint_y=None,
                                       height=dp(8))
        self.add_widget(self.overall_bar)

        # Queue / Log switcher
        tabs = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        self.queue_tab = ToggleButton(text='Songs', group='view',
                                      state='down', allow_no_selection=False)
        self.log_tab = ToggleButton(text='Log', group='view',
                                    allow_no_selection=False)
        for tab in (self.queue_tab, self.log_tab):
            tab.background_normal = ''
            tab.background_down = ''
            tab.bind(state=self._tab_colour)
            self._tab_colour(tab, tab.state)
        self.queue_tab.bind(on_press=lambda *a: self._show('queue'))
        self.log_tab.bind(on_press=lambda *a: self._show('log'))
        tabs.add_widget(self.queue_tab)
        tabs.add_widget(self.log_tab)
        self.add_widget(tabs)

        self.body = BoxLayout()
        self.queue_scroll = ScrollView()
        self.queue_grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.queue_grid.bind(minimum_height=self.queue_grid.setter('height'))
        self.queue_scroll.add_widget(self.queue_grid)

        self.log_scroll = ScrollView()
        self.log_label = Label(
            text='', markup=True, font_size=sp(12), size_hint_y=None,
            halign='left', valign='top', color=(0.8, 0.8, 0.8, 1))
        self.log_label.bind(texture_size=lambda w, s: setattr(w, 'height', s[1]))
        self.log_label.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)))
        self.log_scroll.add_widget(self.log_label)

        self.body.add_widget(self.queue_scroll)
        self.add_widget(self.body)

        self.report_label = _text_label('', 11, (0.6, 0.8, 0.6, 1), 36)
        self.add_widget(self.report_label)

    @staticmethod
    def _tab_colour(tab, state):
        tab.background_color = GREEN if state == 'down' else (0.2, 0.2, 0.2, 1)
        tab.color = (0, 0, 0, 1) if state == 'down' else (0.8, 0.8, 0.8, 1)

    def _show(self, which):
        self.body.clear_widgets()
        self.body.add_widget(self.queue_scroll if which == 'queue'
                             else self.log_scroll)

    # ---------------------------------------------------- UI updates
    # All of these are safe to call from the download thread.
    def log(self, msg, kind='info'):
        colors = {'info': 'cccccc', 'success': '1DB954',
                  'error': 'F44336', 'warning': 'FF9800'}
        line = f'[color={colors.get(kind, "cccccc")}]{escape_markup(str(msg))}[/color]'
        Clock.schedule_once(lambda dt: self._append_log(line))

    def _append_log(self, line):
        self.log_lines.append(line)
        del self.log_lines[:-MAX_LOG_LINES]
        self.log_label.text = '\n'.join(self.log_lines)
        Clock.schedule_once(lambda dt: setattr(self.log_scroll, 'scroll_y', 0), 0.1)

    def set_status(self, text):
        Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', text))

    def set_progress(self, fraction):
        def apply(dt):
            self._frac = max(0.0, min(1.0, fraction))
            self.track_bar.value = self._frac
            self._refresh_overall()
        Clock.schedule_once(apply)

    def set_overall(self, done, total):
        def apply(dt):
            self._done, self._total = done, total
            self._frac = 0.0
            self._refresh_overall()
        Clock.schedule_once(apply)

    def _refresh_overall(self):
        total = self._total
        if not total:
            self.overall_label.text = ''
            self.overall_bar.value = 0
            return
        self.overall_bar.value = min(1.0, (self._done + self._frac) / total)
        self.overall_label.text = (f'{self._done} of {total} done  -  '
                                   f'{total - self._done} left')

    def set_queue(self, tracks):
        def apply(dt):
            self.queue_grid.clear_widgets()
            self.queue_rows = []
            for i, t in enumerate(tracks):
                row = BoxLayout(size_hint_y=None, height=dp(28))
                state = Label(markup=True, font_size=sp(13), size_hint_x=None,
                              width=dp(96), halign='left', valign='middle')
                name = Label(markup=True, font_size=sp(13), halign='left',
                             valign='middle', shorten=True,
                             shorten_from='right', color=(0.85, 0.85, 0.85, 1))
                for lbl in (state, name):
                    lbl.bind(size=lambda w, sz: setattr(w, 'text_size',
                                                        (sz[0], sz[1])))
                row.add_widget(state)
                row.add_widget(name)
                self.queue_rows.append((row, state, name, t))
                self._style_row(i, 'pending', '')
                self.queue_grid.add_widget(row)
        Clock.schedule_once(apply)

    def _style_row(self, i, state, note):
        row, state_lbl, name_lbl, t = self.queue_rows[i]
        word, colour = STATES[state]
        state_lbl.text = f'[color={colour}]{word}[/color]'
        text = escape_markup(f"{i + 1}. {t['artist']} - {t['title']}")
        if note:
            text += f'\n[color={colour}]{escape_markup(note)}[/color]'
            name_lbl.shorten = False
            row.height = dp(48)
        else:
            name_lbl.shorten = True
            row.height = dp(28)
        name_lbl.text = text

    def set_track_state(self, index, state, note=''):
        def apply(dt):
            if index < len(self.queue_rows):
                self._style_row(index, state, note)
                # Keep the active song in view, but only once the list is
                # longer than the screen (otherwise it jumps to the bottom).
                if state == 'active' and \
                        self.queue_grid.height > self.queue_scroll.height:
                    self.queue_scroll.scroll_to(self.queue_rows[index][0],
                                                padding=dp(60), animate=False)
        Clock.schedule_once(apply)

    def set_now(self, track, cover_bytes):
        """Show the song being downloaded and its cover art."""
        if track is None:
            return

        def apply(dt):
            self.now_title.text = track['title']
            self.now_artist.text = track['artist']
            self.now_album.text = track['album']
            self.cover.texture = None
            if cover_bytes:
                try:
                    ext = 'png' if cover_bytes[:4] == b'\x89PNG' else 'jpg'
                    self.cover.texture = CoreImage(
                        io.BytesIO(cover_bytes), ext=ext).texture
                except Exception:
                    pass
        Clock.schedule_once(apply)

    def set_report(self, path):
        Clock.schedule_once(lambda dt: setattr(
            self.report_label, 'text', f'PDF report saved:\n{path}'))

    # ----------------------------------------------------- storage
    def prepare_folder(self):
        """Create <internal storage>/SpotDL Downloader (or a fallback)."""
        target = os.path.join(internal_storage_root(), FOLDER_NAME)
        if _writable_dir(target):
            self.output_path = target
            self.path_label.text = f'Saving to: {target}'
            return True
        # No permission yet: fall back to the app's own storage.
        fallback = os.path.join(App.get_running_app().user_data_dir, FOLDER_NAME)
        os.makedirs(fallback, exist_ok=True)
        self.output_path = fallback
        self.path_label.text = (
            f'Saving to: {fallback}\nGrant "All files access" to use '
            f'{target}')
        return False

    # ------------------------------------------------------ actions
    def on_go(self, *args):
        if self.running:
            # The button doubles as Cancel while a download is running.
            self.cancel_requested = True
            self.set_status('Cancelling...')
            return
        link = self.link_input.text.strip()
        if not link:
            self.set_status('Paste a link first.')
            return
        self.prepare_folder()
        self.running = True
        self.cancel_requested = False
        self.go_btn.text = 'Cancel'
        self.track_bar.value = 0
        self.overall_bar.value = 0
        self.overall_label.text = ''
        self.report_label.text = ''
        self.queue_grid.clear_widgets()
        self.queue_rows = []
        for w in (self.now_title, self.now_artist, self.now_album):
            w.text = ''
        self.cover.texture = None
        self._done = self._total = 0
        self.log_lines.clear()
        self.log_label.text = ''
        self.set_status('Starting...')
        threading.Thread(
            target=self._run, args=(link, self.output_path,
                                    self.format_spinner.text),
            daemon=True).start()

    def _run(self, link, output, fmt):
        try:
            import spotdl_bridge
            spotdl_bridge.download(link, output, fmt, self)
        except Exception as e:
            self.log(f'Fatal error: {e}', 'error')
            self.set_status('Failed - see log')
        finally:
            Clock.schedule_once(self._finished)

    def _finished(self, *args):
        self.running = False
        self.go_btn.text = 'Go'


class SpotDLApp(App):
    title = 'SpotDL Downloader'

    def build(self):
        self.layout = SpotDLLayout()
        # Fetch the newest yt-dlp / ytmusicapi in the background. A download
        # started before this finishes simply waits for it.
        try:
            import updater
            updater.activate(self.user_data_dir)
            updater.start(self.user_data_dir, self._update_log)
        except Exception:
            pass
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                perms = [Permission.WRITE_EXTERNAL_STORAGE,
                         Permission.READ_EXTERNAL_STORAGE]
                if hasattr(Permission, 'READ_MEDIA_AUDIO'):
                    perms.append(Permission.READ_MEDIA_AUDIO)
                request_permissions(perms, self._on_permissions)
            except Exception:
                pass
        # Create the folder straight away (works on Android 10 and below,
        # or once All files access has been granted).
        Clock.schedule_once(lambda dt: self.layout.prepare_folder(), 0)
        return self.layout

    def _update_log(self, msg, kind='info'):
        self.layout.log(msg, kind)

    def _on_permissions(self, *args):
        # Android 11+ needs the special "All files access" switch to create a
        # folder in the root of internal storage.
        if not has_all_files_access():
            self.layout.log(
                'Please allow "All files access" for SpotDL so it can create '
                f'the "{FOLDER_NAME}" folder, then come back to the app.',
                'warning')
            open_all_files_settings()
        Clock.schedule_once(lambda dt: self.layout.prepare_folder(), 0)

    def on_resume(self):
        # Back from the settings screen: try creating the folder again.
        self.layout.prepare_folder()


if __name__ == '__main__':
    SpotDLApp().run()
