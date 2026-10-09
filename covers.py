"""covers.py - loads cover pictures (from a file's tags or a web address)
in the background and puts them on a K.Cover."""
import io
import threading

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage

import library as lib

_cache = {}
_gate = threading.Semaphore(3)


def _texture(data):
    ext = 'png' if data[:4] == b'\x89PNG' else 'jpg'
    return CoreImage(io.BytesIO(data), ext=ext).texture


def _fetch(key, widget, getter):
    with _gate:
        try:
            data = getter()
        except Exception:
            data = None
    if not data:
        _cache[key] = False
        return

    def apply(dt):
        try:
            _cache[key] = _texture(data)
            if getattr(widget, '_cover_key', None) == key:
                widget.texture = _cache[key]
        except Exception:
            _cache[key] = False
    Clock.schedule_once(apply)


def _load(key, widget, getter):
    widget._cover_key = key
    got = _cache.get(key)
    if got:
        widget.texture = got
        return
    widget.texture = None
    if got is False:
        return
    _cache[key] = None
    threading.Thread(target=_fetch, args=(key, widget, getter),
                     daemon=True).start()


def for_file(path, widget):
    _load(('f', path), widget, lambda: lib.read_cover(path))


def for_url(url, widget):
    if not url:
        widget._cover_key = None
        widget.texture = None
        return

    def get():
        import requests
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    _load(('u', url), widget, get)


def for_entry(entry, widget):
    if entry is None:
        widget._cover_key = None
        widget.texture = None
    elif entry['kind'] == 'file':
        for_file(entry['path'], widget)
    else:
        m = entry.get('matched') or {}
        for_url(m.get('cover') or entry['item'].get('cover'), widget)
