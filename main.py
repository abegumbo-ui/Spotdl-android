"""
SpotDL Downloader - Kivy UI
Paste a link or search, press Download, watch every song download.
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
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import platform, escape_markup

import service as svc
import ui_kit as K
from fonts import rich
import player as PL
from player_ui import PlayButton, PlayerBar

try:                      # Android has no CA bundle Python can see
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
except ImportError:
    pass

Window.clearcolor = K.C(K.BG)

FOLDER_NAME = 'SpotDL Downloader'
MAX_LOG_LINES = 300
GO_LABEL = 'Download'
IDLE_TITLE = 'Nothing downloading'

# state -> (label, colour)
STATES = {
    'pending': ('Waiting', K.FAINT),
    'active': ('Downloading', K.INFO),
    'done': ('Done', K.ACCENT),
    'skipped': ('Had it', K.MUTED),
    'failed': ('Failed', K.DANGER),
}


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
        super().__init__(orientation='vertical', padding=(dp(16), dp(14)),
                         spacing=dp(10), **kwargs)
        self.log_lines = []
        self.running = False
        self.output_path = None
        self.state_dir = None
        self.p = {}
        self._st = None             # last state read from the service
        self._mtime = None
        self._seen = {}             # what the screen is already showing
        self.queue_rows = []        # [(row, chip, title, sub, track)]
        self._done = 0
        self._total = 0
        self._failed = 0
        self._frac = 0.0
        self._build_ui()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        # header
        head = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        head.add_widget(K.Icon('logo', size=(dp(38), dp(38)),
                               pos_hint={'center_y': .5}))
        head.add_widget(K.text_label(
            f'[b]SpotDL[/b]  [color={K.MUTED[1:]}]Downloader[/color]', 22))
        self.add_widget(head)

        # link box with a paste shortcut
        box, self.link_input = K.make_input(
            'Paste a link or type an artist name', 'search', on_enter=self.on_go)
        paste = K.Btn('Paste', bg=K.SURFACE, fg=K.MUTED, radius=10)
        paste.size_hint = (None, None)
        paste.size = (dp(66), dp(36))
        paste.pos_hint = {'center_y': .5}
        paste.label.font_size = sp(12)
        paste.bind(on_release=self.on_paste)
        box.add_widget(paste)
        self.add_widget(box)

        self.format_spinner = K.Seg(['mp3', 'm4a', 'opus'])
        self.add_widget(self.format_spinner)

        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        self.search_btn = K.Btn('Search', icon='search', size_hint_x=0.42)
        self.search_btn.bind(on_release=self.open_search)
        self.go_btn = K.Btn(GO_LABEL, icon='download', bg=K.ACCENT,
                            fg=K.ON_ACCENT, size=15)
        self.go_btn.bind(on_release=self.on_go)
        row.add_widget(self.search_btn)
        row.add_widget(self.go_btn)
        self.add_widget(row)

        # Appears when a job finished with failed songs
        self.retry_btn = K.Btn('', icon='retry', bg=K.WARN, fg='#2B1A00',
                               size_hint_y=None, height=0, opacity=0,
                               disabled=True)
        self.retry_btn.bind(on_release=self.on_retry)
        self.add_widget(self.retry_btn)

        self.path_label = K.text_label('', 10.5, K.FAINT, height=28)
        self.add_widget(self.path_label)

        # "Now downloading" card
        card = K.Surface(orientation='vertical', size_hint_y=None,
                         height=dp(216), padding=dp(14), spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(92), spacing=dp(14))
        self.cover = K.Cover(radius=14, size_hint=(None, None),
                             size=(dp(92), dp(92)))
        top.add_widget(self.cover)
        info = BoxLayout(orientation='vertical', spacing=dp(2))
        self.now_title = K.text_label(IDLE_TITLE, 16, K.TEXT, bold=True)
        self.now_title.shorten = True
        self.now_title.shorten_from = 'right'
        self.now_artist = K.text_label('', 13, K.MUTED)
        self.now_album = K.text_label('', 11.5, K.FAINT)
        self.status_label = K.text_label('Ready', 12, K.ACCENT)
        for w in (self.now_title, self.now_artist, self.now_album,
                  self.status_label):
            info.add_widget(w)
        top.add_widget(info)
        card.add_widget(top)
        self.track_bar = K.PillProgress(height=6, color=K.INFO)
        card.add_widget(self.track_bar)
        chips = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(6))
        self.chip_done = K.Chip('0 done', K.ACCENT, pos_hint={'center_y': .5})
        self.chip_left = K.Chip('0 left', K.MUTED, pos_hint={'center_y': .5})
        self.chip_failed = K.Chip('0 failed', K.DANGER,
                                  pos_hint={'center_y': .5})
        for c in (self.chip_done, self.chip_left, self.chip_failed):
            chips.add_widget(c)
        chips.add_widget(Widget())
        card.add_widget(chips)
        self.overall_bar = K.PillProgress(height=10)
        card.add_widget(self.overall_bar)
        self.add_widget(card)

        # Songs / Log switcher
        self.tabs = K.Seg(['Songs', 'Log'], on_select=self._on_tab)
        self.add_widget(self.tabs)

        self.body = BoxLayout()
        self.queue_scroll = ScrollView(bar_width=dp(3), scroll_type=['bars', 'content'])
        self.queue_grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6),
                                     padding=(0, 0, 0, dp(6)))
        self.queue_grid.bind(minimum_height=self.queue_grid.setter('height'))
        self.queue_scroll.add_widget(self.queue_grid)

        self.log_card = K.Surface(bg=K.SURFACE, radius=14, padding=dp(10))
        self.log_scroll = ScrollView(bar_width=dp(3))
        self.log_label = K.text_label('', 11, K.MUTED, mono=True,
                                      size_hint_y=None, valign='top')
        self.log_label.bind(
            texture_size=lambda w, s: setattr(w, 'height', s[1]),
            width=lambda w, v: setattr(w, 'text_size', (v, None)))
        self.log_scroll.add_widget(self.log_label)
        self.log_card.add_widget(self.log_scroll)

        self.body.add_widget(self.queue_scroll)
        self.add_widget(self.body)

        self.player_bar = PlayerBar()
        self.add_widget(self.player_bar)
        self.report_label = K.text_label('', 10.5, K.ACCENT_DIM, height=34)
        self.add_widget(self.report_label)
        self._refresh_overall()

    def _on_tab(self, index, name):
        self._show('queue' if index == 0 else 'log')

    def _show(self, which):
        self.body.clear_widgets()
        self.body.add_widget(self.queue_scroll if which == 'queue'
                             else self.log_card)

    def _set_go(self, running):
        """The main button is Download, or Cancel while a job runs."""
        self.go_btn.text = 'Cancel' if running else GO_LABEL
        self.go_btn.icon.kind = 'close' if running else 'download'
        self.go_btn.icon._draw()
        self.go_btn.set_style(bg=K.DANGER if running else K.ACCENT,
                              fg='#2B0509' if running else K.ON_ACCENT)

    def on_paste(self, *args):
        try:
            from kivy.core.clipboard import Clipboard
            text = (Clipboard.paste() or '').strip()
            if text:
                self.link_input.text = text
        except Exception:
            pass

    # ---------------------------------------------------- UI updates
    # All of these are safe to call from the download thread.
    def log(self, msg, kind='info'):
        colors = {'info': K.MUTED, 'success': K.ACCENT,
                  'error': K.DANGER, 'warning': K.WARN}
        line = (f'[color={colors.get(kind, K.MUTED)[1:]}]'
                f'{rich(str(msg))}[/color]')
        Clock.schedule_once(lambda dt: self._append_log(line))

    def _append_log(self, line):
        self.log_lines.append(line)
        del self.log_lines[:-MAX_LOG_LINES]
        self.log_label.text = '\n'.join(self.log_lines)
        Clock.schedule_once(lambda dt: setattr(self.log_scroll, 'scroll_y', 0), 0.1)

    def set_status(self, text):
        def apply(dt):
            self.status_label.text = rich(text)
            low = text.lower()
            bad = low.startswith('failed') or 'interrupted' in low
            warn = low.startswith('cancel') or 'first' in low
            self.status_label.color = K.C(
                K.DANGER if bad else K.WARN if warn else K.ACCENT)
        Clock.schedule_once(apply)

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
        self.overall_bar.value = (min(1.0, (self._done + self._frac) / total)
                                  if total else 0)
        self.chip_done.text = f'{self._done} of {total} finished' if total \
            else 'No job yet'
        self.chip_left.text = f'{max(0, total - self._done)} left'
        self.chip_left.opacity = 1 if total else 0
        self.chip_failed.text = f'{self._failed} failed'
        self.chip_failed.opacity = 1 if self._failed else 0

    def set_queue(self, tracks):
        def apply(dt):
            self.queue_grid.clear_widgets()
            self.queue_rows = []
            for i, t in enumerate(tracks):
                row = K.Surface(bg=K.SURFACE, radius=14, size_hint_y=None,
                                height=dp(62), padding=(dp(12), dp(8)),
                                spacing=dp(10))
                chip = K.Chip('Waiting', K.FAINT, pos_hint={'center_y': .5})
                col = BoxLayout(orientation='vertical')
                title = K.text_label('', 13, K.TEXT, bold=True)
                title.shorten = True
                title.shorten_from = 'right'
                sub = K.text_label('', 11, K.MUTED)
                col.add_widget(title)
                col.add_widget(sub)
                row.add_widget(chip)
                row.add_widget(col)
                play = PlayButton(None, lambda: None, size=36,
                                  pos_hint={'center_y': .5})
                play.opacity, play.disabled, play.width = 0, True, 0
                row.add_widget(play)
                t['play'] = play
                self.queue_rows.append((row, chip, title, sub, t))
                self._style_row(i, 'pending', '')
                self.queue_grid.add_widget(row)
        Clock.schedule_once(apply)

    def _style_row(self, i, state, note, path=''):
        row, chip, title, sub, t = self.queue_rows[i]
        play = t.get('play')
        if play is not None:
            has = bool(path) and state in ('done', 'skipped')
            play.opacity, play.disabled = (1 if has else 0), not has
            play.width = dp(36) if has else 0
            if has:
                play.key = ('file', path)
                play._play = lambda: PL.get().play_file(
                    path, t['title'], t['artist'], ('file', path))
                play._shown = None
        word, color = STATES[state]
        chip.text = word
        chip.set_color(color)
        title.text = rich(f"{t.get('i', i) + 1}. {t['title']}")
        artist = rich(t['artist'])
        if note:
            sub.text = (f'{artist}\n[color={color[1:]}]'
                        f'{rich(note)}[/color]')
            row.height = dp(88)
        else:
            sub.text = artist
            row.height = dp(62)
        row.set_bg(K.SURFACE2 if state == 'active' else K.SURFACE)

    def set_track_state(self, index, state, note='', path=''):
        def apply(dt):
            if index < len(self.queue_rows):
                self._style_row(index, state, note, path)
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
            self.now_title.text = rich(track['title'])
            self.now_artist.text = rich(track['artist'])
            self.now_album.text = rich(track['album'])
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
            self.report_label, 'text',
            f'PDF report saved: {rich(path)}'))

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
            self._set_go(alive)
        if st.get('running') and not alive and \
                self._seen.get('interrupted') != st.get('job'):
            self._seen['interrupted'] = st.get('job')
            self.set_status('The download was interrupted. Press Download to resume.')
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
            self.tabs.set_label(0, 'Failed songs' if win['kind'] == 'failed'
                                else 'Songs')
            self.set_queue([{'artist': r['a'], 'title': r['t'], 'i': r['i']}
                            for r in rows_in])
        rows = seen.setdefault('rows', {})
        for k, q in enumerate(rows_in):
            key = (q['s'], q['n'], q.get('p', ''))
            if rows.get(k) != key:
                rows[k] = key
                self.set_track_state(k, q['s'], q['n'], q.get('p', ''))
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
                f'[color={colors.get(k, "cccccc")}]{rich(m)}[/color]'
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

    def open_search(self, *args):
        """Search Spotify and YouTube Music and pick songs / artists."""
        if self.running:
            self.set_status('A download is running. Cancel it or wait for '
                            'it to finish before starting another.')
            return
        import search_screen
        search_screen.SearchScreen(
            on_download=self._download_picked,
            initial=self.link_input.text.strip()
            if not self.link_input.text.startswith('http') else '').open()

    def _download_picked(self, items, title):
        """Download the songs chosen on the search screen."""
        self._begin_job({'items': items, 'title': title})

    def on_retry(self, *args):
        """Download again only the songs that failed in the last job."""
        if not self.running and os.path.exists(self.p['failed']):
            self._begin_job({'retry': True})

    def _begin_job(self, extra):
        self.prepare_folder()
        # Clear the screen for the new job
        self.track_bar.value = 0
        self.overall_bar.value = 0
        self.report_label.text = ''
        self.queue_grid.clear_widgets()
        self.queue_rows = []
        self.now_title.text = 'Starting...'
        self.now_artist.text = self.now_album.text = ''
        self.cover.texture = None
        self._done = self._total = self._failed = 0
        self._refresh_overall()
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
        self._set_go(True)
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
        try:                      # search uses the newest downloaded ytmusicapi
            import updater
            updater.activate(self.user_data_dir)
        except Exception:
            pass
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
