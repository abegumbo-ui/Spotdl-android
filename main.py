"""
SpotDL Downloader - Kivy UI
Paste a link, press Go, watch every song download.
"""
import io
import json
import os
import threading
import time

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

import service as svc

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
        self.running = False
        self.output_path = None
        self.state_dir = None
        self.p = {}
        self._st = None             # last state read from the service
        self._mtime = None
        self._seen = {}             # what the screen is already showing
        self.queue_rows = []        # [(label, track)]
        self._done = 0
        self._total = 0
        self._failed = 0
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

        # Appears when a job finished with failed songs
        self.retry_btn = Button(
            text='', bold=True, font_size=sp(15), size_hint_y=None,
            height=0, opacity=0, disabled=True, background_normal='',
            background_color=(0.9, 0.55, 0.1, 1), color=(0, 0, 0, 1))
        self.retry_btn.bind(on_press=self.on_retry)
        self.add_widget(self.retry_btn)

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
        text = f'{self._done} of {total} finished  -  {total - self._done} left'
        if self._failed:
            text += f'  -  {self._failed} failed'
        self.overall_label.text = text

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
        text = escape_markup(f"{t.get('i', i) + 1}. {t['artist']} - {t['title']}")
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

    # ------------------------------------------- background download job
    def attach(self, state_dir):
        """Start watching the progress file written by the download service."""
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.p = svc.paths(state_dir)
        Clock.schedule_interval(self.poll, 0.5)

    def poll(self, dt):
        try:
            mtime = os.path.getmtime(self.p['state'])
            if mtime != self._mtime:
                with open(self.p['state']) as f:
                    self._st = json.load(f)
                self._mtime = mtime
        except (OSError, ValueError):
            pass
        st = self._st
        if not st:
            return
        # A download that stopped updating (phone killed it) is not running.
        alive = bool(st.get('running')) and \
            time.time() - st.get('updated', 0) < svc.STALE_AFTER
        if self.running != alive:
            self.running = alive
            self.go_btn.text = 'Cancel' if alive else 'Go'
        if st.get('running') and not alive and \
                self._seen.get('interrupted') != st.get('job'):
            self._seen['interrupted'] = st.get('job')
            self.set_status('The download was interrupted. Press Go to resume.')
        if st.get('seq') != self._seen.get('seq'):
            self._seen['seq'] = st.get('seq')
            self._apply(st)

    def _apply(self, st):
        seen = self._seen
        win = st.get('win') or {'kind': 'window', 'rows': []}
        rows_in = win['rows']
        sig = (st.get('job'), win['kind'], tuple(r['i'] for r in rows_in))
        if sig != seen.get('queue_sig'):
            seen['queue_sig'] = sig
            seen['rows'] = {}
            self.queue_tab.text = ('Failed songs' if win['kind'] == 'failed'
                                   else 'Songs')
            self.set_queue([{'artist': r['a'], 'title': r['t'], 'i': r['i']}
                            for r in rows_in])
        rows = seen.setdefault('rows', {})
        for k, q in enumerate(rows_in):
            key = (q['s'], q['n'])
            if rows.get(k) != key:
                rows[k] = key
                self.set_track_state(k, q['s'], q['n'])
        counts = st.get('counts') or {}
        failed = counts.get('failed', 0)
        if failed != self._failed:
            self._failed = failed
            self._refresh_overall()
        retry_ok = bool(st.get('can_retry')) and not self.running
        retry_key = (retry_ok, failed)
        if retry_key != seen.get('retry'):
            seen['retry'] = retry_key
            self.retry_btn.text = (f'Retry {failed} failed song'
                                   f'{"" if failed == 1 else "s"}')
            self.retry_btn.height = dp(44) if retry_ok else 0
            self.retry_btn.opacity = 1 if retry_ok else 0
            self.retry_btn.disabled = not retry_ok
        if (st['done'], st['total']) != seen.get('overall'):
            seen['overall'] = (st['done'], st['total'])
            self.set_overall(st['done'], st['total'])
        if self.running is False and st.get('finished') and failed:
            self._failed = failed
        if st['progress'] != seen.get('progress'):
            seen['progress'] = st['progress']
            self.set_progress(st['progress'])
        if st['status'] != seen.get('status') and \
                seen.get('interrupted') != st.get('job'):
            seen['status'] = st['status']
            self.set_status(st['status'])
        now = st.get('now')
        if now and now['ver'] != seen.get('cover_ver'):
            seen['cover_ver'] = now['ver']
            data = None
            if now.get('cover'):
                try:
                    with open(self.p['cover'], 'rb') as f:
                        data = f.read()
                except OSError:
                    pass
            self.set_now(now, data)
        log = st.get('log') or []
        if len(log) != seen.get('log_len') or \
                (log and log[-1] != seen.get('log_last')):
            seen['log_len'], seen['log_last'] = len(log), log[-1] if log else None
            colors = {'info': 'cccccc', 'success': '1DB954',
                      'error': 'F44336', 'warning': 'FF9800'}
            self.log_lines = [
                f'[color={colors.get(k, "cccccc")}]{escape_markup(m)}[/color]'
                for m, k in log]
            self.log_label.text = '\n'.join(self.log_lines)
            Clock.schedule_once(
                lambda dt: setattr(self.log_scroll, 'scroll_y', 0), 0.1)
        if st.get('report') != seen.get('report'):
            seen['report'] = st.get('report')
            if st.get('report'):
                self.set_report(st['report'])

    # ------------------------------------------------------ actions
    def on_go(self, *args):
        if self.running:
            # The button doubles as Cancel while a download is running.
            open(self.p['cancel'], 'w').close()
            self.set_status('Cancelling...')
            return
        link = self.link_input.text.strip()
        if not link:
            self.set_status('Paste a link first.')
            return
        self._begin_job({'link': link})

    def on_retry(self, *args):
        """Download again only the songs that failed in the last job."""
        if not self.running and os.path.exists(self.p['failed']):
            self._begin_job({'retry': True})

    def _begin_job(self, extra):
        self.prepare_folder()
        # Clear the screen for the new job
        self.track_bar.value = 0
        self.overall_bar.value = 0
        self.overall_label.text = ''
        self.report_label.text = ''
        self.queue_grid.clear_widgets()
        self.queue_rows = []
        for w in (self.now_title, self.now_artist, self.now_album):
            w.text = ''
        self.cover.texture = None
        self._done = self._total = self._failed = 0
        self.retry_btn.height, self.retry_btn.opacity = 0, 0
        self.retry_btn.disabled = True
        self.log_lines.clear()
        self.log_label.text = ''
        self._seen = {}
        # Hand the job to the background service
        job = dict({'id': time.time(), 'output': self.output_path,
                    'format': self.format_spinner.text,
                    'data_dir': App.get_running_app().user_data_dir}, **extra)
        try:
            os.remove(self.p['cancel'])
        except OSError:
            pass
        with open(self.p['job'], 'w') as f:
            json.dump(job, f)
        self._st = {'job': job['id'], 'running': True, 'status': 'Starting...',
                    'progress': 0.0, 'done': 0, 'total': 0, 'win': None,
                    'now': None, 'log': [], 'report': '', 'seq': -1,
                    'updated': time.time()}
        self._mtime = None
        try:                      # make the first poll show the fresh state
            os.remove(self.p['state'])
        except OSError:
            pass
        self.running = True
        self.go_btn.text = 'Cancel'
        self.set_status('Starting... you can leave the app; it keeps going.')
        self._start_job(self.p['job'])

    def _start_job(self, job_path):
        if platform == 'android':
            try:
                from jnius import autoclass
                activity = autoclass('org.kivy.android.PythonActivity').mActivity
                service = autoclass('com.spotdlapp.spotdl.ServiceDownloader')
                service.start(activity, '', 'SpotDL Downloader',
                              'Downloading in the background', job_path)
                return
            except Exception as e:
                self.log(f'Background service unavailable ({e}); '
                         'downloading inside the app instead.', 'warning')
        threading.Thread(target=svc.run_job, args=(job_path,),
                         daemon=True).start()


class SpotDLApp(App):
    title = 'SpotDL Downloader'

    def build(self):
        self.layout = SpotDLLayout()
        # Progress files shared with the background download service. (The
        # service also updates yt-dlp / ytmusicapi at the start of each job.)
        self.layout.attach(os.path.join(self.user_data_dir, 'jobs'))
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                perms = [Permission.WRITE_EXTERNAL_STORAGE,
                         Permission.READ_EXTERNAL_STORAGE]
                if hasattr(Permission, 'READ_MEDIA_AUDIO'):
                    perms.append(Permission.READ_MEDIA_AUDIO)
                # Android 13+: needed to show the "downloading" notification
                perms.append('android.permission.POST_NOTIFICATIONS')
                request_permissions(perms, self._on_permissions)
            except Exception:
                pass
        # Create the folder straight away (works on Android 10 and below,
        # or once All files access has been granted).
        Clock.schedule_once(lambda dt: self.layout.prepare_folder(), 0)
        return self.layout

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
