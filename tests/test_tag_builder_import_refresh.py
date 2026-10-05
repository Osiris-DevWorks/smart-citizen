"""Imported Tag Builder configs must survive a later widget-driven save.

Regression for the Export/Import Settings feature: `_tag_builder_pages` is
built once at tab construction, so an import that rewrites the
`tag_builder/*` keys underneath a live tab leaves the pages holding the
PRE-import config. The next `_persist_tag_builder_state()` — reachable from
Save Tag Changes, Generate Enhancements, and Export Settings — then wrote
that stale state back over everything the import restored, which is how
imported tag configs were being lost.

`EnhancementsTab.reload_tag_builder_from_settings()` (called by
`MainWindow._handle_import_settings`) resyncs the pages so none of those
paths can resurrect the old config.

Needs a real QApplication for the widgets, so it uses the offscreen Qt
platform like tests/test_ui_mode.py rather than pytest-qt (not a dev dep).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import CATEGORIES, default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

CUSTOM_SEPARATOR = "underscore"


@pytest.fixture
def json_backend(tmp_path):
    """Redirect BOTH the settings backend and the user data dir.

    Swapping ``_backend`` alone leaves ``get_enhancements_dir()`` pointing at
    the real ``Documents\\Smart Citizen\\{channel}\\cache``, because it derives
    from the data-dir setting rather than the backend object. That went
    unnoticed while nothing here read a file from it; the tag-config stamp
    (#363) does, so without the redirect these tests would pass or fail
    depending on whether the developer's own install happens to have a stamp
    and whether it happens to match. ``set_user_data_dir`` writes through
    ``settings()``, which is the swapped backend, so restoring ``_backend``
    still undoes it.
    """
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    AppSettings.set_user_data_dir(tmp_path / "data")
    yield AppSettings._backend
    AppSettings._backend = saved


def _stamp_matching_current_config() -> None:
    """Record the stamp a successful generation of the live config would leave,
    i.e. put the generated INIs "in sync" for a freshness check."""
    AppSettings.set_tag_config_stamp(AppSettings.get_current_tag_config_fingerprint())


def _seed_generated_output() -> None:
    """Put generated INIs on disk. The freshness check only reports staleness
    when there is output that can actually be stale (#363), so a refresh with
    no output is unconditionally clean and would prove nothing.

    get_enhancements_dir(), not get_cache_dir(): that is where the generator
    writes and where the check looks (they differ for non-English languages).
    """
    enh_dir = AppSettings.get_enhancements_dir()
    enh_dir.mkdir(parents=True, exist_ok=True)
    for filename in AppSettings.ENHANCEMENTS_FILES.values():
        (enh_dir / filename).write_text("; generated\n", encoding="utf-8")


def _import_custom_configs():
    """Mimic Import Settings writing a customised backup into settings."""
    for cat in CATEGORIES:
        cfg = default_config(cat)
        cfg.separator = CUSTOM_SEPARATOR
        AppSettings.set_tag_config(cat, cfg)
    AppSettings.set_tag_annotate_mission_descs(False)


def _separators() -> dict:
    return {c: AppSettings.get_tag_config(c).separator for c in CATEGORIES}


class TestImportRefresh:
    def test_stale_pages_clobber_import_without_refresh(self, qapp, json_backend):
        """Locks the failure mode itself, so a future refactor can't undo the fix."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()                 # built against an empty profile
        _import_custom_configs()                # import lands underneath it
        tab._persist_tag_builder_state()        # Save / Generate / Export
        assert all(v != CUSTOM_SEPARATOR for v in _separators().values()), (
            "expected the un-refreshed page state to overwrite the import — "
            "if this now passes, the clobber path changed and this test needs review"
        )

    def test_refresh_makes_import_survive_a_later_save(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()  # the fix
        tab._persist_tag_builder_state()
        assert _separators() == {c: CUSTOM_SEPARATOR for c in CATEGORIES}

    def test_refresh_updates_the_visible_pages(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()
        assert {c: p.config.separator for c, p in tab._tag_builder_pages.items()} == {
            c: CUSTOM_SEPARATOR for c in CATEGORIES
        }

    def test_refresh_syncs_annotate_toggle(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()                # imported it as False
        tab.reload_tag_builder_from_settings()
        assert tab._annotate_mission_descs_cb.isChecked() is False

    def test_refresh_leaves_save_button_clean_when_the_inis_match(
            self, qapp, json_backend):
        """A refresh must not light the button for *unsaved edits* — the pages
        equal the persisted config by the time it returns, so there are none.

        This used to assert an unconditional clean, which is what #363 changed:
        the refresh now re-derives from the tag-config stamp instead of
        asserting. Seeding a stamp that matches the imported config is what
        makes "nothing to do" true rather than merely assumed, so the original
        guarantee is still pinned — it just has to be set up honestly now.
        """
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _seed_generated_output()
        _import_custom_configs()
        _stamp_matching_current_config()        # INIs already built from it
        tab.reload_tag_builder_from_settings()
        assert tab._tag_dirty is False

    def test_refresh_lights_the_button_when_the_import_outdates_the_inis(
            self, qapp, json_backend):
        """#363, the Import Settings route into the reported bug.

        An import that changes the tag config leaves the generated INIs built
        from the *pre-import* one. Clearing the button unconditionally hid that
        exactly as launch did: grey button, stale output, and no indication
        anything needed regenerating.
        """
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _seed_generated_output()
        _stamp_matching_current_config()        # generated against the OLD config
        _import_custom_configs()                # ...which the import then changes
        tab.reload_tag_builder_from_settings()
        assert tab._tag_dirty is True

    def test_refresh_does_not_write_title_tags(self, qapp, json_backend):
        """The import path mirrors General Tags; it must not persist over them."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        AppSettings.set_mission_title_tag("rep_track", True)  # non-default
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()
        assert AppSettings.get_mission_title_tags()["rep_track"] is True

    def test_reset_to_defaults_still_persists_title_tags(self, qapp, json_backend):
        """The refactor must not change Reset-to-defaults' write behaviour."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        AppSettings.set_mission_title_tag("rep_track", True)
        tab._tag_builder_pages["mission_titles"]._reset_to_defaults()
        assert AppSettings.get_mission_title_tags()["rep_track"] == (
            AppSettings.get_mission_title_tag_default("rep_track")
        )
