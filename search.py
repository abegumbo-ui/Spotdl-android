"""
search.py - search songs and artists on Spotify and YouTube Music.

No screen code here (see search_screen.py). Everything returned is plain data:

song card    {'title', 'artist', 'album', 'duration',
              'sources': {'ytm': {'item', 'thumb'}, 'sp': {'item', 'thumb'}}}
artist card  {'name', 'sources': {'ytm': {'id', 'thumb'}, 'sp': {'id', 'thumb'}}}
album        {'source', 'id', 'title', 'year', 'kind', 'thumb', 'total'}

An 'item' is what the downloader takes. The audio always comes from YouTube
Music; the source only decides whose title / album / cover art and tags are
used:
  ytm item - a YouTube Music song, with YouTube Music's album art
  sp item  - a Spotify track, matched to its YouTube Music audio when the
             download starts, with Spotify's cover art and album details
"""
import json
import re
import time

import spotdl_bridge as b

SPOTIFY_API = 'https://api.spotify.com/v1'
_token = {'value': None, 'expires': 0.0, 'down_until': 0.0}
FAST = 6                          # seconds Spotify gets to answer a search
DOWN_FOR = 300                    # after a failure, don't ask again for 5 min


# --------------------------------------------------------------------------
# Spotify access (no login: shared app credentials, or the embed page's token)
# --------------------------------------------------------------------------
def spotify_token(force=False, timeout=FAST):
    """A Spotify token, or None. After a failure Spotify is left alone for a
    few minutes, so a blocked connection costs one short wait, not one per
    search."""
    import requests
    if not force and _token['value'] and time.time() < _token['expires']:
        return _token['value']
    if time.time() < _token['down_until']:
        return None
    try:
        r = requests.post('https://accounts.spotify.com/api/token',
                          data={'grant_type': 'client_credentials'},
                          auth=b.SPOTIFY_CLIENT, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        _token.update(value=j['access_token'],
                      expires=time.time() + j.get('expires_in', 3600) - 60)
        return _token['value']
    except Exception:
        pass
    try:      # the token the public embed player itself uses
        r = requests.get(
            'https://open.spotify.com/embed/track/4uLU6hMCjMI75M1A2tKUQC',
            headers=b.SPOTIFY_UA, timeout=timeout)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                      r.text, re.S)
        tok = (json.loads(m.group(1))['props']['pageProps']['state']
               ['settings']['session']['accessToken'])
        _token.update(value=tok, expires=time.time() + 1800)
        return tok
    except Exception:
        _token['down_until'] = time.time() + DOWN_FOR
        return None


def spotify_get(path, params=None, fast=True):
    """GET from Spotify's API, refreshing the token once if it was refused.
    `fast` (searches) gives up quickly instead of waiting out rate limits."""
    last = None
    for attempt in range(2):
        tok = spotify_token(force=attempt > 0)
        if not tok:
            break
        try:
            return b._api_get(SPOTIFY_API + path, tok, params,
                              timeout=FAST + 4 if fast else 30,
                              tries=1 if fast else 4)
        except Exception as e:
            last = e
    raise RuntimeError(f'Spotify is not available ({last or "no access"})')


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def small(url, px=160):
    """A smaller picture for list rows (Google image URLs take a size)."""
    if url and ('googleusercontent.com' in url or 'ggpht.com' in url):
        return re.sub(r'=w\d+-h\d+.*$', f'=w{px}-h{px}-l90-rj', url)
    return url


def _smallest_ok(images, want=120):
    """Spotify image list -> the smallest one that is at least `want` wide."""
    imgs = sorted((i for i in images or [] if i.get('url')),
                  key=lambda i: i.get('width') or 0)
    for i in imgs:
        if (i.get('width') or 0) >= want:
            return i['url']
    return imgs[-1]['url'] if imgs else None


def _fmt(seconds):
    if not seconds:
        return ''
    seconds = int(round(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


# --------------------------------------------------------------------------
class Searcher:
    def __init__(self):
        self._yt = None
        self.notes = []              # things worth telling the user

    @property
    def yt(self):
        if self._yt is None:
            from ytmusicapi import YTMusic
            self._yt = YTMusic()
        return self._yt

    # -- songs -----------------------------------------------------------------
    def _ytm_songs(self, query):
        out = []
        for r in self.yt.search(query, filter='songs', limit=20):
            if not r.get('videoId'):
                continue
            thumbs = r.get('thumbnails') or []
            art = thumbs[-1]['url'] if thumbs else None
            album = r.get('album') or {}
            item = b._track(
                r['videoId'], r.get('title'), b._names(r.get('artists')),
                album.get('name') or '', cover=art,
                duration=r.get('duration_seconds'), video_type=b.AUDIO_TRACK)
            out.append({'title': item['title'], 'artist': item['artist'],
                        'album': item['album'],
                        'duration': r.get('duration_seconds'),
                        'src': 'ytm', 'item': item, 'thumb': small(art)})
        return out

    def _spotify_songs(self, query):
        out = []
        j = spotify_get('/search', {'q': query, 'type': 'track', 'limit': 20})
        for t in (j.get('tracks') or {}).get('items') or []:
            if not t.get('name'):
                continue
            row = b._api_row(t, 0)
            row['album'] = (t.get('album') or {}).get('name') or ''
            row['track_number'] = t.get('track_number')
            out.append({'title': row['title'], 'artist': row['artist'],
                        'album': row['album'], 'duration': row['duration'],
                        'src': 'sp', 'item': row,
                        'thumb': _smallest_ok((t.get('album') or {})
                                              .get('images'))})
        return out

    def search_songs(self, query):
        """Song cards; the same song found on both services is one card."""
        ytm, sp = [], []
        try:
            ytm = self._ytm_songs(query)
        except Exception as e:
            self.notes.append(f'YouTube Music search failed: {b._clean_error(e)}')
        try:
            sp = self._spotify_songs(query)
        except Exception as e:
            self.notes.append(f'Spotify search unavailable: {b._clean_error(e)}')
        return pair_songs(ytm, sp)

    # -- artists ---------------------------------------------------------------
    def search_artists(self, query):
        ytm, sp = [], []
        try:
            for r in self.yt.search(query, filter='artists', limit=8):
                thumbs = r.get('thumbnails') or []
                ytm.append({'name': r.get('artist') or '', 'src': 'ytm',
                            'id': r.get('browseId'),
                            'thumb': small(thumbs[-1]['url'] if thumbs else None)})
        except Exception as e:
            self.notes.append(f'YouTube Music search failed: {b._clean_error(e)}')
        try:
            j = spotify_get('/search', {'q': query, 'type': 'artist', 'limit': 8})
            for a in (j.get('artists') or {}).get('items') or []:
                sp.append({'name': a.get('name') or '', 'src': 'sp',
                           'id': a.get('id'),
                           'thumb': _smallest_ok(a.get('images'))})
        except Exception as e:
            self.notes.append(f'Spotify search unavailable: {b._clean_error(e)}')
        return pair_artists(ytm, sp)

    # -- one search for everything -----------------------------------------------
    def search_all(self, query, emit):
        """Search Spotify and YouTube Music together, like a normal search bar.

        Runs every lookup at the same time. `emit(result)` is called each time
        another one arrives with everything found so far:
          {'top': card|None, 'songs': [...], 'artists': [...],
           'albums': [...], 'notes': [...], 'done': bool}
        Cards carry a 'kind' of 'song', 'artist' or 'album'."""
        import threading
        lock = threading.Lock()
        parts = {'ytm_songs': [], 'sp_songs': [], 'ytm_artists': [],
                 'sp_artists': [], 'ytm_albums': [], 'sp_albums': [],
                 'ytm_top': None}
        notes = []
        jobs = {'ytm_songs': self._ytm_songs,
                'ytm_artists': self._ytm_artists,
                'ytm_albums': self._ytm_albums,
                'ytm_top': self._ytm_top,
                'spotify': self._spotify_all}
        left = {'n': len(jobs)}

        def merged(done):
            songs = pair_songs(parts['ytm_songs'], parts['sp_songs'])
            artists = pair_artists(parts['ytm_artists'], parts['sp_artists'])
            albums = pair_albums(parts['ytm_albums'], parts['sp_albums'])
            for c in songs:
                c['kind'] = 'song'
            for c in artists:
                c['kind'] = 'artist'
            for c in albums:
                c['kind'] = 'album'
            return {'top': pick_top(query, parts['ytm_top'], songs, artists,
                                    albums),
                    'songs': songs, 'artists': artists, 'albums': albums,
                    'notes': list(notes), 'done': done}

        def run(name, fn):
            try:
                out = fn(query)
                with lock:
                    if name == 'spotify':
                        parts['sp_songs'], parts['sp_artists'], \
                            parts['sp_albums'] = out
                    else:
                        parts[name] = out
            except Exception as e:
                with lock:
                    label = 'Spotify' if name == 'spotify' else 'YouTube Music'
                    note = f'{label} search unavailable: {b._clean_error(e)}'
                    if note not in notes:
                        notes.append(note)
            with lock:
                left['n'] -= 1
                result = merged(left['n'] == 0)
            emit(result)

        for name, fn in jobs.items():
            threading.Thread(target=run, args=(name, fn), daemon=True).start()

    def _ytm_artists(self, query):
        out = []
        for r in self._fresh().search(query, filter='artists', limit=6):
            thumbs = r.get('thumbnails') or []
            out.append({'name': r.get('artist') or '', 'src': 'ytm',
                        'id': r.get('browseId'),
                        'thumb': small(thumbs[-1]['url'] if thumbs else None)})
        return out

    def _ytm_albums(self, query):
        out = []
        for r in self._fresh().search(query, filter='albums', limit=8):
            if not r.get('browseId'):
                continue
            thumbs = r.get('thumbnails') or []
            out.append({
                'source': 'ytm', 'id': r['browseId'],
                'title': r.get('title') or '', 'year': str(r.get('year') or ''),
                'kind': (r.get('type') or 'Album').title(), 'total': None,
                'artist': b._names(r.get('artists')),
                'thumb': small(thumbs[-1]['url'] if thumbs else None)})
        return out

    def _ytm_top(self, query):
        """YouTube Music's own 'Top result' for the words typed, as a card
        kind + name (used to decide what to show first)."""
        for r in self._fresh().search(query, limit=6):
            kind = r.get('resultType')
            if kind in ('artist', 'album', 'song', 'single', 'ep'):
                return {'kind': 'album' if kind in ('single', 'ep') else kind,
                        'name': r.get('artist') or r.get('title') or '',
                        'title': r.get('title') or '',
                        'id': r.get('browseId') or r.get('videoId')}
            break
        return None

    def _fresh(self):
        """A separate YouTube Music client per lookup (they run in threads)."""
        from ytmusicapi import YTMusic
        return YTMusic()

    def _spotify_all(self, query):
        """Songs, artists and albums from ONE Spotify request."""
        j = spotify_get('/search', {'q': query, 'type': 'track,artist,album',
                                    'limit': 10})
        songs, artists, albums = [], [], []
        for t in (j.get('tracks') or {}).get('items') or []:
            if not t.get('name'):
                continue
            row = b._api_row(t, 0)
            row['album'] = (t.get('album') or {}).get('name') or ''
            row['track_number'] = t.get('track_number')
            songs.append({'title': row['title'], 'artist': row['artist'],
                          'album': row['album'], 'duration': row['duration'],
                          'src': 'sp', 'item': row,
                          'thumb': _smallest_ok((t.get('album') or {})
                                                .get('images'))})
        for a in (j.get('artists') or {}).get('items') or []:
            artists.append({'name': a.get('name') or '', 'src': 'sp',
                            'id': a.get('id'),
                            'thumb': _smallest_ok(a.get('images'))})
        for a in (j.get('albums') or {}).get('items') or []:
            albums.append({
                'source': 'sp', 'id': a.get('id'), 'title': a.get('name') or '',
                'year': (a.get('release_date') or '')[:4],
                'kind': (a.get('album_type') or 'album').title(),
                'total': a.get('total_tracks'),
                'artist': ', '.join(x.get('name', '')
                                    for x in a.get('artists') or []),
                'thumb': _smallest_ok(a.get('images'))})
        return songs, artists, albums

    # -- one artist's releases and songs ------------------------------------------
    def artist_albums(self, source, artist_id, artist_name=''):
        """Albums and singles of an artist, newest first when dates are known."""
        out = []
        if source == 'ytm':
            artist = self.yt.get_artist(artist_id)
            for section, kind in (('albums', 'Album'), ('singles', 'Single')):
                block = artist.get(section) or {}
                rels = block.get('results') or []
                if block.get('browseId') and block.get('params'):
                    try:
                        rels = self.yt.get_artist_albums(block['browseId'],
                                                         block['params'])
                    except Exception:
                        pass
                for r in rels:
                    if r.get('browseId'):
                        thumbs = r.get('thumbnails') or []
                        out.append({'source': 'ytm', 'id': r['browseId'],
                                    'title': r.get('title') or '',
                                    'year': str(r.get('year') or ''),
                                    'kind': kind, 'total': None,
                                    'artist': artist.get('name') or artist_name,
                                    'thumb': small(thumbs[-1]['url']
                                                   if thumbs else None)})
        else:
            url = f'/artists/{artist_id}/albums'
            params = {'include_groups': 'album,single', 'limit': 50}
            seen = set()
            while url:
                j = spotify_get(url, params, fast=False)
                for a in j.get('items') or []:
                    key = (a.get('name'), a.get('release_date'))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({'source': 'sp', 'id': a['id'],
                                'title': a.get('name') or '',
                                'year': (a.get('release_date') or '')[:4],
                                'kind': (a.get('album_type') or 'album').title(),
                                'total': a.get('total_tracks'),
                                'artist': artist_name,
                                'thumb': _smallest_ok(a.get('images'))})
                nxt = j.get('next')
                url = nxt.replace(SPOTIFY_API, '') if nxt else None
                params = None
            out.sort(key=lambda a: a['year'], reverse=True)
        return out

    def album_items(self, album):
        """The songs of one album, as downloader items."""
        if album['source'] == 'ytm':
            items = b.tracks_from_album(self.yt, album['id'], album.get('artist', ''))
            for it in items:
                it['duration_text'] = _fmt(it.get('duration'))
            return items
        tok_items, _ = self._sp_album(album['id'])
        for it in tok_items:
            it['duration_text'] = _fmt(it.get('duration'))
        return tok_items

    def _sp_album(self, album_id):
        j = spotify_get(f'/albums/{album_id}', fast=False)
        title, cover = j.get('name') or '', b._images(j.get('images'))
        year = (j.get('release_date') or '')[:4]
        artists = ', '.join(a.get('name', '') for a in j.get('artists') or [])
        out, page = [], j['tracks']
        while page:
            for t in page.get('items') or []:
                row = b._api_row(t, len(out) + 1, title, cover)
                row.update(year=year, album_artist=artists,
                           track_number=t.get('track_number') or row['position'],
                           track_total=j.get('total_tracks'))
                out.append(row)
            nxt = page.get('next')
            page = (spotify_get(nxt.replace(SPOTIFY_API, ''), fast=False)
                    if nxt else None)
        return out, title


# --------------------------------------------------------------------------
# pairing the same song / artist found on both services
# --------------------------------------------------------------------------
def pair_songs(ytm, sp):
    cards, used = [], set()
    for y in ytm:
        match = None
        for i, s in enumerate(sp):
            if i in used:
                continue
            close = (not y['duration'] or not s['duration']
                     or abs(y['duration'] - s['duration']) <= 6)
            if close and b._overlap(y['title'], s['title']) >= 0.8 \
                    and b._overlap(y['artist'], s['artist']) > 0:
                match = i
                break
        card = {'title': y['title'], 'artist': y['artist'], 'album': y['album'],
                'duration': y['duration'], 'sources': {'ytm': y}}
        if match is not None:
            used.add(match)
            card['sources']['sp'] = sp[match]
        cards.append(card)
    for i, s in enumerate(sp):
        if i not in used:
            cards.append({'title': s['title'], 'artist': s['artist'],
                          'album': s['album'], 'duration': s['duration'],
                          'sources': {'sp': s}})
    return cards


def pair_albums(ytm, sp):
    """One card per album; the same album on both services is one card."""
    cards, used = [], set()
    for y in ytm:
        match = None
        for i, a in enumerate(sp):
            if i in used:
                continue
            if b._overlap(y['title'], a['title']) >= 0.8 and \
                    b._overlap(y['artist'], a['artist']) > 0:
                match = i
                break
        card = {'title': y['title'], 'artist': y['artist'], 'year': y['year'],
                'kind_name': y['kind'], 'sources': {'ytm': y}}
        if match is not None:
            used.add(match)
            card['sources']['sp'] = sp[match]
        cards.append(card)
    for i, a in enumerate(sp):
        if i not in used:
            cards.append({'title': a['title'], 'artist': a['artist'],
                          'year': a['year'], 'kind_name': a['kind'],
                          'sources': {'sp': a}})
    return cards


def pick_top(query, ytm_top, songs, artists, albums):
    """What to show first. YouTube Music's own choice if it answered;
    otherwise an artist whose name is what was typed, else the first song."""
    q = b._norm(query)
    if ytm_top:
        want = b._norm(ytm_top['name'])
        pool = {'artist': [(c, c['name']) for c in artists],
                'album': [(c, c['title']) for c in albums],
                'song': [(c, c['title']) for c in songs]}.get(ytm_top['kind'], [])
        for c, name in pool:
            if b._norm(name) == want:
                return c
    for c in artists:
        if b._norm(c['name']) == q:
            return c
    for pool in (songs, albums, artists):
        if pool:
            return pool[0]
    return None


def pair_artists(ytm, sp):
    cards, used = [], set()
    for y in ytm:
        match = next((i for i, s in enumerate(sp) if i not in used
                      and b._norm(s['name']) == b._norm(y['name'])), None)
        card = {'name': y['name'], 'sources': {'ytm': y}}
        if match is not None:
            used.add(match)
            card['sources']['sp'] = sp[match]
        cards.append(card)
    cards += [{'name': s['name'], 'sources': {'sp': s}}
              for i, s in enumerate(sp) if i not in used]
    return cards


# --------------------------------------------------------------------------
# What a pasted link is (shown as a card before anything is downloaded)
# --------------------------------------------------------------------------
_YT_HOST = re.compile(r'(?:music\.)?youtube\.com|youtu\.be', re.I)


def is_link(text):
    """A pasted link, or an address typed in (with or without https://)."""
    t = text.strip()
    return bool(b.looks_like_address(t) or re.match(r'https?://', t, re.I) or
                re.match(r'(?:www\.|music\.)?(?:youtube\.com|youtu\.be)/', t, re.I)
                or re.match(r'open\.spotify\.com/', t, re.I))


def _artist_card(name, thumb=None, ytm_id=None, sp_id=None):
    sources = {}
    if ytm_id:
        sources['ytm'] = {'name': name, 'src': 'ytm', 'id': ytm_id,
                          'thumb': small(thumb) if thumb else None}
    if sp_id:
        sources['sp'] = {'name': name, 'src': 'sp', 'id': sp_id, 'thumb': thumb}
    return {'name': name, 'kind': 'artist', 'sources': sources}


def link_card(searcher, text, log=lambda *a, **k: None):
    """Work out what a pasted link points at. Returns a dict with 'kind':
       song     {'card': song card}
       album    {'card': album card}
       artist   {'card': artist card}
       playlist {'title', 'count', 'thumb', 'link'}
       web      {'title', 'items', 'count', 'thumb', 'site'}  (any website)
    Raises ValueError with a readable message when it cannot tell."""
    typed = text.strip()
    text = typed
    if not re.match(r'https?://', text, re.I):
        text = 'https://' + text
    m = b._SPOTIFY.search(text)
    if m:
        return _spotify_link(searcher, text, m.group(1), m.group(2), log)
    if not _YT_HOST.search(text):
        items, title = b.tracks_from_web(typed, log)      # any other website
        site = items[0].get('album') if items else ''
        return {'kind': 'web', 'title': title, 'items': items, 'site': site,
                'count': len(items), 'link': typed,
                'thumb': next((i.get('cover_raw') for i in items
                               if i.get('cover_raw')), None),
                'duration': items[0].get('duration') if len(items) == 1
                else None}
    yt = searcher.yt
    m = re.search(r'/browse/(MPRE[\w-]+)', text)
    if m:
        a = yt.get_album(m.group(1))
        thumbs = a.get('thumbnails') or []
        album = {'source': 'ytm', 'id': m.group(1), 'title': a.get('title') or '',
                 'year': str(a.get('year') or ''), 'kind': 'Album',
                 'total': a.get('trackCount'),
                 'artist': b._names(a.get('artists')),
                 'thumb': small(thumbs[-1]['url'] if thumbs else None)}
        return {'kind': 'album', 'card': {
            'kind': 'album', 'title': album['title'], 'artist': album['artist'],
            'year': album['year'], 'kind_name': 'Album',
            'sources': {'ytm': album}}}
    m = re.search(r'/(?:channel|browse)/(UC[\w-]{20,})', text)
    if m:
        a = yt.get_artist(m.group(1))
        thumbs = a.get('thumbnails') or []
        return {'kind': 'artist', 'card': _artist_card(
            a.get('name') or '', thumbs[-1]['url'] if thumbs else None,
            ytm_id=m.group(1))}
    if b._CHANNEL.search(text):
        name = b.youtube_page_name(text)
        if not name:
            raise ValueError("Couldn't read this channel's name. "
                             'Type the artist name in the search box instead.')
        found = searcher._ytm_artists(name)
        if not found:
            raise ValueError(f'No YouTube Music artist found for "{name}".')
        return {'kind': 'artist', 'card': _artist_card(
            found[0]['name'], found[0]['thumb'], ytm_id=found[0]['id'])}
    m = re.search(r'[?&]list=([\w-]+)', text)
    if m and ('watch?v=' not in text or 'playlist' in text):
        pl = yt.get_playlist(m.group(1), limit=1)
        thumbs = pl.get('thumbnails') or []
        return {'kind': 'playlist', 'title': pl.get('title') or 'Playlist',
                'count': pl.get('trackCount'), 'link': text,
                'thumb': small(thumbs[-1]['url'] if thumbs else None)}
    m = b._YT_ID.search(text)
    if m:
        t = b.track_from_video_id(yt, m.group(1))
        return {'kind': 'song', 'card': _song_card_from_item(t, 'ytm')}
    raise ValueError("Couldn't tell what this YouTube link is.")


def _song_card_from_item(item, src):
    return {'kind': 'song', 'title': item['title'], 'artist': item['artist'],
            'album': item.get('album', ''), 'duration': item.get('duration'),
            'sources': {src: {'item': item, 'src': src,
                              'thumb': small(item.get('cover')) if src == 'ytm'
                              else item.get('cover'),
                              'title': item['title'], 'artist': item['artist'],
                              'album': item.get('album', ''),
                              'duration': item.get('duration')}}}


def _spotify_link(searcher, text, kind, sid, log):
    if kind == 'track':
        items, _ = b.spotify_items(text, log)
        if not items:
            raise ValueError("Couldn't read that Spotify song.")
        it = items[0]
        return {'kind': 'song', 'card': _song_card_from_item(it, 'sp')}
    if kind == 'album':
        j = spotify_get(f'/albums/{sid}')
        album = {'source': 'sp', 'id': sid, 'title': j.get('name') or '',
                 'year': (j.get('release_date') or '')[:4],
                 'kind': (j.get('album_type') or 'album').title(),
                 'total': j.get('total_tracks'),
                 'artist': ', '.join(x.get('name', '')
                                     for x in j.get('artists') or []),
                 'thumb': _smallest_ok(j.get('images'))}
        return {'kind': 'album', 'card': {
            'kind': 'album', 'title': album['title'], 'artist': album['artist'],
            'year': album['year'], 'kind_name': album['kind'],
            'sources': {'sp': album}}}
    if kind == 'artist':
        name, thumb = '', None
        try:
            j = spotify_get(f'/artists/{sid}')
            name, thumb = j.get('name') or '', _smallest_ok(j.get('images'))
        except Exception:
            name = b.spotify_artist_name(text)
        if not name:
            raise ValueError("Couldn't read this Spotify artist.")
        card = _artist_card(name, thumb, sp_id=sid)
        try:                        # the same artist on YouTube Music
            for y in searcher._ytm_artists(name):
                if b._norm(y['name']) == b._norm(name):
                    card['sources']['ytm'] = y
                    break
        except Exception:
            pass
        return {'kind': 'artist', 'card': card}
    # playlist
    title, count, thumb = 'Spotify playlist', None, None
    try:
        j = spotify_get(f'/playlists/{sid}', {'fields': 'name,images,tracks.total'})
        title, count = j.get('name') or title, (j.get('tracks') or {}).get('total')
        thumb = _smallest_ok(j.get('images'))
    except Exception:
        pass
    return {'kind': 'playlist', 'title': title, 'count': count,
            'thumb': thumb, 'link': text}


# --------------------------------------------------------------------------
# Artist pages
# --------------------------------------------------------------------------
def artist_page(searcher, source, artist_id, name=''):
    """{'name', 'thumb', 'top': [download items], 'albums': [album dicts]}"""
    page = {'name': name, 'thumb': None, 'top': [], 'albums': []}
    if source == 'ytm':
        a = searcher.yt.get_artist(artist_id)
        page['name'] = a.get('name') or name
        thumbs = a.get('thumbnails') or []
        page['thumb'] = thumbs[-1]['url'] if thumbs else None
        for r in (a.get('songs') or {}).get('results') or []:
            if not r.get('videoId'):
                continue
            alb = r.get('album') or {}
            page['top'].append(b._track(
                r['videoId'], r.get('title'), b._names(r.get('artists')),
                alb.get('name') or '',
                cover=(r.get('thumbnails') or [{}])[-1].get('url'),
                duration=r.get('duration_seconds'), video_type=b.AUDIO_TRACK))
    else:
        try:
            j = spotify_get(f'/artists/{artist_id}')
            page['name'] = j.get('name') or name
            page['thumb'] = _smallest_ok(j.get('images'), want=300)
        except Exception:
            pass
        try:
            j = spotify_get(f'/artists/{artist_id}/top-tracks', {'market': 'US'})
            for t in j.get('tracks') or []:
                row = b._api_row(t, 0)
                row['album'] = (t.get('album') or {}).get('name') or ''
                row['track_number'] = t.get('track_number')
                page['top'].append(row)
        except Exception:
            pass
    for it in page['top']:
        it['duration_text'] = _fmt(it.get('duration'))
    page['albums'] = searcher.artist_albums(source, artist_id, page['name'])
    return page


def extract_shared_link(text):
    """What to put in the search bar when another app shares `text` with us:
    the first web address in it (shared text is often "Title https://..."),
    otherwise the text itself."""
    text = (text or '').strip()
    m = re.search(r"https?://[^\s<>\"']+", text)
    if m:
        return m.group(0).rstrip('.,;)')
    return text
