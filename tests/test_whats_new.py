"""The What's New dialog: shown once per version, from the bundled notes."""

from types import SimpleNamespace

import pytest

from src.gui import main_window
from src.gui.main_window import MainWindow
from src.utils import release_notes
from src.utils.release_notes import bundled_release_notes
from src.utils.settings import AppSettings

NOTES = (
    "# Smart Citizen 9.9.9\n"
    "\n"
    "> If Windows blocks the installer: ...\n"
    "\n"
    "**Download:** latest release.\n"
    "\n"
    "## Highlights\n"
    "\n"
    "- Something new.\n"
    "\n"
    "## Fixes\n"
    "\n"
    "- Something fixed.\n"
)


@pytest.fixture
def notes_dir(tmp_path, monkeypatch):
    """Point the bundled-docs lookup at tmp_path/docs."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(
        release_notes, "get_resource_path", lambda rel: str(tmp_path / rel)
    )
    return docs


class TestBundledReleaseNotes:
    def test_starts_at_the_first_section(self, notes_dir):
        (notes_dir / "9.9.9-RELEASE-NOTES.md").write_text(NOTES, encoding="utf-8")
        text = bundled_release_notes("9.9.9")
        assert text.startswith("## Highlights")
        assert "Download" not in text and "Windows blocks" not in text
        assert text.endswith("- Something fixed.")

    def test_notes_without_a_section_are_kept_whole(self, notes_dir):
        (notes_dir / "9.9.9-RELEASE-NOTES.md").write_text(
            "﻿Just a line.\n", encoding="utf-8"
        )
        assert bundled_release_notes("9.9.9") == "Just a line."

    def test_missing_notes_read_as_empty(self, notes_dir):
        assert bundled_release_notes("9.9.9") == ""

    def test_the_release_workflow_file_name(self):
        assert (
            release_notes.release_notes_path("3.0.1")
            .as_posix()
            .endswith("docs/3.0.1-RELEASE-NOTES.md")
        )


class TestShownOncePerVersion:
    @pytest.fixture
    def shown(self, tmp_profile, notes_dir, monkeypatch):
        """Run the real _maybe_show_whats_new on a stub window, with the
        dialog replaced by a recorder; returns the list of versions shown."""

        class Calls(list):
            pass

        calls = Calls()

        class FakeDialog:
            def __init__(self, parent, version, notes_html):
                calls.append((version, notes_html))

            def exec(self):
                return 0

        monkeypatch.setattr(main_window, "WhatsNewDialog", FakeDialog)
        monkeypatch.setattr(main_window, "get_version", lambda: "9.9.9")
        stub = SimpleNamespace(markdown_to_html=lambda md: f"<html>{md}</html>")
        calls.run = lambda: MainWindow._maybe_show_whats_new(stub)
        return calls

    def test_fresh_install_shows_and_records(self, shown, notes_dir):
        (notes_dir / "9.9.9-RELEASE-NOTES.md").write_text(NOTES, encoding="utf-8")
        shown.run()
        assert len(shown) == 1
        version, html = shown[0]
        assert version == "9.9.9" and html.startswith("<html>## Highlights")
        assert AppSettings.get_whats_new_seen_version() == "9.9.9"

    def test_second_launch_shows_nothing(self, shown, notes_dir):
        (notes_dir / "9.9.9-RELEASE-NOTES.md").write_text(NOTES, encoding="utf-8")
        shown.run()
        shown.run()
        assert len(shown) == 1

    def test_update_from_an_older_version_shows(self, shown, notes_dir):
        (notes_dir / "9.9.9-RELEASE-NOTES.md").write_text(NOTES, encoding="utf-8")
        AppSettings.set_whats_new_seen_version("9.9.8")
        shown.run()
        assert len(shown) == 1
        assert AppSettings.get_whats_new_seen_version() == "9.9.9"

    def test_no_bundled_notes_shows_and_records_nothing(self, shown):
        shown.run()
        assert shown == []
        assert AppSettings.get_whats_new_seen_version() == ""


def test_seen_version_is_per_install_state():
    assert (
        AppSettings.WHATS_NEW_SEEN_VERSION in AppSettings.PROFILE_DEFAULT_EXCLUDE_KEYS
    )
    assert AppSettings.is_smart_sync_local_key(AppSettings.WHATS_NEW_SEEN_VERSION)


def test_dialog_builds(qapp):
    from src.gui.whats_new_dialog import WhatsNewDialog

    dlg = WhatsNewDialog(None, version="9.9.9", notes_html="<p>hi</p>")
    assert dlg.windowTitle() == "What's New"
    dlg.deleteLater()
