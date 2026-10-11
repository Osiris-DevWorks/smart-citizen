"""Mission Titles page: checkbox toggles must mark Save Tag Changes dirty (#259).

Reported: toggling "Underline Direct" on the Enhancements tab's Mission
Titles page didn't light up the Save Tag Changes button. Every other
control on this page (the 5 dropdowns, General Tags / Scanning checkboxes)
emits ``config_changed`` after updating ``self.config``, and MainWindow
wires that signal to ``_mark_tag_dirty()`` (which enables the button — it's
disabled while not dirty). Four handler methods updated ``self.config`` and
refreshed the preview but never emitted the signal: ``_on_mt_standardize_toggle``,
``_on_mt_abbrev_toggle`` (backs Cargo/Haul/Rank *and* Underline Direct),
``_on_mt_shorten_titles_toggle``, and ``_on_mt_shorten_sizes_toggle`` — 7
checkboxes silently failed to arm the dirty state.

Drives the real ``_TagBuilderPage`` widget headlessly (QT_QPA_PLATFORM=
offscreen), same pattern as tests/test_restore_backup.py — no pytest-qt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.gui.enhancements_tab import _TagBuilderPage  # noqa: E402
from src.utils.tag_builder import default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def page(qapp):
    return _TagBuilderPage("mission_titles", default_config("mission_titles"))


def _emits_config_changed(page, action) -> bool:
    fired = []
    page.config_changed.connect(lambda: fired.append(True))
    action()
    return bool(fired)


class TestMissionTitlesDirtySignal:
    def test_underline_direct_checkbox_marks_dirty(self, page):
        assert _emits_config_changed(
            page, lambda: page._mt_underline_direct.setChecked(not page._mt_underline_direct.isChecked())
        )

    def test_shorten_titles_checkbox_marks_dirty(self, page):
        assert _emits_config_changed(
            page, lambda: page._mt_shorten_titles.setChecked(not page._mt_shorten_titles.isChecked())
        )

    def test_shorten_sizes_checkbox_marks_dirty(self, page):
        assert _emits_config_changed(
            page, lambda: page._mt_shorten_sizes.setChecked(not page._mt_shorten_sizes.isChecked())
        )

    def test_standardize_hauling_names_checkbox_marks_dirty(self, page):
        assert _emits_config_changed(
            page, lambda: page._mt_standardize.setChecked(not page._mt_standardize.isChecked())
        )

    @pytest.mark.parametrize("key", ["cargo", "haul", "rank"])
    def test_remove_word_checkboxes_mark_dirty(self, page, key):
        box = page._mt_abbrev_boxes[key]
        assert _emits_config_changed(page, lambda: box.setChecked(not box.isChecked()))

    def test_dropdowns_still_mark_dirty(self, page):
        """Sanity check the fix didn't accidentally break the controls that
        already worked — the 5 dropdowns on this page."""
        assert _emits_config_changed(page, lambda: page._mt_placement.setCurrentIndex(
            (page._mt_placement.currentIndex() + 1) % page._mt_placement.count()
        ))

    def test_config_actually_updates_alongside_the_signal(self, page):
        """The signal firing is only half the bug — confirm the underlying
        config value is the thing driving it, not a coincidental double-fire."""
        new_state = not page._mt_underline_direct.isChecked()
        page._mt_underline_direct.setChecked(new_state)
        assert ("underline_direct" in page.config.abbreviated_phrases) == new_state
