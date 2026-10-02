"""Unit tests for AppSettings.get_sc_install_root cross-check logic.

When SC_INSTALL_ROOT and GAME_INSTALL_PATH disagree (stale root from a
pre-1.4.2 installer), GAME_INSTALL_PATH wins. The comparison uses
os.path.normcase so drive-letter casing differences on Windows don't
cause spurious mismatches.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
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


# tests/conftest.py's autouse no_real_install_detection_inputs keeps every test
# here off the real launcher log and the one-folder drive listing, and
# TestScanUsesLauncherLog patches its own inputs in. The common-path walk is
# still real, so a test that resolves an install root with nothing saved
# patches the walk or _scan_common_sc_install_locations itself.


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
    # candidate through ``_pick_live_sc_install`` (a current active-channel
    # Data.p4k first, then the newest Data.p4k; scan order only breaks a
    # tie), because "first hit" is exactly the
    # bug issue #370 fixed: an abandoned install on an earlier drive letter
    # beat the real one. None-when-nothing-matches and per-process caching
    # are unchanged. See ``test_sc_install_scan_picks_live.py`` for the
    # ranking algorithm itself, and
    # ``test_multiple_candidates_all_reach_the_ranker`` below for proof this
    # function actually hands every match to it rather than short-circuiting.

    @pytest.fixture(autouse=True)
    def live_is_active(self, monkeypatch):
        """The scan reads the active channel. Pin it so these tests never read
        the developer's real settings node."""
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))

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

        def _spy_pick(candidates, channel):
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


def _fake_install(tmp_path, *parts, ages=None):
    """A minimal real-looking install at <tmp_path>/<parts>, with a Data.p4k in
    each channel of *ages* (``{channel: days old}``, e.g. ``{"LIVE": 3, "PTU": 0}``).
    The default is a LIVE one of no particular age."""
    root = tmp_path.joinpath(*parts)
    for channel, age_days in (ages or {"LIVE": None}).items():
        p4k = root / channel / "Data.p4k"
        p4k.parent.mkdir(parents=True)
        p4k.write_bytes(b"x" * 16)
        if age_days is not None:
            stamp = time.time() - age_days * 24 * 3600
            os.utime(p4k, (stamp, stamp))
    return root


def _launcher_log(tmp_path, *mentions):
    """A launcher log in the real format (one JSON-ish line per event, backslashes
    escaped) naming each ``(root, "YYYY-MM-DD HH:MM:SS.mmm")`` mention."""
    lines = []
    for root, stamp in mentions:
        escaped = str(root).replace("\\", "\\\\")
        lines.append(
            '{ "t":"%s", "[main][info] ": "[Pipeline] Verifying Star Citizen LIVE '
            '4.10.0-live.12572603 at %s (type: verify, forceDP: false)"  },'
            % (stamp, escaped)
        )
    log = tmp_path / "log.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


class TestScanUsesLauncherLog:
    """First-run detection also reads the RSI Launcher log, which names the install
    the launcher maintains wherever the player put it. A fixed list of folder
    shapes can never cover that: an install under ``E:\\Other Games\\Roberts Space
    Industries\\StarCitizen`` hit the "Star Citizen Path Required" dialog on a
    portable's first run even though the launcher had been verifying it for weeks."""

    @pytest.fixture
    def scan(self, monkeypatch):
        """Run the real scan with the common-path walk replaced by ``common``, the
        launcher log replaced by the file ``log`` (None = no log), and the
        one-folder probe replaced by ``shallow``."""
        import src.utils.install_scanner as scanner
        import src.utils.settings as settings_mod

        def _run(*, common=(), log=None, shallow=(), channel="LIVE"):
            monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
            monkeypatch.setattr(
                settings_mod.AppSettings, "get_active_channel", staticmethod(lambda: channel)
            )
            monkeypatch.setattr(
                settings_mod, "iter_common_sc_install_locations",
                lambda drives=None: iter([Path(c) for c in common]),
            )
            monkeypatch.setattr(
                settings_mod, "read_launcher_installs",
                lambda log_path=None: (
                    scanner.read_launcher_installs(log) if log else ({}, False)
                ),
            )
            monkeypatch.setattr(
                settings_mod, "iter_shallow_sc_install_locations",
                lambda drives=None: iter([Path(c) for c in shallow]),
            )
            return settings_mod._scan_common_sc_install_locations()

        return _run

    @pytest.fixture
    def ranked(self, monkeypatch):
        """Record what reaches _pick_live_sc_install, which then picks the first."""
        import src.utils.settings as settings_mod

        seen = []
        monkeypatch.setattr(
            settings_mod, "_pick_live_sc_install",
            lambda c, channel: seen.extend(c) or c[0],
        )
        return seen

    def test_finds_an_install_in_a_custom_folder_the_log_names(self, tmp_path, scan):
        root = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        log = _launcher_log(tmp_path, (root, "2026-09-30 21:01:02.003"))
        assert scan(log=log) == str(root)

    def test_install_the_log_names_but_is_gone_is_ignored(self, tmp_path, scan):
        gone = tmp_path / "Other Games" / "Roberts Space Industries" / "StarCitizen"
        log = _launcher_log(tmp_path, (gone, "2026-09-30 21:01:02.003"))
        assert scan(log=log) is None

    def test_a_missing_launcher_log_is_tolerated(self, tmp_path, scan):
        common = _fake_install(tmp_path, "Games", "Roberts Space Industries", "StarCitizen")
        assert scan(common=[common], log=tmp_path / "missing.log") == str(common)

    def test_root_found_both_ways_reaches_the_ranker_once(self, tmp_path, scan, ranked):
        both = _fake_install(tmp_path, "Roberts Space Industries", "StarCitizen")
        only_common = _fake_install(tmp_path, "Games", "Roberts Space Industries", "StarCitizen")
        log = _launcher_log(tmp_path, (both, "2026-09-30 21:01:02.003"))
        scan(common=[both, only_common], log=log)
        assert ranked == [str(both), str(only_common)]

    def test_the_same_root_in_different_casing_reaches_the_ranker_once(
        self, tmp_path, scan, ranked
    ):
        """The log keeps whatever casing the launcher wrote, and Windows paths are
        case-insensitive, so the dedup has to be too."""
        both = _fake_install(tmp_path, "Roberts Space Industries", "StarCitizen")
        logged = Path(str(both).lower())
        log = _launcher_log(tmp_path, (logged, "2026-09-30 21:01:02.003"))
        scan(common=[both], log=log)
        assert ranked == [str(logged)]

    def test_most_recently_mentioned_install_is_ranked_first(self, tmp_path, scan, ranked):
        """The launcher appends to its log, so the newer mention comes last. It
        still has to reach the ranker first, where it wins a Data.p4k tie."""
        old = _fake_install(tmp_path, "Old", "StarCitizen")
        new = _fake_install(tmp_path, "New", "StarCitizen")
        log = _launcher_log(
            tmp_path, (old, "2026-08-01 10:00:00.000"), (new, "2026-09-30 21:01:02.003")
        )
        scan(log=log)
        assert ranked == [str(new), str(old)]

    def test_launcher_named_install_is_ranked_ahead_of_common_path_hits(
        self, tmp_path, scan, ranked
    ):
        """A tie on Data.p4k age goes to the install the launcher last used."""
        launcher = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        common = _fake_install(tmp_path, "Games", "Roberts Space Industries", "StarCitizen")
        log = _launcher_log(tmp_path, (launcher, "2026-09-30 21:01:02.003"))
        scan(common=[common], log=log)
        assert ranked == [str(launcher), str(common)]

    def test_the_one_folder_probe_finds_what_the_log_does_not_name(self, tmp_path, scan):
        """The launcher's logs can be cleared or rotated, so the log is not always
        there to name a custom library folder."""
        root = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        assert scan(log=tmp_path / "missing.log", shallow=[root]) == str(root)

    def test_the_one_folder_hits_always_join_the_ranking(self, tmp_path, scan, ranked):
        """Neither the log nor a common path proves where the live install is,
        so the probe's hits are ranked with theirs, after them in scan order."""
        common = _fake_install(tmp_path, "Games", "Roberts Space Industries", "StarCitizen")
        logged = _fake_install(tmp_path, "Other Games", "StarCitizen")
        shallow = _fake_install(tmp_path, "Elsewhere", "StarCitizen")
        log = _launcher_log(tmp_path, (logged, "2026-09-30 21:01:02.003"))
        scan(common=[common], log=log, shallow=[shallow])
        assert ranked == [str(logged), str(common), str(shallow)]

    def test_a_folder_found_both_ways_reaches_the_ranker_once(self, tmp_path, scan, ranked):
        """The probe overlaps the common paths: Program Files and RSI's own
        folder are both one level below a drive's top."""
        both = _fake_install(tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen")
        scan(common=[both], shallow=[Path(str(both).upper())])
        assert ranked == [str(both)]

    def test_a_stale_install_at_a_common_path_loses_to_a_newer_one_folder_install(
        self, tmp_path, scan
    ):
        """The #370 shape with no launcher log to settle it: an abandoned install
        whose Data.p4k stopped being patched sits at a common path, and the live
        one is in a custom library folder. The newer Data.p4k wins."""
        stale = _fake_install(tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen")
        year_ago = time.time() - 365 * 24 * 3600
        os.utime(stale / "LIVE" / "Data.p4k", (year_ago, year_ago))
        live = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        assert scan(common=[stale], shallow=[live]) == str(live)

    def test_a_log_that_only_names_a_shell_does_not_stop_the_probe(self, tmp_path, scan):
        """The log can still mention a folder the game has since left, with
        Bin64 but no Data.p4k."""
        shell = tmp_path / "Old Games" / "StarCitizen"
        (shell / "LIVE" / "Bin64").mkdir(parents=True)
        live = _fake_install(tmp_path, "Other Games", "StarCitizen")
        log = _launcher_log(tmp_path, (shell, "2026-09-30 21:01:02.003"))
        assert scan(log=log, shallow=[live]) == str(live)

    def test_a_leftover_shell_does_not_stop_the_one_folder_probe(self, tmp_path, scan):
        """The game moved from Program Files to a custom folder and the old
        channel folder stayed behind with no Data.p4k. The common-path walk
        accepts that shell. It must not get saved as the install."""
        shell = tmp_path / "Program Files" / "Roberts Space Industries" / "StarCitizen"
        (shell / "LIVE" / "USER").mkdir(parents=True)
        real = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        assert scan(common=[shell], shallow=[real]) == str(real)

    def test_a_shell_and_the_one_folder_hit_both_reach_the_ranker(self, tmp_path, scan, ranked):
        """Nothing is filtered out before the ranker, so the support log it
        writes names every candidate."""
        shell = tmp_path / "Program Files" / "Roberts Space Industries" / "StarCitizen"
        (shell / "LIVE").mkdir(parents=True)
        real = _fake_install(tmp_path, "Other Games", "StarCitizen")
        scan(common=[shell], shallow=[real])
        assert ranked == [str(shell), str(real)]

    def test_a_root_holding_the_active_channel_beats_a_newer_library_without_it(
        self, tmp_path, scan
    ):
        """The launcher can keep a channel in its own library folder. During a
        PTU cycle that folder's Data.p4k is the newest, but with LIVE active a
        root without LIVE would leave every LIVE path pointing nowhere."""
        live = _fake_install(
            tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen",
            ages={"LIVE": 3},
        )
        ptu = _fake_install(tmp_path, "SC PTU", "StarCitizen", ages={"PTU": 0})
        assert scan(common=[live], shallow=[ptu]) == str(live)

    def test_the_active_channel_decides_which_library_wins(self, tmp_path, scan):
        live = _fake_install(
            tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen",
            ages={"LIVE": 0},
        )
        ptu = _fake_install(tmp_path, "SC PTU", "StarCitizen", ages={"PTU": 3})
        assert scan(common=[live], shallow=[ptu], channel="PTU") == str(ptu)

    def test_a_log_named_library_without_the_active_channel_loses_to_one_with_it(
        self, tmp_path, scan
    ):
        """The log naming a PTU-only library says nothing about where LIVE is."""
        ptu = _fake_install(tmp_path, "SC PTU", "StarCitizen", ages={"PTU": 0})
        live = _fake_install(tmp_path, "Other Games", "StarCitizen", ages={"LIVE": 3})
        log = _launcher_log(tmp_path, (ptu, "2026-09-30 21:01:02.003"))
        assert scan(log=log, shallow=[live]) == str(live)

    def test_an_abandoned_active_channel_does_not_beat_the_live_library(self, tmp_path, scan):
        """#370 again, through the channel preference: a leftover install still
        holds a LIVE Data.p4k nobody has patched for over a year, while the
        library the launcher maintains holds only PTU. The leftover's LIVE is
        not current, so it gets no preference and the live library wins."""
        leftover = _fake_install(
            tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen",
            ages={"LIVE": 400},
        )
        library = _fake_install(
            tmp_path, "Roberts Space Industries", "StarCitizen", ages={"PTU": 1}
        )
        log = _launcher_log(tmp_path, (library, "2026-09-30 21:01:02.003"))
        assert scan(common=[leftover], log=log) == str(library)

    def test_the_active_channel_s_own_age_ranks_roots_that_both_hold_it(self, tmp_path, scan):
        """An old library kept its PTU patched, but its LIVE was left behind two
        months ago (recent enough to still count as current) when LIVE moved to
        a new library. With LIVE active, the newest Data.p4k in any channel
        would pick the old library; LIVE's own age picks the new one."""
        old = _fake_install(
            tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen",
            ages={"LIVE": 60, "PTU": 0},
        )
        new = _fake_install(tmp_path, "Other Games", "StarCitizen", ages={"LIVE": 3})
        assert scan(common=[old], shallow=[new]) == str(new)

    def test_the_cached_pick_is_kept_per_channel(self, tmp_path, scan, monkeypatch):
        """The ranking depends on the active channel, so a pick cached while
        LIVE was active must not answer for PTU (Import Settings can change the
        channel and then re-detect in the same session)."""
        import src.utils.settings as settings_mod

        live = _fake_install(tmp_path, "Games", "StarCitizen", ages={"LIVE": 3})
        ptu = _fake_install(tmp_path, "SC PTU", "StarCitizen", ages={"PTU": 0})
        assert scan(common=[live], shallow=[ptu]) == str(live)
        monkeypatch.setattr(
            settings_mod.AppSettings, "get_active_channel", staticmethod(lambda: "PTU")
        )
        assert settings_mod._scan_common_sc_install_locations() == str(ptu)

    def test_the_support_log_names_the_pick_and_every_candidate_with_its_dates(
        self, tmp_path, scan, caplog
    ):
        """The audit trail for a wrong pick: the chosen root, then each candidate
        in rank order (the reverse of scan order here) with its newest Data.p4k
        and the active channel's own, the PTU-only library's missing LIVE
        spelled out."""
        live = _fake_install(
            tmp_path, "Program Files", "Roberts Space Industries", "StarCitizen",
            ages={"LIVE": 3},
        )
        ptu = _fake_install(tmp_path, "SC PTU", "StarCitizen", ages={"PTU": 0})
        with caplog.at_level("WARNING", logger="src.utils.settings"):
            scan(common=[ptu], shallow=[live])

        def day(root, channel):
            stamp = (root / channel / "Data.p4k").stat().st_mtime
            return datetime.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")

        live_day, ptu_day = day(live, "LIVE"), day(ptu, "PTU")
        assert live_day != ptu_day
        message = caplog.text
        assert "Multiple Star Citizen installs found" in message
        assert f"using {live} (a current LIVE first" in message
        assert (
            f"{live} (Data.p4k {live_day}, LIVE {live_day}), "
            f"{ptu} (Data.p4k {ptu_day}, LIVE none)"
        ) in message

    @staticmethod
    def _stamp_p4k(monkeypatch, root, stamp):
        """Make every Data.p4k under *root* report ``st_mtime == stamp``."""
        from types import SimpleNamespace

        real_stat = Path.stat

        def stat(self, *args, **kwargs):
            if self.name == "Data.p4k" and str(self).startswith(str(root)):
                return SimpleNamespace(st_mtime=stamp)
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)

    def test_a_data_p4k_dated_before_1970_does_not_break_detection(
        self, tmp_path, scan, monkeypatch, caplog
    ):
        """A copy or restore tool that dropped timestamps leaves a pre-epoch
        mtime. It cannot be compared or printed on Windows, so it reads as
        missing and the support log still gets written."""
        undated = _fake_install(tmp_path, "A", "StarCitizen")
        current = _fake_install(tmp_path, "B", "StarCitizen")
        self._stamp_p4k(monkeypatch, undated, -86400.0)
        with caplog.at_level("WARNING", logger="src.utils.settings"):
            assert scan(common=[undated, current]) == str(current)
        assert f"{undated} (Data.p4k none" in caplog.text

    def test_a_data_p4k_dated_beyond_any_calendar_does_not_break_the_support_log(
        self, tmp_path, scan, monkeypatch, caplog
    ):
        """A wrong clock can leave a stamp no date can print (year 33658 here).
        The log says "unknown" for it and detection still completes."""
        bogus = _fake_install(tmp_path, "A", "StarCitizen")
        normal = _fake_install(tmp_path, "B", "StarCitizen")
        self._stamp_p4k(monkeypatch, bogus, 1e12)
        with caplog.at_level("WARNING", logger="src.utils.settings"):
            assert scan(common=[bogus, normal]) in (str(bogus), str(normal))
        assert f"{bogus} (Data.p4k unknown" in caplog.text

    def test_a_no_install_profile_walks_the_drives_once_across_channel_switches(
        self, monkeypatch
    ):
        """Switching channels re-runs detection when nothing is saved. The walk
        over the drives, the log and the probe must not repeat each time."""
        import src.utils.settings as settings_mod

        calls = {"common": 0, "log": 0, "probe": 0}

        def counted(name, result):
            def fn(*args, **kwargs):
                calls[name] += 1
                return result
            return fn

        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        monkeypatch.setattr(settings_mod, "iter_common_sc_install_locations", counted("common", iter(())))
        monkeypatch.setattr(settings_mod, "read_launcher_installs", counted("log", ({}, False)))
        monkeypatch.setattr(settings_mod, "iter_shallow_sc_install_locations", counted("probe", iter(())))
        channel = {"active": "LIVE"}
        monkeypatch.setattr(
            settings_mod.AppSettings, "get_active_channel", staticmethod(lambda: channel["active"])
        )

        for active in ("LIVE", "PTU", "LIVE", "PTU"):
            channel["active"] = active
            assert settings_mod._scan_common_sc_install_locations() is None
        assert calls == {"common": 1, "log": 1, "probe": 1}

    @staticmethod
    def _install_and_junction(tmp_path):
        r"""The game moved off C: the usual way: the data sits at D:\StarCitizen
        and a junction at its old Program Files path points to it. Returns
        ``(real, link)``, or skips where a junction cannot be made."""
        import subprocess

        real = _fake_install(tmp_path, "D", "StarCitizen")
        link = tmp_path / "C" / "Program Files" / "Roberts Space Industries" / "StarCitizen"
        link.parent.mkdir(parents=True)
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real)], capture_output=True
        )
        if made.returncode != 0 or not link.exists():
            pytest.skip("cannot create a junction here")
        return real, link

    def test_a_junction_to_an_install_is_not_a_second_install(self, tmp_path, scan, ranked):
        """The common walk sees the junction, the probe sees the real folder."""
        real, link = self._install_and_junction(tmp_path)
        scan(common=[link], shallow=[real])
        assert ranked == [str(link)]

    @pytest.mark.parametrize("source", ["common", "log", "shallow"])
    def test_a_junction_and_its_target_from_one_source_count_once(
        self, tmp_path, scan, ranked, source
    ):
        """Both can come from the same source: two common paths, a launcher log
        that mentions the install before and after the move, or a top-level
        junction that the probe lists twice."""
        real, link = self._install_and_junction(tmp_path)
        if source == "log":
            log = _launcher_log(
                tmp_path, (link, "2026-08-01 10:00:00.000"), (real, "2026-09-30 21:01:02.003")
            )
            scan(log=log)
        else:
            scan(**{source: [link, real]})
        assert len(ranked) == 1

    def test_the_same_root_twice_from_one_source_reaches_the_ranker_once(
        self, tmp_path, scan, ranked
    ):
        """The within-source dedup does not depend on junctions: spellings that
        differ only in casing, both from the common walk."""
        root = _fake_install(tmp_path, "Roberts Space Industries", "StarCitizen")
        scan(common=[root, Path(str(root).upper())])
        assert ranked == [str(root)]

    def test_the_ranker_stats_each_candidate_once(self, tmp_path, monkeypatch):
        """Ranking and the support log report the same Data.p4k dates, so the
        files are read once per candidate, not once for each purpose."""
        import src.utils.settings as settings_mod

        a = _fake_install(tmp_path, "A", "StarCitizen")
        b = _fake_install(tmp_path, "B", "StarCitizen")
        reads = []
        real = settings_mod._p4k_mtimes
        monkeypatch.setattr(
            settings_mod, "_p4k_mtimes", lambda root: reads.append(root) or real(root)
        )
        settings_mod._pick_live_sc_install([str(a), str(b)], channel="LIVE")
        assert sorted(reads) == sorted([str(a), str(b)])

    def test_fresh_profile_gets_the_log_named_install_and_keeps_it(
        self, tmp_path, json_backend, monkeypatch
    ):
        """End to end through get_sc_install_root(): nothing saved, no installer
        registry value, only the launcher log at its default place under
        %APPDATA% knows where the game is."""
        import src.utils.install_scanner as scanner
        import src.utils.settings as settings_mod

        root = _fake_install(tmp_path, "Other Games", "Roberts Space Industries", "StarCitizen")
        appdata = tmp_path / "appdata"
        log_dir = appdata / "rsilauncher" / "logs"
        log_dir.mkdir(parents=True)
        _launcher_log(log_dir, (root, "2026-09-30 21:01:02.003"))
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        monkeypatch.setattr(
            settings_mod, "iter_common_sc_install_locations", lambda drives=None: iter(())
        )
        # The real reader, undoing the autouse stub, so the default log path is used.
        monkeypatch.setattr(settings_mod, "read_launcher_installs", scanner.read_launcher_installs)

        assert AppSettings.get_sc_install_root() == str(root)
        assert AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "") == str(root)

    def test_fresh_profile_without_a_log_gets_the_one_folder_install(
        self, tmp_path, json_backend, monkeypatch
    ):
        """End to end with no launcher log: the one-folder probe over a fake
        drive finds the install and it is saved."""
        import src.utils.install_scanner as scanner
        import src.utils.settings as settings_mod

        drive = tmp_path / "drive"
        root = _fake_install(drive, "Other Games", "Roberts Space Industries", "StarCitizen")
        monkeypatch.setattr(settings_mod, "_sc_scan_cache", settings_mod._SC_SCAN_UNSET)
        monkeypatch.setattr(
            settings_mod, "iter_common_sc_install_locations", lambda drives=None: iter(())
        )
        monkeypatch.setattr(
            settings_mod, "iter_shallow_sc_install_locations",
            lambda drives=None: scanner.iter_shallow_sc_install_locations([str(drive)]),
        )

        assert AppSettings.get_sc_install_root() == str(root)
        assert AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "") == str(root)


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
