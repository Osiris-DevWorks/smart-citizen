"""Name tag reader for the player ID test (Qt-free, like the scan decoder).

Reads the name tags Star Citizen draws over ships and players from a capture
of the game's window: lines of HUD capitals, digits, hyphens and underscores.
Pure Python, no model: glyphs are matched to reference glyphs on a grid
(``sco_tag_glyphs.py``), the way ``sco_digit_reader.py`` reads the scanner's
digits.

How it differs from the scan decoder:

- it searches a whole picture, in each colour channel at several brightness
  cuts, where the scan decoder reads one small panel
- it reads lines of letters with marks and gaps, not the ``N,NNN`` shape
- a finer grid (8 by 12) and a width check, since letters are a bigger set
- extra checks for look-alikes (O 0 D Q, B 8, S 5) and for small tags

``find_lines`` finds lines of capitals in one channel at one cut,
``read_line`` reads one of them, and ``read_place`` reads the tag at a point
of a small picture with every pass put together (``combine``).

The mask, the blob labelling, the cut for touching glyphs and a glyph's
pixels are this module's own copies of the scan decoder's helpers as they
stood in 3.0.0. The reader was tuned and measured against those, so they are
kept apart from ``sco_digit_reader.py``, which changes with the scanner.
"""
from __future__ import annotations

import re
import time
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field


class Frame:
    """One capture as three channel byte strings, row after row."""

    def __init__(self, width: int, height: int, red: bytes, green: bytes, blue: bytes):
        self.width, self.height = width, height
        self.red, self.green, self.blue = red, green, blue

    @classmethod
    def from_rgb32(cls, width: int, height: int, data: bytes) -> "Frame":
        """A capture from ``QImage.Format_RGB32`` bytes with no row padding
        (B, G, R, A for each pixel on x86)."""
        if len(data) != width * height * 4:
            raise ValueError("unexpected row padding")
        return cls(width, height, data[2::4], data[1::4], data[0::4])

    def channels(self):
        return {"r": self.red, "g": self.green, "b": self.blue}

    def crop(self, x: int, y: int, w: int, h: int) -> "Frame":
        x, y = max(0, x), max(0, y)
        w, h = min(w, self.width - x), min(h, self.height - y)
        out = []
        for channel in (self.red, self.green, self.blue):
            out.append(b"".join(channel[(y + row) * self.width + x:(y + row) * self.width + x + w]
                                for row in range(h)))
        return Frame(w, h, *out)

    def rows(self, channel: str) -> list[bytes]:
        data = self.channels()[channel]
        return [data[y * self.width:(y + 1) * self.width] for y in range(self.height)]


# -- the scan decoder's helpers, as they stood in 3.0.0 -----------------------

# A capital-tall blob up to this many capital heights wide is taken for
# touching glyphs and cut apart; each part must be at least MIN_PART_WIDTH
# capital heights wide.
MAX_JOINED_WIDTH = 2.6
MIN_PART_WIDTH = 0.2

_RUN = re.compile(rb"\x01+")


def _components(width: int, height: int, mask: bytearray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes ``(x, y, w, h)`` of 8-connected foreground blobs.

    8-connected so a thin stroke that only touches diagonally (the planet
    HUD's "3") stays one glyph. Works on runs: a run joins every run in the
    row above that overlaps it or touches it at a corner.
    """
    parent: list[int] = []
    bbox: list[list[int]] = []    # per run, [x0, y0, x1, y1], merged into roots

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    above: list[tuple[int, int, int]] = []    # (x0, x1, run id), x1 inclusive
    for y in range(height):
        row = y * width
        current = []
        k, n_above = 0, len(above)
        for m in _RUN.finditer(mask, row, row + width):
            x0, x1 = m.start() - row, m.end() - row - 1
            rid = len(parent)
            parent.append(rid)
            box = [x0, y, x1, y]
            bbox.append(box)
            # Skip runs above that end left of this one's reach; they can't
            # touch this run or any later one in the row.
            while k < n_above and above[k][1] < x0 - 1:
                k += 1
            j, root = k, rid
            while j < n_above and above[j][0] <= x1 + 1:
                a = find(above[j][2])
                if a != root:
                    # The run's set joins the run above's set.
                    parent[root] = a
                    ba = bbox[a]
                    if box[0] < ba[0]:
                        ba[0] = box[0]
                    if box[1] < ba[1]:
                        ba[1] = box[1]
                    if box[2] > ba[2]:
                        ba[2] = box[2]
                    if box[3] > ba[3]:
                        ba[3] = box[3]
                    root, box = a, ba
                j += 1
            current.append((x0, x1, rid))
        above = current
    return [(b[0], b[1], b[2] - b[0] + 1, b[3] - b[1] + 1)
            for i, b in enumerate(bbox) if parent[i] == i]


def _mask(width: int, height: int, red: bytes, threshold: int, max_run: int) -> bytearray:
    table = bytes(1 if v >= threshold else 0 for v in range(256))
    mask = bytearray(red.translate(table))
    # Drop wide horizontal runs (panel edges, bright horizons).
    wide = re.compile(rb"\x01{%d,}" % (max_run + 1))
    spans = [m.span() for row in range(0, width * height, width)
             for m in wide.finditer(mask, row, row + width)]
    for start, end in spans:
        mask[start:end] = bytes(end - start)
    return mask


def _split_joined(width, mask, box, digit_px) -> list[tuple[int, int, int, int]]:
    """Cut a blob too wide for one glyph into glyph-wide parts.

    Cuts at the column with the fewest lit pixels (that column is the bridge
    and belongs to neither part), nearest the middle on a tie, and again in
    a part still too wide. Each part's box is trimmed to its own pixels.
    Returns ``[box]`` for a blob narrow enough already, and nothing for one
    too wide to be touching glyphs.
    """
    x0, y0, w, h = box
    if w <= digit_px:
        return [box]
    min_part = max(2, round(MIN_PART_WIDTH * digit_px))
    if w > MAX_JOINED_WIDTH * digit_px or w < 2 * min_part + 1:
        return []
    ink = [sum(mask[y * width + x] for y in range(y0, y0 + h)) for x in range(x0, x0 + w)]
    cut = min(range(min_part, w - min_part), key=lambda i: (ink[i], abs(2 * i + 1 - w)))
    parts = []
    for start, end in ((x0, x0 + cut), (x0 + cut + 1, x0 + w)):
        rows = [y for y in range(y0, y0 + h)
                if any(mask[y * width + x] for x in range(start, end))]
        if rows:
            part = (start, rows[0], end - start, rows[-1] - rows[0] + 1)
            parts.extend(_split_joined(width, mask, part, digit_px))
    return parts


def _glyph_pixels(width, red, box, top, base, threshold):
    """One channel's pixels of one glyph, cut to its inked columns in the row."""
    x0, _, w, _ = box
    cols = [x for x in range(x0, x0 + w)
            if any(red[y * width + x] >= threshold for y in range(top, base))]
    if not cols:
        return None
    return [[red[y * width + x] for x in range(cols[0], cols[-1] + 1)]
            for y in range(top, base)]


# -- the tag reader -----------------------------------------------------------

# Raised whenever find_lines changes what it finds, so that lines cached by
# the test scripts are found afresh. 2: hyphens are cut off the glyph they
# ran into, and a full stop has to be a square on the baseline. 3: a line
# knows whether anything stands close beside its ends.
FINDER = 4

# Capital height of a contact tag's name, measured on a 3840x2160 capture.
CAP_AT_2160 = 17.0
# The brightness cuts each channel is looked at with. 230 is for tags over
# bright ground (sand, snow, sky, a lit hull), where 190 lets the background
# through: on the second run's crops it took bright or busy backgrounds from
# 71 right of 105 to 96. The cut at 100 the first tests used added nothing
# once 230 was there, so the count of passes is unchanged.
THRESHOLDS = (230, 190, 140)
CHANNELS = ("r", "g", "b")
GRID_W, GRID_H = 8, 12     # the grid that did best in step 2
# How much a glyph's width (in capital heights) may differ from a
# reference's before the match is marked down.
ASPECT_WEIGHT = 0.8


@dataclass
class Glyph:
    box: tuple[int, int, int, int]
    kind: str                       # "tall", or the punctuation mark itself
    ranked: list = field(default_factory=list)   # [(score, char), ...] best first

    @property
    def char(self) -> str:
        if self.kind != "tall":
            return self.kind
        return self.ranked[0][1] if self.ranked else "?"

    @property
    def score(self) -> float:
        if self.kind != "tall":
            return 1.0
        return self.ranked[0][0] if self.ranked else 0.0


@dataclass
class Line:
    glyphs: list
    channel: str
    threshold: int
    top: int
    base: int
    cap_px: float
    # Blobs of lower-case height sitting on the line's baseline, in or beside
    # it. A tag is all capitals, so two or more means ordinary prose.
    lowercase: int = 0
    # Blobs standing close beside the line's first or last glyph, at its own
    # height, that are not part of it. A tag stands alone, so anything there
    # may be the rest of a name that something else is drawn across.
    crowded: int = 0

    @property
    def box(self) -> tuple[int, int, int, int]:
        x0 = min(g.box[0] for g in self.glyphs)
        x1 = max(g.box[0] + g.box[2] for g in self.glyphs)
        return x0, self.top, x1 - x0, self.base - self.top

    def contains(self, x: int, y: int, pad: int = 6) -> bool:
        bx, by, bw, bh = self.box
        return bx - pad <= x <= bx + bw + pad and by - pad <= y <= by + bh + pad

    @property
    def text(self) -> str:
        out = []
        for i, g in enumerate(self.glyphs):
            if i:
                prev = self.glyphs[i - 1]
                gap = g.box[0] - (prev.box[0] + prev.box[2])
                wide = gap >= 0.42 * (self.base - self.top)
                if wide and g.kind == "tall" and prev.kind == "tall":
                    out.append(" ")
            out.append(g.char)
        return "".join(out)

    @property
    def pattern(self) -> str:
        return "".join("T" if g.kind == "tall" else g.kind for g in self.glyphs)

    @property
    def score(self) -> float:
        tall = [g.score for g in self.glyphs if g.kind == "tall"]
        return sum(tall) / len(tall) if tall else 0.0

    @property
    def confidence(self) -> float:
        """Sum of how far each glyph's match is above 0.5: more glyphs and
        better matches both raise it, and a poor glyph lowers it."""
        return sum(g.score - 0.5 for g in self.glyphs if g.kind == "tall")

    @property
    def worst(self) -> float:
        tall = [g.score for g in self.glyphs if g.kind == "tall"]
        return min(tall) if tall else 0.0


def _is_tall(box, cap_px) -> bool:
    return 0.78 * cap_px <= box[3] <= 1.3 * cap_px


def _small_kind(box, top, base, cap_px):
    """What punctuation a small blob is, by where it sits in the line."""
    x, y, w, h = box
    height = max(1.0, base - top)
    rel_top, rel_bottom = (y - top) / height, (y + h - top) / height
    if h > 0.45 * cap_px or w > 0.9 * cap_px or w * h < 3:
        return None
    if rel_top >= 0.25 and rel_bottom <= 0.78 and w >= 0.22 * cap_px and h <= 0.3 * cap_px:
        return "-"
    if w * h < 4:
        return None             # only a hyphen may be as small as three pixels
    if rel_top >= 0.6 and rel_bottom >= 0.85 and rel_bottom <= 1.25:
        if w >= 0.5 * cap_px:
            return "_"
        # A full stop is a small square standing on the baseline. A HUD tick
        # under a targeted contact's tag is a thin upright, and hangs lower.
        if abs(y + h - base) <= max(1, round(0.08 * height)) and h <= w + 1:
            return "."
        return None
    if -0.15 <= rel_top <= 0.15 and rel_bottom <= 0.55 and w <= 0.3 * cap_px:
        return "'"
    return None


# The game sets a hyphen close against the glyph after it, and the point of
# a 4 sits at the hyphen's own height, so "-4" often comes out as one blob.
# Set to False to leave such a blob whole.
PEEL_HYPHENS = True


def _peel_hyphens(width: int, mask, box, cap_px: float):
    """Cut a hyphen off either side of a glyph it has run into. Returns the
    glyph's box without it and the hyphens cut off.

    A hyphen is a flat bar: columns inked only in one thin band of rows near
    the middle, the band staying at one height. The point of a 4 is thin
    too, but it climbs from column to column, so it is left alone."""
    x, y, w, h = box
    lo, hi = y + 0.2 * h, y + 0.8 * h
    thick = max(2, round(0.3 * cap_px))
    need = max(3, round(0.22 * cap_px))
    keep = max(3, round(0.3 * cap_px))       # what must be left of the glyph

    def band(col: int):
        rows = [r for r in range(y, y + h) if mask[r * width + col]]
        if not rows or rows[0] < lo or rows[-1] > hi or rows[-1] - rows[0] + 1 > thick:
            return None
        return rows[0], rows[-1]

    hyphens = []
    left, right = x, x + w                   # the glyph's columns, right exclusive
    for step in (1, -1):
        col = left if step == 1 else right - 1
        first = band(col)
        run = []
        while first is not None and left <= col < right:
            rows = band(col)
            if rows is None or abs(rows[0] - first[0]) > 1 or abs(rows[1] - first[1]) > 1:
                break
            run.append((col, rows))
            col += step
        if len(run) < need or right - left - len(run) < keep:
            continue
        cols = [c for c, _ in run]
        top = min(rows[0] for _, rows in run)
        base = max(rows[1] for _, rows in run)
        hyphens.append((min(cols), top, len(cols), base - top + 1))
        if step == 1:
            left += len(run)
        else:
            right -= len(run)
    if not hyphens:
        return box, []
    rows = [r for r in range(y, y + h) if any(mask[r * width + c] for c in range(left, right))]
    if not rows:
        return box, []
    return (left, rows[0], right - left, rows[-1] - rows[0] + 1), hyphens


def _in_a_gap(small_box, chain) -> bool:
    """True when *small_box* lies between two neighbouring glyphs of *chain*
    without reaching into either one's columns."""
    left, right = small_box[0], small_box[0] + small_box[2]
    for a, b in zip(chain, chain[1:]):
        if a[0] + a[2] - 1 <= left and right <= b[0] + 1:
            return True
    return False


def find_lines(frame: Frame, channel: str, threshold: int, cap_px: float,
               min_glyphs: int = 3) -> list[Line]:
    """Lines of capital-height glyphs in one channel at one threshold."""
    width, height = frame.width, frame.height
    data = frame.channels()[channel]
    mask = _mask(width, height, data, threshold, int(1.2 * cap_px))
    boxes = _components(width, height, mask)
    tall, small, mid = [], [], []
    for box in boxes:
        if 0.4 * cap_px <= box[3] <= 2.2 * cap_px and box[2] <= 1.6 * cap_px:
            mid.append(box)         # anything a letter of another height could be
        if _is_tall(box, cap_px):
            if PEEL_HYPHENS:
                box, hyphens = _peel_hyphens(width, mask, box, cap_px)
                small.extend(hyphens)
            if box[2] <= 1.25 * cap_px:
                tall.append(box)
            else:
                # Touching glyphs: the digit reader's own cut, with the width
                # limit of a letter instead of a digit.
                tall.extend(p for p in _split_joined(width, mask, box, 1.25 * cap_px)
                            if _is_tall(p, cap_px))
        elif (box[3] <= 0.45 * cap_px and box[2] <= 0.9 * cap_px
              and box[2] * box[3] >= (3 if cap_px < SMALL_CAP and box[2] >= 3 else 4)):
            # Under SMALL_CAP a hyphen is three pixels in a row, no more.
            small.append(box)
    tall.sort()
    small.sort()
    mid.sort()
    solid = sorted(b for b in boxes if b[2] * b[3] >= 0.1 * cap_px * cap_px)
    tol = max(2, round(0.15 * cap_px))
    used: set[int] = set()
    lines = []
    for i, first in enumerate(tall):
        if i in used:
            continue
        chain = [first]
        used.add(i)
        for j in range(i + 1, len(tall)):
            nxt, last = tall[j], chain[-1]
            if nxt[0] > last[0] + last[2] + 1.6 * cap_px:
                break
            if j in used:
                continue
            gap = nxt[0] - (last[0] + last[2])
            if (gap >= -1 and abs(nxt[1] - last[1]) <= tol
                    and abs(nxt[1] + nxt[3] - last[1] - last[3]) <= tol):
                chain.append(nxt)
                used.add(j)
        if len(chain) < min_glyphs:
            continue
        bottoms = sorted(b[1] + b[3] for b in chain)
        base = bottoms[len(bottoms) // 2]
        tops = sorted(b[1] for b in chain)
        top = tops[len(tops) // 2]
        x0, x1 = chain[0][0], chain[-1][0] + chain[-1][2]
        glyphs = [Glyph(b, "tall") for b in chain]
        for k in range(bisect_left(small, (x0,)), len(small)):
            s = small[k]
            if s[0] > x1:
                break
            kind = _small_kind(s, top, base, cap_px)
            # A mark counts only in a gap between two capital-height glyphs:
            # a speck over or under a glyph is a broken stroke or the scene.
            if kind and _in_a_gap(s, chain):
                glyphs.append(Glyph(s, kind))
        glyphs.sort(key=lambda g: g.box[0])
        lines.append(Line(glyphs, channel, threshold, top, base, cap_px,
                          _lowercase_in(chain, mid, top, base, tol, cap_px),
                          _beside(chain, solid, top, base, cap_px)))
    return lines


def _beside(chain, solid, top: int, base: int, cap_px: float) -> int:
    """How many blobs stand within a capital's height of the chain's first or
    last glyph, in the line's own band of rows, without being part of it.
    *solid* is every blob too big to be a speck or a hyphen, sorted."""
    x0, x1 = chain[0][0], chain[-1][0] + chain[-1][2]
    reach = cap_px
    band_top, band_base = top - 0.1 * cap_px, base + 0.25 * cap_px
    widest = 12 * cap_px                     # nothing wider than this is looked at
    count = 0
    for k in range(bisect_left(solid, (int(x0 - reach - widest),)), len(solid)):
        bx, by, bw, bh = solid[k]
        if bx > x1 + reach:
            break
        if bw > widest or min(by + bh, band_base) - max(by, band_top) < 2:
            continue
        left_of = bx + bw <= x0 + 1 and x0 - (bx + bw) <= reach
        right_of = bx >= x1 - 1 and bx - x1 <= reach
        # A blob reaching in from outside counts too: it starts beyond an end
        # and runs across it.
        across = (bx < x0 - 1 and x0 + 1 < bx + bw <= x0 + reach) or (
            x1 - reach <= bx < x1 - 1 and bx + bw > x1 + 1)
        if left_of or right_of or across:
            count += 1
    return count


def _lowercase_in(chain, mid, top: int, base: int, tol: int, cap_px: float) -> int:
    """How many letters of another height stand on the baseline beside the
    glyphs of *chain*, close up the way letters in a word are. A tag is all
    capitals of one height. Prose mixes heights: lower-case letters among
    capitals, or capitals and tall letters among lower-case ones. Scenery
    behind a tag is not counted: it is either joined to a letter or stands
    apart from them."""
    x0, x1 = chain[0][0], chain[-1][0] + chain[-1][2]
    close = 0.4 * cap_px
    reach = 1.5 * cap_px
    line_height = base - top
    edges = [(b[0], b[0] + b[2]) for b in chain]
    count = 0
    for k in range(bisect_left(mid, (int(x0 - reach),)), len(mid)):
        m = mid[k]
        if m[0] > x1 + reach:
            break
        shorter = 0.5 * line_height <= m[3] <= 0.82 * line_height
        taller = 1.18 * line_height <= m[3] <= 1.7 * line_height
        if abs(m[1] + m[3] - base) > tol or not (shorter or taller):
            continue
        left, right = m[0], m[0] + m[2]
        if any(a < right - 1 and left + 1 < b for a, b in edges):
            continue                    # over a glyph of the line: part of it, or behind it
        if any(0 <= left - b <= close or 0 <= a - right <= close for a, b in edges):
            count += 1
            edges.append((left, right))
    return count


def features(pixels, grid_w: int = GRID_W, grid_h: int = GRID_H) -> list[float]:
    """The digit reader's glyph features on a finer grid: area-sampled,
    min-max normalised, mean removed, unit length."""
    h, w = len(pixels), len(pixels[0])
    lo = min(min(r) for r in pixels)
    hi = max(max(r) for r in pixels)
    out = []
    for gy in range(grid_h):
        y0, y1 = gy * h / grid_h, (gy + 1) * h / grid_h
        for gx in range(grid_w):
            x0, x1 = gx * w / grid_w, (gx + 1) * w / grid_w
            total = area = 0.0
            for y in range(int(y0), min(h, int(y1 + 0.999))):
                wy = min(y + 1, y1) - max(y, y0)
                for x in range(int(x0), min(w, int(x1 + 0.999))):
                    wx = min(x + 1, x1) - max(x, x0)
                    total += wy * wx * pixels[y][x]
                    area += wy * wx
            out.append((total / area - lo) / (hi - lo + 1e-9))
    mean = sum(out) / len(out)
    centred = [v - mean for v in out]
    norm = sum(v * v for v in centred) ** 0.5 or 1.0
    return [v / norm for v in centred]


def glyph_features(frame: Frame, line: Line, glyph: Glyph):
    """(features, width in capital heights) of one tall glyph, or None."""
    data = frame.channels()[line.channel]
    pixels = _glyph_pixels(frame.width, data, glyph.box, line.top, line.base, line.threshold)
    if pixels is None or not pixels or not pixels[0]:
        return None
    return features(pixels), len(pixels[0]) / max(1, line.base - line.top)


@dataclass(frozen=True)
class Reference:
    char: str
    feat: tuple
    aspect: float
    source: str          # "<shot>:<text>", so a test can leave a tag out


# A glyph narrower than this many capital heights is a plain bar (an "I").
# Trimmed to its own columns it is solid ink, with no shape to correlate, so
# bars are matched to bars by width alone.
BAR_ASPECT = 0.3


def rank(feat, aspect, references, skip=lambda ref: False):
    """Best score per character, highest first."""
    best: dict[str, float] = {}
    bar = aspect < BAR_ASPECT
    for ref in references:
        if skip(ref) or (ref.aspect < BAR_ASPECT) != bar:
            continue
        if bar:
            score = 1.0 - abs(aspect - ref.aspect)
        else:
            score = sum(a * b for a, b in zip(feat, ref.feat))
            score -= ASPECT_WEIGHT * abs(aspect - ref.aspect)
        if score > best.get(ref.char, -9.0):
            best[ref.char] = score
    return sorted(((s, c) for c, s in best.items()), reverse=True)


# The round letters. They match each other closely on the grid, and in the
# game's font they differ in two small places, which are looked at directly:
# a Q has a short tail under the baseline, and a D's left stroke runs square
# to its top and bottom where an O's corners are cut off. An O and a 0 are the
# same shape, so nothing here tells those two apart.
ROUND = "O0DQ"
# The ends of the left stroke against its middle, with the background taken
# away: at or above SQUARE the corners are square (a D), at or below CUT they
# are cut off (not a D). In between, the grid's own order stands. Measured on
# the labelled 4K crops of both runs: a D has 0.90 to 0.98 in the middle and
# 0.33 at its lowest twentieth, an O 0.00 in the middle and 0.25 at its
# highest twentieth, on plain backgrounds and on bright ones alike.
SQUARE = 0.50
CUT = 0.20
# Capitals shorter than this many pixels (a game window about 1440 px tall
# or less: 8.5 px at 1080, 11 to 12 px at 1440) have strokes a pixel or two
# wide. They get their own measure, small_measures below. Should that find
# too little contrast, the first measure is kept: the plain ratio of the
# stroke's ends to its middle, with its own two limits.
SMALL_CAP = 14
SMALL_SQUARE = 0.72
SMALL_CUT = 0.35
# Set to False to read without the round-letter check.
CHECK_ROUND_LETTERS = True
# Set to False to leave a small B or 8 as the grid read it.
CHECK_SQUARE_LETTERS = True


def stroke_ends(frame: Frame, line: Line, glyph: Glyph, small: bool = False) -> float:
    """How bright the top and bottom ends of a glyph's left stroke are,
    against the stroke's middle: near 1 for a D, near 0 for an O.

    The background is taken away first, or the cut corners of an O over
    bright ground would count as ink. It is the low quarter of the glyph's
    own pixels, which is what shows through its hollow. And the stroke is
    the brighter of the two columns from the first one inked over half the
    glyph's height: the very first can be glow, which fades towards its ends
    the way an O's corners do.

    With *small* it is the plain ratio at that first column, nothing taken
    away, which is all a stroke a pixel wide allows."""
    data = frame.channels()[line.channel]
    width = frame.width
    x, y, w, h = glyph.box
    base = min(y + h, line.base) if line.base - y >= 3 else y + h
    height = base - y
    if height < 3:
        return 0.0
    columns = [[data[r * width + x + c] for r in range(y, base)] for c in range(w)]

    def level_of(column) -> int:
        middle = sorted(column[len(column) // 4:(3 * len(column)) // 4])
        return middle[len(middle) // 2] or 1

    for c, column in enumerate(columns):
        if sum(1 for v in column if v >= line.threshold) >= 0.5 * height:
            if small:
                return min(column[0], column[-1]) / level_of(column)
            stroke = max(columns[c:c + 2], key=level_of)
            values = sorted(v for col in columns for v in col)
            background = values[len(values) // 4]
            level = level_of(stroke)
            return (min(stroke[0], stroke[-1]) - background) / max(1, level - background)
    return 0.0


def rows_under(frame: Frame, line: Line, glyph: Glyph) -> int:
    """How many rows of a glyph lie under the line's baseline and are
    narrow: the tail of a Q. A wide row there is the glyph's own bottom
    stroke sitting a pixel low, which does not count."""
    data = frame.channels()[line.channel]
    width = frame.width
    x, y, w, h = glyph.box
    rows = 0
    for r in range(line.base, min(frame.height, y + h)):
        inked = sum(1 for v in data[r * width + x:r * width + x + w] if v >= line.threshold)
        if 1 <= inked <= max(1, 0.45 * w):
            rows += 1
    return rows


# Small capitals (under SMALL_CAP px) are measured on the glyph's own ink,
# whatever threshold the pass found it at: the pixels that reach CORE_SHARE of
# the way from the background (the darkest tenth of the pixels round the
# glyph) to its brightest stroke. Everything here was picked on half the
# names of the third run and checked on the other half (step10_halves.py).
CORE_SHARE = 0.5
CORE_GROUND = 0.10
# A Q's tail has to be brighter than that, or the glow under an O counts as
# one. At this share 1 O or D in 300 shows a tail, and 1 Q in 10 shows none.
TAIL_SHARE = 0.6
# How much squarer the left stroke's ends are than the right stroke's: about
# 0 for an O, an 8 or a Q, which are alike on both sides, and well above it
# for a D or a B. Blur and glow touch both sides alike, so they cancel out.
# The cut between the two, by the capitals' height: (under this height, a D
# at or over this). Wrong for about 7 glyphs in 100 at 8.5 px, each way, and
# for 1 to 3 in 100 at 11 px.
SMALL_LEAN = ((10, 0.20), (SMALL_CAP, 0.38))
# The same measure tells a B from an 8, at 10 px and over only: (from this
# height, a B at or over this). Under 10 px it is wrong too often to use.
SMALL_B = (10, 0.23)
# Set to False to keep the first small measure (the plain ratio of the left
# stroke's ends to its middle), as the reader stood before the third run.
SMALL_CORE = True


def _core(frame: Frame, line: Line, glyph: Glyph):
    """A small glyph's own ink: (rows of the body with the background taken
    away, the inked columns of each narrow row under the body, the ink
    level), or None when there is too little contrast to tell.

    The body is the rows from the first to the last that is inked over a
    third of the glyph's width. Narrow rows straight under it are a tail."""
    data = frame.channels()[line.channel]
    width, height = frame.width, frame.height
    x, y, w, h = glyph.box
    x0, x1 = max(0, x - 1), min(width, x + w + 1)
    y0, y1 = max(0, y - 2), min(height, y + h + 2)
    block = [data[r * width + x0:r * width + x1] for r in range(y0, y1)]
    values = sorted(v for row in block for v in row)
    background = values[int(CORE_GROUND * len(values))]
    peak = values[int(0.9 * (len(values) - 1))]
    if peak - background < 24:
        return None
    floor = background + CORE_SHARE * (peak - background)
    cols = [c for c in range(x1 - x0) if any(row[c] >= floor for row in block)]
    left, right = cols[0], cols[-1]
    span = right - left + 1
    inked = [sum(1 for v in row[left:right + 1] if v >= floor) for row in block]
    body = [r for r, n in enumerate(inked) if n >= max(2, 0.34 * span)]
    if len(body) < 3:
        return None
    top, bottom = body[0], body[-1]
    rows = [[max(0, v - background) for v in row[left:right + 1]] for row in block[top:bottom + 1]]
    tail = []
    tail_floor = background + TAIL_SHARE * (peak - background)
    for r in range(bottom + 1, len(block)):
        cols = [c - left for c in range(left, right + 1) if block[r][c] >= tail_floor]
        if not cols:
            break
        tail.append(cols)
    return rows, tail, floor - background


def small_measures(frame: Frame, line: Line, glyph: Glyph):
    """(ends, lean, tail) of a small glyph, or None. *ends* is how bright
    the two ends of the left stroke are against its middle, *lean* is that
    less the same at the right stroke, *tail* is the count of narrow rows
    under the body that sit in its right half (a Q's tail)."""
    got = _core(frame, line, glyph)
    if got is None:
        return None
    rows, tail, level = got
    span = len(rows[0])

    def stroke(order) -> float:
        for c in order:
            column = [row[c] for row in rows]
            if sum(1 for v in column if v >= level) >= 0.5 * len(column):
                middle = sorted(column[len(column) // 4:(3 * len(column)) // 4] or column)
                return min(column[0], column[-1]) / (middle[len(middle) // 2] or 1)
        return 0.0

    left = stroke(range(span))
    right = stroke(range(span - 1, -1, -1))
    under = sum(1 for cols in tail
                if cols and len(cols) <= max(1, 0.5 * span) and min(cols) >= 0.4 * span)
    return left, left - right, under


def _small_round_letter(frame: Frame, line: Line, glyph: Glyph, cap: int):
    """round_letter for capitals under SMALL_CAP px, or None to fall back."""
    got = small_measures(frame, line, glyph)
    if got is None:
        return None
    _ends, lean, tail = got
    if tail >= 1:
        return "Q"
    if lean >= next(cut for limit, cut in SMALL_LEAN if cap < limit):
        return "D"
    for _score, char in glyph.ranked:
        if char in "O0":
            return char
    return "O"


def _small_b_or_8(frame: Frame, line: Line, glyph: Glyph):
    """"B" or "8" for a small glyph the grid read as one of the two, by its
    left stroke's ends, or None where that is not to be trusted."""
    cap = max(1, line.base - line.top)
    if not (SMALL_B[0] <= cap < SMALL_CAP):
        return None
    got = small_measures(frame, line, glyph)
    if got is None:
        return None
    return "B" if got[1] >= SMALL_B[1] else "8"


def round_letter(frame: Frame, line: Line, glyph: Glyph) -> str:
    """Which round letter a glyph is. The tail and the left stroke decide
    where they are clear, and rule letters out where they are half clear.
    The grid's own order picks among what is left."""
    cap = max(1, line.base - line.top)
    if SMALL_CORE and cap < SMALL_CAP:
        char = _small_round_letter(frame, line, glyph, cap)
        if char is not None:
            return char
    under = rows_under(frame, line, glyph)
    if under >= max(2, round(0.12 * cap)):
        return "Q"
    small = cap < SMALL_CAP
    ends = stroke_ends(frame, line, glyph, small)
    if ends >= (SMALL_SQUARE if small else SQUARE):
        return "D"
    ruled_out = set()
    if under < 0.06 * cap:
        ruled_out.add("Q")          # a tail would be longer than this
    if ends <= (SMALL_CUT if small else CUT):
        ruled_out.add("D")
    for _score, char in glyph.ranked:
        if char in ROUND and char not in ruled_out:
            return char
    return "O"


def read_line(frame: Frame, line: Line, references, skip=lambda ref: False) -> None:
    for glyph in line.glyphs:
        if glyph.kind != "tall":
            continue
        got = glyph_features(frame, line, glyph)
        glyph.ranked = rank(got[0], got[1], references, skip) if got else []
        if CHECK_ROUND_LETTERS and glyph.ranked and glyph.ranked[0][1] in ROUND:
            _rename(glyph, round_letter(frame, line, glyph))
        elif CHECK_SQUARE_LETTERS and glyph.ranked and glyph.ranked[0][1] in "B8":
            char = _small_b_or_8(frame, line, glyph)
            if char:
                _rename(glyph, char)
    if CHECK_ROUND_LETTERS:
        _zeros_by_company(line)
    if CHECK_SERIAL_SHAPE:
        _serial_shape(line)


# A ship nobody has identified shows its serial: two letters, four digits and
# two letters, with a hyphen between the groups. In a line of that shape each
# place is read as the kind of character that belongs there, which settles S
# against 5, B against 8, G against 6 and O against 0.
SERIAL_PATTERN = "TT-TTTT-TT"
DIGITS = "0123456789"
# Set to False to read without the serial shape.
CHECK_SERIAL_SHAPE = True


def _serial_shape(line: Line) -> None:
    if line.pattern != SERIAL_PATTERN:
        return
    tall = [g for g in line.glyphs if g.kind == "tall"]
    # A name can have the same shape (AB-COOL-XY). It is a serial only when
    # most of the middle group reads as digits by itself.
    if sum(1 for g in tall[2:6] if g.char in DIGITS) < 3:
        return
    for place, glyph in enumerate(tall):
        wants_digit = 2 <= place < 6
        if not glyph.ranked or (glyph.char in DIGITS) == wants_digit:
            continue
        if not wants_digit and glyph.char == "0":
            _rename(glyph, "O")             # the same shape: the letter here
            continue
        for score, char in glyph.ranked:
            if (char in DIGITS) == wants_digit:
                glyph.ranked = [(score, char)] + [(s, c) for s, c in glyph.ranked if c != char]
                break
        else:
            if wants_digit:
                _rename(glyph, "1")         # a plain bar among digits is a one


def _rename(glyph: Glyph, char: str) -> None:
    """Make *char* the glyph's reading. The grid's best score stands."""
    if glyph.ranked and char != glyph.ranked[0][1]:
        rest = [(s, c) for s, c in glyph.ranked if c != char]
        glyph.ranked = [(glyph.ranked[0][0], char)] + rest


def _zeros_by_company(line: Line) -> None:
    """Settle O against 0, which are the same shape, by what stands beside
    them: a run of them touching a digit from 1 to 9 in the same word is
    zeros, and any other run is the letter."""
    height = max(1, line.base - line.top)
    glyphs = line.glyphs
    i = 0
    while i < len(glyphs):
        if glyphs[i].kind != "tall" or glyphs[i].char not in "O0":
            i += 1
            continue
        j = i
        while (j + 1 < len(glyphs) and glyphs[j + 1].kind == "tall"
               and glyphs[j + 1].char in "O0" and not _word_gap(glyphs[j], glyphs[j + 1], height)):
            j += 1
        before = glyphs[i - 1] if i > 0 else None
        after = glyphs[j + 1] if j + 1 < len(glyphs) else None
        digit = any(
            other is not None and other.kind == "tall" and other.char in "123456789"
            and not _word_gap(*pair, height)
            for other, pair in ((before, (before, glyphs[i])), (after, (glyphs[j], after))))
        for glyph in glyphs[i:j + 1]:
            _rename(glyph, "0" if digit else "O")
        i = j + 1


def _word_gap(left: Glyph, right: Glyph, height: int) -> bool:
    return right.box[0] - (left.box[0] + left.box[2]) >= 0.42 * height


def letters(line: Line) -> str:
    """A line's capital-height glyphs alone: no marks, no spaces."""
    return "".join(g.char for g in line.glyphs if g.kind == "tall")


def gaps(line: Line) -> list[str]:
    """What stands between each two neighbouring capital-height glyphs of a
    line: its marks, a space, or nothing."""
    height = max(1, line.base - line.top)
    out = []
    before = None
    marks = ""
    for glyph in line.glyphs:
        if glyph.kind != "tall":
            marks += glyph.kind
            continue
        if before is not None:
            out.append(marks or (" " if _word_gap(before, glyph, height) else ""))
        before, marks = glyph, ""
    return out


# A hyphen or an underscore is wide and seldom seen where there is none, but
# it is easily lost (run into its neighbour, or broken up), so a third of the
# passes seeing it is enough. A full stop or an apostrophe is a speck, and
# specks are common, so most passes must agree on one.
WIDE_MARKS = "-_"
SPECKS = ".'"
# Passes whose strength is within this share of the strongest count as level
# with it. Among those, the letters most passes read win.
LEVEL = 0.97


def _mark_agreed(mark: str, seen: list[str]) -> bool:
    count = sum(mark in s for s in seen)
    if mark in WIDE_MARKS:
        return 3 * count >= len(seen)
    return 2 * count > len(seen)


# Characters that differ only in a corner or a tail. One pass tells them
# apart wrongly a few times in a hundred at 4K and more often at small sizes,
# and its mistakes are not the next pass's. So passes that agree on every
# other letter settle each of these by a count.
ALIKE = {**{c: "O" for c in "O0DQ"}, **{c: "B" for c in "B8"}, **{c: "S" for c in "S5"}}
# Set to False to let the single strongest pass decide those letters too.
VOTE_ALIKE = True
# In a serial's digits and letters, what a character of the wrong kind stands
# for. Used on the finished reading, where the count may have left one.
DIGIT_FOR = {"O": "0", "D": "0", "Q": "0", "S": "5", "B": "8", "G": "6", "Z": "2", "I": "1"}
LETTER_FOR = {"0": "O", "5": "S", "8": "B", "6": "G", "2": "Z", "1": "I"}


def skeleton(text: str) -> str:
    """*text* with each character that has look-alikes replaced by one of them."""
    return "".join(ALIKE.get(c, c) for c in text)


def _serial_text(text: str) -> str:
    """A finished reading shaped like a serial, with each place made the kind
    of character that belongs there. Left alone unless at least two of the
    middle four are digits already and the others could be."""
    if not CHECK_SERIAL_SHAPE or len(text) != 10 or text[2] != "-" or text[7] != "-":
        return text
    outer, middle = text[:2] + text[8:], text[3:7]
    if not (outer + middle).isalnum():
        return text
    if (sum(c in DIGITS for c in middle) < 2
            or any(c not in DIGITS and c not in DIGIT_FOR for c in middle)):
        return text
    fixed = [LETTER_FOR.get(c, c) for c in outer]
    digits = "".join(DIGIT_FOR.get(c, c) for c in middle)
    return f"{fixed[0]}{fixed[1]}-{digits}-{fixed[2]}{fixed[3]}"


def combine(lines: list[Line], weight) -> tuple[str, Line | None]:
    """One reading from the passes over one tag, and the pass it rests on.

    The strongest pass decides the letters, and where several readings are
    level, the one most passes gave. Passes that differ from it only in
    look-alike characters (ALIKE) settle each of those by a count. What
    stands between the letters is settled by the same passes."""
    key_of = skeleton if VOTE_ALIKE else (lambda found: found)
    best: dict[str, tuple[float, Line]] = {}
    passes: Counter = Counter()
    for line in lines:
        key = key_of(letters(line))
        score = weight(line)
        passes[key] += 1
        if key not in best or score > best[key][0]:
            best[key] = (score, line)
    if not best:
        return "", None
    top = max(score for score, _ in best.values())
    level = [key for key, (score, _) in best.items() if score >= LEVEL * top] if top > 0 else []
    key = (max(level, key=lambda found: (passes[found], best[found][0])) if level
           else max(best, key=lambda found: best[found][0]))
    agreeing = [line for line in lines if key_of(letters(line)) == key]
    strongest = letters(best[key][1])
    chosen = []
    for i, char in enumerate(strongest):
        if char in ALIKE and VOTE_ALIKE:
            votes = Counter(letters(line)[i] for line in agreeing)
            char = max(votes, key=lambda found: (votes[found], found == char))
        chosen.append(char)
    same = [gaps(line) for line in agreeing]
    text = "".join(chosen[:1])
    for i in range(len(chosen) - 1):
        seen = [found[i] for found in same]
        # The commonest of the marked gaps whose every mark enough passes saw.
        marked = Counter(s for s in seen if s.strip()
                         and all(_mark_agreed(mark, seen) for mark in set(s)))
        if marked:
            between = max(marked, key=lambda s: (marked[s], len(s)))
        else:
            between = " " if 2 * sum(s != "" for s in seen) > len(seen) else ""
        text += between + chosen[i + 1]
    return _serial_text(text), best[key][1]


def _overlap(a: Line, b: Line) -> bool:
    ax, ay, aw, ah = a.box
    bx, by, bw, bh = b.box
    if ax + aw <= bx or bx + bw <= ax:
        return False
    inter = min(ay + ah, by + bh) - max(ay, by)
    return inter > 0.5 * min(ah, bh)


def all_lines(frame: Frame, cap_px: float, channels=None, thresholds=None,
              timings: dict | None = None) -> list[Line]:
    """Every line from every channel and threshold, duplicates and all."""
    found = []
    for channel in channels or CHANNELS:
        for threshold in thresholds or THRESHOLDS:
            start = time.perf_counter()
            lines = find_lines(frame, channel, threshold, cap_px)
            if timings is not None:
                timings[(channel, threshold)] = time.perf_counter() - start
            found.extend(lines)
    return found


# A bar says little: any thin upright matches an I. So a bar counts for this
# share of a shaped glyph when passes are weighed against each other.
BAR_WEIGHT = 0.3


def weight(line: Line) -> float:
    """How much a pass's reading counts: each glyph by how far its match is
    above 0.5, a bar for less."""
    height = max(1, line.base - line.top)
    total = 0.0
    for glyph in line.glyphs:
        if glyph.kind == "tall":
            bar = glyph.box[2] / height < BAR_ASPECT
            total += (glyph.score - 0.5) * (BAR_WEIGHT if bar else 1.0)
    return total


def read_place(frame: Frame, point, cap_px: float, references, reach: int = 6):
    """The reader's whole look at one tag: every pass over *frame* (a small
    picture round the tag), the lines that hold *point*, and one reading
    from them. Returns (text, the pass it rests on, crowded, passes).

    *crowded* is how many blobs stand beside the line's ends in every pass
    that read those letters: anything there means the name may run on under
    it. With a wider *reach* the tag may have moved off the point a little.
    Then only the lines at the place nearest the point are read."""
    x, y = point
    lines = [line for line in all_lines(frame, cap_px) if line.contains(x, y, pad=reach)]
    if reach > 6 and lines:
        def off(line: Line) -> float:
            bx, by, bw, bh = line.box
            return abs(bx + bw / 2 - x) + abs(by + bh / 2 - y)
        nearest = min(lines, key=off)
        lines = [line for line in lines if line is nearest or _overlap(line, nearest)]
    for line in lines:
        read_line(frame, line, references)
    text, best = combine(lines, weight)
    same = [found for found in lines if best is not None and letters(found) == letters(best)]
    crowded = min((found.crowded for found in same), default=0)
    return text, best, crowded, len(lines)


def merge(lines: list[Line]) -> list[Line]:
    """One line per place: of the lines that overlap, keep the one with the
    most glyphs, then the best score."""
    kept: list[Line] = []
    for line in sorted(lines, key=lambda found: (-len(found.glyphs), -found.score)):
        if not any(_overlap(line, other) for other in kept):
            kept.append(line)
    return sorted(kept, key=lambda found: (found.box[1], found.box[0]))
