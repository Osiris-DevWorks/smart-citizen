"""SCO digit reader: the mining signature read off real HUD captures.

Fixtures in ``tests/fixtures/sco/`` are named ``<source>_<value>.png``:
crops of Amr's 2560x1600 screenshots (Drake Golem ``g*``, MISC Prospector
``p*``), lossless crops SCO saved in-game (``live*``), and other HUD text
the reader must ignore (``hud*_none``: "UNKNOWN", red "WARNING"). Qt-free:
the channels go straight to ``read_signature``.
"""
from pathlib import Path

import pytest

from src.utils import sco_digit_reader
from src.utils.sco_digit_reader import read_signature
from src.utils.sco_digit_samples import DIGIT_SAMPLES

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "sco").glob("*.png"))
READOUTS = [p for p in FIXTURES if not p.stem.endswith("_none")]
OTHER_TEXT = [p for p in FIXTURES if p.stem.endswith("_none")]


def _channels(path):
    from PyQt6.QtGui import QImage

    img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB32)
    data = img.constBits().asstring(img.sizeInBytes())
    return img.width(), img.height(), data[2::4], data[1::4]


def _expected(path):
    digits = path.stem.split("_")[1]
    return f"{digits[:-3]},{digits[-3:]}"


def _read(path):
    w, h, red, green = _channels(path)
    return read_signature(w, h, red, 11, green=green)


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


@pytest.mark.parametrize("stem", ["live02_8540", "live06_7800", "live24_15600"])
def test_reads_without_its_own_glyphs(monkeypatch, stem):
    # Each of these was misread in-game (8 as 0/6/9, 8 as 0, 6 as 8). Read
    # with that crop's own glyphs removed, so the rest of the set (and the
    # decode check) has to carry it.
    source = "live_" + stem[4:6]
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
    assert read_signature(w, h, bytes(w * h), 11) is None
    # A lone bright bar is not a signature.
    red = bytearray(w * h)
    for y in range(20, 31):
        red[y * w + 50:y * w + 53] = b"\xff\xff\xff"
    assert read_signature(w, h, bytes(red), 11) is None
    assert read_signature(w, h, b"short", 11) is None
