"""
fonts.py - makes song titles in any script show as real letters.

Kivy draws text with one font, and the default (Roboto) covers Latin,
Cyrillic and Greek (so Spanish, French, Russian ... already work) but has no
Hebrew, Arabic, Japanese, Thai ... letters; those showed as empty boxes.

`rich(text)` returns Kivy markup in which every run of letters from another
script is wrapped in a font that has them:
  * Hebrew, Arabic, Armenian, Georgian -> DejaVu Sans, which ships inside Kivy
    (so this works on every phone without extra files)
  * Chinese, Japanese, Korean, Thai, Indian scripts ... -> a Noto font that
    Android already has in /system/fonts, when the phone has one.

Right-to-left text (Hebrew, Arabic) needs its letters shown right to left. If
the phone's text engine does that itself it is left alone; otherwise the run
is reversed here (`rich` checks once, by drawing a test word).
"""
import glob
import os
import re
import sys


def escape_markup(text):
    """Same as kivy.utils.escape_markup, without importing Kivy (the
    background job uses this module too and has no screen)."""
    return text.replace('&', '&amp;').replace('[', '&bl;').replace(']', '&br;')


def _find_dejavu():
    """DejaVu Sans ships inside Kivy; find it without importing Kivy."""
    for base in sys.path:
        path = os.path.join(base or '.', 'kivy', 'data', 'fonts', 'DejaVuSans.ttf')
        if os.path.exists(path):
            return path
    return ''


DEJAVU = _find_dejavu()
FONT_DIRS = ['/system/fonts', '/system/font', '/product/fonts',
             '/system_ext/fonts', '/vendor/fonts',
             '/usr/share/fonts/truetype/noto', '/usr/share/fonts/opentype/noto']

# (first, last) code points -> script name
RANGES = [
    (0x0590, 0x05FF, 'hebrew'), (0xFB1D, 0xFB4F, 'hebrew'),
    (0x0600, 0x06FF, 'arabic'), (0x0750, 0x077F, 'arabic'),
    (0x08A0, 0x08FF, 'arabic'), (0xFB50, 0xFDFF, 'arabic'),
    (0xFE70, 0xFEFF, 'arabic'),
    (0x0530, 0x058F, 'armenian'), (0x10A0, 0x10FF, 'georgian'),
    (0x0900, 0x097F, 'devanagari'), (0x0980, 0x09FF, 'bengali'),
    (0x0A00, 0x0A7F, 'gurmukhi'), (0x0A80, 0x0AFF, 'gujarati'),
    (0x0B80, 0x0BFF, 'tamil'), (0x0C00, 0x0C7F, 'telugu'),
    (0x0C80, 0x0CFF, 'kannada'), (0x0D00, 0x0D7F, 'malayalam'),
    (0x0D80, 0x0DFF, 'sinhala'), (0x0E00, 0x0E7F, 'thai'),
    (0x0E80, 0x0EFF, 'lao'), (0x0F00, 0x0FFF, 'tibetan'),
    (0x1000, 0x109F, 'myanmar'), (0x1780, 0x17FF, 'khmer'),
    (0x1200, 0x137F, 'ethiopic'),
    (0x1100, 0x11FF, 'cjk'), (0x2E80, 0x2FDF, 'cjk'), (0x3000, 0x303F, 'cjk'),
    (0x3040, 0x30FF, 'cjk'), (0x3100, 0x312F, 'cjk'), (0x3130, 0x318F, 'cjk'),
    (0x31F0, 0x31FF, 'cjk'), (0x3400, 0x4DBF, 'cjk'), (0x4E00, 0x9FFF, 'cjk'),
    (0xAC00, 0xD7AF, 'cjk'), (0xF900, 0xFAFF, 'cjk'), (0xFF00, 0xFFEF, 'cjk'),
    (0x20000, 0x2FA1F, 'cjk'),
]
RTL = {'hebrew', 'arabic'}
BUNDLED = {'hebrew', 'arabic', 'armenian', 'georgian'}      # DejaVu covers these
# file-name patterns (inside the font folders) that hold each script
PATTERNS = {
    'cjk': ['NotoSansCJK-Regular*', 'NotoSansCJK*', 'NotoSansSC-Regular*',
            'NotoSansJP-Regular*', 'NotoSansKR-Regular*', 'SourceHanSans*',
            'DroidSansFallbackFull*', 'DroidSansFallback*'],
}
_cache = {}


def script_of(ch):
    """Script name for a character, 'weak' for spaces/digits/punctuation, or
    'default' for letters the normal font already has."""
    cp = ord(ch)
    if cp < 0x0530:
        if ch.isalpha():
            return 'default'
        return 'weak'
    for lo, hi, name in RANGES:
        if lo <= cp <= hi:
            return name
    if 0x2000 <= cp <= 0x2BFF or 0x1F000 <= cp <= 0x1FAFF:
        return 'weak'
    return 'default' if ch.isalpha() else 'weak'


def font_for(script):
    """Path of a font that has `script`, or None to keep the normal font."""
    if script in BUNDLED:
        return DEJAVU if os.path.exists(DEJAVU) else None
    if script in _cache:
        return _cache[script]
    pats = PATTERNS.get(script) or [f'NotoSans{script.capitalize()}-Regular*',
                                    f'NotoSans{script.capitalize()}*',
                                    f'NotoSerif{script.capitalize()}-Regular*']
    found = None
    for d in FONT_DIRS:
        for pat in pats:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            hits = [h for h in hits if not re.search(r'Bold|Italic|Light|Thin',
                                                     os.path.basename(h))
                    or pat.endswith('*')] or hits
            if hits:
                found = hits[0]
                break
        if found:
            break
    if found is None and os.path.exists(DEJAVU):
        found = DEJAVU                 # better than nothing for odd scripts
    _cache[script] = found
    return found


# --------------------------------------------------------------------------
# right-to-left handling
# --------------------------------------------------------------------------
_MIRROR = str.maketrans('()[]{}<>', ')(][}{><')
_sdl_bidi = None


def sdl_does_bidi():
    """True if this phone's text engine already shows Hebrew/Arabic right to
    left. Found once by drawing a test word and looking at which letter ends
    up on the left."""
    global _sdl_bidi
    if _sdl_bidi is not None:
        return _sdl_bidi
    _sdl_bidi = False
    try:
        from kivy.core.text import Label as CoreLabel

        def profile(text):
            lab = CoreLabel(text=text, font_name=DEJAVU, font_size=44)
            lab.refresh()
            tex = lab.texture
            w, h = tex.size
            px = tex.pixels
            return [sum(px[(y * w + x) * 4 + 3] for y in range(h))
                    for x in range(w)]

        full = profile('אבג')       # alef bet gimel
        alef = profile('א')
        gimel = profile('ג')
        n = min(len(alef), len(gimel), len(full) // 2)

        def distance(a):
            return sum(abs(full[i] - a[i]) for i in range(n))

        # alef drawn on the left = plain left-to-right (no bidi support)
        _sdl_bidi = distance(gimel) < distance(alef)
    except Exception:
        _sdl_bidi = False
    return _sdl_bidi


def _reverse_run(run):
    """Visual order for a right-to-left run when the engine does not do it:
    reverse the letters, keep digit groups readable, mirror brackets."""
    parts = re.split(r'(\d+)', run)
    out = []
    for p in reversed(parts):
        out.append(p if p.isdigit() else p[::-1].translate(_MIRROR))
    return ''.join(out)


# --------------------------------------------------------------------------
# splitting text into runs
# --------------------------------------------------------------------------
def runs(text):
    """[(script, text)]; weak characters stay with the surrounding script only
    when they sit between two letters of the same right-to-left script, so a
    bracket around a Hebrew word stays on the left-to-right side."""
    raw = []
    for ch in text:
        s = script_of(ch)
        if raw and raw[-1][0] == s:
            raw[-1][1] += ch
        else:
            raw.append([s, ch])
    merged = []
    for i, (s, t) in enumerate(raw):
        if s == 'weak':
            prev = raw[i - 1][0] if i else None
            nxt = raw[i + 1][0] if i + 1 < len(raw) else None
            if prev == nxt and prev in RTL | {'cjk', 'thai'}:
                s = prev               # between two words of one script
            else:
                s = 'default'
        if merged and merged[-1][0] == s:
            merged[-1][1] += t
        else:
            merged.append([s, t])
    return [(s, t) for s, t in merged]


def needs_fonts(text):
    return any(ord(c) >= 0x0530 and script_of(c) not in ('weak', 'default')
               for c in text)


def rich(text, fix_rtl=True):
    """Kivy markup for `text`, safe to put in a Label with markup=True."""
    text = str(text)
    if not needs_fonts(text):
        return escape_markup(text)
    bidi_ok = sdl_does_bidi() if fix_rtl else True
    out = []
    for script, chunk in runs(text):
        if script in RTL and not bidi_ok:
            chunk = _reverse_run(chunk)
        if script == 'default':
            out.append(escape_markup(chunk))
            continue
        path = font_for(script)
        if path:
            out.append(f'[font={path}]{escape_markup(chunk)}[/font]')
        else:
            out.append(escape_markup(chunk))
    return ''.join(out)


def visual(text):
    """Plain text in left-to-right visual order (for the PDF, which cannot
    reorder). Hebrew/Arabic runs are reversed, everything else is untouched."""
    out = []
    for script, chunk in runs(str(text)):
        out.append(_reverse_run(chunk) if script in RTL else chunk)
    return ''.join(out)
