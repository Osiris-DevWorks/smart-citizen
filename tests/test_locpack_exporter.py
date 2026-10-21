"""Tests for src.utils.locpack_exporter — zip packaging of applied global.ini."""
from __future__ import annotations

import zipfile
from datetime import datetime

import pytest

from src.utils.locpack_exporter import default_locpack_filename, write_locpack_zip

pytestmark = pytest.mark.unit


# ── default_locpack_filename ──────────────────────────────────────────────────
class TestDefaultLocpackFilename:
    def test_uses_channel_and_today(self):
        result = default_locpack_filename("LIVE", today=datetime(2026, 5, 9))
        assert result == "SmartCitizen-LocPack-LIVE-20260509.zip"

    def test_distinct_per_channel(self):
        """Channel-specific because LIVE/PTU stock keys diverge — applying
        a PTU export to LIVE could produce missing-key validation errors.
        Filename surfaces the channel so the recipient can avoid that."""
        live = default_locpack_filename("LIVE", today=datetime(2026, 1, 1))
        ptu = default_locpack_filename("PTU", today=datetime(2026, 1, 1))
        assert live != ptu
        assert "LIVE" in live and "PTU" in ptu

    def test_zip_suffix(self):
        assert default_locpack_filename("LIVE").endswith(".zip")

    def test_default_today_when_omitted(self):
        """When `today` is None, uses datetime.now() — should still produce
        a parseable YYYYMMDD substring."""
        result = default_locpack_filename("LIVE")
        # Format: SmartCitizen-LocPack-LIVE-YYYYMMDD.zip
        date_part = result.split("-")[-1].replace(".zip", "")
        assert len(date_part) == 8
        assert date_part.isdigit()


# ── write_locpack_zip ─────────────────────────────────────────────────────────
class TestWriteLocpackZip:
    def test_writes_global_ini_at_zip_root(self, tmp_path):
        """Zip should contain `global.ini` at the root, no nested dirs —
        recipients drop straight into the game's loc directory without
        having to navigate sub-folders. Uses write_bytes (not write_text)
        to bypass Windows newline translation — keeps the test focused on
        zip structure, not on platform-specific line endings."""
        src = tmp_path / "global.ini"
        payload = b"vehicle_NameTestShip=Test Ship\n"
        src.write_bytes(payload)
        dst = tmp_path / "out.zip"

        write_locpack_zip(src, dst)

        with zipfile.ZipFile(dst) as zf:
            assert zf.namelist() == ["global.ini"]
            assert zf.read("global.ini") == payload

    def test_returns_uncompressed_size(self, tmp_path):
        """Return value is the source size in bytes — the GUI uses it for
        status feedback ("Source size: 12,345 bytes"). Uses write_bytes
        to control byte count exactly (write_text on Windows would
        CRLF-expand and inflate the count)."""
        src = tmp_path / "global.ini"
        payload = b"key=value\n" * 100  # exactly 1000 bytes
        src.write_bytes(payload)
        dst = tmp_path / "out.zip"

        result = write_locpack_zip(src, dst)

        assert result == 1000

    def test_overwrites_existing_zip(self, tmp_path):
        """If the output path already exists, write_locpack_zip should
        overwrite it (mode='w' on ZipFile). Avoids the user having to
        manually delete an old export before re-running."""
        src = tmp_path / "global.ini"
        payload = b"new=content\n"
        src.write_bytes(payload)
        dst = tmp_path / "out.zip"
        dst.write_bytes(b"stale junk that should not survive")

        write_locpack_zip(src, dst)

        with zipfile.ZipFile(dst) as zf:
            assert zf.read("global.ini") == payload

    def test_compressed_smaller_than_source(self, tmp_path):
        """Sanity check that DEFLATE is actually being applied — not
        STORED. Real loc-files are mostly repetitive English text (~85%
        compression typical), so a 10KB highly-repetitive source should
        compress significantly."""
        src = tmp_path / "global.ini"
        # Highly repetitive content — guarantees deflate gives a big win.
        src.write_text("repeat_key=repeat_value\n" * 1000, encoding="utf-8")
        dst = tmp_path / "out.zip"

        write_locpack_zip(src, dst)

        assert dst.stat().st_size < src.stat().st_size // 4, (
            "Zip should be <25% of source size for highly repetitive input "
            "— if not, ZIP_DEFLATED isn't being applied"
        )

    def test_missing_source_raises_filenotfounderror(self, tmp_path):
        """The GUI handler converts this into a friendly "Apply Enhancements
        first" message, but the raw exception type is part of the API
        contract — locks it in. The literal apostrophes in the message
        text mean we match against a quote-less substring."""
        src = tmp_path / "does_not_exist.ini"
        dst = tmp_path / "out.zip"

        with pytest.raises(FileNotFoundError, match=r"Apply Enhancements"):
            write_locpack_zip(src, dst)
