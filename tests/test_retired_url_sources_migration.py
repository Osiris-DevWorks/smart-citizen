"""Tests for the 1.0 retired-URL-source cleanup.

Covers:
- migrate_legacy_settings() seeds only the live sources (global + user) for
  fresh installs, with a [global, user] hierarchy. The five sources retired
  in 0.7.0 (contracts/components/ships/commodities/gear) are NOT registered.
- migrate_remove_retired_url_sources() prunes the five retired sources from
  upgraded users' registries, but only when their stored path is a URL —
  local-path overrides are preserved. Also handles the orphan-hierarchy
  case where a source is in the merge hierarchy without a per-source path
  registration (gear was shipped this way in some pre-1.0 builds).
- Both migrations are idempotent (safe to re-run on every launch).
"""
from __future__ import annotations

import os
import sys

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.settings import AppSettings


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures (mirror the pattern from test_channel_layout.py)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at a temp file so tests don't stomp on the real
    Windows Registry."""
    settings_file = tmp_path / "test_registry.ini"

    def _isolated():
        return QSettings(str(settings_file), QSettings.Format.IniFormat)

    monkeypatch.setattr(AppSettings, "settings", staticmethod(_isolated))
    yield


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    """Redirect get_user_data_dir() so the migrators that touch path-helpers
    don't try to mkdir under a real Documents folder."""
    user_dir = tmp_path / "Smart Citizen"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(
        AppSettings, "get_user_data_dir", staticmethod(lambda: user_dir)
    )
    return user_dir


def _seed_pre_1_0_defaults():
    """Recreate the pre-1.0 default settings shape (5 retired URL sources +
    global + user) so we can exercise the upgrader path."""
    AppSettings.set_source_path(
        AppSettings.SOURCE_GLOBAL,
        "C:\\fake\\base.ini",
    )
    AppSettings.set_source_enabled(AppSettings.SOURCE_GLOBAL, True)
    for name in AppSettings.RETIRED_URL_SOURCE_NAMES:
        AppSettings.set_source_path(
            name,
            f"https://raw.githubusercontent.com/Osiris-DevWorks/smart-citizen/main/data/{name}.ini",
        )
        AppSettings.set_source_enabled(name, True)
        AppSettings.set_source_auto_update(name, True)
    AppSettings.set_source_path(AppSettings.SOURCE_USER, "C:\\fake\\user.ini")
    AppSettings.set_merge_hierarchy([
        AppSettings.SOURCE_GLOBAL,
        AppSettings.SOURCE_COMPONENTS,
        AppSettings.SOURCE_CONTRACTS,
        AppSettings.SOURCE_COMMODITIES,
        AppSettings.SOURCE_GEAR,
        AppSettings.SOURCE_USER,
    ])


# ─────────────────────────────────────────────────────────────────────────────
# migrate_legacy_settings — fresh-install defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestFreshInstallDefaults:
    """A fresh install (empty registry) gets only global + user."""

    def test_seeds_global_and_user_only(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.migrate_legacy_settings()

        assert AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)
        assert AppSettings.get_source_path(AppSettings.SOURCE_USER)
        for name in AppSettings.RETIRED_URL_SOURCE_NAMES:
            assert not AppSettings.get_source_path(name), (
                f"Retired source {name!r} should NOT be registered on a "
                f"fresh 1.0 install — it was retired in 0.7.0"
            )

    def test_default_hierarchy_is_global_user(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.migrate_legacy_settings()
        assert AppSettings.get_merge_hierarchy() == [
            AppSettings.SOURCE_GLOBAL,
            AppSettings.SOURCE_USER,
        ]

    def test_idempotent(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.migrate_legacy_settings()
        first_hierarchy = AppSettings.get_merge_hierarchy()
        first_global_path = AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)

        # Re-run — should be a no-op
        AppSettings.migrate_legacy_settings()
        assert AppSettings.get_merge_hierarchy() == first_hierarchy
        assert AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL) == first_global_path


# ─────────────────────────────────────────────────────────────────────────────
# migrate_remove_retired_url_sources — upgrader cleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestRetiredUrlSourcePrune:
    def test_prunes_all_when_paths_are_urls(
        self, isolated_qsettings, fake_user_data_dir
    ):
        _seed_pre_1_0_defaults()
        # Sanity: retired sources are present before migration
        for name in AppSettings.RETIRED_URL_SOURCE_NAMES:
            assert AppSettings.get_source_path(name)

        result = AppSettings.migrate_remove_retired_url_sources()
        assert result is True

        for name in AppSettings.RETIRED_URL_SOURCE_NAMES:
            assert not AppSettings.get_source_path(name), (
                f"Retired source {name!r} should have been removed"
            )

    def test_prunes_them_from_hierarchy(
        self, isolated_qsettings, fake_user_data_dir
    ):
        _seed_pre_1_0_defaults()
        AppSettings.migrate_remove_retired_url_sources()
        # The seeded hierarchy had components/contracts/commodities in the
        # middle. After prune, only global + user should remain.
        assert AppSettings.get_merge_hierarchy() == [
            AppSettings.SOURCE_GLOBAL,
            AppSettings.SOURCE_USER,
        ]

    def test_preserves_local_path_overrides(
        self, isolated_qsettings, fake_user_data_dir
    ):
        """If a user manually re-pointed a retired source at a local file
        (rare but possible), don't blow away their config."""
        _seed_pre_1_0_defaults()
        # Override: pretend the user pointed contracts at a local custom INI
        AppSettings.set_source_path(
            AppSettings.SOURCE_CONTRACTS, "C:\\my\\custom_contracts.ini"
        )

        AppSettings.migrate_remove_retired_url_sources()

        # Components/ships/commodities (still URLs) should be gone
        assert not AppSettings.get_source_path(AppSettings.SOURCE_COMPONENTS)
        assert not AppSettings.get_source_path(AppSettings.SOURCE_SHIPS)
        assert not AppSettings.get_source_path(AppSettings.SOURCE_COMMODITIES)
        # Contracts (local path) should be preserved
        assert (
            AppSettings.get_source_path(AppSettings.SOURCE_CONTRACTS)
            == "C:\\my\\custom_contracts.ini"
        )

    def test_idempotent(self, isolated_qsettings, fake_user_data_dir):
        _seed_pre_1_0_defaults()
        first = AppSettings.migrate_remove_retired_url_sources()
        second = AppSettings.migrate_remove_retired_url_sources()
        assert first is True   # first run did the work
        assert second is False  # second run was a no-op (marker set)

    def test_handles_empty_registry(self, isolated_qsettings, fake_user_data_dir):
        """Fresh install with no retired sources to prune — should be a no-op
        and set the marker so subsequent runs skip cleanly."""
        result = AppSettings.migrate_remove_retired_url_sources()
        assert result is False  # nothing was removed
        # Marker should still be set so we don't re-scan on every launch
        result2 = AppSettings.migrate_remove_retired_url_sources()
        assert result2 is False

    def test_prunes_orphan_hierarchy_entry(
        self, isolated_qsettings, fake_user_data_dir
    ):
        """Some pre-1.0 builds shipped 'gear' in the merge hierarchy without
        a corresponding per-source path registration. The migrator must
        still drop it from the hierarchy — otherwise it shows up as a
        Gear (0 keys) phantom in the Merge Preview forever."""
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, "C:\\fake\\base.ini")
        AppSettings.set_source_path(AppSettings.SOURCE_USER, "C:\\fake\\user.ini")
        # Gear is in hierarchy with no path stored — orphan entry.
        AppSettings.set_merge_hierarchy([
            AppSettings.SOURCE_GLOBAL,
            AppSettings.SOURCE_GEAR,
            AppSettings.SOURCE_USER,
        ])

        result = AppSettings.migrate_remove_retired_url_sources()
        assert result is True
        assert AppSettings.get_merge_hierarchy() == [
            AppSettings.SOURCE_GLOBAL,
            AppSettings.SOURCE_USER,
        ]
