"""SCO digit reader: the mining signature read off real HUD captures.

Fixtures in ``tests/fixtures/sco/`` are named ``<source>_<value>.png``:
crops of 2560x1600 in-game screenshots (Drake Golem ``g*``, MISC Prospector
``p*``, Prospector on a planet with the orange HUD panel ``q*``), lossless
crops SCO saved in-game (``live*``), Golem readouts at a wide field of
view, drawn about 0.65 of their usual size (``fov*``, #546), lossless SCO
captures of an Argo MOLE over Microtech on a 2560x1440 screen with Windows
HDR on (``hdr*``: the clipped white digits bloom, and over snow the panel
behind them is as red as they are), and other HUD text the reader must
ignore (``hud*_none``: "UNKNOWN", red "WARNING"). Qt-free: the channels go
straight to ``read_signature``.
"""
import re
from pathlib import Path

import pytest

from src.utils import sco_digit_reader
from src.utils.sco_digit_reader import DIGIT_HEIGHT_AT_1600, read_signature
from src.utils.sco_digit_samples import DIGIT_SAMPLES

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "sco").glob("*.png"))
READOUTS = [p for p in FIXTURES if not p.stem.endswith("_none")]
OTHER_TEXT = [p for p in FIXTURES if p.stem.endswith("_none")]


def _channels(path):
    from PyQt6.QtGui import QImage

    img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB32)
    data = img.constBits().asstring(img.sizeInBytes())
    return img.width(), img.height(), data[2::4], data[1::4], data[0::4]


def _expected(path):
    digits = path.stem.split("_")[1]
    return f"{digits[:-3]},{digits[-3:]}"


# Screen height each fixture was captured at, by source prefix; the rest are
# 1600 px. The hdr crops are SCO's own captures on a 2560x1440 screen with
# Windows HDR on.
SCREEN_HEIGHTS = {"hdr": 1440}


def _screen_height(path):
    return SCREEN_HEIGHTS.get(re.match(r"[a-z]+", path.stem).group(), 1600)


def _read(path):
    w, h, red, green, blue = _channels(path)
    digit_px = DIGIT_HEIGHT_AT_1600 * _screen_height(path) / 1600
    return read_signature(w, h, red, digit_px, green=green, blue=blue)


@pytest.mark.parametrize("path", READOUTS, ids=lambda p: p.stem)
def test_reads_every_readout(path):
    reading = _read(path)
    assert reading is not None and reading.text == _expected(path)


@pytest.mark.parametrize("path", OTHER_TEXT, ids=lambda p: p.stem)
def test_ignores_other_hud_text(path):
    assert _read(path) is None


def test_samples_cover_every_digit():
    assert {d for d, *_ in DIGIT_SAMPLES} == set("0123456789")


def test_samples_are_well_formed():
    # A hand-added sample whose hex doesn't fill width x height would give
    # ragged rows, and the read task would fail and stop the capture timer.
    for digit, w, h, hexdata, source in DIGIT_SAMPLES:
        assert digit in "0123456789" and w > 0 and h > 0, source
        assert len(hexdata) == 2 * w * h, (digit, source)
        bytes.fromhex(hexdata)


def test_samples_hold_no_duplicate_glyphs():
    glyphs = [s[:4] for s in DIGIT_SAMPLES]
    assert len(glyphs) == len(set(glyphs))


def test_cut_glyphs_gives_back_the_stored_samples():
    # The stored live_00 glyphs were cut from this crop; cutting it again
    # gives the same entries, which is what scripts/add_sco_sample.py relies on.
    path = next(p for p in READOUTS if p.stem == "live00_15600")
    w, h, red, green, blue = _channels(path)
    glyphs = sco_digit_reader.cut_glyphs(w, h, red, 5, green=green, blue=blue)
    stored = [(gw, gh, bytes.fromhex(hx)) for d, gw, gh, hx, s in DIGIT_SAMPLES
              if s == "live_00"]
    assert glyphs == stored


def test_cut_glyphs_needs_a_row_of_that_many_digits():
    path = next(p for p in READOUTS if p.stem == "live00_15600")
    w, h, red, green, blue = _channels(path)
    assert sco_digit_reader.cut_glyphs(w, h, red, 4, green=green, blue=blue) is None
    assert sco_digit_reader.cut_glyphs(w, h, b"short", 5) is None


def test_box_wraps_the_digits():
    path = next(p for p in READOUTS if p.stem == "p2_2000")
    w, h, *_ = _channels(path)
    x, y, bw, bh = _read(path).box
    assert 9 <= bh <= 13 and 25 <= bw <= 45
    assert 0 < x < w - bw and 0 < y < h - bh


@pytest.mark.parametrize("stem", ["live02_8540", "live06_7800", "live24_15600",
                                  "q1_14160", "q2_17080", "fov3_3170"])
def test_reads_without_its_own_glyphs(monkeypatch, stem):
    # The live crops were misread in-game (8 as 0/6/9, 8 as 0, 6 as 8); the
    # q crops were skipped as coloured text on the orange planet panel. Read
    # with that crop's own glyphs removed, so the rest of the set (and the
    # decode check) has to carry it. fov3 is a wide field of view readout
    # (#546) that the other small glyphs carry.
    prefix = stem.split("_")[0]
    source = "live_" + prefix[4:] if prefix.startswith("live") else prefix
    monkeypatch.setattr(sco_digit_reader, "DIGIT_SAMPLES",
                        tuple(s for s in DIGIT_SAMPLES if s[4] != source))
    sco_digit_reader._references.cache_clear()
    try:
        path = next(p for p in READOUTS if p.stem == stem)
        assert _read(path).text == _expected(path)
    finally:
        sco_digit_reader._references.cache_clear()


def test_blank_and_noise_read_nothing():
    w, h = 200, 60
    assert read_signature(w, h, bytes(w * h), DIGIT_HEIGHT_AT_1600) is None
    # A lone bright bar is not a signature.
    red = bytearray(w * h)
    for y in range(20, 31):
        red[y * w + 50:y * w + 53] = b"\xff\xff\xff"
    assert read_signature(w, h, bytes(red), DIGIT_HEIGHT_AT_1600) is None
    assert read_signature(w, h, b"short", DIGIT_HEIGHT_AT_1600) is None


def test_colour_channels_of_another_length_read_nothing():
    w, h, red, green, blue = _channels(READOUTS[0])
    assert read_signature(w, h, red, DIGIT_HEIGHT_AT_1600, green=green[:-1], blue=blue) is None


def _read_scaled(path, screen_height):
    """Read a crop scaled to what a *screen_height* screen captures."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    factor = screen_height / _screen_height(path)
    img = QImage(str(path))
    img = img.scaled(round(img.width() * factor), round(img.height() * factor),
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    data = img.constBits().asstring(img.sizeInBytes())
    return read_signature(img.width(), img.height(), data[2::4],
                          DIGIT_HEIGHT_AT_1600 * screen_height / 1600,
                          green=data[1::4], blue=data[0::4])


# Readouts that do not read right yet scaled down to a smaller screen (#523
# review): a comma that touches the next digit, thin strokes on the planet
# panel that break apart, or small glyphs that look alike (6 read as 0).
# Reference glyphs cut from real crops at those sizes are what fixes them
# (scripts/add_sco_sample.py), so this list may only shrink.
# The fov crops are already about 0.65 of the usual size (#546), so at 1080
# their digits are under 5 px tall.
SCALED_DOWN_MISSES = {
    1080: {"live24_15600", "live42_12900", "live51_48000",
           "p3_15697", "q1_14160", "q2_17080", "fov1_2000", "fov2_3170", "fov4_15360"},
    1440: {"live24_15600", "live51_48000", "live52_48000", "p3_15697", "q1_14160"},
}


# The scaling tests stand in for screens no fixture was captured on, so they
# scale the 1600 px crops only. A real capture at its own size (hdr) is not
# scaled: scaling would scale its one pixel of HDR bloom too, which a real
# screen of that size does not have.
SCALED = [p for p in READOUTS if _screen_height(p) == 1600]


@pytest.mark.parametrize("screen_height", sorted(SCALED_DOWN_MISSES))
@pytest.mark.parametrize("path", SCALED, ids=lambda p: p.stem)
def test_reads_at_smaller_screen_heights(path, screen_height):
    """The digit size follows the screen height. Fixtures are 1600 px crops,
    scaled here to what other screens would capture (until testers send real
    ones, which the glob picks up). Every readout reads right but the known
    misses, and a known miss that starts reading right must leave the list."""
    reading = _read_scaled(path, screen_height)
    right = reading is not None and reading.text == _expected(path)
    if path.stem in SCALED_DOWN_MISSES[screen_height]:
        assert not right, f"{path.stem} reads right at {screen_height}: take it off the list"
    else:
        assert right


@pytest.mark.parametrize("path", SCALED, ids=lambda p: p.stem)
def test_reads_every_readout_on_a_4k_screen(path):
    """#523: on a 3840x2160 screen 3,400 showed nothing. Scaled to 2160 px, a
    "4" touches the digit after it and the two read as one blob too wide for
    a digit (48,000 read as 8,000), or comes apart at the first threshold
    (14,160 read as 1,160): either way a digit is lost, and 3,400 without
    its 4 is too short to be a readout at all."""
    reading = _read_scaled(path, 2160)
    assert reading is not None and reading.text == _expected(path)


def test_digits_at_a_wide_field_of_view_are_found():
    """#546: a wider field of view draws the cockpit readout smaller (7 px
    digits where the reader expects 11). They read right at the expected
    size, through the smaller of ``DIGIT_SCALES``."""
    path = next(p for p in READOUTS if p.stem == "fov1_2000")
    reading = _read(path)
    assert reading.text == "2,000" and reading.box[3] < 0.75 * DIGIT_HEIGHT_AT_1600


def test_a_comma_sized_blob_below_the_row_is_no_comma():
    """#546: the taller scan box takes in HUD text below the readout. A small
    blob far under the gap between the first two digits was taken for the
    comma, and 21,200 was cut to a four-digit row that read nothing."""
    w, h, red, green, blue = _channels(next(p for p in READOUTS if p.stem == "fov5_21200"))
    x, *_ = read_signature(w, h, red, DIGIT_HEIGHT_AT_1600, green=green, blue=blue).box
    extra = 40
    red, green, blue = (bytearray(c) + bytearray(w * extra) for c in (red, green, blue))
    for y in range(h + 25, h + 28):
        for dx in (8, 9):
            for c in (red, green, blue):
                c[y * w + x + dx] = 255
    reading = read_signature(w, h + extra, bytes(red), DIGIT_HEIGHT_AT_1600,
                             green=bytes(green), blue=bytes(blue))
    assert reading is not None and reading.text == "21,200"


def test_touching_digits_are_cut_apart():
    # Two "0"s joined by one pixel, then three, each 3 wide and 5 tall.
    w, h, mask = _grid([
        "###.###...###.###.###",
        "#.#.#.#...#.#.#.#.#.#",
        "#.###.#...#.###.#####",
        "#.#.#.#...#.#.#.#.#.#",
        "###.###...###.###.###",
    ])
    pair, triple = sorted(sco_digit_reader._components(w, h, mask))
    assert pair == (0, 0, 7, 5) and triple == (10, 0, 11, 5)
    # The bridge column goes to neither part.
    assert sco_digit_reader._split_joined(w, mask, pair, 5) == [(0, 0, 3, 5), (4, 0, 3, 5)]
    assert sco_digit_reader._split_joined(w, mask, triple, 5) == [
        (10, 0, 3, 5), (14, 0, 3, 5), (18, 0, 3, 5)]
    # Narrow enough already: kept whole; far too wide for digits: dropped.
    assert sco_digit_reader._split_joined(w, mask, (0, 0, 3, 5), 5) == [(0, 0, 3, 5)]
    assert sco_digit_reader._split_joined(w, mask, triple, 4) == []


def test_an_undecoded_threshold_does_not_end_the_search(monkeypatch):
    """A threshold that reads only a number that decodes to nothing hands on
    to the next; its reading stands only when no threshold decodes."""
    from src.utils.sco_digit_reader import SignatureReading

    by_threshold = {180: "1,160", 210: None, 150: "14,160"}
    monkeypatch.setattr(sco_digit_reader, "DIGIT_SCALES", (1.0,))
    monkeypatch.setattr(sco_digit_reader, "_candidate_rows",
                        lambda w, h, mask, digit_px, boxes=None: [((0, 0, 1, 1),), ])
    seen = []

    def read_row(width, red, row, threshold):
        seen.append(threshold)
        text = by_threshold[threshold]
        return text and SignatureReading(text, (0, 0, 1, 1), 0.9)

    monkeypatch.setattr(sco_digit_reader, "_read_row", read_row)
    w, h = 4, 4
    assert read_signature(w, h, bytes(w * h)).text == "14,160"
    assert seen == [180, 210, 150]
    by_threshold[150] = None                                   # nothing decodes anywhere
    assert read_signature(w, h, bytes(w * h)).text == "1,160"
    by_threshold[210] = "17,080"                               # a decode wins over it
    assert read_signature(w, h, bytes(w * h)).text == "17,080"


def _grid(rows):
    """A mask from strings: ``#`` is foreground."""
    return len(rows[0]), len(rows), bytearray(1 if c == "#" else 0 for r in rows for c in r)


def test_blobs_join_across_corners_and_later_rows():
    # A "U" only joins at its base, two rows after both arms start; the
    # diagonal pair touches at a corner only; the dot stands alone.
    w, h, mask = _grid([
        "#..#..#....",
        "#..#...#...",
        "####.......",
        ".........#.",
    ])
    assert sorted(sco_digit_reader._components(w, h, mask)) == [
        (0, 0, 4, 3), (6, 0, 2, 2), (9, 3, 1, 1),
    ]


def test_mask_drops_runs_wider_than_a_glyph():
    w, h = 10, 2
    red = bytes([255] * 4 + [0] + [255] * 3 + [0, 0] + [255] * 10)
    mask = sco_digit_reader._mask(w, h, red, 180, max_run=3)
    # Row 0: the 4-wide run goes, the 3-wide one stays. Row 1: all 10 go.
    assert bytes(mask) == bytes([0] * 5 + [1] * 3 + [0] * 12)


def _on_a_bright_panel(w, h, red, green, blue):
    """A readout's channels as the orange panel over snow leaves them: red
    saturated everywhere, green and blue squeezed toward the panel's."""
    return (w, h, b"\xff" * len(red),
            bytes(140 + v * 115 // 255 for v in green),
            bytes(110 + v * 145 // 255 for v in blue))


@pytest.mark.parametrize("stem", ["live00_15600", "p2_2000"])
def test_digits_on_a_red_saturated_panel_are_read_in_blue(stem):
    """Over snow or a bright sky the orange panel behind the readout is as
    red as the white digits (both over 230 on Microtech), so red holds
    nothing to read while blue still does. A readout recoloured that way
    reads nothing in red alone and reads right once blue is there."""
    path = next(p for p in READOUTS if p.stem == stem)
    w, h, red, green, blue = _on_a_bright_panel(*_channels(path))
    assert read_signature(w, h, red, DIGIT_HEIGHT_AT_1600) is None
    reading = read_signature(w, h, red, DIGIT_HEIGHT_AT_1600, green=green, blue=blue)
    assert reading is not None and reading.text == _expected(path)


def test_the_sharpest_threshold_wins_over_the_first():
    """A low threshold blurred this 6 (on a dark panel, SCO's own capture)
    into an 8, and 8,000 decodes as 6,000 does. Every threshold of the
    channel is read and the best match kept, so it reads 6,000."""
    path = next(p for p in READOUTS if p.stem == "hdr9_6000")
    assert _read(path).text == "6,000"


def test_a_number_no_deposit_has_is_not_swapped_for_one():
    """70,000 is no deposit, and its 7 is close to a 1. Runner-up digits
    are tried only within ALT_MARGIN of the best, so the reader shows 70,000
    as it is rather than 10,000 or 76,000, which decode."""
    path = next(p for p in READOUTS if p.stem == "hdr10_70000")
    assert _read(path).text == "70,000"


def test_two_bloomed_zeros_are_cut_at_their_bridge():
    """With HDR the clipped white digits bloom, and two 0s touch along a
    column with more ink than either hollow (a real mask, from 10,000). No
    part may be narrower than a 1, so the cut lands between them."""
    w, h, mask = _grid([
        ".####....####.",
        "######..#####.",
        "##..##.###..##",
        "##..#####...##",
        "##..#####...##",
        "##..#####...##",
        "##..#####...##",
        "##..#####...##",
        "##..#####...##",
        "##..##.###..##",
        "######..#####.",
        ".####...#####.",
    ])
    assert sco_digit_reader._split_joined(w, mask, (0, 0, w, h), 9.9) == [
        (0, 0, 6, 12), (7, 0, 7, 12)]


# A real mask, from 30,000 with HDR: the comma's foot joins the next digits
# and hangs below their baseline.
COMMA_JOINED_ON_THE_LEFT = [
    "....#####..#####.",
    "...######..######",
    "...###.######..##",
    "...##..######..##",
    "...##..######..##",
    "...##..######..##",
    "...##..######..##",
    "...##..######..##",
    ".#.##..######..##",
    "######.######..##",
    "##.######..######",
    "##..#####..#####.",
    "##...............",
]


def test_a_comma_joined_to_the_next_digit_is_peeled_off():
    """The columns on the left that hold only the comma's low ink are taken
    off as the comma."""
    w, h, mask = _grid(COMMA_JOINED_ON_THE_LEFT)
    digits, comma = sco_digit_reader._peel_comma(w, mask, (0, 0, w, h))
    assert comma == (0, 8, 3, 5) and digits == (3, 0, 14, 12)


def test_a_comma_joined_to_the_digit_before_is_peeled_off():
    """The same comma joined to the foot of the digit before it (the mask
    mirrored) comes off the right edge."""
    w, h, mask = _grid([row[::-1] for row in COMMA_JOINED_ON_THE_LEFT])
    digits, comma = sco_digit_reader._peel_comma(w, mask, (0, 0, w, h))
    assert comma == (w - 3, 8, 3, 5) and digits == (0, 0, 14, 12)


def test_a_foot_on_the_baseline_is_no_comma():
    """A "1" with a foot (a wide field of view Golem readout) has a right
    column inked only at the bottom, but it ends on the baseline: no comma."""
    w, h, mask = _grid([
        "###.",
        ".##.",
        ".##.",
        ".##.",
        ".##.",
        ".##.",
        "####",
    ])
    assert sco_digit_reader._peel_comma(w, mask, (0, 0, w, h)) == ((0, 0, w, h), None)


def test_a_comma_is_sized_against_its_own_digits():
    """With HDR a 10,000 readout drew 12 px digits and a 6 px comma where the
    reader expected 9.9 px digits; against those the comma looked too tall
    and the row was dropped. Sized against its own digits it counts."""
    path = next(p for p in READOUTS if p.stem == "hdr4_10000")
    reading = _read(path)
    assert reading.text == "10,000" and reading.box[3] > DIGIT_HEIGHT_AT_1600 * 1440 / 1600


def test_cut_glyphs_cuts_a_red_saturated_readout_from_blue():
    """scripts/add_sco_sample.py cuts glyphs the way the reader finds them,
    so a bright-planet crop whose red is saturated gives its blue glyphs."""
    path = next(p for p in READOUTS if p.stem == "live00_15600")
    w, h, red, green, blue = _on_a_bright_panel(*_channels(path))
    assert sco_digit_reader.cut_glyphs(w, h, red, 5) is None
    glyphs = sco_digit_reader.cut_glyphs(w, h, red, 5, green=green, blue=blue)
    assert glyphs is not None and len(glyphs) == 5
    # Each glyph is blue pixels: the red ones would all be 255.
    assert all(min(pixels) < 255 for _, _, pixels in glyphs)
