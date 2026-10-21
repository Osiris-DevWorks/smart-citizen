"""#494: the Enhancements tab's status checks with a DataForge cache folder
that cannot be made.

``refresh_forge_status`` and ``_compute_initial_enhancements_dirty`` read the
cache through ``get_dataforge_cache_dir()``, which creates the folder. When
Windows refused it (a folder whose permissions deny new folders, Controlled
folder access) or its drive was gone, they raised. Building the tab runs both,
and the tab is built with the main window, so Smart Citizen could not open;
later in a session the same checks broke a language switch halfway and kept
the Enhancements tab's Apply from asking for its reload. They now read
``get_dataforge_cache_leaf()``, which creates nothing, and a cache folder that
is not there reads as not extracted through the stamp checks they already had.

Real Windows refusals through ``tests/unusable_folder.py``: a cache folder
override that denies new folders, the default ``%LOCALAPPDATA%\\Smart Citizen``
denied the same way, and an override on a drive that is not there. A cache
already there under folders that refuse new ones still reads up to date.
Offscreen Qt through the session ``qapp``, settings in ``tmp_profile``.
"""
from __future__ import annotations

import contextlib

import pytest

from src.utils import i18n
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from tests.unusable_folder import missing_drive_folder, new_folders_denied

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_UNUSABLE = ("refused override", "refused default", "missing drive")


@contextlib.contextmanager
def _unusable_cache(kind: str, profile):
    """Make the cache folder unusable the *kind* way for the block. Yields
    the folder that refuses new folders, or None for a missing drive."""
    if kind == "missing drive":
        AppSettings.set_cache_dir(missing_drive_folder())
        yield None
        return
    if kind == "refused override":
        base = profile / "cache"
        AppSettings.set_cache_dir(base)
    else:
        base = profile / "LocalAppData" / "Smart Citizen"
    base.mkdir(parents=True)
    with new_folders_denied(base):
        yield base


def _new_tab():
    from src.gui.enhancements_tab import EnhancementsTab
    return EnhancementsTab()


def _reads_not_extracted(tab) -> None:
    assert tab._forge_status_label.text() == tr("enhancements.forge_status_not_extracted")
    assert tab._generate_enhancements_btn.isEnabled(), "Generate must be lit to extract"


class TestStatusChecksWithUnusableCache:
    @pytest.mark.parametrize("kind", _UNUSABLE)
    def test_the_tab_builds_and_reads_not_extracted(self, tmp_profile, qapp, english_ui, kind):
        with _unusable_cache(kind, tmp_profile) as base:
            tab = _new_tab()
            _reads_not_extracted(tab)
            tab.refresh_enhancements_status()
            tab.refresh_enhancements_dirty_state()
            _reads_not_extracted(tab)
            if base is not None:
                assert list(base.iterdir()) == [], "a status check made part of the cache folder"

    def test_a_language_switch_translates_the_whole_tab(self, tmp_profile, qapp, english_ui):
        """The forge status is read partway through retranslate_ui, so the
        Tag Builder below it used to stay in the old language."""
        with _unusable_cache("refused override", tmp_profile):
            tab = _new_tab()
            english_title = tab._tag_builder_group_box.title()
            i18n.set_language("german")
            tab.retranslate_ui()
            assert tab._tag_builder_group_box.title() == tr("enhancements.tag_builder_group")
            assert tab._tag_builder_group_box.title() != english_title
            assert tab._forge_status_label.text() == tr("enhancements.forge_status_not_extracted")

    def test_applying_the_categories_asks_for_one_reload(
        self, tmp_profile, qapp, english_ui, slot_errors
    ):
        with _unusable_cache("refused override", tmp_profile):
            tab = _new_tab()
            reloads = []
            tab.merge_requested.connect(lambda: reloads.append(1))
            checkbox = next(iter(tab._enhancements_checkboxes.values()))
            checkbox.setChecked(not checkbox.isChecked())
            assert tab._apply_categories_btn.isEnabled()
            tab._apply_categories_btn.click()
            assert slot_errors == []
            assert reloads == [1]

    def test_a_stamped_cache_under_refusing_folders_reads_up_to_date(
        self, tmp_profile, qapp, english_ui
    ):
        """A cache that is already there needs no new folder, so a folder
        above it that refuses new ones changes nothing."""
        from src.utils.pak_extractor import (
            DATAFORGE_LIBS_SUBPATH, P4K_MTIME_STAMP, P4K_SIZE_STAMP,
        )

        p4k = tmp_profile / "StarCitizen" / "LIVE" / "Data.p4k"
        p4k.write_bytes(b"p4k")
        base = tmp_profile / "cache"
        leaf = base / "LIVE" / "cache" / "dataforge"
        (leaf / DATAFORGE_LIBS_SUBPATH).mkdir(parents=True)
        (leaf / DATAFORGE_LIBS_SUBPATH / "record.xml").write_text("<x/>", encoding="utf-8")
        (leaf / P4K_MTIME_STAMP).write_text(str(p4k.stat().st_mtime))
        (leaf / P4K_SIZE_STAMP).write_text(str(p4k.stat().st_size))
        AppSettings.set_cache_dir(base)
        with new_folders_denied(base, base / "LIVE", base / "LIVE" / "cache", leaf):
            tab = _new_tab()
            assert tab._forge_status_label.text() == tr("enhancements.forge_status_up_to_date")
