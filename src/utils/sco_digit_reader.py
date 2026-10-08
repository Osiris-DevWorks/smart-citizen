"""Read the mining scan signature (e.g. ``7,200``) off a screen capture.

Qt-free: works on the red channel of a capture as raw bytes, so tests can
drive it with fixture images. ``src/gui/sco_overlay.py`` wraps it as the
SCO ``SignatureReader``.

The readout is a short row of ~11 px tall digits (at 1600 px screen
height) with a comma before the last three. Steps:

1. Threshold the red channel. The digits are white-cored, and red keeps
   their shape best through the HUD's colour fringing. Horizontal runs
   wider than a glyph are dropped first, so a bright panel edge touching
   the digits can't merge with them.
2. Find connected blobs, keep digit-sized ones, and chain neighbours that
   share a top and baseline. A chain only counts if a comma-sized blob
   sits before its last three digits, which rules out other HUD text.
3. Match each digit to the nearest reference glyph in
   ``sco_digit_samples.py`` (min-max normalised, coarse grid, correlation).
4. Prefer the reading that decodes to a known deposit. Where a digit's
   runner-up is close, try it too: valid signatures are sparse, so this
   fixes look-alike misses such as 6 vs 8.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Optional

from src.utils.mining_signatures import decode_signature
from src.utils.sco_digit_samples import DIGIT_SAMPLES

# Digit height in px on a 1600 px tall screen; callers scale it.
DIGIT_HEIGHT_AT_1600 = 11

# Red level that counts as "glyph"; tried in order until one finds a row.
THRESHOLDS = (180, 210, 150)

# Glyphs are compared on this coarse grid. Small on purpose: it absorbs
# per-cockpit font weight and JPEG/fringe noise.
GRID_W, GRID_H = 4, 7

# A runner-up digit within this score of the best is tried as an alternative.
ALT_MARGIN = 0.15

# A reading that decodes to nothing is only reported above this mean score.
MIN_UNDECODED_SCORE = 0.75


@dataclass(frozen=True)
class SignatureReading:
    """Text found in the capture plus its box ``(x, y, w, h)`` in capture px."""
    text: str
    box: tuple[int, int, int, int]
    score: float


def _components(width: int, height: int, mask: bytearray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes ``(x, y, w, h)`` of 4-connected foreground blobs."""
    seen = bytearray(width * height)
    boxes = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        x0, y0, x1, y1 = width, height, -1, -1
        while stack:
            i = stack.pop()
            y, x = divmod(i, width)
            x0, x1 = min(x0, x), max(x1, x)
            y0, y1 = min(y0, y), max(y1, y)
            for j, ok in ((i - 1, x > 0), (i + 1, x < width - 1),
                          (i - width, y > 0), (i + width, y < height - 1)):
                if ok and mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        boxes.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return boxes


def _mask(width: int, height: int, red: bytes, threshold: int, max_run: int) -> bytearray:
    table = bytes(1 if v >= threshold else 0 for v in range(256))
    mask = bytearray(red.translate(table))
    # Drop wide horizontal runs (panel edges, bright horizons).
    for y in range(height):
        row = y * width
        x = 0
        while x < width:
            if not mask[row + x]:
                x += 1
                continue
            end = x
            while end < width and mask[row + end]:
                end += 1
            if end - x > max_run:
                mask[row + x:row + end] = bytes(end - x)
            x = end
    return mask


def _candidate_rows(width, height, mask, digit_px):
    """Digit chains shaped like ``N,NNN`` or ``NN,NNN``: (boxes, top, base)."""
    boxes = _components(width, height, mask)
    digits = sorted(b for b in boxes
                    if 0.75 * digit_px <= b[3] <= 1.35 * digit_px and b[2] <= digit_px)
    commas = [b for b in boxes if b[3] <= 0.6 * digit_px and b[2] <= 0.5 * digit_px]
    rows = []
    used = set()
    for i, first in enumerate(digits):
        if i in used:
            continue
        chain = [first]
        used.add(i)
        for j in range(i + 1, len(digits)):
            if j in used:
                continue
            nxt, last = digits[j], chain[-1]
            gap = nxt[0] - (last[0] + last[2])
            if gap > 1.6 * digit_px:
                if nxt[0] > last[0] + 3 * digit_px:
                    break
                continue
            if (gap >= -1 and abs(nxt[1] - last[1]) <= 2
                    and abs(nxt[1] + nxt[3] - last[1] - last[3]) <= 2):
                chain.append(nxt)
                used.add(j)
        if len(chain) < 4:
            continue
        bottoms = sorted(b[1] + b[3] for b in chain)
        base = bottoms[len(bottoms) // 2]
        top = min(b[1] for b in chain)
        for k in range(len(chain) - 1):
            left, right = chain[k], chain[k + 1]
            has_comma = any(
                left[0] + left[2] - 1 <= c[0] and c[0] + c[2] <= right[0] + 1
                and c[1] + c[3] >= base - 2 and c[1] >= top + 0.5 * digit_px
                for c in commas
            )
            if has_comma and 1 <= k + 1 <= 2 and len(chain) - (k + 1) >= 3:
                rows.append((chain[:k + 4], top, base))
                break
    return rows


def _features(pixels: list[list[int]]) -> list[float]:
    """Area-sample a glyph onto the grid, min-max normalise, unit vector."""
    h, w = len(pixels), len(pixels[0])
    lo = min(min(r) for r in pixels)
    hi = max(max(r) for r in pixels)
    out = []
    for gy in range(GRID_H):
        y0, y1 = gy * h / GRID_H, (gy + 1) * h / GRID_H
        for gx in range(GRID_W):
            x0, x1 = gx * w / GRID_W, (gx + 1) * w / GRID_W
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


@lru_cache(maxsize=1)
def _references() -> tuple[tuple[str, tuple[float, ...]], ...]:
    refs = []
    for digit, w, h, hexdata in DIGIT_SAMPLES:
        raw = bytes.fromhex(hexdata)
        pixels = [list(raw[y * w:(y + 1) * w]) for y in range(h)]
        refs.append((digit, tuple(_features(pixels))))
    return tuple(refs)


def _rank_digit(pixels: list[list[int]]) -> list[tuple[float, str]]:
    """Best correlation per digit, highest first."""
    feat = _features(pixels)
    best: dict[str, float] = {}
    for digit, ref in _references():
        score = sum(a * b for a, b in zip(feat, ref))
        if score > best.get(digit, -2.0):
            best[digit] = score
    return sorted(((s, d) for d, s in best.items()), reverse=True)


def _glyph_pixels(width, red, box, top, base, threshold):
    """Red pixels of one digit, trimmed to its inked columns within the row."""
    x0, _, w, _ = box
    cols = [x for x in range(x0, x0 + w)
            if any(red[y * width + x] >= threshold for y in range(top, base))]
    if not cols:
        return None
    return [[red[y * width + x] for x in range(cols[0], cols[-1] + 1)]
            for y in range(top, base)]


def _read_row(width, red, row, threshold) -> Optional[SignatureReading]:
    boxes, top, base = row
    ranked = []
    for box in boxes:
        pixels = _glyph_pixels(width, red, box, top, base, threshold)
        if pixels is None:
            return None
        ranked.append(_rank_digit(pixels))
    # Each digit's best guess, plus a runner-up when it's close.
    options = [[r[0]] + [alt for alt in r[1:2] if r[0][0] - alt[0] <= ALT_MARGIN]
               for r in ranked]
    best_any = best_decoded = None
    for combo in product(*options):
        text = "".join(d for _, d in combo)
        score = sum(s for s, _ in combo) / len(combo)
        if best_any is None or score > best_any[0]:
            best_any = (score, text)
        if decode_signature(int(text)) and (best_decoded is None or score > best_decoded[0]):
            best_decoded = (score, text)
    if best_decoded is not None:
        score, text = best_decoded
    elif best_any[0] >= MIN_UNDECODED_SCORE:
        score, text = best_any
    else:
        return None
    x0 = boxes[0][0]
    x1 = max(b[0] + b[2] for b in boxes)
    split = len(text) - 3
    return SignatureReading(f"{text[:split]},{text[split:]}", (x0, top, x1 - x0, base - top),
                            score)


def read_signature(width: int, height: int, red: bytes,
                   digit_px: float = DIGIT_HEIGHT_AT_1600) -> Optional[SignatureReading]:
    """Find and read the signature in a ``width`` x ``height`` red channel.

    *digit_px* is the expected digit height in capture pixels. Returns the
    best reading, preferring one that decodes, or None.
    """
    if len(red) != width * height or width <= 0 or height <= 0:
        return None
    max_run = int(1.2 * digit_px)
    for threshold in THRESHOLDS:
        mask = _mask(width, height, red, threshold, max_run)
        readings = [r for row in _candidate_rows(width, height, mask, digit_px)
                    if (r := _read_row(width, red, row, threshold))]
        if readings:
            decoded = [r for r in readings
                       if decode_signature(int(r.text.replace(",", "")))]
            return max(decoded or readings, key=lambda r: r.score)
    return None
