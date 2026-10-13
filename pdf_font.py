"""
pdf_font.py - just enough TrueType reading to put a font into a PDF.

The PDF's built-in Helvetica only has Western letters. For anything else
(Hebrew, Arabic, Cyrillic, Greek ...) report.py embeds a TrueType font and
writes each letter as its glyph number. No outside libraries are needed.
"""
import struct
import zlib


class TTF:
    def __init__(self, data):
        self.data = data
        n = struct.unpack('>H', data[4:6])[0]
        self.tables = {}
        for i in range(n):
            tag, _, off, length = struct.unpack('>4sIII',
                                                data[12 + 16 * i:28 + 16 * i])
            self.tables[tag.decode('latin-1')] = (off, length)
        head = self.tables['head'][0]
        self.units = struct.unpack('>H', data[head + 18:head + 20])[0]
        self.bbox = struct.unpack('>4h', data[head + 36:head + 44])
        hhea = self.tables['hhea'][0]
        self.ascent, self.descent = struct.unpack('>2h', data[hhea + 4:hhea + 8])
        self.n_hmetrics = struct.unpack('>H', data[hhea + 34:hhea + 36])[0]
        self._cmap = self._find_cmap()

    # ---- character -> glyph number ----------------------------------------
    def _find_cmap(self):
        off = self.tables['cmap'][0]
        count = struct.unpack('>H', self.data[off + 2:off + 4])[0]
        best = None
        for i in range(count):
            plat, enc, sub = struct.unpack(
                '>HHI', self.data[off + 4 + 8 * i:off + 12 + 8 * i])
            fmt = struct.unpack('>H', self.data[off + sub:off + sub + 2])[0]
            if fmt in (4, 12) and (plat, enc) in ((3, 1), (3, 10), (0, 3),
                                                   (0, 4), (0, 0), (0, 1)):
                if best is None or fmt == 12:
                    best = (fmt, off + sub)
        return best

    def glyph(self, cp):
        """Glyph number for a code point (0 = missing)."""
        if not self._cmap:
            return 0
        fmt, base = self._cmap
        d = self.data
        if fmt == 12:
            groups = struct.unpack('>I', d[base + 12:base + 16])[0]
            lo, hi = 0, groups - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                s, e, g = struct.unpack('>III', d[base + 16 + 12 * mid:
                                                  base + 28 + 12 * mid])
                if cp < s:
                    hi = mid - 1
                elif cp > e:
                    lo = mid + 1
                else:
                    return g + cp - s
            return 0
        if cp > 0xFFFF:
            return 0
        seg = struct.unpack('>H', d[base + 6:base + 8])[0] // 2
        ends = base + 14
        starts = ends + 2 * seg + 2
        deltas = starts + 2 * seg
        ranges = deltas + 2 * seg
        for i in range(seg):
            end = struct.unpack('>H', d[ends + 2 * i:ends + 2 * i + 2])[0]
            if cp > end:
                continue
            start = struct.unpack('>H', d[starts + 2 * i:starts + 2 * i + 2])[0]
            if cp < start:
                return 0
            delta = struct.unpack('>h', d[deltas + 2 * i:deltas + 2 * i + 2])[0]
            ro = struct.unpack('>H', d[ranges + 2 * i:ranges + 2 * i + 2])[0]
            if ro == 0:
                return (cp + delta) & 0xFFFF
            addr = ranges + 2 * i + ro + 2 * (cp - start)
            g = struct.unpack('>H', d[addr:addr + 2])[0]
            return (g + delta) & 0xFFFF if g else 0
        return 0

    # ---- widths ---------------------------------------------------------------------
    def advance(self, gid):
        """Advance width of a glyph in 1/1000 em."""
        hmtx = self.tables['hmtx'][0]
        idx = min(gid, self.n_hmetrics - 1)
        w = struct.unpack('>H', self.data[hmtx + 4 * idx:hmtx + 4 * idx + 2])[0]
        return round(w * 1000 / self.units)


def embed(ttf, used_gids, add):
    """Add the font's PDF objects through `add(body_bytes) -> object number`
    and return the number of the Type0 font object."""
    raw = ttf.data
    packed = zlib.compress(raw, 6)
    file_obj = add(b'<< /Length %d /Length1 %d /Filter /FlateDecode >>\n'
                   b'stream\n' % (len(packed), len(raw)) + packed +
                   b'\nendstream')
    k = 1000 / ttf.units
    x0, y0, x1, y1 = (round(v * k) for v in ttf.bbox)
    desc = add(b'<< /Type /FontDescriptor /FontName /EmbeddedSans /Flags 4 '
               b'/FontBBox [%d %d %d %d] /ItalicAngle 0 /Ascent %d /Descent %d '
               b'/CapHeight 729 /StemV 80 /FontFile2 %d 0 R >>'
               % (x0, y0, x1, y1, round(ttf.ascent * k),
                  round(ttf.descent * k), file_obj))
    widths = b' '.join(b'%d [%d]' % (g, ttf.advance(g))
                       for g in sorted(used_gids))
    cid = add(b'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /EmbeddedSans '
              b'/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) '
              b'/Supplement 0 >> /FontDescriptor %d 0 R /DW 600 /W [%s] '
              b'/CIDToGIDMap /Identity >>' % (desc, widths))
    return add(b'<< /Type /Font /Subtype /Type0 /BaseFont /EmbeddedSans '
               b'/Encoding /Identity-H /DescendantFonts [%d 0 R] >>' % cid)
