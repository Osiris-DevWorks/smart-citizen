"""Encoding-tolerant INI text reading (#251).

base.ini is normally UTF-8 (with BOM) straight out of Data.p4k, but the
cached copy can stop being clean UTF-8 on a user's machine. The #251 report
(a stock English install; byte 0xA0 at one position in an otherwise-valid
file, while a healthy install's extraction of the same LIVE data decodes
perfectly) was machine-local corruption — possibly in the user's own
Data.p4k, so re-extracting can reintroduce it. A file re-saved by an
external editor in ANSI (legacy Notepad's default) is the other realistic
shape. Strict decodes crashed the enhancements generator and Apply to Game,
and silently truncated the strings table — a full blocker from one bad byte.

Shared by ``src/parser/ini_parser.py`` and ``src/merger/ini_merger.py``.
``scripts/generate_enhancements_ini.py`` carries its own mirror so it stays
stdlib+lxml-only for standalone runs; keep the two in sync.

One deliberate difference: this copy reads through ``read_bytes_retrying``.
A generation swaps each enhancement INI in with ``os.replace``, and a reader
that opens the file during the swap gets PermissionError for a moment;
``parse_ini_file`` would turn that into a silently empty category, which an
Apply during a hidden generation would write into global.ini. The mirror
reads only base.ini, which a generation never replaces, so it keeps a plain
read.
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.utils.atomic_io import read_bytes_retrying

logger = logging.getLogger(__name__)

# Deletion table for counting high (non-ASCII) bytes at C speed: translating
# with this removes every byte >= 0x80, so the length delta is the count.
_HIGH_BYTES = bytes(range(0x80, 0x100))


def read_ini_text(path: Path) -> str:
    """Read an INI file's text, tolerating non-UTF-8 content.

    The two realistic failure shapes need OPPOSITE fallbacks, so we pick by
    measuring:

    * A few corrupt bytes in an otherwise-UTF-8 file -> decode UTF-8 with
      errors="replace". Only the corrupt byte degrades (to U+FFFD); a cp1252
      decode here would instead mojibake every legitimate multi-byte
      character in the file ("é" -> "Ã©", thousands of them).
    * A genuinely ANSI/cp1252 file -> decode cp1252. Here it's reversed:
      nearly EVERY high byte is an invalid UTF-8 start byte, so a UTF-8
      replace-decode would destroy all of them.

    Discriminator: in a real cp1252 file the replacement count tracks the
    high-byte count (each high byte fails UTF-8 on its own); in corrupted
    UTF-8 it's a tiny fraction (most high bytes sit inside valid multi-byte
    sequences). Split at half.
    """
    raw = read_bytes_retrying(path)
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    utf8_replaced = body.decode("utf-8", errors="replace")
    bad = utf8_replaced.count("�")
    high = len(body) - len(body.translate(None, _HIGH_BYTES))
    if bad * 2 <= high:
        logger.warning(
            f"{path} is UTF-8 with {bad} corrupt byte(s) "
            f"(of {high} non-ASCII); replaced with U+FFFD"
        )
        return utf8_replaced
    logger.warning(f"{path} is not UTF-8 (looks ANSI); decoding as Windows-1252")
    return body.decode("cp1252", errors="replace")
