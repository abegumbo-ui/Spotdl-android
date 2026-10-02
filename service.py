"""
service.py - runs a download job in the background.

On Android this file is started by python-for-android as a *foreground
service* (see `services =` in buildozer.spec): it keeps running, with a
notification, when the app is closed or the screen is off. The app screen and
this service talk through small files in a shared folder:

    job.json        written by the app: what to download
    state.json      written by the service: progress, queue, log, ...
    now_cover.bin   cover art of the song being downloaded
    cancel          created by the app to ask the service to stop

The same code also runs in a plain thread (desktop, or if the service cannot
be started), so the app screen only ever reads state.json.
"""
import json
import os
import sys
import threading
import time
import traceback

try:                                   # make sibling modules importable
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass

LOG_LINES = 300
WINDOW = 40               # songs shown at a time (a playlist can have 10,000)
MAX_FAILED_SHOWN = 300
STALE_AFTER = 20          # seconds without a heartbeat = service is gone


# --------------------------------------------------------------------------
# Shared-file protocol
# --------------------------------------------------------------------------
def paths(state_dir):
    return {
        'job': os.path.join(state_dir, 'job.json'),
        'state': os.path.join(state_dir, 'state.json'),
        'cover': os.path.join(state_dir, 'now_cover.bin'),
        'cancel': os.path.join(state_dir, 'cancel'),
        'failed': os.path.join(state_dir, 'failed.json'),
    }


def _atomic_write(path, data, mode='w'):
    tmp = path + '.tmp'
    with open(tmp, mode) as f:
        f.write(data)
    os.replace(tmp, path)


class FileUI:
    """The `ui` object spotdl_bridge talks to. Instead of drawing widgets it
    records everything in state.json for the app screen to display."""

    def __init__(self, state_dir, job_id):
        self.p = paths(state_dir)
        self.lock = threading.Lock()
        self.dirty = True
        self.seq = 0
        self._stop = False
        self.failed_path = self.p['failed']
        self.queue = []              # every song: {'a', 't', 's', 'n'}
        self.active = 0
        self.s = {'job': job_id, 'running': True, 'status': 'Starting...',
                  'progress': 0.0, 'done': 0, 'total': 0,
                  'now': None, 'log': [], 'report': '', 'cover_ver': 0,
                  'finished': False, 'can_retry': False}
        self._writer = threading.Thread(target=self._loop, daemon=True)
        self._writer.start()

    # -- file writer: saves changes ~3x a second and a heartbeat every 2s ----
    def _loop(self):
        last = 0.0
        while not self._stop:
            time.sleep(0.3)
            if self.dirty or time.time() - last > 2:
                self.flush()
                last = time.time()

    def flush(self):
        with self.lock:
            self.dirty = False
            self.seq += 1
            snap = dict(self.s, seq=self.seq, updated=time.time())
            snap.update(self._queue_view())
            try:
                _atomic_write(self.p['state'], json.dumps(snap))
            except OSError:
                self.dirty = True

    def _queue_view(self):
        """Counts for the whole job plus just the songs worth showing: the
        ones around the current song, or the failed ones once it is over."""
        counts = {'done': 0, 'skipped': 0, 'failed': 0, 'pending': 0,
                  'active': 0}
        for q in self.queue:
            counts[q['s']] = counts.get(q['s'], 0) + 1
        if self.s['finished'] and counts['failed']:
            idx = [i for i, q in enumerate(self.queue) if q['s'] == 'failed']
            idx = idx[:MAX_FAILED_SHOWN]
            title = 'failed'
        else:
            start = max(0, min(self.active, len(self.queue)) - 2)
            idx = list(range(start, min(len(self.queue), start + WINDOW)))
            title = 'window'
        rows = [dict(self.queue[i], i=i) for i in idx]
        return {'counts': counts, 'queue_len': len(self.queue),
                'win': {'kind': title, 'rows': rows}}

    def close(self):
        self._stop = True
        self.flush()

    def _set(self, **kw):
        with self.lock:
            self.s.update(kw)
            self.dirty = True

    # -- cancel flag ---------------------------------------------------------
    @property
    def cancel_requested(self):
        return os.path.exists(self.p['cancel'])

    # -- the interface spotdl_bridge uses ------------------------------------
    def log(self, msg, kind='info'):
        with self.lock:
            self.s['log'].append([str(msg), kind])
            del self.s['log'][:-LOG_LINES]
            self.dirty = True

    def set_status(self, text):
        self._set(status=text)

    def set_progress(self, fraction):
        self._set(progress=max(0.0, min(1.0, float(fraction))))

    def set_overall(self, done, total):
        self._set(done=done, total=total, progress=0.0)

    def set_queue(self, tracks):
        with self.lock:
            self.queue = [{'a': t['artist'], 't': t['title'], 's': 'pending',
                           'n': ''} for t in tracks]
            self.active = 0
            self.dirty = True

    def set_track_state(self, index, state, note=''):
        with self.lock:
            if index < len(self.queue):
                self.queue[index].update(s=state, n=note)
                if state == 'active':
                    self.active = index
                self.dirty = True

    def set_now(self, track, cover_bytes):
        if track is None:
            return
        with self.lock:
            self.s['cover_ver'] += 1
            try:
                if cover_bytes:
                    _atomic_write(self.p['cover'], cover_bytes, 'wb')
                elif os.path.exists(self.p['cover']):
                    os.remove(self.p['cover'])
            except OSError:
                pass
            self.s['now'] = {'title': track['title'], 'artist': track['artist'],
                             'album': track['album'],
                             'cover': bool(cover_bytes),
                             'ver': self.s['cover_ver']}
            self.dirty = True

    def set_report(self, path):
        self._set(report=path)


# --------------------------------------------------------------------------
# Android helpers (all optional: any failure is ignored)
# --------------------------------------------------------------------------
class _Keepalive:
    """Keeps the CPU and Wi-Fi awake while a download runs with the screen off."""

    def __init__(self):
        self.locks = []

    def __enter__(self):
        try:
            from jnius import autoclass
            service = autoclass('org.kivy.android.PythonService').mService
            Context = autoclass('android.content.Context')
            pm = service.getSystemService(Context.POWER_SERVICE)
            wl = pm.newWakeLock(1, 'SpotDL:download')      # PARTIAL_WAKE_LOCK
            wl.acquire()
            self.locks.append(wl)
            wifi = service.getSystemService(Context.WIFI_SERVICE)
            wfl = wifi.createWifiLock(3, 'SpotDL:wifi')    # FULL_HIGH_PERF
            wfl.acquire()
            self.locks.append(wfl)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        for lock in self.locks:
            try:
                lock.release()
            except Exception:
                pass


def notify(title, text):
    """Post a normal notification, e.g. when the download has finished."""
    try:
        from jnius import autoclass
        service = autoclass('org.kivy.android.PythonService').mService
        Context = autoclass('android.content.Context')
        Build = autoclass('android.os.Build$VERSION')
        NotificationManager = autoclass('android.app.NotificationManager')
        Builder = autoclass('android.app.Notification$Builder')
        nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
        channel_id = 'spotdl_done'
        if Build.SDK_INT >= 26:
            Channel = autoclass('android.app.NotificationChannel')
            nm.createNotificationChannel(
                Channel(channel_id, 'Download finished',
                        NotificationManager.IMPORTANCE_DEFAULT))
            builder = Builder(service, channel_id)
        else:
            builder = Builder(service)
        icon = service.getApplicationInfo().icon      # the app's own icon
        builder.setSmallIcon(icon).setContentTitle(title).setContentText(text)
        builder.setAutoCancel(True)
        nm.notify(7, builder.build())
    except Exception:
        pass


# --------------------------------------------------------------------------
# The job
# --------------------------------------------------------------------------
def run_job(job_path):
    """Run the download described in job.json. Never raises."""
    with open(job_path) as f:
        job = json.load(f)
    state_dir = os.path.dirname(job_path)
    ui = FileUI(state_dir, job.get('id'))
    try:
        with _Keepalive():
            base = job['data_dir']
            import updater
            updater.activate(base)
            ui.set_status('Checking for updates...')
            updater.check_and_update(base, ui.log)
            import spotdl_bridge
            retry = bool(job.get('retry'))
            if not retry:        # a normal job starts with a clean failed list
                try:
                    os.remove(ui.failed_path)
                except OSError:
                    pass
            spotdl_bridge.download(job.get('link', ''), job['output'],
                                   job['format'], ui,
                                   retry_path=ui.failed_path if retry else None)
    except Exception as e:
        ui.log(f'Error: {e}', 'error')
        ui.log(traceback.format_exc(), 'error')
        ui.set_status('Failed - see log')
    finally:
        with ui.lock:
            status = ui.s['status']
        ui._set(running=False, finished=True,
                can_retry=os.path.exists(ui.failed_path)
                and not ui.cancel_requested)
        ui.close()
        notify('SpotDL Downloader', status)


def main():
    """Entry point when python-for-android starts this file as a service."""
    job_path = os.environ.get('PYTHON_SERVICE_ARGUMENT', '')
    if job_path and os.path.exists(job_path):
        run_job(job_path)


if __name__ == '__main__':
    main()
