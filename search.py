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
_token = {'value': None, 'expires': 0.0}


# --------------------------------------------------------------------------
# Spotify access (no login: shared app credentials, or the embed page's token)
# --------------------------------------------------------------------------
def spotify_token(force=False):
    import requests
    if not force and _token['value'] and time.time() < _token['expires']:
        return _token['value']
    try:
        r = requests.post('https://accounts.spotify.com/api/token',
                          data={'grant_type': 'client_credentials'},
                          auth=b.SPOTIFY_CLIENT, timeout=20)
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
            headers=b.SPOTIFY_UA, timeout=20)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                      r.text, re.S)
        tok = (json.loads(m.group(1))['props']['pageProps']['state']
               ['settings']['session']['accessToken'])
        _token.update(value=tok, expires=time.time() + 1800)
        return tok
    except Exception:
        return None


def spotify_get(path, params=None):
    """GET from Spotify's API, refreshing the token once if it was refused."""
    last = None
    for attempt in range(2):
        tok = spotify_token(force=attempt > 0)
        if not tok:
            break
        try:
            return b._api_get(SPOTIFY_API + path, tok, params)
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
                j = spotify_get(url, params)
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
        j = spotify_get(f'/albums/{album_id}')
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
            page = spotify_get(nxt.replace(SPOTIFY_API, '')) if nxt else None
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
