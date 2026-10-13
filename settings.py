"""settings.py - the few things the user can change (settings.json in the
app's private folder). No Kivy in here: the background service reads it too."""
import json
import os
import threading
import time

DEFAULTS = {
    'workers': 3,              # songs downloaded at the same time (1-5)
    'auto_update': True,       # check yt-dlp / ytmusicapi at most once a day
    'last_update_check': 0.0,
    'upgrade_mode': False,     # redo songs saved in a lower format / no cover
}
UPDATE_EVERY = 24 * 3600
_lock = threading.Lock()


def _path(data_dir):
    return os.path.join(data_dir, 'settings.json')


def load(data_dir):
    s = dict(DEFAULTS)
    try:
        with open(_path(data_dir), encoding='utf-8') as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    s['workers'] = max(1, min(5, int(s.get('workers') or 3)))
    return s


def save(data_dir, **changes):
    with _lock:
        s = load(data_dir)
        s.update({k: v for k, v in changes.items() if k in DEFAULTS})
        os.makedirs(data_dir, exist_ok=True)
        tmp = _path(data_dir) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(s, f)
        os.replace(tmp, _path(data_dir))
        return s


def update_due(data_dir):
    s = load(data_dir)
    return s['auto_update'] and time.time() - s['last_update_check'] >= UPDATE_EVERY
