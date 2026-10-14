"""SCO digit reader: the mining signature read off real HUD captures.

Fixtures in ``tests/fixtures/sco/`` are named ``<source>_<value>.png``:
crops of 2560x1600 in-game screenshots (Drake Golem ``g*``, MISC Prospector
``p*``, Prospector on a planet with the orange HUD panel ``q*``), lossless
crops SCO saved in-game (``live*``), and other HUD text
the reader must ignore (``hud*_none``: "UNKNOWN", red "WARNING"). Qt-free:
the channels go straight to ``read_signature``.
"""
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


def _read(path):
    w, h, red, green, blue = _channels(path)
    return read_signature(w, h, red, DIGIT_HEIGHT_AT_1600, green=green, blue=blue)


@pytest.mark.parametrize("path", READOUTS, ids=lambda p: p.stem)
def test_reads_every_readout(path):
    reading = _read(path)
    assert reading is not None and reading.text == _expected(path)


@pytest.mark.parametrize("path", OTHER_TEXT, ids=lambda p: p.stem)
def test_ignores_other_hud_text(path):
    assert _read(path) is None


def test_samples_cover_every_digit():
    assert {d for d, *_ in DIGIT_SAMPLES} == set("0123456789")


def test_box_wraps_the_digits():
    path = next(p for p in READOUTS if p.stem == "p2_2000")
    w, h, *_ = _channels(path)
    x, y, bw, bh = _read(path).box
    assert 9 <= bh <= 13 and 25 <= bw <= 45
    assert 0 < x < w - bw and 0 < y < h - bh


@pytest.mark.parametrize("stem", ["live02_8540", "live06_7800", "live24_15600",
                                  "q1_14160", "q2_17080"])
def test_reads_without_its_own_glyphs(monkeypatch, stem):
    # The live crops were misread in-game (8 as 0/6/9, 8 as 0, 6 as 8); the
    # q crops were skipped as coloured text on the orange planet panel. Read
    # with that crop's own glyphs removed, so the rest of the set (and the
    # decode check) has to carry it.
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


@pytest.mark.parametrize("screen_height", [1080, 1440, 2160])
def test_reads_at_other_screen_heights(screen_height):
    """The digit size follows the screen height. Fixtures are 1600 px crops,
    scaled here to what other screens would capture (until testers send real
    ones, which the glob picks up)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    path = next(p for p in READOUTS if p.stem.startswith("live"))
    factor = screen_height / 1600
    img = QImage(str(path))
    img = img.scaled(round(img.width() * factor), round(img.height() * factor),
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    data = img.constBits().asstring(img.sizeInBytes())
    reading = read_signature(img.width(), img.height(), data[2::4],
                             DIGIT_HEIGHT_AT_1600 * factor, green=data[1::4], blue=data[0::4])
    assert reading is not None
    assert reading.text.replace(",", "") == path.stem.split("_")[-1]


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
