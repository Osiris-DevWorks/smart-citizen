"""Non-UTF-8 base.ini tolerance (#251).

A 2.2.0 user's Generate Enhancements crashed with ``UnicodeDecodeError:
'utf-8' codec can't decode byte 0xa0`` — one bad byte in an
otherwise-valid-UTF-8 base.ini, on a stock English install. A healthy
install's extraction of the same LIVE data decodes perfectly, so the file
was machine-local corruption (possibly in the user's own Data.p4k, meaning
re-extraction can reintroduce it). Both INI readers now tolerate bad input
instead of failing:

  * ``scripts/generate_enhancements_ini.parse_ini`` crashed the whole
    enhancements run on the first bad byte.
  * ``src/parser/ini_parser.parse_ini_file`` was quietly worse: its broad
    except caught the mid-iteration decode error and returned a silently
    TRUNCATED result — every key after the bad byte vanished.

The two realistic failure shapes need OPPOSITE fallbacks, discriminated by
whether the UTF-8 replacement count tracks the file's high-byte count:

  * corrupted UTF-8 (the #251 report) -> UTF-8 errors="replace": only the
    corrupt byte degrades; a cp1252 decode would mojibake every legitimate
    multi-byte character in the file ("é" -> "Ã©").
  * genuinely ANSI/cp1252 file (e.g. re-saved by legacy Notepad) -> cp1252:
    here nearly every high byte is individually invalid UTF-8, and a UTF-8
    replace-decode would destroy all of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser.ini_parser import parse_ini_file  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _generator_parse_ini():
    """Import the standalone generator script's parse_ini lazily so a missing
    lxml (its only third-party dep) skips these cases instead of erroring."""
    pytest.importorskip("lxml")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import generate_enhancements_ini as gen
    return gen.parse_ini


# ── Fixture files ─────────────────────────────────────────────────────────────

# The #251 shape: valid UTF-8 throughout (with plenty of legitimate multi-byte
# characters) except ONE bare corrupt byte, with keys after it that a
# truncating parser would lose.
def _corrupted_utf8_bytes() -> bytes:
    good = (
        "vehicle_NameHunter=Drake Cutlass Black\n"
        "item_NameSHLD_Aspirum=Aspirum™ Shield — Mk. II\n"
        "npc_name=Sebastián Muñoz\n"
    ).encode("utf-8")
    bad_line = b"corrupt_line=before\xa0after\n"
    tail = "key_after_bad_byte=must survive\nlast=entrée\n".encode("utf-8")
    return good + bad_line + tail


# The ANSI shape: the whole file written in cp1252 (every high byte is a
# standalone character, individually invalid as UTF-8).
_CP1252_CONTENT = (
    "vehicle_NameHunter=Drake Cutlass Black\n"
    "mission_prompt=Continuer\xa0?\n"
    "item_NameSHLD_Aspirum=Bouclier «\xa0Aspirum\xa0»\n"
    "key_after_bad_byte=must survive\n"
)


@pytest.fixture
def corrupted_utf8_ini(tmp_path) -> Path:
    p = tmp_path / "base.ini"
    p.write_bytes(_corrupted_utf8_bytes())
    return p


@pytest.fixture
def cp1252_ini(tmp_path) -> Path:
    p = tmp_path / "base.ini"
    p.write_bytes(_CP1252_CONTENT.encode("cp1252"))
    return p


@pytest.fixture
def utf8_bom_ini(tmp_path) -> Path:
    p = tmp_path / "base.ini"
    p.write_bytes("﻿vehicle_NameHunter=Drake Cutlass Black\nk2=v2\n".encode("utf-8"))
    return p


# ── App parser (src/parser/ini_parser.py) ─────────────────────────────────────

class TestAppParser:
    def test_corrupted_utf8_preserves_valid_multibyte_chars(self, corrupted_utf8_ini):
        """The actual #251 file shape. Pre-fix this silently truncated at the
        bad byte; and a naive whole-file cp1252 fallback would mojibake every
        legitimate é/™/— in the file. Only the corrupt byte may degrade."""
        result = parse_ini_file(corrupted_utf8_ini)
        assert result["key_after_bad_byte"] == "must survive"
        # Legitimate multi-byte characters must survive intact, NOT as mojibake.
        assert result["item_NameSHLD_Aspirum"] == "Aspirum™ Shield — Mk. II"
        assert result["npc_name"] == "Sebastián Muñoz"
        assert result["last"] == "entrée"
        # The corrupt byte itself degrades to U+FFFD, nothing more.
        assert result["corrupt_line"] == "before�after"
        assert len(result) == 6

    def test_cp1252_file_parses_completely(self, cp1252_ini):
        result = parse_ini_file(cp1252_ini)
        # Pre-fix this returned only the keys before the 0xA0 byte.
        assert result["key_after_bad_byte"] == "must survive"
        assert result["mission_prompt"] == "Continuer\xa0?"
        assert result["item_NameSHLD_Aspirum"] == "Bouclier «\xa0Aspirum\xa0»"
        assert len(result) == 4

    def test_utf8_bom_still_parses(self, utf8_bom_ini):
        result = parse_ini_file(utf8_bom_ini)
        assert result == {"vehicle_NameHunter": "Drake Cutlass Black", "k2": "v2"}

    def test_utf8_without_bom_still_parses(self, tmp_path):
        p = tmp_path / "base.ini"
        p.write_text("clé=révisé — ✓\n", encoding="utf-8")
        assert parse_ini_file(p) == {"clé": "révisé — ✓"}

    def test_cp1252_undefined_byte_does_not_crash(self, tmp_path):
        # 0x81 is undefined even in cp1252; errors="replace" must absorb it.
        p = tmp_path / "base.ini"
        p.write_bytes(b"good_key=ok\nweird=\x81\nlater_key=still here\n")
        result = parse_ini_file(p)
        assert result["good_key"] == "ok"
        assert result["later_key"] == "still here"

    def test_bom_then_cp1252_body_strips_bom(self, tmp_path):
        # An editor can prepend a UTF-8 BOM and still save the body as ANSI.
        p = tmp_path / "base.ini"
        p.write_bytes(b"\xef\xbb\xbf" + "k=v\xa0!\n".encode("cp1252"))
        result = parse_ini_file(p)
        assert result == {"k": "v\xa0!"}
        assert "﻿k" not in result


# ── Generator parser (scripts/generate_enhancements_ini.py) ──────────────────

class TestGeneratorParser:
    def test_corrupted_utf8_preserves_valid_multibyte_chars(self, corrupted_utf8_ini):
        parse_ini = _generator_parse_ini()
        # Pre-fix this raised UnicodeDecodeError (the #251 traceback).
        result = parse_ini(corrupted_utf8_ini)
        assert result["key_after_bad_byte"] == "must survive"
        assert result["item_NameSHLD_Aspirum"] == "Aspirum™ Shield — Mk. II"
        assert result["corrupt_line"] == "before�after"
        assert len(result) == 6

    def test_cp1252_file_parses_completely(self, cp1252_ini):
        parse_ini = _generator_parse_ini()
        result = parse_ini(cp1252_ini)
        assert result["key_after_bad_byte"] == "must survive"
        assert result["mission_prompt"] == "Continuer\xa0?"
        assert len(result) == 4

    def test_utf8_bom_still_parses(self, utf8_bom_ini):
        parse_ini = _generator_parse_ini()
        assert parse_ini(utf8_bom_ini) == {
            "vehicle_NameHunter": "Drake Cutlass Black", "k2": "v2",
        }

    def test_metadata_suffix_still_stripped(self, tmp_path):
        parse_ini = _generator_parse_ini()
        p = tmp_path / "base.ini"
        p.write_bytes("key,P=value\xa0x\n".encode("cp1252"))
        assert parse_ini(p) == {"key": "value\xa0x"}


# ── Apply path (src/merger/ini_merger.py) ─────────────────────────────────────

class TestMergerAppliesCorruptedBase:
    def test_merge_ini_files_survives_corrupted_utf8_source(self, corrupted_utf8_ini, tmp_path):
        """merge_ini_files reads base.ini on Apply to Game — pre-fix a corrupt
        byte there raised IOError and failed the whole apply."""
        from src.merger.ini_merger import merge_ini_files

        out = tmp_path / "global.ini"
        merge_ini_files(corrupted_utf8_ini, {"vehicle_NameHunter": "OVERRIDDEN"}, out)
        text = out.read_text(encoding="utf-8")
        assert "vehicle_NameHunter=OVERRIDDEN" in text
        # Untouched keys pass through with their multi-byte chars intact.
        assert "item_NameSHLD_Aspirum=Aspirum™ Shield — Mk. II" in text
        assert "key_after_bad_byte=must survive" in text

    def test_merge_ini_files_preserves_trailing_newline_shape(self, tmp_path):
        from src.merger.ini_merger import merge_ini_files

        src = tmp_path / "base.ini"
        src.write_text("a=1\nb=2\n", encoding="utf-8")
        out = tmp_path / "out.ini"
        merge_ini_files(src, {}, out)
        # utf-8-sig strips the BOM (#261) written on the applied file — see
        # test_merge_ini_files_writes_utf8_bom below for the BOM assertion
        # itself; this test is purely about the trailing-newline shape.
        assert out.read_text(encoding="utf-8-sig") == "a=1\nb=2\n"

        src.write_text("a=1\nb=2", encoding="utf-8")  # no trailing newline
        merge_ini_files(src, {}, out)
        assert out.read_text(encoding="utf-8-sig") == "a=1\nb=2"

    def test_merge_ini_files_writes_utf8_bom(self, tmp_path):
        """#261: the applied global.ini must carry a UTF-8 BOM — Star
        Citizen's own loc-string loader needs it to reliably detect the
        file's encoding, or the game shows every key as a raw @KeyName
        placeholder instead of the resolved string."""
        from src.merger.ini_merger import merge_ini_files

        src = tmp_path / "base.ini"
        src.write_text("a=1\nb=2\n", encoding="utf-8")
        out = tmp_path / "out.ini"
        merge_ini_files(src, {}, out)
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")


# ── Sibling #251-class guards (corrupt bytes in app-written state files) ──────

class TestCorruptStateFileGuards:
    def test_json_settings_corrupt_bytes_start_empty(self, tmp_path):
        """Portable-mode settings.json with corrupt bytes previously escaped
        the (OSError, JSONDecodeError) guard as UnicodeDecodeError and crashed
        the portable app at startup."""
        from src.utils.json_settings import JsonSettings

        p = tmp_path / "settings.json"
        p.write_bytes(b'{"key": "val\xa0ue"}')
        s = JsonSettings(p)
        assert s.value("key", "default") == "default"

    def test_enhancements_stamp_corrupt_bytes_reads_empty(self, tmp_path, monkeypatch):
        from src.utils.settings import AppSettings

        monkeypatch.setattr(
            AppSettings, "get_enhancements_dir", staticmethod(lambda language=None: tmp_path)
        )
        (tmp_path / AppSettings.ENHANCEMENTS_STAMP_NAME).write_bytes(b"stamp\xa0value")
        assert AppSettings.get_enhancements_stamp() == ""

    def test_backup_if_changing_survives_corrupt_user_ini(self, tmp_path):
        """_backup_if_changing runs on EVERY save; a corrupt user.ini raised
        UnicodeDecodeError past its OSError guard and bricked all saves. It
        must instead treat the corrupt file as 'changing' and snapshot it."""
        from src.utils.user_ini_manager import _backup_if_changing

        user_ini = tmp_path / "user.ini"
        user_ini.write_bytes(b"key=broken\xa0value\n")
        _backup_if_changing(user_ini, "key=clean value\n")
        backups = list((tmp_path / "backups").glob("*")) if (tmp_path / "backups").exists() else []
        assert backups, "corrupt file should have been snapshotted before overwrite"

    def test_backup_if_changing_identical_save_does_not_snapshot(self, tmp_path):
        """The byte comparison must normalize \\r\\n (text-mode writes) so an
        identical re-save doesn't churn history out of the backup rotation."""
        from src.utils.user_ini_manager import _backup_if_changing

        user_ini = tmp_path / "user.ini"
        # Simulate what text-mode open() writes on Windows: \r\n on disk.
        user_ini.write_bytes(b"key=value\r\n")
        _backup_if_changing(user_ini, "key=value\n")
        backups_dir = tmp_path / "backups"
        assert not backups_dir.exists() or not list(backups_dir.glob("*"))

    def test_locstring_workarounds_skip_corrupt_patch_file(self, tmp_path):
        """A *.patch.json with corrupt bytes raises UnicodeDecodeError (a
        ValueError but NOT a JSONDecodeError), which previously escaped the
        (JSONDecodeError, OSError) guard and crashed the patch scan. It must
        instead be skipped like any malformed patch, with valid sibling
        patch files still loading."""
        from src.utils.dataforge_patcher import load_locstring_workarounds

        (tmp_path / "corrupt.patch.json").write_bytes(b'{"locstring\xa0broken"}')
        (tmp_path / "valid.patch.json").write_text(
            '{"locstring_workarounds": [{"target": "key_a", "append_from": "key_b"}]}',
            encoding="utf-8",
        )
        out = load_locstring_workarounds(tmp_path)
        assert [w.target for w in out] == ["key_a"]


# ── A read during a generation's swap (src/utils/ini_io.py) ───────────────────

def _sharing_violation_twice(monkeypatch) -> list:
    """Path.read_bytes raises PermissionError twice, then reads, as a reader
    does that opens an enhancement INI while a generation swaps it in."""
    from src.utils import atomic_io

    monkeypatch.setattr(atomic_io, "READ_DELAY_S", 0)
    real_read_bytes = Path.read_bytes
    calls = []

    def flaky(self):
        calls.append(self)
        if len(calls) <= 2:
            raise PermissionError(13, "The process cannot access the file")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    return calls


class TestReadDuringSwap:
    """A generation swaps each enhancement INI in with os.replace, and a
    reader that opens it during the swap gets PermissionError for a moment.
    parse_ini_file turned that into a silently empty category, which an
    Apply during a hidden generation would write into global.ini."""

    def test_read_ini_text_retries_a_brief_sharing_violation(self, tmp_path, monkeypatch):
        from src.utils.ini_io import read_ini_text

        path = tmp_path / "ships_desc_enhancements.ini"
        path.write_text("vehicle_Desc_A=Sebastián\nvehicle_Desc_B=two\n", encoding="utf-8")
        calls = _sharing_violation_twice(monkeypatch)

        text = read_ini_text(path)

        assert len(calls) == 3
        assert text.replace("\r\n", "\n") == "vehicle_Desc_A=Sebastián\nvehicle_Desc_B=two\n"

    def test_parse_ini_file_keeps_a_category_read_during_a_swap(self, tmp_path, monkeypatch):
        path = tmp_path / "ships_desc_enhancements.ini"
        path.write_text("vehicle_Desc_A=one\nvehicle_Desc_B=two\n", encoding="utf-8")
        _sharing_violation_twice(monkeypatch)

        assert parse_ini_file(path) == {"vehicle_Desc_A": "one", "vehicle_Desc_B": "two"}
