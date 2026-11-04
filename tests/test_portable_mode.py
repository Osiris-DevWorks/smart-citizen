"""Tests for portable-mode path routing.

PR-B in the standalone-build series. Verifies that flipping
``build_mode.IS_PORTABLE`` redirects ``AppSettings.get_user_data_dir()``
to the next-to-binary location and switches the settings backend to
``JsonSettings``. Tests use ``monkeypatch`` to flip the constant
without rebuilding — production code paths set it at build time
(PR-C) but the tests need to exercise both branches in one run.
"""
from __future__ import annotations

import sys

import pytest

from src.utils import build_mode
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_appsettings_backend():
    """Each test starts with a clean ``AppSettings._backend``.

    Without this, a test that sets the JSON backend would leak state
    into subsequent tests (and into the registry-mode tests in the
    rest of the suite). Defensive — also prevents state leakage from
    the other test files in this run.
    """
    saved = AppSettings._backend
    AppSettings._backend = None
    yield
    AppSettings._backend = saved


# ── build_mode default ────────────────────────────────────────────────────────
class TestBuildModeDefault:
    def test_default_ships_registry_mode(self):
        """Ship default is False — protects against an accidental
        portable-only release that would silently switch every
        production user to the JSON backend."""
        assert build_mode.IS_PORTABLE is False


# ── _portable_data_dir resolution ─────────────────────────────────────────────
class TestPortableDataDir:
    def test_unfrozen_uses_repo_root_portable_data(self, monkeypatch):
        """Dev mode (no PyInstaller bundle): data lives at
        ``<repo-root>/portable_data/`` so a developer flipping
        IS_PORTABLE=True doesn't touch their real Documents tree."""
        # Make sure sys.frozen isn't set (the test process should never
        # have it, but be defensive against pytest plugins that might).
        monkeypatch.delattr(sys, "frozen", raising=False)

        result = AppSettings._portable_data_dir()

        assert result.name == "portable_data"
        assert result.is_absolute()

    def test_frozen_uses_exe_dir_data(self, monkeypatch, tmp_path):
        """Frozen build: ``<exe-dir>/data/``. Simulated by setting
        sys.frozen + sys.executable since we can't actually build a
        PyInstaller bundle in tests."""
        fake_exe = tmp_path / "SmartCitizen-Portable.exe"
        fake_exe.write_bytes(b"")  # so resolve() works
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))

        result = AppSettings._portable_data_dir()

        assert result == tmp_path.resolve() / "data"


# ── get_user_data_dir routing ─────────────────────────────────────────────────
class TestGetUserDataDirRouting:
    def test_registry_mode_uses_documents_path(self, monkeypatch):
        """When IS_PORTABLE is False, get_user_data_dir() goes through
        the registry-override → Documents → ~/Documents resolution
        (existing behavior, unchanged)."""
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)

        result = AppSettings.get_user_data_dir()

        # Registry mode should land in something under the user's
        # home / Documents-like tree. Just check it's NOT the portable
        # path — the actual resolution depends on the test machine's
        # registry state, which we don't want to assert on here.
        assert result.name != "portable_data"
        assert "data" not in result.parts[-2:] or result.parts[-1] != "data"

    def test_portable_mode_routes_to_portable_data(self, monkeypatch):
        """When IS_PORTABLE is True, get_user_data_dir() returns
        _portable_data_dir() — bypasses USER_DATA_DIR override and
        Documents resolution entirely."""
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)

        result = AppSettings.get_user_data_dir()

        assert result == AppSettings._portable_data_dir()

    def test_portable_mode_creates_directory(self, monkeypatch, tmp_path):
        """get_user_data_dir() promises to create the directory if
        missing — should hold in portable mode too. Simulate frozen
        mode pointed at a clean tmp_path so we control the target."""
        fake_exe = tmp_path / "SmartCitizen-Portable.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)

        target = tmp_path.resolve() / "data"
        assert not target.exists()

        result = AppSettings.get_user_data_dir()

        assert result == target
        assert target.exists()


# ── setup_portable_backend_if_needed ──────────────────────────────────────────
class TestSetupPortableBackend:
    def test_noop_in_registry_mode(self, monkeypatch):
        """No-op in registry mode — _backend stays None so settings()
        keeps returning a fresh QSettings."""
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)
        AppSettings._backend = None

        AppSettings.setup_portable_backend_if_needed()

        assert AppSettings._backend is None

    def test_installs_json_backend_in_portable_mode(self, monkeypatch, tmp_path):
        """Portable mode swaps in a JsonSettings rooted at the portable
        data dir."""
        fake_exe = tmp_path / "SmartCitizen-Portable.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)
        AppSettings._backend = None

        AppSettings.setup_portable_backend_if_needed()

        assert isinstance(AppSettings._backend, JsonSettings)
        assert AppSettings._backend.file_path() == tmp_path.resolve() / "data" / "config.json"

    def test_idempotent_when_backend_already_set(self, monkeypatch, tmp_path):
        """Calling setup twice shouldn't replace an existing backend
        — that would lose any in-memory state and leak the file
        handle on the previous instance."""
        fake_exe = tmp_path / "SmartCitizen-Portable.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)

        AppSettings.setup_portable_backend_if_needed()
        first_backend = AppSettings._backend

        AppSettings.setup_portable_backend_if_needed()
        second_backend = AppSettings._backend

        assert first_backend is second_backend


# ── End-to-end: settings round-trip through portable backend ─────────────────
class TestPortableModeRoundTrip:
    def test_appsettings_methods_use_json_backend_when_portable(self, monkeypatch, tmp_path):
        """Sanity check that the existing AppSettings get_*/set_*
        methods route through the JSON backend cleanly when portable
        mode is active. If they fall through to a fresh QSettings
        instead, the settings would silently end up in the user's
        registry — a data-leak bug we want to catch in CI."""
        fake_exe = tmp_path / "SmartCitizen-Portable.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)
        AppSettings._backend = None
        AppSettings.setup_portable_backend_if_needed()

        # Round-trip via a real AppSettings public method.
        AppSettings.set_theme("dark")
        assert AppSettings.get_theme() == "dark"

        # Confirm it actually landed in the JSON file, not the registry.
        config_path = tmp_path.resolve() / "data" / "config.json"
        assert config_path.exists()
        import json
        with config_path.open() as f:
            data = json.load(f)
        assert data.get("theme") == "dark"
