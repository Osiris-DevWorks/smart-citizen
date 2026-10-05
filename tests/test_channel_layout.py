"""Tests for 0.9.3 Star Citizen channel-aware layout.

Covers:
- Channel-scoped path helpers nest under the active channel.
- get_available_channels() reports only channels whose Data.p4k exists.
- migrate_game_path_to_channel_layout() handles flat → channel-nested
  migration (both registry side and filesystem side), is idempotent, and
  merges into empty channel shells left by eager path-helper mkdir calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.settings import AppSettings


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at an in-memory / file-scoped store so tests don't
    stomp on the real Windows Registry. Uses IniFormat under tmp_path which
    QSettings will use when we force the format + path.

    Returns the SAME instance on every AppSettings.settings() call. A fresh
    QSettings per call relied on cross-instance write visibility: IniFormat
    buffers writes and only flushes on sync()/destruction, so a setValue on
    one instance was not reliably seen by a value() read on the next. That
    surfaced as an environment-dependent CI failure (a set-then-get inside a
    single test reading back empty). One shared instance makes set and get
    hit the same in-memory store, removing the disk-flush dependency.
    """
    settings_file = tmp_path / "test_registry.ini"
    # One instance, reused for the whole test, so set-then-get is consistent.
    shared = QSettings(str(settings_file), QSettings.Format.IniFormat)

    def _isolated():
        return shared

    monkeypatch.setattr(AppSettings, "settings", staticmethod(_isolated))
    # Clear any lru_cache or cached state on AppSettings if added later.
    yield
    # Explicit cleanup not needed — tmp_path handles file removal.


@pytest.fixture
def fake_sc_root(tmp_path):
    """Build a fake SC install root containing LIVE and PTU Data.p4k files."""
    root = tmp_path / "StarCitizen"
    for channel in ("LIVE", "PTU"):
        (root / channel).mkdir(parents=True)
        (root / channel / "Data.p4k").write_bytes(b"dummy")
    # TECH-PREVIEW intentionally absent to test the "disabled channel" path.
    return root


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    """Redirect AppSettings.get_user_data_dir() to a tmp_path so we don't
    touch the real ``Documents\\Smart Citizen\\``."""
    user_dir = tmp_path / "Smart Citizen"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(
        AppSettings, "get_user_data_dir", staticmethod(lambda: user_dir)
    )
    return user_dir


# ─────────────────────────────────────────────────────────────────────────────
# Channel constants & API
# ─────────────────────────────────────────────────────────────────────────────


class TestChannelConstants:
    def test_channels_defined(self):
        assert set(AppSettings.AVAILABLE_CHANNELS) == {
            "LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW"
        }

    def test_default_is_live(self):
        assert AppSettings.DEFAULT_CHANNEL == "LIVE"


class TestActiveChannel:
    def test_unset_returns_default(self, isolated_qsettings):
        assert AppSettings.get_active_channel() == AppSettings.DEFAULT_CHANNEL

    def test_set_and_get_roundtrip(self, isolated_qsettings):
        AppSettings.set_active_channel("PTU")
        assert AppSettings.get_active_channel() == "PTU"

    def test_unknown_stored_value_falls_back_to_default(self, isolated_qsettings):
        # Simulate a corrupt registry value.
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "NOT-A-CHANNEL")
        assert AppSettings.get_active_channel() == AppSettings.DEFAULT_CHANNEL

    def test_set_rejects_unknown_channel(self, isolated_qsettings):
        with pytest.raises(ValueError):
            AppSettings.set_active_channel("NOT-A-CHANNEL")


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers nest under active channel
# ─────────────────────────────────────────────────────────────────────────────


class TestChannelScopedPaths:
    def test_cache_dir_nests_under_active_channel(
        self, isolated_qsettings, fake_user_data_dir
    ):
        AppSettings.set_active_channel("PTU")
        cache = AppSettings.get_cache_dir()
        assert cache == fake_user_data_dir / "PTU" / "cache"
        assert cache.exists()

    def test_backups_dir_nests_under_active_channel(
        self, isolated_qsettings, fake_user_data_dir
    ):
        AppSettings.set_active_channel("EPTU")
        backups = AppSettings.get_backups_dir()
        assert backups == fake_user_data_dir / "EPTU" / "backups"

    def test_user_ini_path_nests_under_active_channel(
        self, isolated_qsettings, fake_user_data_dir
    ):
        AppSettings.set_active_channel("LIVE")
        ini_path = AppSettings.get_user_ini_path()
        assert ini_path == fake_user_data_dir / "LIVE" / "user.ini"

    def test_dataforge_cache_dir_nests_under_active_channel(
        self, isolated_qsettings, tmp_path, monkeypatch
    ):
        # PR #26 moved the DataForge cache out of user_data_dir (Documents)
        # to LOCALAPPDATA so OneDrive sync / Defender don't churn on the
        # 1.4 GB extract. The test mirrors that — path must be under
        # %LOCALAPPDATA%\Smart Citizen\<channel>\cache\dataforge.
        fake_local = tmp_path / "LocalAppData"
        fake_local.mkdir()
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_active_channel("TECH-PREVIEW")
        df = AppSettings.get_dataforge_cache_dir()
        assert df == fake_local / "Smart Citizen" / "TECH-PREVIEW" / "cache" / "dataforge"

    def test_switching_channel_changes_all_paths(
        self, isolated_qsettings, fake_user_data_dir
    ):
        """Critical contract: every path helper tracks get_active_channel()."""
        AppSettings.set_active_channel("LIVE")
        live_cache = AppSettings.get_cache_dir()
        live_user = AppSettings.get_user_ini_path()

        AppSettings.set_active_channel("PTU")
        ptu_cache = AppSettings.get_cache_dir()
        ptu_user = AppSettings.get_user_ini_path()

        assert live_cache != ptu_cache
        assert live_user != ptu_user
        assert live_cache.parent.name == "LIVE"
        assert ptu_cache.parent.name == "PTU"


class TestUserDataDirOverride:
    def test_user_data_dir_override_wins(self, isolated_qsettings, tmp_path):
        custom_dir = tmp_path / "Custom Smart Citizen Data"

        AppSettings.set_user_data_dir(custom_dir)

        assert AppSettings.get_user_data_dir() == custom_dir
        assert custom_dir.exists()

    def test_user_data_dir_alias_is_honored(self, isolated_qsettings, tmp_path):
        custom_dir = tmp_path / "Alias Smart Citizen Data"
        AppSettings.settings().setValue("UserDataDir", str(custom_dir))

        assert AppSettings.get_user_data_dir() == custom_dir
        assert AppSettings.settings().value(AppSettings.USER_DATA_DIR, "") == str(custom_dir)

    def test_channel_paths_nest_under_custom_user_data_dir(
        self, isolated_qsettings, tmp_path
    ):
        custom_dir = tmp_path / "Custom Data"
        AppSettings.set_user_data_dir(custom_dir)
        AppSettings.set_active_channel("PTU")

        assert AppSettings.get_cache_dir() == custom_dir / "PTU" / "cache"
        assert AppSettings.get_user_ini_path() == custom_dir / "PTU" / "user.ini"

    def test_clearing_user_data_dir_reverts_to_documents_default(
        self, isolated_qsettings, tmp_path, monkeypatch
    ):
        docs_dir = tmp_path / "Documents"
        monkeypatch.setattr(
            AppSettings, "_resolve_docs_base", staticmethod(lambda: docs_dir)
        )

        AppSettings.set_user_data_dir(tmp_path / "Custom Data")
        AppSettings.set_user_data_dir(None)

        assert AppSettings.get_user_data_dir() == docs_dir / "Smart Citizen"


# ─────────────────────────────────────────────────────────────────────────────
# SC install root + channel install path + p4k path
# ─────────────────────────────────────────────────────────────────────────────


class TestSCInstallRoot:
    def test_set_and_get(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        assert AppSettings.get_sc_install_root() == str(fake_sc_root)

    def test_channel_install_path_composes_root_and_channel(
        self, isolated_qsettings, fake_sc_root
    ):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("PTU")
        assert Path(AppSettings.get_channel_install_path()) == fake_sc_root / "PTU"

    def test_p4k_path_includes_channel(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("LIVE")
        assert AppSettings.get_p4k_path() == fake_sc_root / "LIVE" / "Data.p4k"

    def test_global_ini_path_under_channel(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("LIVE")
        expected = fake_sc_root / "LIVE" / "data" / "Localization" / "english" / "global.ini"
        assert AppSettings.get_global_ini_path() == expected


# ─────────────────────────────────────────────────────────────────────────────
# Channel auto-detection
# ─────────────────────────────────────────────────────────────────────────────


class TestAvailableChannels:
    def test_reports_only_channels_with_p4k(
        self, isolated_qsettings, fake_sc_root
    ):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        # fake_sc_root fixture ships LIVE + PTU Data.p4k; EPTU/TECH-PREVIEW are missing.
        available = AppSettings.get_available_channels()
        assert available == ["LIVE", "PTU"]

    def test_returns_all_when_root_unset(self, isolated_qsettings, monkeypatch):
        """Combo shouldn't be empty before the user configures the root —
        we return all channels so they can pick one as they set the path.
        Stub get_sc_install_root to avoid the auto-detect fallback that
        otherwise picks up the real machine's StarCitizen install."""
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert AppSettings.get_available_channels() == list(
            AppSettings.AVAILABLE_CHANNELS
        )

    def test_empty_list_when_root_set_but_no_channels_installed(
        self, isolated_qsettings, tmp_path
    ):
        # The root must look like a real SC install so get_sc_install_root()
        # accepts it: as of #119 it validates that the saved root contains at
        # least one channel subdir, else it rejects the value and falls through
        # to auto-detect. Create the LIVE channel folder but no Data.p4k inside,
        # so the root is valid yet no channel is actually installed, which
        # makes get_available_channels() filter everything out.
        sc_root = tmp_path / "StarCitizen"
        (sc_root / "LIVE").mkdir(parents=True)
        AppSettings.set_sc_install_root(str(sc_root))
        assert AppSettings.get_available_channels() == []


# ─────────────────────────────────────────────────────────────────────────────
# Migrator
# ─────────────────────────────────────────────────────────────────────────────


class TestMigrateGamePathToChannelLayout:
    def test_registry_split_from_live_suffix(self, isolated_qsettings, tmp_path):
        s = AppSettings.settings()
        s.setValue(
            AppSettings.GAME_INSTALL_PATH,
            r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE",
        )
        AppSettings.migrate_game_path_to_channel_layout()
        assert (
            s.value(AppSettings.SC_INSTALL_ROOT, "")
            == r"C:\Program Files\Roberts Space Industries\StarCitizen"
        )
        assert s.value(AppSettings.ACTIVE_CHANNEL, "") == "LIVE"
        assert s.value(AppSettings.CHANNEL_LAYOUT_MIGRATED, False, type=bool)

    def test_registry_split_from_ptu_suffix(self, isolated_qsettings, tmp_path):
        s = AppSettings.settings()
        s.setValue(
            AppSettings.GAME_INSTALL_PATH,
            r"D:\Games\StarCitizen\PTU",
        )
        AppSettings.migrate_game_path_to_channel_layout()
        assert s.value(AppSettings.SC_INSTALL_ROOT, "") == r"D:\Games\StarCitizen"
        assert s.value(AppSettings.ACTIVE_CHANNEL, "") == "PTU"

    def test_registry_no_channel_suffix_defaults_to_live(
        self, isolated_qsettings, tmp_path
    ):
        s = AppSettings.settings()
        s.setValue(AppSettings.GAME_INSTALL_PATH, r"D:\SomeWeirdPath")
        AppSettings.migrate_game_path_to_channel_layout()
        assert s.value(AppSettings.SC_INSTALL_ROOT, "") == r"D:\SomeWeirdPath"
        assert s.value(AppSettings.ACTIVE_CHANNEL, "") == "LIVE"

    def test_registry_no_legacy_path_sets_default_channel(
        self, isolated_qsettings
    ):
        """First-time-ever user: no legacy path at all. Migrator should
        still set ACTIVE_CHANNEL so downstream callers get a real value."""
        AppSettings.migrate_game_path_to_channel_layout()
        assert AppSettings.settings().value(AppSettings.ACTIVE_CHANNEL, "") == "LIVE"

    def test_filesystem_moves_flat_layout_into_live(
        self, isolated_qsettings, fake_user_data_dir
    ):
        # Flat pre-0.9.3 layout.
        (fake_user_data_dir / "user.ini").write_text("k=v")
        (fake_user_data_dir / "base.ini").write_text("stock=strings")
        (fake_user_data_dir / "cache").mkdir()
        (fake_user_data_dir / "cache" / "foo.ini").write_text("x")
        (fake_user_data_dir / "backups").mkdir()
        (fake_user_data_dir / "backups" / "global.ini.bak_20240101").write_text("b")

        AppSettings.migrate_game_path_to_channel_layout()

        live = fake_user_data_dir / "LIVE"
        assert live.exists()
        assert (live / "user.ini").read_text() == "k=v"
        assert (live / "base.ini").read_text() == "stock=strings"
        assert (live / "cache" / "foo.ini").exists()
        assert (live / "backups" / "global.ini.bak_20240101").exists()
        # Nothing left at the top level that looks like flat data.
        assert not (fake_user_data_dir / "user.ini").exists()
        assert not (fake_user_data_dir / "cache").exists()

    def test_filesystem_merges_into_empty_live_shell(
        self, isolated_qsettings, fake_user_data_dir
    ):
        """A previous app-start may have touched ``get_cache_dir()`` which
        auto-creates ``LIVE\\cache\\``. An empty LIVE shell shouldn't block
        the migrator — flat data must still move in, merged with any empty
        same-named subfolders under LIVE."""
        (fake_user_data_dir / "LIVE").mkdir()
        (fake_user_data_dir / "LIVE" / "cache").mkdir()   # empty shell
        (fake_user_data_dir / "LIVE" / "backups").mkdir()  # empty shell
        # Flat data that should be folded into LIVE.
        (fake_user_data_dir / "user.ini").write_text("k=v")
        (fake_user_data_dir / "cache").mkdir()
        (fake_user_data_dir / "cache" / "base.ini").write_text("stock")

        AppSettings.migrate_game_path_to_channel_layout()

        assert (fake_user_data_dir / "LIVE" / "user.ini").read_text() == "k=v"
        # The flat ``cache/base.ini`` got merged into the existing empty
        # ``LIVE/cache/`` shell.
        assert (fake_user_data_dir / "LIVE" / "cache" / "base.ini").read_text() == "stock"

    def test_skips_when_populated_channel_dir_exists(
        self, isolated_qsettings, fake_user_data_dir
    ):
        """A populated LIVE dir means the user already has channel-aware
        layout; don't touch sibling flat data (which could be partial
        leftovers the user is intentionally keeping)."""
        (fake_user_data_dir / "LIVE").mkdir()
        (fake_user_data_dir / "LIVE" / "user.ini").write_text("channel=live")
        # Sibling flat data that should NOT get moved.
        (fake_user_data_dir / "stray.txt").write_text("don't touch")

        AppSettings.migrate_game_path_to_channel_layout()

        assert (fake_user_data_dir / "stray.txt").read_text() == "don't touch"
        assert (fake_user_data_dir / "LIVE" / "user.ini").read_text() == "channel=live"

    def test_idempotent(self, isolated_qsettings, fake_user_data_dir):
        (fake_user_data_dir / "user.ini").write_text("original")

        AppSettings.migrate_game_path_to_channel_layout()
        first_state = (fake_user_data_dir / "LIVE" / "user.ini").read_text()

        # Second call should no-op — marker is set.
        AppSettings.migrate_game_path_to_channel_layout()
        second_state = (fake_user_data_dir / "LIVE" / "user.ini").read_text()

        assert first_state == second_state == "original"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
