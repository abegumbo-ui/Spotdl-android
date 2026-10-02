"""
report.py - writes the download report as a PDF using only the standard
library (no reportlab / Pillow), so it adds nothing to the Android build.

Text is set in the built-in Helvetica font, which covers Western European
characters. Anything else (e.g. Japanese titles) is shown as '?'.
"""
import time

PAGE_W, PAGE_H = 595, 842
MARGIN = 50
GREEN, RED, ORANGE, GREY, BLACK = ((0.07, 0.55, 0.25), (0.8, 0.1, 0.1),
                                   (0.85, 0.5, 0.0), (0.4, 0.4, 0.4),
                                   (0, 0, 0))


def _esc(text):
    data = str(text).encode('cp1252', errors='replace')
    out = data.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
    return out.decode('latin-1')


def _wrap(text, size, width):
    """Greedy word wrap using an average Helvetica character width."""
    max_chars = max(10, int(width / (size * 0.5)))
    lines, line = [], ''
    for word in str(text).split():
        while len(word) > max_chars:                 # very long token
            if line:
                lines.append(line)
                line = ''
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if len(line) + len(word) + (1 if line else 0) > max_chars:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}' if line else word
    if line:
        lines.append(line)
    return lines or ['']


def _jpeg_info(data):
    """(width, height, components) for a baseline/progressive JPEG, or None."""
    if data[:2] != b'\xff\xd8':
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return (int.from_bytes(data[i + 7:i + 9], 'big'),
                    int.from_bytes(data[i + 5:i + 7], 'big'), data[i + 9])
        i += 2 + int.from_bytes(data[i + 2:i + 4], 'big')
    return None


class _Pdf:
    def __init__(self):
        self.pages = []          # list of (content_stream_text, uses_image)
        self._cur = []
        self.y = PAGE_H - MARGIN
        self.image = None        # (bytes, w, h, comps)

    # -- drawing -----------------------------------------------------------
    def _new_page(self):
        self.pages.append(self._cur)
        self._cur = []
        self.y = PAGE_H - MARGIN

    def text(self, text, size=10, bold=False, color=BLACK, indent=0,
             width=None, gap=3):
        width = width or (PAGE_W - 2 * MARGIN - indent)
        font = 'F2' if bold else 'F1'
        for line in _wrap(text, size, width):
            if self.y - size < MARGIN:
                self._new_page()
            self.y -= size
            r, g, b = color
            self._cur.append(
                f'BT /{font} {size} Tf {r} {g} {b} rg '
                f'{MARGIN + indent} {self.y:.1f} Td ({_esc(line)}) Tj ET')
            self.y -= gap

    def space(self, pts):
        self.y -= pts

    def rule(self):
        if self.y - 6 < MARGIN:
            self._new_page()
        self.y -= 4
        self._cur.append(f'0.8 g {MARGIN} {self.y:.1f} '
                         f'{PAGE_W - 2 * MARGIN} 0.7 re f')
        self.y -= 6

    def place_cover(self, x, y, size):
        self._cur.append(f'q {size} 0 0 {size} {x} {y} cm /Im1 Do Q')

    # -- serialisation -------------------------------------------------------
    def save(self, path):
        self.pages.append(self._cur)
        objs = []                                    # bodies, 1-indexed later

        def add(body):
            objs.append(body)
            return len(objs)

        add(b'')                                     # 1: catalog (filled later)
        add(b'')                                     # 2: pages  (filled later)
        f1 = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica '
                 b'/Encoding /WinAnsiEncoding >>')
        f2 = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold '
                 b'/Encoding /WinAnsiEncoding >>')
        img = None
        if self.image:
            data, w, h, comps = self.image
            cs = b'/DeviceRGB' if comps == 3 else (
                b'/DeviceGray' if comps == 1 else b'/DeviceCMYK')
            head = (b'<< /Type /XObject /Subtype /Image /Width %d /Height %d '
                    b'/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode '
                    b'/Length %d >>\nstream\n' % (w, h, cs, len(data)))
            img = add(head + data + b'\nendstream')
        kids = []
        for ops in self.pages:
            stream = '\n'.join(ops).encode('latin-1')
            c = add(b'<< /Length %d >>\nstream\n' % len(stream) + stream +
                    b'\nendstream')
            res = b'<< /Font << /F1 %d 0 R /F2 %d 0 R >>' % (f1, f2)
            if img:
                res += b' /XObject << /Im1 %d 0 R >>' % img
            res += b' >>'
            p = add(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                    b'/Resources %s /Contents %d 0 R >>'
                    % (PAGE_W, PAGE_H, res, c))
            kids.append(p)
        objs[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
        objs[1] = (b'<< /Type /Pages /Kids [%s] /Count %d >>'
                   % (b' '.join(b'%d 0 R' % k for k in kids), len(kids)))

        out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets = []
        for n, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b'%d 0 obj\n' % n + body + b'\nendobj\n'
        xref = len(out)
        out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
        for off in offsets:
            out += b'%010d 00000 n \n' % off
        out += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                % (len(objs) + 1, xref))
        with open(path, 'wb') as f:
            f.write(out)


def build_report(path, title, link, audio_format, results, missing,
                 cover_bytes=None):
    """results: [{'track','status','note'}], missing: [{'title','artist','reason'}]"""
    done = [r for r in results if r['status'] == 'done']
    skipped = [r for r in results if r['status'] == 'skipped']
    failed = [r for r in results if r['status'] == 'failed']
    total = len(results) + len(missing)

    pdf = _Pdf()
    info = _jpeg_info(cover_bytes) if cover_bytes else None
    if info:
        pdf.image = (cover_bytes, info[0], info[1], info[2])
        pdf.place_cover(PAGE_W - MARGIN - 90, PAGE_H - MARGIN - 90, 90)
    text_w = PAGE_W - 2 * MARGIN - (100 if info else 0)

    pdf.text('SpotDL Downloader - Download report', 10, color=GREY,
             width=text_w)
    pdf.text(title, 20, bold=True, width=text_w, gap=6)
    pdf.text(time.strftime('%Y-%m-%d %H:%M'), 10, color=GREY, width=text_w)
    pdf.text(f'Source: {link}', 9, color=GREY, width=text_w)
    pdf.text(f'Format: {audio_format}', 9, color=GREY, width=text_w)
    pdf.y = min(pdf.y, PAGE_H - MARGIN - 100)
    pdf.space(6)
    pdf.rule()

    pdf.text(f'{total} songs: {len(done)} downloaded, {len(skipped)} already '
             f'in the folder, {len(failed) + len(missing)} failed or '
             f'unavailable', 12, bold=True, gap=6)
    pdf.space(4)

    def section(heading, color, rows):
        if not rows:
            return
        pdf.text(f'{heading} ({len(rows)})', 13, bold=True, color=color, gap=6)
        for n, (line, note) in enumerate(rows, 1):
            pdf.text(f'{n}. {line}', 10, indent=8)
            if note:
                pdf.text(note, 9, color=color, indent=22)
        pdf.space(8)

    def name(t):
        extra = f" [{t['album']}]" if t.get('album') else ''
        return f"{t['title']} - {t['artist']}{extra}"

    section('Failed / not downloaded', RED,
            [(name(r['track']), 'Reason: ' + (r['note'] or 'unknown'))
             for r in failed] +
            [(f"{m['title']} - {m['artist']}", 'Reason: ' + m['reason'])
             for m in missing])
    section('Downloaded', GREEN,
            [(name(r['track']), r['note'] and 'Note: ' + r['note'])
             for r in done])
    section('Already in the folder (skipped)', GREY,
            [(name(r['track']), '') for r in skipped])
    pdf.save(path)
