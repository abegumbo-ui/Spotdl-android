"""history.py - the jobs you have run, so any of them can be filled in or
redone later. No Kivy in here: the background service writes it."""
import json
import os
import time

KEEP = 30


def _paths(base):
    return os.path.join(base, 'history.json'), os.path.join(base, 'history')


def _load(base):
    try:
        with open(_paths(base)[0], encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save(base, entries):
    path, folder = _paths(base)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False)
    os.replace(tmp, path)


def add(base, job, title, counts):
    """Remember a finished job. Link jobs keep the link; picked-song jobs keep
    their song list in a file of their own."""
    if job.get('retry'):
        return
    path, folder = _paths(base)
    entry = {'id': job.get('id') or time.time(), 'time': time.time(),
             'title': title or job.get('title') or job.get('link') or 'Download',
             'link': job.get('link') or '', 'format': job.get('format', ''),
             'counts': counts, 'items_file': ''}
    if job.get('items'):
        os.makedirs(folder, exist_ok=True)
        entry['items_file'] = os.path.join(folder, f"{int(entry['time'])}.json")
        try:
            with open(entry['items_file'], 'w', encoding='utf-8') as f:
                json.dump({'items': job['items'], 'title': job.get('title', '')},
                          f, ensure_ascii=False)
        except OSError:
            entry['items_file'] = ''
    entries = [e for e in _load(base)
               if not (e['link'] and e['link'] == entry['link'])
               and not (e.get('title') == entry['title'] and e['items_file'])]
    entries.insert(0, entry)
    for old in entries[KEEP:]:
        if old.get('items_file'):
            try:
                os.remove(old['items_file'])
            except OSError:
                pass
    _save(base, entries[:KEEP])


def entries(base):
    return _load(base)


def find_link(base, link):
    for e in _load(base):
        if e['link'] and e['link'] == link:
            return e
    return None


def spec(entry):
    """What to feed back into a new job to run this one again."""
    if entry.get('items_file') and os.path.exists(entry['items_file']):
        with open(entry['items_file'], encoding='utf-8') as f:
            data = json.load(f)
        return {'items': data['items'], 'title': data.get('title', '')}
    return {'link': entry['link']}


def remove(base, entry_id):
    entries = _load(base)
    for e in entries:
        if e['id'] == entry_id and e.get('items_file'):
            try:
                os.remove(e['items_file'])
            except OSError:
                pass
    _save(base, [e for e in entries if e['id'] != entry_id])
