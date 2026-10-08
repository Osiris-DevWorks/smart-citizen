"""SCO digit reader: the mining signature read off real HUD captures.

Fixtures in ``tests/fixtures/sco/`` are crops of Amr's 2560x1600 screenshots
(Drake Golem ``g*``, MISC Prospector ``p*``), named ``<shot>_<value>.png``.
Qt-free: the red channel goes straight to ``read_signature``.
"""
from pathlib import Path

import pytest

from src.utils import sco_digit_reader
from src.utils.sco_digit_reader import read_signature
from src.utils.sco_digit_samples import DIGIT_SAMPLES

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "sco").glob("*.png"))


def _red_channel(path):
    from PyQt6.QtGui import QImage

    img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB32)
    return img.width(), img.height(), img.constBits().asstring(img.sizeInBytes())[2::4]


def _expected(path):
    digits = path.stem.split("_")[1]
    return f"{digits[:-3]},{digits[-3:]}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_reads_every_sample(path):
    w, h, red = _red_channel(path)
    reading = read_signature(w, h, red, 11)
    assert reading is not None and reading.text == _expected(path)


def test_fixtures_cover_every_digit():
    assert {d for d, *_ in DIGIT_SAMPLES} == set("0123456789")
    assert len(FIXTURES) == 8


def test_box_wraps_the_digits():
    path = next(p for p in FIXTURES if p.stem == "p2_2000")
    w, h, red = _red_channel(path)
    x, y, bw, bh = read_signature(w, h, red, 11).box
    assert 9 <= bh <= 13 and 25 <= bw <= 45
    assert 0 < x < w - bw and 0 < y < h - bh


def test_decode_breaks_a_look_alike_tie(monkeypatch):
    # Without the p4 shot's own glyphs its 8 scores as 6 by a hair; 6,540 is
    # no deposit and 8,540 is 2 x Iron, so the decode check picks 8.
    src = (Path(sco_digit_reader.__file__).parent / "sco_digit_samples.py").read_text()
    shots = [line.rsplit("# ", 1)[1] for line in src.splitlines() if line.startswith('    ("')]
    without_p4 = tuple(s for s, shot in zip(DIGIT_SAMPLES, shots) if shot != "p4")
    monkeypatch.setattr(sco_digit_reader, "DIGIT_SAMPLES", without_p4)
    sco_digit_reader._references.cache_clear()
    try:
        path = next(p for p in FIXTURES if p.stem == "p4_8540")
        w, h, red = _red_channel(path)
        assert read_signature(w, h, red, 11).text == "8,540"
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
