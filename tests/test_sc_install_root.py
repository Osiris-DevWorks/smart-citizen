"""Unit tests for AppSettings.get_sc_install_root cross-check logic.

When SC_INSTALL_ROOT and GAME_INSTALL_PATH disagree (stale root from a
pre-1.4.2 installer), GAME_INSTALL_PATH wins. The comparison uses
os.path.normcase so drive-letter casing differences on Windows don't
cause spurious mismatches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic.

    Also stubs _read_legacy_installer_sc_directory() to None so this file's
    tests aren't at the mercy of the developer machine's actual registry.
    That helper reads the live HKCU tree with nothing else standing between
    it and get_sc_install_root() — on a machine that ever ran the pre-0.9
    installer (a real "SC Localization Editor" registry tree, `sc_directory`
    still pointing at a real install), get_sc_install_root() picks that up
    for real, and a test expecting "" (blocking auto-detection by mocking
    only Path.exists on the RSI default paths) goes red — that mock can't
    stop this step, since _path_ends_in_channel is a pure string check with
    no filesystem access. Tests that want to exercise this fallback path
    on purpose override the stub explicitly (see
    test_legacy_installer_registry_used_as_last_resort below).
    """
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    monkeypatch.setattr(
        AppSettings, "_read_legacy_installer_sc_directory", staticmethod(lambda: None)
    )
    yield AppSettings._backend
    AppSettings._backend = saved


class TestInstallRootCrossCheck:
    def test_matching_root_returns_unchanged(self, json_backend):
        """SC_INSTALL_ROOT matches GAME_INSTALL_PATH parent -- returns as-is."""
        root = r"D:\Games\StarCitizen"
        game_path = r"D:\Games\StarCitizen\LIVE"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        assert os.path.normcase(result) == os.path.normcase(root)

    def test_disagreeing_root_derives_from_game_path(self, json_backend):
        """SC_INSTALL_ROOT disagrees with GAME_INSTALL_PATH -- derives from game path."""
        stale_root = r"C:\OldLocation\StarCitizen"
        game_path = r"D:\NewLocation\StarCitizen\LIVE"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, stale_root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        expected = r"D:\NewLocation\StarCitizen"
        assert os.path.normcase(result) == os.path.normcase(expected)

    def test_only_sc_install_root_set(self, json_backend, monkeypatch):
        """Only SC_INSTALL_ROOT set (no GAME_INSTALL_PATH) -- returns SC_INSTALL_ROOT.

        Mocks _is_valid_sc_root to return True since this test exercises the
        cross-check logic, not path validation (which is tested separately).
        """
        root = r"E:\RSI\StarCitizen"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        # GAME_INSTALL_PATH not set (defaults to "")

        # Mock validation to return True -- test focuses on cross-check, not validation
        monkeypatch.setattr("src.utils.settings._is_valid_sc_root", lambda p: True)

        result = AppSettings.get_sc_install_root()
        assert result == root

    def test_neither_set_falls_through(self, json_backend, monkeypatch):
        """Neither setting set -- falls through to auto-detection.

        The drive-scan fallback is stubbed out directly (rather than faking
        Path.exists) so this doesn't depend on whether the test machine
        happens to have a real -- or stub -- SC install anywhere findable.
        """
        # Ensure neither key is set
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        monkeypatch.setattr("src.utils.settings._scan_common_sc_install_locations", lambda: None)

        result = AppSettings.get_sc_install_root()
        assert result == ""

    @pytest.mark.regression
    def test_legacy_installer_registry_used_as_last_resort(self, json_backend, monkeypatch):
        """Neither QSettings key is set, but the old installer's registry key
        (_read_legacy_installer_sc_directory) resolves to a channel-suffixed
        path -- get_sc_install_root() derives the root from it and persists
        SC_INSTALL_ROOT, same as get_game_install_path()'s equivalent step.

        Locks the resolution order: this fallback only fires after both
        QSettings keys come back empty, and before filesystem auto-detection.
        """
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        monkeypatch.setattr(
            AppSettings, "_read_legacy_installer_sc_directory",
            staticmethod(lambda: r"D:\Games\StarCitizen\LIVE"),
        )

        result = AppSettings.get_sc_install_root()
        assert os.path.normcase(result) == os.path.normcase(r"D:\Games\StarCitizen")
        # Persisted so the next call doesn't need the registry again.
        assert os.path.normcase(
            json_backend.value(AppSettings.SC_INSTALL_ROOT, "")
        ) == os.path.normcase(r"D:\Games\StarCitizen")

    def test_ptu_channel_recognized(self, json_backend):
        """GAME_INSTALL_PATH ending in PTU is recognized as a channel folder."""
        root = r"D:\Games\StarCitizen"
        game_path = r"D:\Games\StarCitizen\PTU"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        assert os.path.normcase(result) == os.path.normcase(root)

    def test_disagreeing_ptu_path_overrides(self, json_backend):
        """Stale root + fresh PTU game path -- derives from PTU path."""
        stale_root = r"C:\Old\StarCitizen"
        game_path = r"D:\New\StarCitizen\PTU"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, stale_root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        expected = r"D:\New\StarCitizen"
        assert os.path.normcase(result) == os.path.normcase(expected)

    def test_game_path_without_channel_suffix_used_as_root(self, json_backend, monkeypatch):
        """GAME_INSTALL_PATH that doesn't end in a channel name is treated
        as the root itself when SC_INSTALL_ROOT is not set.

        Mocks _is_valid_sc_root to return True since this test exercises the
        cross-check logic, not path validation (which is tested separately).
        """
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, r"D:\Games\StarCitizen")

        # Mock validation to return True -- test focuses on cross-check, not validation
        monkeypatch.setattr("src.utils.settings._is_valid_sc_root", lambda p: True)

        # Block filesystem auto-detection
        original_exists = Path.exists
        def _fake_exists(self):
            s = str(self)
            if "Roberts Space Industries" in s:
                return False
            return original_exists(self)
        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = AppSettings.get_sc_install_root()
        assert result == r"D:\Games\StarCitizen"


class TestSetInstallRootSwitchesLocation:
    """Regression: switching the install root to a new drive must stick.

    set_sc_install_root() used to refresh GAME_INSTALL_PATH by reading back
    through get_channel_install_path() -> get_sc_install_root(), whose
    cross-check compares the just-set root against the *still-stale* legacy
    GAME_INSTALL_PATH and reverts to the old location. The form field showed
    the new path while P4K extraction kept using the old one.
    """

    @pytest.mark.regression
    def test_switch_from_c_to_d_persists_new_root(self, json_backend):
        """Pick D: while a stale C: install is stored -> D: wins, not C:."""
        # Pre-existing default-location install on C:.
        json_backend.setValue(
            AppSettings.SC_INSTALL_ROOT,
            r"C:\Program Files\Roberts Space Industries\StarCitizen",
        )
        json_backend.setValue(
            AppSettings.GAME_INSTALL_PATH,
            r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE",
        )

        # User browses to their real install on D:.
        new_root = r"D:\Games\StarCitizen"
        AppSettings.set_sc_install_root(new_root)

        assert os.path.normcase(AppSettings.get_sc_install_root()) == os.path.normcase(
            new_root
        )
        # The legacy key (used by P4K extraction) must follow to D:, not C:.
        assert os.path.normcase(
            AppSettings.get_game_install_path()
        ) == os.path.normcase(r"D:\Games\StarCitizen\LIVE")

    @pytest.mark.regression
    def test_switch_respects_active_channel(self, json_backend):
        """The synced legacy path uses the active channel, not a hardcoded LIVE."""
        json_backend.setValue(
            AppSettings.SC_INSTALL_ROOT, r"C:\Old\StarCitizen"
        )
        json_backend.setValue(
            AppSettings.GAME_INSTALL_PATH, r"C:\Old\StarCitizen\LIVE"
        )
        AppSettings.set_active_channel("PTU")

        AppSettings.set_sc_install_root(r"D:\New\StarCitizen")

        assert os.path.normcase(
            AppSettings.get_game_install_path()
        ) == os.path.normcase(r"D:\New\StarCitizen\PTU")

    def test_empty_path_clears_legacy_key(self, json_backend):
        """Clearing the root clears the synced legacy path too."""
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, r"D:\Games\StarCitizen")
        json_backend.setValue(
            AppSettings.GAME_INSTALL_PATH, r"D:\Games\StarCitizen\LIVE"
        )
        AppSettings.set_sc_install_root("")
        assert json_backend.value(AppSettings.GAME_INSTALL_PATH, "") == ""


class TestIsValidScRoot:
    """Tests for the _is_valid_sc_root path validation helper."""

    def test_nonexistent_path_returns_false(self):
        """A path that doesn't exist should return False."""
        from src.utils.settings import _is_valid_sc_root
        assert _is_valid_sc_root(r"C:\Nonexistent\Path") is False

    def test_path_without_channel_subdirs_returns_false(self):
        """A directory without LIVE/PTU/etc. subdirs should return False."""
        from src.utils.settings import _is_valid_sc_root
        # Use a directory that exists but has no channel subdirs
        assert _is_valid_sc_root(r"C:\Windows") is False

    def test_stale_registry_value_rejected(self, tmp_path):
        """A stale value like 'SmartCitizen 1.4.1' should be rejected."""
        from src.utils.settings import _is_valid_sc_root
        # Create a directory that looks like a stale app install
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        assert _is_valid_sc_root(str(stale_dir)) is False

    def test_valid_root_with_live_subdir(self, tmp_path):
        """A root with LIVE subdir should be accepted."""
        from src.utils.settings import _is_valid_sc_root
        root = tmp_path / "StarCitizen"
        root.mkdir()
        (root / "LIVE").mkdir()
        assert _is_valid_sc_root(str(root)) is True

    def test_valid_root_with_multiple_channels(self, tmp_path):
        """A root with multiple channel subdirs should be accepted."""
        from src.utils.settings import _is_valid_sc_root
        root = tmp_path / "StarCitizen"
        root.mkdir()
        (root / "LIVE").mkdir()
        (root / "PTU").mkdir()
        assert _is_valid_sc_root(str(root)) is True

    def test_channel_path_not_root(self, tmp_path):
        """A channel path (ending in LIVE) is not a valid root."""
        from src.utils.settings import _is_valid_sc_root
        # _is_valid_sc_root checks for channel SUBDIRS, so a channel
        # path itself is NOT a valid root (it has no subdirs named LIVE)
        channel = tmp_path / "StarCitizen" / "LIVE"
        channel.mkdir(parents=True)
        assert _is_valid_sc_root(str(channel)) is False

    def test_invalid_path_string_returns_false(self):
        """An invalid path string should return False without crashing."""
        from src.utils.settings import _is_valid_sc_root
        assert _is_valid_sc_root("") is False
        assert _is_valid_sc_root("not_a_path|with invalid chars") is False

    @pytest.mark.regression
    def test_stale_sc_install_root_dropped_by_getter(self, tmp_path, json_backend, monkeypatch):
        """End-to-end: SC_INSTALL_ROOT pointing at a directory with no channel
        subdirs is rejected by get_sc_install_root() and falls through.

        Regression for the 'SmartCitizen 1.4.1' stale-registry bug."""
        # Simulate the stale registry value: a dir that exists but has no
        # channel subdirectories
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(stale_dir))
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        # Block auto-detection directly so this doesn't depend on whether
        # the test machine happens to have a real -- or stub -- SC install
        # anywhere the drive scan would find.
        monkeypatch.setattr("src.utils.settings._scan_common_sc_install_locations", lambda: None)

        result = AppSettings.get_sc_install_root()
        # The stale value must be rejected, falling through to '' (no auto-detect)
        assert result == ""

    @pytest.mark.regression
    def test_stale_game_install_path_dropped_by_getter(self, tmp_path, json_backend, monkeypatch):
        """End-to-end: GAME_INSTALL_PATH pointing at a stale dir (no channel subdirs)
        is rejected by get_sc_install_root() when SC_INSTALL_ROOT is unset."""
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, str(stale_dir))

        monkeypatch.setattr("src.utils.settings._scan_common_sc_install_locations", lambda: None)

        result = AppSettings.get_sc_install_root()
        # The stale value must be rejected, falling through to ''
        assert result == ""


class TestScanCommonScInstallLocations:
    """A tester's real install (a real Data.p4k, correctly detected via
    sc_install_root) turned up at ``E:\\Games\\Roberts Space Industries\\
    StarCitizen`` -- a shape neither of the old hardcoded C:\\-only
    candidates could ever match, so a portable build's first run (no saved
    settings yet) surfaced the "configure your install path" dialog even
    though a real install existed. This scans every local drive letter for
    a handful of common shapes instead of just two fixed C:\\ paths."""

    # The walk itself moved to install_scanner.iter_common_sc_install_locations
    # in 2.4, so the validator these patch is that module's
    # ``looks_like_sc_root``. This is NOT a first-hit consumer, despite an
    # earlier version of this comment claiming so (#385 review) --
    # ``_scan_common_sc_install_locations`` still ranks every matching
    # candidate through ``_pick_live_sc_install`` (newest Data.p4k wins,
    # scan order only breaks a tie), because "first hit" is exactly the
    # bug issue #370 fixed: an abandoned install on an earlier drive letter
    # beat the real one. None-when-nothing-matches and per-process caching
    # are unchanged. See ``test_sc_install_scan_picks_live.py`` for the
    # ranking algorithm itself, and
    # ``test_multiple_candidates_all_reach_the_ranker`` below for proof this
    # function actually hands every match to it rather than short-circuiting.

    def test_finds_install_at_a_matching_candidate(self, monkeypatch):
        import src.utils.settings as settings_mod
        from src.utils.settings import _scan_common_sc_install_locations

        # The scan result is cached in-memory for the process's lifetime
        # (see the function's own docstring) — reset it so an earlier
        # test's outcome in this same run can't leak in here.
        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        target = r"C:\Games\Roberts Space Industries\StarCitizen"
        monkeypatch.setattr(
            "src.utils.install_scanner.looks_like_sc_root",
            lambda p: os.path.normcase(str(p)) == os.path.normcase(target),
        )
        assert _scan_common_sc_install_locations() == target

    def test_returns_none_when_nothing_valid_anywhere(self, monkeypatch):
        import src.utils.settings as settings_mod
        from src.utils.settings import _scan_common_sc_install_locations

        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        monkeypatch.setattr(
            "src.utils.install_scanner.looks_like_sc_root", lambda p: False
        )
        assert _scan_common_sc_install_locations() is None

    def test_result_is_cached_for_process_lifetime(self, monkeypatch):
        """A second call must not re-scan — it should return the cached
        result even if the underlying validator's answer would now differ,
        proving the cache (not a fresh scan) is what answered."""
        import src.utils.settings as settings_mod
        from src.utils.settings import _scan_common_sc_install_locations

        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        target = r"C:\Games\Roberts Space Industries\StarCitizen"
        monkeypatch.setattr(
            "src.utils.install_scanner.looks_like_sc_root",
            lambda p: os.path.normcase(str(p)) == os.path.normcase(target),
        )
        assert _scan_common_sc_install_locations() == target
        # Flip the validator so a real re-scan would find nothing.
        monkeypatch.setattr(
            "src.utils.install_scanner.looks_like_sc_root", lambda p: False
        )
        assert _scan_common_sc_install_locations() == target

    def test_multiple_candidates_all_reach_the_ranker(self, monkeypatch):
        """Empirically the gap this diff closes: every existing test here
        engineers exactly one matching candidate, so nothing previously
        distinguished a real call to ``_pick_live_sc_install(candidates)``
        from a naive ``candidates[0]`` -- verified by temporarily patching
        line 135 to the latter during the #385 review and finding the whole
        suite, including every test in this class, still passed.

        Spies on the ranker directly instead of relying on real Data.p4k
        mtimes (there's no file on disk under either of these paths), and
        has the spy pick the LAST candidate rather than the first, so this
        fails distinctly from both "only the first hit ever arrives" and
        "the ranker is bypassed entirely" regressions.
        """
        import src.utils.settings as settings_mod
        from src.utils.settings import _scan_common_sc_install_locations

        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        # Two of the four documented subpaths, both under the same (real)
        # C:\ drive so no drive-existence mocking is needed.
        matching = {
            os.path.normcase(r"C:\Program Files\Roberts Space Industries\StarCitizen"),
            os.path.normcase(r"C:\Games\Roberts Space Industries\StarCitizen"),
        }
        monkeypatch.setattr(
            "src.utils.install_scanner.looks_like_sc_root",
            lambda p: os.path.normcase(str(p)) in matching,
        )
        seen_candidates = []

        def _spy_pick(candidates):
            seen_candidates.extend(candidates)
            return candidates[-1]

        monkeypatch.setattr(settings_mod, "_pick_live_sc_install", _spy_pick)

        result = _scan_common_sc_install_locations()

        assert len(seen_candidates) == 2, (
            "the ranker must see every matching candidate, not just the first"
        )
        assert result == seen_candidates[-1]

    def test_documented_subpaths_cover_default_and_secondary_drive_shapes(self):
        """Locks the exact candidate list down -- covers RSI Launcher's own
        default (Program Files, both bitness variants), a secondary drive
        kept in RSI's own shape, and one nested under a personal "Games"
        folder (the real shape a tester's install turned up in)."""
        from src.utils.install_scanner import COMMON_SC_SUBPATHS

        assert COMMON_SC_SUBPATHS == (
            r"Program Files\Roberts Space Industries\StarCitizen",
            r"Program Files (x86)\Roberts Space Industries\StarCitizen",
            r"Roberts Space Industries\StarCitizen",
            r"Games\Roberts Space Industries\StarCitizen",
        )


class TestGetScInstallRootUsesDriveScan:
    """Integration: get_sc_install_root()/get_game_install_path() must fall
    through to the drive scan (and persist what it finds) when nothing else
    resolves -- exactly the "portable build, fresh profile" case a tester
    hit."""

    def test_get_sc_install_root_persists_scan_result(self, json_backend, monkeypatch):
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        found_root = r"E:\Games\Roberts Space Industries\StarCitizen"
        monkeypatch.setattr(
            "src.utils.settings._scan_common_sc_install_locations", lambda: found_root
        )
        result = AppSettings.get_sc_install_root()

        assert result == found_root
        # Persisted -- a subsequent call doesn't need the scan to run again.
        assert json_backend.value(AppSettings.SC_INSTALL_ROOT, "") == found_root

    def test_get_game_install_path_persists_scan_result_with_channel(self, json_backend, monkeypatch, tmp_path):
        """The channel subdir must actually exist for the result to persist
        (see the sibling "not persisted" test below) -- a real directory on
        disk, not a fake path, so ``Path(result).is_dir()`` is genuinely
        true."""
        found_root = tmp_path / "StarCitizen"
        (found_root / "PTU").mkdir(parents=True)
        # Patch BEFORE touching active_channel: set_active_channel() itself
        # queries get_sc_install_root() internally (to sync the legacy path)
        # -- with the patch not yet in place, that inner call would find
        # this machine's own real (or stub) install and persist THAT,
        # clobbering the very state this test is trying to control.
        monkeypatch.setattr(
            "src.utils.settings._scan_common_sc_install_locations", lambda: str(found_root)
        )
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)
        AppSettings.set_active_channel("PTU")

        result = AppSettings.get_game_install_path()

        expected = str(found_root / "PTU")
        assert result == expected
        assert json_backend.value(AppSettings.GAME_INSTALL_PATH, "") == expected

    def test_scan_result_not_persisted_when_active_channel_folder_absent(self, json_backend, monkeypatch, tmp_path):
        """The scan only proves SOME channel folder exists at this root, not
        the active one -- if the active channel isn't actually installed
        there, the guessed path is still returned (best guess) but must not
        be cached, or the next read would trust a path that doesn't exist
        instead of re-scanning.

        Sets ACTIVE_CHANNEL directly rather than via set_active_channel(),
        which has its own separate, unconditional GAME_INSTALL_PATH sync —
        this test isolates get_game_install_path()'s own guard."""
        found_root = tmp_path / "StarCitizen"
        found_root.mkdir()  # root exists, but no "PTU" subfolder inside it
        monkeypatch.setattr(
            "src.utils.settings._scan_common_sc_install_locations", lambda: str(found_root)
        )
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)
        json_backend.setValue(AppSettings.ACTIVE_CHANNEL, "PTU")

        result = AppSettings.get_game_install_path()

        expected = str(found_root / "PTU")
        assert result == expected
        assert json_backend.value(AppSettings.GAME_INSTALL_PATH, "") == ""

    def test_no_scan_result_returns_empty(self, json_backend, monkeypatch):
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)
        monkeypatch.setattr("src.utils.settings._scan_common_sc_install_locations", lambda: None)

        assert AppSettings.get_sc_install_root() == ""
        assert AppSettings.get_game_install_path() == ""
