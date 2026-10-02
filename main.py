"""
SpotDL Artist Downloader - Kivy UI
"""
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform, escape_markup

import threading
import os

MAX_LOG_LINES = 300

Window.clearcolor = (0.05, 0.05, 0.05, 1)


class LogLabel(Label):
    pass


class SpotDLLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', padding=16, spacing=8, **kwargs)
        self.log_lines = []
        self._build_ui()

    def _build_ui(self):
        # Title
        title = Label(
            text='[b][color=1DB954]SpotDL[/color][/b]  Artist Downloader',
            markup=True, font_size='22sp', size_hint_y=None, height=48,
            halign='left', valign='middle'
        )
        title.bind(size=title.setter('text_size'))
        self.add_widget(title)

        # Artist input
        self.artist_input = TextInput(
            hint_text='Artist name (e.g. Kendrick Lamar)',
            multiline=False, size_hint_y=None, height=44,
            background_color=(0.1, 0.1, 0.1, 1),
            foreground_color=(0.9, 0.9, 0.9, 1),
            hint_text_color=(0.4, 0.4, 0.4, 1),
            cursor_color=(0.11, 0.73, 0.33, 1),
            font_name='RobotoMono-Regular',
            font_size='14sp'
        )
        self.add_widget(self.artist_input)

        # Format row
        fmt_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        fmt_label = Label(text='Format:', size_hint_x=None, width=70,
                          color=(0.6, 0.6, 0.6, 1), font_size='13sp')
        self.format_spinner = Spinner(
            text='m4a',
            values=['m4a', 'opus'],
            size_hint_x=0.3,
            background_color=(0.11, 0.73, 0.33, 1),
            color=(0, 0, 0, 1),
            font_size='13sp'
        )
        self.download_btn = Button(
            text='Download Artist',
            background_color=(0.11, 0.73, 0.33, 1),
            color=(0, 0, 0, 1),
            bold=True, font_size='14sp'
        )
        self.download_btn.bind(on_press=self.on_download)
        fmt_row.add_widget(fmt_label)
        fmt_row.add_widget(self.format_spinner)
        fmt_row.add_widget(self.download_btn)
        self.add_widget(fmt_row)

        # Output path label
        self.path_label = Label(
            text='Output: /sdcard/Music/SpotDL',
            color=(0.35, 0.35, 0.35, 1), font_size='11sp',
            size_hint_y=None, height=20,
            halign='left'
        )
        self.path_label.bind(size=self.path_label.setter('text_size'))
        self.add_widget(self.path_label)

        # Log area
        log_header = Label(
            text='LOG OUTPUT', color=(0.3, 0.3, 0.3, 1),
            font_size='10sp', size_hint_y=None, height=18,
            halign='left'
        )
        log_header.bind(size=log_header.setter('text_size'))
        self.add_widget(log_header)

        self.scroll = ScrollView()
        self.log_label = Label(
            text='', markup=True,
            font_name='RobotoMono-Regular',
            font_size='12sp',
            size_hint_y=None,
            halign='left', valign='top',
            color=(0.8, 0.8, 0.8, 1)
        )
        self.log_label.bind(texture_size=self.log_label.setter('size'))
        self.log_label.bind(width=lambda *x: self.log_label.setter('text_size')(
            self.log_label, (self.log_label.width, None)))
        self.scroll.add_widget(self.log_label)
        self.add_widget(self.scroll)

    def log(self, msg, kind='info'):
        color_map = {
            'info':    'cccccc',
            'success': '1DB954',
            'error':   'F44336',
            'warning': 'FF9800',
        }
        c = color_map.get(kind, 'cccccc')
        self.log_lines.append(f'[color={c}]{escape_markup(msg)}[/color]')
        del self.log_lines[:-MAX_LOG_LINES]
        Clock.schedule_once(self._refresh_log)

    def _refresh_log(self, *args):
        self.log_label.text = '\n'.join(self.log_lines)
        Clock.schedule_once(lambda *a: setattr(
            self.scroll, 'scroll_y', 0), 0.1)

    def on_download(self, *args):
        artist = self.artist_input.text.strip()
        if not artist:
            self.log('Please enter an artist name.', 'error')
            return

        self.download_btn.disabled = True
        self.download_btn.text = 'Downloading...'
        self.log_lines.clear()
        self.log(f'Starting: {artist}', 'info')

        fmt = self.format_spinner.text
        output = self._get_output_path()
        self.path_label.text = f'Output: {output}'

        threading.Thread(
            target=self._run_download,
            args=(artist, output, fmt),
            daemon=True
        ).start()

    def _get_output_path(self):
        candidates = []
        if platform == 'android':
            try:
                from android.storage import primary_external_storage_path
                candidates.append(os.path.join(
                    primary_external_storage_path(), 'Music', 'SpotDL'))
            except Exception:
                candidates.append('/sdcard/Music/SpotDL')
        else:
            candidates.append(os.path.join(
                os.path.expanduser('~'), 'Music', 'SpotDL'))
        # App-private fallback that is always writable.
        candidates.append(os.path.join(App.get_running_app().user_data_dir,
                                       'SpotDL'))
        for path in candidates:
            try:
                os.makedirs(path, exist_ok=True)
                probe = os.path.join(path, '.write_test')
                with open(probe, 'w') as f:
                    f.write('ok')
                os.remove(probe)
                return path
            except Exception:
                continue
        return candidates[-1]

    def _run_download(self, artist, output_path, fmt):
        try:
            import spotdl_bridge
            spotdl_bridge.download_artist(artist, output_path, fmt, self)
        except Exception as e:
            self.log(f'Fatal error: {e}', 'error')
        finally:
            Clock.schedule_once(self._done)

    def _done(self, *args):
        self.download_btn.disabled = False
        self.download_btn.text = 'Download Artist'


class SpotDLApp(App):
    def build(self):
        request_permissions([
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.INTERNET,
        ])
        return SpotDLLayout()


if __name__ == '__main__':
    SpotDLApp().run()
