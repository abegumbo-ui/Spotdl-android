"""
updater.py - keeps yt-dlp and ytmusicapi up to date without rebuilding the APK.

Both packages are pure Python, so the app downloads the newest wheel from PyPI
on startup, unpacks it into its private storage and puts it first on sys.path.
The versions bundled in the APK are the fallback if the phone is offline or an
update fails to import.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import threading
import zipfile

# PyPI project name -> top-level import name
PACKAGES = {'yt-dlp': 'yt_dlp', 'ytmusicapi': 'ytmusicapi'}

_done = threading.Event()
_lock = threading.Lock()


def _root(base):
    return os.path.join(base, 'pylibs')


def _marker(base, name):
    return os.path.join(_root(base), f'{name}.json')


def _ver_key(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '')) or (0,)


def _read_marker(base, name):
    try:
        with open(_marker(base, name)) as f:
            data = json.load(f)
        if os.path.isdir(data['path']):
            return data
    except Exception:
        pass
    return None


def _bundled_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _purge(module):
    for k in [k for k in sys.modules if k == module or k.startswith(module + '.')]:
        del sys.modules[k]


def activate(base):
    """Put previously downloaded updates first on sys.path (no network)."""
    for name in PACKAGES:
        data = _read_marker(base, name)
        if data and data['path'] not in sys.path:
            sys.path.insert(0, data['path'])


def _latest_wheel(name, session):
    r = session.get(f'https://pypi.org/pypi/{name}/json', timeout=15)
    r.raise_for_status()
    data = r.json()
    version = data['info']['version']
    for f in data['urls']:
        if f.get('packagetype') == 'bdist_wheel' and \
                f['filename'].endswith('py3-none-any.whl'):
            return version, f['url'], f['digests']['sha256']
    raise RuntimeError(f'no universal wheel for {name} {version}')


def _install(base, name, module, version, url, sha256, session):
    r = session.get(url, timeout=120)
    r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest() != sha256:
        raise RuntimeError('checksum mismatch')
    target = os.path.join(_root(base), f'{name}-{version}')
    tmp = target + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(tmp)
    shutil.rmtree(target, ignore_errors=True)
    os.rename(tmp, target)
    return target


def check_and_update(base, log=print):
    """Run once at startup (in a thread). Never raises."""
    with _lock:
        try:
            os.makedirs(_root(base), exist_ok=True)
            activate(base)
            try:
                import requests
                try:
                    import certifi
                    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
                except ImportError:
                    pass
                session = requests.Session()
            except Exception as e:
                log(f'Update check skipped: {e}', 'warning')
                return
            for name, module in PACKAGES.items():
                try:
                    _update_one(base, name, module, session, log)
                except Exception as e:
                    log(f'Could not update {name}: {e}', 'warning')
        finally:
            _done.set()


def _update_one(base, name, module, session, log):
    marker = _read_marker(base, name)
    current = marker['version'] if marker else _bundled_version(name)
    latest, url, sha = _latest_wheel(name, session)
    if current and _ver_key(latest) <= _ver_key(current):
        log(f'{name} {current} is up to date', 'info')
        return
    log(f'Updating {name} {current or "?"} -> {latest}...', 'info')
    path = _install(base, name, module, latest, url, sha, session)
    # Make sure the new version really imports before committing to it.
    _purge(module)
    sys.path.insert(0, path)
    try:
        __import__(module)
    except Exception as e:
        sys.path.remove(path)
        _purge(module)
        shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError(f'new version failed to load ({e})')
    with open(_marker(base, name), 'w') as f:
        json.dump({'version': latest, 'path': path}, f)
    # Remove older downloaded versions.
    root = _root(base)
    for d in os.listdir(root):
        full = os.path.join(root, d)
        if d.startswith(name + '-') and full != path and os.path.isdir(full):
            if full in sys.path:
                sys.path.remove(full)
            shutil.rmtree(full, ignore_errors=True)
    log(f'{name} updated to {latest}', 'success')


def start(base, log=print):
    """Begin the update check in the background."""
    _done.clear()
    threading.Thread(target=check_and_update, args=(base, log),
                     daemon=True).start()


def wait(timeout=45):
    """Block until the startup update check has finished (or timed out)."""
    _done.wait(timeout)
