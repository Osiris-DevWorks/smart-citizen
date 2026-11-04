"""Tests for src.utils.json_settings.JsonSettings — the QSettings-compatible
JSON backend used in standalone (portable) mode.

The backend has to mirror QSettings semantics closely enough that
AppSettings's existing get_*/set_* methods work against it without any
per-call adapters. These tests pin the QSettings-compatibility surface:
``value`` (with and without `type=` coercion), ``setValue``, ``remove``,
``sync``, plus persistence + the atomic-write guarantee.
"""
from __future__ import annotations

import json
import threading

import pytest

from src.utils.json_settings import JsonSettings

pytestmark = pytest.mark.unit


# ── value() default + type coercion ───────────────────────────────────────────
class TestValueDefaults:
    def test_missing_key_no_default_returns_none(self, tmp_path):
        """``settings.value("missing")`` returns None — matches QSettings."""
        s = JsonSettings(tmp_path / "config.json")
        assert s.value("missing") is None

    def test_missing_key_with_default_returns_default(self, tmp_path):
        s = JsonSettings(tmp_path / "config.json")
        assert s.value("missing", "fallback") == "fallback"

    def test_default_is_returned_through_type_coercion(self, tmp_path):
        """When the key isn't set, type= still applies to the default."""
        s = JsonSettings(tmp_path / "config.json")
        assert s.value("missing", "true", type=bool) is True


class TestBoolCoercion:
    @pytest.mark.parametrize("stored,expected", [
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("anything_else", False),
    ])
    def test_bool_coerces_strings_and_natives(self, tmp_path, stored, expected):
        """QSettings-on-Windows often round-trips bools as the literal
        strings 'true'/'false'. The JSON backend stores native bools but
        must still accept string sentinels for parity with anything that
        gets written by hand or migrated from elsewhere."""
        s = JsonSettings(tmp_path / "config.json")
        s.setValue("flag", stored)
        assert s.value("flag", type=bool) == expected


class TestStrCoercion:
    def test_str_returns_string(self, tmp_path):
        s = JsonSettings(tmp_path / "config.json")
        s.setValue("path", "/some/path")
        assert s.value("path", type=str) == "/some/path"

    def test_str_coerces_int_to_string(self, tmp_path):
        s = JsonSettings(tmp_path / "config.json")
        s.setValue("epoch", 1234567890)
        assert s.value("epoch", type=str) == "1234567890"

    def test_str_returns_empty_for_none(self, tmp_path):
        """Mirrors QSettings: type=str on a None value returns ""."""
        s = JsonSettings(tmp_path / "config.json")
        s.setValue("path", None)
        assert s.value("path", type=str) == ""


# ── setValue / remove ─────────────────────────────────────────────────────────
class TestSetValueAndRemove:
    def test_setvalue_persists_immediately(self, tmp_path):
        """No batching — every write hits disk so a crash mid-session
        doesn't lose user-visible settings."""
        path = tmp_path / "config.json"
        s = JsonSettings(path)
        s.setValue("theme", "dark")

        with path.open() as f:
            on_disk = json.load(f)
        assert on_disk == {"theme": "dark"}

    def test_remove_drops_key(self, tmp_path):
        s = JsonSettings(tmp_path / "config.json")
        s.setValue("temp", "x")
        s.remove("temp")
        assert s.value("temp") is None

    def test_remove_missing_key_is_no_op(self, tmp_path):
        """Silent no-op for missing keys — QSettings parity."""
        s = JsonSettings(tmp_path / "config.json")
        s.remove("never_set")  # must not raise

    def test_sync_is_no_op(self, tmp_path):
        """sync() exists for API parity but is a no-op since we already
        persist on every setValue."""
        s = JsonSettings(tmp_path / "config.json")
        s.sync()  # must not raise


# ── Persistence across instances ──────────────────────────────────────────────
class TestPersistence:
    def test_round_trip_via_disk(self, tmp_path):
        """Write with one instance, read with a fresh one — values
        should round-trip exactly."""
        path = tmp_path / "config.json"
        a = JsonSettings(path)
        a.setValue("theme", "dark")
        a.setValue("count", 42)
        a.setValue("enabled", True)

        b = JsonSettings(path)
        assert b.value("theme") == "dark"
        assert b.value("count") == 42
        assert b.value("enabled") is True

    def test_unreadable_file_starts_empty(self, tmp_path):
        """Corrupt / truncated JSON shouldn't crash the app — QSettings
        is similarly forgiving on a damaged registry tree."""
        path = tmp_path / "config.json"
        path.write_text("{not valid json", encoding="utf-8")

        s = JsonSettings(path)
        assert s.value("anything") is None
        # And subsequent writes should overwrite the corrupt content.
        s.setValue("k", "v")
        assert s.value("k") == "v"

    def test_non_dict_json_starts_empty(self, tmp_path):
        """JSON parse succeeds but the root isn't an object — same
        forgiving fallback."""
        path = tmp_path / "config.json"
        path.write_text('["not", "a", "dict"]', encoding="utf-8")

        s = JsonSettings(path)
        assert s.value("anything") is None

    def test_missing_parent_dir_is_created_on_write(self, tmp_path):
        """If the parent directory doesn't exist yet (first-launch in a
        fresh portable install), creating it is the backend's job, not
        the caller's."""
        path = tmp_path / "deep" / "nested" / "config.json"
        s = JsonSettings(path)
        s.setValue("k", "v")
        assert path.exists()


# ── Atomic write ──────────────────────────────────────────────────────────────
class TestAtomicWrite:
    def test_write_uses_tmp_then_rename(self, tmp_path):
        """A crash mid-write should leave the original file intact, not
        produce a half-written/truncated config. The implementation
        writes to a .tmp sibling then renames — verify the .tmp doesn't
        linger after a successful write."""
        path = tmp_path / "config.json"
        s = JsonSettings(path)
        s.setValue("k", "v")

        tmp_siblings = list(tmp_path.glob("config.json.tmp*"))
        assert tmp_siblings == [], (
            f".tmp file leaked after successful write: {tmp_siblings}"
        )


# ── Thread safety ─────────────────────────────────────────────────────────────
class TestThreadSafety:
    def test_concurrent_writes_dont_corrupt(self, tmp_path):
        """AppSettings is called from multiple threads (workers + main).
        Confirm the internal lock prevents a torn write or lost update."""
        s = JsonSettings(tmp_path / "config.json")
        threads = []
        # 10 threads × 50 writes each — enough to interleave reliably.
        for t_idx in range(10):
            def worker(idx=t_idx):
                for i in range(50):
                    s.setValue(f"thread_{idx}_key_{i}", i)
            threads.append(threading.Thread(target=worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 500 keys should be present and readable.
        assert len(s.keys()) == 500
        for t_idx in range(10):
            for i in range(50):
                assert s.value(f"thread_{t_idx}_key_{i}") == i
