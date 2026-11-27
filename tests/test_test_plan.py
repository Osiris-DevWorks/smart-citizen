"""Tests for the tester Test Plan (#144): pure logic + AppSettings persistence."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import test_plan  # noqa: E402
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


# ── pure logic ───────────────────────────────────────────────────────────────
def test_plan_hash_is_stable_short_hex():
    h = test_plan.plan_hash()
    assert h == test_plan.plan_hash()
    assert len(h) == 12
    int(h, 16)  # hex-parsable


def test_all_item_keys_match_total():
    keys = test_plan.all_item_keys()
    assert len(keys) == test_plan.total_items()
    assert len(set(keys)) == len(keys)  # unique
    assert keys[0] == test_plan.item_key(0, 0)


def test_progress_empty_and_full():
    assert test_plan.progress(set()) == (0, test_plan.total_items(), 0)
    done, total, pct = test_plan.progress(set(test_plan.all_item_keys()))
    assert (done, total, pct) == (total, total, 100)


def test_progress_ignores_stale_keys():
    # A key not in the current plan must not push the count past the total.
    done, total, _ = test_plan.progress({"999:999", test_plan.item_key(0, 0)})
    assert done == 1
    assert done <= total


def test_build_report_includes_tester_marks_and_version():
    checked = {test_plan.item_key(0, 0)}
    report = test_plan.build_report(checked, "Maverick", "2.1.0")
    assert "2.1.0" in report
    assert "Maverick" in report
    assert "✅" in report and "⬜" in report
    # Blank tester falls back to Anonymous.
    assert "Anonymous" in test_plan.build_report(set(), "  ", "2.1.0")


def test_build_report_includes_notes_when_present():
    report = test_plan.build_report(set(), "Tester", "2.1.0", notes="weird flicker on apply")
    assert "Notes" in report
    assert "weird flicker on apply" in report
    # No Notes section when blank.
    assert "Notes" not in test_plan.build_report(set(), "Tester", "2.1.0", notes="   ")


def test_discord_chunks_respect_limit_and_preserve_lines():
    report = test_plan.build_report(set(), "Tester", "2.1.0")
    chunks = test_plan.discord_chunks(report, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    # Every non-empty source line survives somewhere in the chunks.
    joined = "\n".join(chunks)
    for line in report.split("\n"):
        if line.strip():
            assert line in joined


def test_discord_chunks_hard_slices_overlong_line():
    long_line = "x" * 500
    chunks = test_plan.discord_chunks(long_line, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == long_line


# ── persistence ───────────────────────────────────────────────────────────────
@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def test_checks_round_trip(json_backend):
    keys = {test_plan.item_key(0, 0), test_plan.item_key(1, 0)}
    AppSettings.set_test_plan_checks(keys)
    assert AppSettings.get_test_plan_checks() == keys


def test_checks_dropped_when_plan_hash_changes(json_backend, monkeypatch):
    AppSettings.set_test_plan_checks({test_plan.item_key(0, 0)})
    # Simulate the plan content changing under a saved set of marks.
    monkeypatch.setattr(test_plan, "plan_hash", lambda: "deadbeefcafe")
    assert AppSettings.get_test_plan_checks() == set()


def test_tester_name_round_trip(json_backend):
    assert AppSettings.get_tester_name() == ""
    AppSettings.set_tester_name("Goose")
    assert AppSettings.get_tester_name() == "Goose"


def test_webhook_url_stored_then_env_fallback(json_backend, monkeypatch):
    monkeypatch.delenv(AppSettings.TEST_WEBHOOK_ENV, raising=False)
    assert AppSettings.get_test_webhook_url() == ""
    monkeypatch.setenv(AppSettings.TEST_WEBHOOK_ENV, "https://discord/env")
    assert AppSettings.get_test_webhook_url() == "https://discord/env"
    # A stored override wins over the env var.
    AppSettings.set_test_webhook_url("https://discord/stored")
    assert AppSettings.get_test_webhook_url() == "https://discord/stored"


# ── per-item notes ────────────────────────────────────────────────────────────
def test_build_report_puts_item_note_under_its_item():
    key = test_plan.item_key(0, 0)
    first_item = test_plan.TEST_SECTIONS[0]["items"][0]
    report = test_plan.build_report(
        {key}, "Tester", "3.1.0", item_notes={key: "  flickers\non 4K  "}
    )
    lines = report.split("\n")
    at = lines.index(f"✅ {first_item}")
    # Whitespace and line breaks fold to one line so the note stays one line.
    assert lines[at + 1] == "> 📝 flickers on 4K"


def test_build_report_leaves_out_blank_item_notes():
    key = test_plan.item_key(0, 0)
    report = test_plan.build_report(set(), "Tester", "3.1.0", item_notes={key: "   "})
    assert "📝" not in report
    assert "📝" not in test_plan.build_report(set(), "Tester", "3.1.0")


def test_item_notes_round_trip(json_backend):
    assert AppSettings.get_test_plan_item_notes() == {}
    key = test_plan.item_key(1, 0)
    AppSettings.set_test_plan_item_notes({key: "works", test_plan.item_key(0, 0): " "})
    assert AppSettings.get_test_plan_item_notes() == {key: "works"}


def test_item_notes_dropped_when_plan_hash_changes(json_backend, monkeypatch):
    AppSettings.set_test_plan_item_notes({test_plan.item_key(0, 0): "ok"})
    monkeypatch.setattr(test_plan, "plan_hash", lambda: "deadbeefcafe")
    assert AppSettings.get_test_plan_item_notes() == {}


def test_item_notes_ignore_unreadable_value(json_backend):
    json_backend.setValue(AppSettings.TEST_PLAN_ITEM_NOTES, "not json")
    assert AppSettings.get_test_plan_item_notes() == {}


def test_item_notes_have_no_backup_default_and_are_not_synced():
    assert AppSettings.TEST_PLAN_ITEM_NOTES in AppSettings.PROFILE_DEFAULT_EXCLUDE_KEYS
    assert AppSettings.is_smart_sync_local_key(AppSettings.TEST_PLAN_ITEM_NOTES)


# ── panel ─────────────────────────────────────────────────────────────────────
def test_panel_keeps_item_notes_and_reports_them(qapp, json_backend):
    from src.gui.test_plan_panel import TestPlanPanel

    key = test_plan.item_key(0, 0)
    panel = TestPlanPanel()
    panel._note_edits[key].setText("crashed once")
    panel._note_edits[key].editingFinished.emit()
    assert AppSettings.get_test_plan_item_notes() == {key: "crashed once"}
    assert "> 📝 crashed once" in panel._build_report()

    # A new panel (next launch) shows the saved note.
    again = TestPlanPanel()
    assert again._note_edits[key].text() == "crashed once"

    again._reset()
    assert again._note_edits[key].text() == ""
    assert AppSettings.get_test_plan_item_notes() == {}
    panel.deleteLater()
    again.deleteLater()
