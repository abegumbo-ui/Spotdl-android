"""
SpotDL Downloader - Kivy UI
Paste a link, press Go, watch the progress.
"""
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform, escape_markup

Window.clearcolor = (0.05, 0.05, 0.05, 1)

FOLDER_NAME = 'SpotDL Downloader'
MAX_LOG_LINES = 300
GREEN = (0.11, 0.73, 0.33, 1)


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
                         spacing=dp(10), **kwargs)
        self.log_lines = []
        self.cancel_requested = False
        self.running = False
        self.output_path = None
        self._build_ui()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        title = _text_label(
            '[b][color=1DB954]SpotDL[/color][/b]  Downloader', 24,
            (1, 1, 1, 1), 48, markup=True)
        self.add_widget(title)

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

        self.path_label = _text_label('', 12, (0.5, 0.5, 0.5, 1), 34)
        self.add_widget(self.path_label)

        self.status_label = _text_label('Ready', 15, (1, 1, 1, 1), 44)
        self.add_widget(self.status_label)

        self.track_bar = ProgressBar(max=1, value=0, size_hint_y=None,
                                     height=dp(10))
        self.add_widget(self.track_bar)
        self.overall_label = _text_label('', 12, (0.6, 0.6, 0.6, 1), 24)
        self.add_widget(self.overall_label)

        self.add_widget(_text_label('LOG', 11, (0.4, 0.4, 0.4, 1), 20))
        self.scroll = ScrollView()
        self.log_label = Label(
            text='', markup=True, font_size=sp(12), size_hint_y=None,
            halign='left', valign='top', color=(0.8, 0.8, 0.8, 1))
        self.log_label.bind(texture_size=lambda w, s: setattr(w, 'height', s[1]))
        self.log_label.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)))
        self.scroll.add_widget(self.log_label)
        self.add_widget(self.scroll)

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
        Clock.schedule_once(lambda dt: setattr(self.scroll, 'scroll_y', 0), 0.1)

    def set_status(self, text):
        Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', text))

    def set_progress(self, fraction):
        Clock.schedule_once(
            lambda dt: setattr(self.track_bar, 'value', max(0, min(1, fraction))))

    def set_overall(self, done, total):
        Clock.schedule_once(lambda dt: setattr(
            self.overall_label, 'text', f'{done} of {total} tracks complete'))

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
        self.overall_label.text = ''
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
            Clock.schedule_once(self._done)

    def _done(self, *args):
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
