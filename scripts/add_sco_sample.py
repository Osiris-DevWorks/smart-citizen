"""Turn SCO digit crops into reference glyphs for the digit reader.

The Smart Citizen Overlay saves one crop per reading to
``{user_data_root}\\logs\\sco_samples\\`` as ``<date>_<time>_<digits>.png``,
named after what it *read*. When a crop was misread, rename it to the real
number first (or pass ``--digits``). Each digit is cut out the way the reader
sees it and becomes a ``DIGIT_SAMPLES`` entry in
``src/utils/sco_digit_samples.py``.

Usage:
    python scripts/add_sco_sample.py crop.png [crop2.png ...]
    python scripts/add_sco_sample.py crop.png --digits 12900 --source live_54
    python scripts/add_sco_sample.py crops/*.png --screen-height 1080 --write

Without ``--write`` the entries are printed for review. With it they are
added to the end of ``DIGIT_SAMPLES``; a glyph already in the set is skipped.
Copy the crop to ``tests/fixtures/sco/<source>_<digits>.png`` too, so the
reader's tests check it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.utils.sco_digit_reader import DIGIT_HEIGHT_AT_1600, cut_glyphs  # noqa: E402
from src.utils.sco_digit_samples import DIGIT_SAMPLES  # noqa: E402

SAMPLES_FILE = ROOT / "src" / "utils" / "sco_digit_samples.py"


def crop_entries(path: Path, digits: str, source: str,
                 screen_height: int = 1600) -> list[tuple[str, int, int, str, str]]:
    """``DIGIT_SAMPLES`` entries for each digit of the readout in *path*.

    Raises ValueError when the crop can't be loaded or holds no row of
    ``len(digits)`` digits.
    """
    from PyQt6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"{path}: not an image")
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    data = image.constBits().asstring(image.sizeInBytes())
    # Format_RGB32 is B, G, R, A in memory on x86 (see hud_signature_reader).
    glyphs = cut_glyphs(image.width(), image.height(), data[2::4], len(digits),
                        DIGIT_HEIGHT_AT_1600 * screen_height / 1600,
                        green=data[1::4], blue=data[0::4])
    if glyphs is None:
        raise ValueError(f"{path}: no row of {len(digits)} digits found")
    return [(digit, w, h, pixels.hex(), source)
            for digit, (w, h, pixels) in zip(digits, glyphs)]


def format_entry(entry: tuple[str, int, int, str, str]) -> str:
    digit, w, h, hexdata, source = entry
    return f'    ("{digit}", {w}, {h}, "{hexdata}", "{source}"),'


def add_entries(entries: list[tuple[str, int, int, str, str]],
                samples_file: Path = SAMPLES_FILE,
                existing=DIGIT_SAMPLES) -> int:
    """Insert *entries* before ``DIGIT_SAMPLES``' closing parenthesis.

    Skips any glyph already in *existing* or earlier in *entries*. Returns
    how many were added.
    """
    seen = {e[:4] for e in existing}
    new = []
    for entry in entries:
        if entry[:4] not in seen:
            seen.add(entry[:4])
            new.append(entry)
    if not new:
        return 0
    text = samples_file.read_text(encoding="utf-8")
    end = text.rstrip().rfind(")")
    if end < 0:
        raise ValueError(f"{samples_file}: no closing parenthesis for DIGIT_SAMPLES")
    lines = "".join(format_entry(e) + "\n" for e in new)
    samples_file.write_text(text[:end] + lines + text[end:], encoding="utf-8", newline="")
    return len(new)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crops", type=Path, nargs="+", help="Crop PNGs named <...>_<digits>.png")
    ap.add_argument("--digits", help="The real number, when there is one crop (overrides its name)")
    ap.add_argument("--source", help="Source id for the entries, when there is one crop "
                                     "(default: the file name without the digits)")
    ap.add_argument("--screen-height", type=int, default=1600,
                    help="Height in px of the screen the crops came from (default 1600)")
    ap.add_argument("--write", action="store_true",
                    help="Add the entries to src/utils/sco_digit_samples.py")
    args = ap.parse_args(argv)
    if len(args.crops) > 1 and (args.digits or args.source):
        ap.error("--digits and --source need a single crop")

    entries, failed = [], 0
    for path in args.crops:
        prefix, _, named = path.stem.rpartition("_")
        digits = (args.digits or named).replace(",", "")
        if not digits.isdecimal():
            print(f"{path}: name it <...>_<digits>.png or pass --digits", file=sys.stderr)
            failed += 1
            continue
        try:
            entries += crop_entries(path, digits, args.source or prefix or path.stem,
                                    args.screen_height)
        except ValueError as e:
            print(e, file=sys.stderr)
            failed += 1

    if args.write:
        added = add_entries(entries)
        print(f"Added {added} glyph(s) to {SAMPLES_FILE.relative_to(ROOT)} "
              f"({len(entries) - added} already there).")
    else:
        for entry in entries:
            print(format_entry(entry))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
