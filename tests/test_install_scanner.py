"""Duplicate-install scanner (2.4) — `src/utils/install_scanner.py`.

Everything here runs against fabricated install trees under `tmp_path`: no
real Star Citizen install, no QSettings registry, no Qt. That is the whole
reason the module is settings-free — the GUI half passes the configured root
in, so the scan itself is pure I/O over explicit inputs.

Coverage:

* per-install reads (channels, build manifest, apply watermark, user.cfg)
* the leftover case: a channel folder with no `Data.p4k`, which the looser
  `settings._is_valid_sc_root` still accepts and which silently swallows
  every apply
* RSI Launcher log parsing, including the trailing prose the launcher glues
  onto its logged paths
* the verdicts, above all `mismatch` — configured install != the one the
  launcher starts, which is the bug this whole feature exists to catch
* the `SC_CHANNELS` / `AppSettings.AVAILABLE_CHANNELS` sync contract
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from src.utils import install_scanner as scanner
from src.utils.install_scanner import (
    APPLY_STAMP_MARKER,
    SC_CHANNELS,
    VERDICT_MATCH,
    VERDICT_MATCH_LEFTOVER,
    VERDICT_MISMATCH,
    VERDICT_NONE,
    VERDICT_SINGLE,
    VERDICT_SINGLE_ELSEWHERE,
    VERDICT_SINGLE_LEFTOVER,
    VERDICT_UNCONFIGURED,
    VERDICT_UNKNOWN_ACTIVE,
    channel_dirs,
    looks_like_sc_root,
    parse_launcher_log,
    read_install,
    resolve_logged_root,
    scan_installs,
    version_sort_key,
)

pytestmark = [pytest.mark.unit]


# -- Fixtures ----------------------------------------------------------------

def make_install(
    root: Path,
    channel: str = "LIVE",
    version: str = "4.9.188.23497",
    *,
    game_data: bool = True,
    applied_language: str | None = None,
    stamp: str | None = None,
    user_cfg_language: str | None = None,
) -> Path:
    """Build a fake Star Citizen install tree and return its root.

    Always lays down ``Bin64\\``, because a real install keeps it even after
    its game data is gone -- that is what separates a genuinely stale Star
    Citizen folder (worth reporting) from any other directory that happens to
    have channel-named subfolders (not worth reporting). Tests that need a
    non-install tree build it by hand instead.
    """
    channel_dir = root / channel
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "Bin64").mkdir(exist_ok=True)
    if game_data:
        (channel_dir / "Data.p4k").write_bytes(b"p4k" * 100)
    if version:
        (channel_dir / "build_manifest.id").write_text(json.dumps({
            "Data": {
                "Version": version,
                "Branch": "sc-alpha-4.9.0",
                "BuildDateStamp": "Wed Jul 29 2026",
            }
        }), encoding="utf-8")
    if user_cfg_language:
        (channel_dir / "user.cfg").write_text(
            f"g_language = {user_cfg_language}\n", encoding="utf-8"
        )
    if applied_language:
        loc = channel_dir / "data" / "Localization" / applied_language
        loc.mkdir(parents=True, exist_ok=True)
        body = "some_key=some value\n"
        if stamp:
            body += f"Frontend_PU_Version=Alpha 4.9{APPLY_STAMP_MARKER}{stamp}\n"
        (loc / "global.ini").write_text(body, encoding="utf-8-sig")
    return root


def launcher_log(path: Path, entries) -> Path:
    """Write a log in the RSI Launcher's own JSON-escaped line format.

    *entries* is a sequence of ``(timestamp, install_root)``. The trailing
    ``(type: install, ...)`` prose is included on purpose — recovering the
    real path out from under it is part of what's being tested.
    """
    lines = []
    for stamp, root in entries:
        escaped = str(root).replace("\\", "\\\\")
        lines.append(
            '{ "t":"%s", "[main][info] ": "[Pipeline] Installing Star Citizen '
            'LIVE 4.9.188 at %s (type: install, forceDP: false)"  },'
            % (stamp, escaped)
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -- Channel / install reads -------------------------------------------------

class TestReadInstall:
    def test_reads_channels_version_and_size(self, tmp_path):
        root = make_install(tmp_path / "SC", "LIVE", "4.9.188.23497")
        make_install(root, "PTU", "4.9.190.00001")

        install = read_install(root)

        assert install is not None
        assert install.channel_names == ["LIVE", "PTU"]
        assert install.has_game_data
        assert not install.is_leftover
        assert install.newest_version == "4.9.190.00001"
        assert install.channels[0].branch == "sc-alpha-4.9.0"
        assert install.channels[0].build_date == "Wed Jul 29 2026"
        assert install.channels[0].game_data_size > 0

    def test_channels_come_back_in_declared_order_not_filesystem_order(self, tmp_path):
        root = tmp_path / "SC"
        for channel in ("PTU", "LIVE", "HOTFIX"):
            make_install(root, channel)
        assert read_install(root).channel_names == ["LIVE", "PTU", "HOTFIX"]

    def test_non_install_directory_returns_none(self, tmp_path):
        (tmp_path / "SmartCitizen 1.4.1").mkdir()
        assert read_install(tmp_path / "SmartCitizen 1.4.1") is None
        assert read_install(tmp_path / "does-not-exist") is None

    def test_missing_manifest_is_not_an_error(self, tmp_path):
        root = make_install(tmp_path / "SC", version="")
        install = read_install(root)
        assert install.newest_version == ""
        assert install.has_game_data

    def test_corrupt_manifest_is_not_an_error(self, tmp_path):
        root = make_install(tmp_path / "SC")
        (root / "LIVE" / "build_manifest.id").write_text("{not json", encoding="utf-8")
        assert read_install(root).newest_version == ""

    def test_reads_user_cfg_language(self, tmp_path):
        root = make_install(tmp_path / "SC", user_cfg_language="german")
        assert read_install(root).channels[0].user_cfg_language == "german"

    def test_last_user_cfg_language_assignment_wins(self, tmp_path):
        root = make_install(tmp_path / "SC", user_cfg_language="english")
        (root / "LIVE" / "user.cfg").write_text(
            'g_language = english\nG_Language = "french"\n', encoding="utf-8"
        )
        assert read_install(root).channels[0].user_cfg_language == "french"


class TestSmartCitizenDataIsNotAnInstall:
    r"""Regression: a drive scan reported the user's own Smart Citizen data
    folders as Star Citizen installs.

    Smart Citizen nests its per-channel data as
    ``{user_data_root}\{LIVE|PTU|...}\`` (0.9.3+), so every data root and
    every portable build's ``data\`` directory has channel-named subfolders
    and passed the original channel-names-only check. Discovery now needs
    positive Star Citizen evidence.
    """

    @staticmethod
    def make_smart_citizen_data(root: Path, channels=("LIVE", "PTU")) -> Path:
        """The real shape: user.ini / cache / backups under each channel, and
        at least one channel left completely empty."""
        for index, channel in enumerate(channels):
            channel_dir = root / channel
            channel_dir.mkdir(parents=True, exist_ok=True)
            if index == 0:
                (channel_dir / "cache").mkdir()
                (channel_dir / "backups").mkdir()
                (channel_dir / "user.ini").write_text("key=value\n", encoding="utf-8")
        return root

    def test_smart_citizen_data_root_is_not_reported(self, tmp_path):
        data_root = self.make_smart_citizen_data(tmp_path / "Smart Citizen")
        assert read_install(data_root) is None
        assert not scanner.is_sc_install_root(data_root)

    def test_portable_build_data_dir_is_not_reported(self, tmp_path):
        data_root = self.make_smart_citizen_data(
            tmp_path / "SmartCitizen-Portable-v2.4.0" / "data",
            channels=("LIVE", "PTU", "HOTFIX", "TECH-PREVIEW"),
        )
        assert read_install(data_root) is None

    def test_deep_scan_skips_it_and_still_finds_a_real_install_below(self, tmp_path):
        """It must not merely be filtered out later -- if the walk stopped
        there it would hide anything genuinely nested underneath."""
        self.make_smart_citizen_data(tmp_path / "Smart Citizen")
        real = make_install(tmp_path / "Smart Citizen" / "Games" / "StarCitizen")
        found, _ = scanner.deep_scan_roots(drives=[str(tmp_path)])
        assert found == [real]

    def test_scan_report_excludes_it_end_to_end(self, tmp_path):
        data_root = self.make_smart_citizen_data(tmp_path / "Smart Citizen")
        real = make_install(tmp_path / "StarCitizen")
        report = scan_installs(
            extra_roots=[data_root, real],
            launcher_log=tmp_path / "none.log", drives=[],
        )
        assert [i.root for i in report.installs] == [real]

    def test_the_old_loose_check_still_matched_it(self, tmp_path):
        """Pins down what actually went wrong, so the loose predicate can't
        quietly be swapped back in at a discovery site."""
        data_root = self.make_smart_citizen_data(tmp_path / "Smart Citizen")
        assert looks_like_sc_root(data_root)
        assert not scanner.is_sc_install_root(data_root)

    @pytest.mark.parametrize("marker", scanner.SC_CHANNEL_MARKERS)
    def test_any_single_marker_qualifies_a_channel(self, tmp_path, marker):
        """Data.p4k alone would be too strict: it would hide the stale-install
        case this feature exists to catch."""
        channel = tmp_path / "StarCitizen" / "LIVE"
        channel.mkdir(parents=True)
        (channel / marker).write_bytes(b"x")
        assert scanner.is_sc_install_root(tmp_path / "StarCitizen")

    def test_no_marker_appears_in_smart_citizens_own_channel_layout(self, tmp_path):
        """The two trees must not overlap, or the fix is coincidence."""
        data_root = self.make_smart_citizen_data(tmp_path / "Smart Citizen")
        for channel_dir in scanner.channel_dirs(data_root):
            assert scanner.channel_markers(channel_dir) == ()


class TestLeftoverInstalls:
    """A channel folder with no Data.p4k passes settings._is_valid_sc_root, so
    it can be auto-picked as the install root and then silently swallow every
    apply. The scanner still finds it, but must call it what it is."""

    def test_channel_without_game_data_is_a_leftover(self, tmp_path):
        root = make_install(tmp_path / "SC", game_data=False, version="")
        install = read_install(root)
        assert install.is_leftover
        assert not install.has_game_data

    def test_leftover_still_passes_the_looser_settings_check(self, tmp_path):
        """Documents the gap this feature closes, so a future tightening of
        _is_valid_sc_root shows up here rather than silently."""
        root = make_install(tmp_path / "SC", game_data=False, version="")
        assert looks_like_sc_root(root)

    def test_leftover_never_outranks_a_real_install(self, tmp_path):
        real = make_install(tmp_path / "Real", version="4.8.0.1")
        dead = make_install(tmp_path / "Dead", game_data=False, version="")
        report = scan_installs(extra_roots=[dead, real], launcher_log=tmp_path / "none.log", drives=[])
        assert report.installs[0].root == real
        assert report.leftovers == [report.installs[1]]


# -- Apply watermark ---------------------------------------------------------

class TestApplyWatermark:
    def test_detects_the_smart_citizen_stamp(self, tmp_path):
        root = make_install(tmp_path / "SC", applied_language="english", stamp="2.3.0")
        install = read_install(root)
        assert install.is_smart_citizen_applied
        assert install.applied_stamp_versions == ["2.3.0"]
        assert install.channels[0].applied_languages == ("english",)

    def test_applied_without_our_stamp_is_reported_separately(self, tmp_path):
        root = make_install(tmp_path / "SC", applied_language="english")
        install = read_install(root)
        assert install.channels[0].is_applied
        assert not install.is_smart_citizen_applied

    def test_stamp_is_found_past_the_first_chunk(self, tmp_path):
        """Regression: the watermark rides on Frontend_PU_Version, which lands
        wherever the merge sorts it — measured ~1.4 MB into a real 11 MB
        global.ini. A head-only read missed it entirely."""
        root = make_install(tmp_path / "SC", applied_language="english")
        target = root / "LIVE" / "data" / "Localization" / "english" / "global.ini"
        padding = "pad_key=" + ("y" * 80) + "\n"
        target.write_text(
            padding * 40_000 + f"Frontend_PU_Version=Alpha{APPLY_STAMP_MARKER}2.3.0\n",
            encoding="utf-8-sig",
        )
        assert target.stat().st_size > scanner._STAMP_CHUNK_BYTES
        assert read_install(root).applied_stamp_versions == ["2.3.0"]

    def test_no_localization_dir_is_not_an_error(self, tmp_path):
        root = make_install(tmp_path / "SC")
        install = read_install(root)
        assert install.channels[0].applied_languages == ()
        assert not install.is_smart_citizen_applied


# -- Launcher log ------------------------------------------------------------

class TestLauncherLog:
    def test_recovers_root_from_a_logged_path(self, tmp_path):
        root = make_install(tmp_path / "SC")
        assert resolve_logged_root(str(root)) == root

    def test_strips_the_trailing_prose_the_launcher_appends(self, tmp_path):
        root = make_install(tmp_path / "SC")
        assert resolve_logged_root(f"{root} (type: install") == root
        assert resolve_logged_root(f"{root} (statistics enabled: false)") == root

    def test_walks_up_from_a_channel_path(self, tmp_path):
        root = make_install(tmp_path / "SC")
        assert resolve_logged_root(str(root / "LIVE")) == root
        assert resolve_logged_root(f"{root}\\LIVE - required: 110085069 bytes") == root

    def test_program_files_x86_parentheses_survive(self, tmp_path):
        root = make_install(tmp_path / "Program Files (x86)" / "RSI" / "StarCitizen")
        assert resolve_logged_root(str(root)) == root

    def test_path_that_no_longer_exists_resolves_to_none(self, tmp_path):
        assert resolve_logged_root(str(tmp_path / "Gone" / "StarCitizen")) is None

    def test_parses_timestamps_and_keeps_the_newest(self, tmp_path):
        root = make_install(tmp_path / "StarCitizen")
        log = launcher_log(tmp_path / "log.log", [
            ("2026-07-11 14:47:35.478", root),
            ("2026-08-14 09:12:01.001", root),
        ])
        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))
        (found_root, stamp), = parsed.values()
        assert found_root == root
        assert stamp == datetime(2026, 8, 14, 9, 12, 1, 1000)

    def test_keeps_real_path_casing_for_display(self, tmp_path):
        """Keys normalize for matching, values must not — a lowercased
        'c:\\program files\\...' in front of the user reads like a bug."""
        root = make_install(tmp_path / "StarCitizen")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", root)])
        (found_root, _), = parse_launcher_log(log.read_text(encoding="utf-8")).values()
        assert str(found_root) == str(root)

    def test_comma_separated_path_lists_split_into_separate_paths(self, tmp_path):
        """The launcher logs [validateNonExistantDirectories] as one
        comma-joined list; each entry must resolve on its own."""
        first = make_install(tmp_path / "One" / "StarCitizen")
        second = make_install(tmp_path / "Two" / "StarCitizen")
        log = tmp_path / "log.log"
        log.write_text(
            '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": '
            '"[LauncherSupport::validateNonExistantDirectories] %s,%s"  },'
            % (str(first).replace("\\", "\\\\"), str(second).replace("\\", "\\\\")),
            encoding="utf-8",
        )
        assert len(parse_launcher_log(log.read_text(encoding="utf-8"))) == 2

    def test_unreadable_log_reports_not_read(self, tmp_path):
        roots, was_read = scanner.read_launcher_installs(tmp_path / "absent.log")
        assert roots == {} and was_read is False

    def test_only_paths_naming_starcitizen_are_considered(self, tmp_path):
        """Documents the cheap filter that keeps the launcher's own program
        and cache directories out of the results. The RSI Launcher always
        creates its `StarCitizen\\<channel>` tree inside the chosen library
        folder, so a real install always carries the name; an install-shaped
        tree under any other name is invisible to this source (the drive scan
        is what finds those)."""
        named = make_install(tmp_path / "StarCitizen")
        other = make_install(tmp_path / "SomeOtherName")
        log = launcher_log(tmp_path / "log.log", [
            ("2026-08-14 09:12:01.001", named),
            ("2026-08-14 09:12:02.002", other),
        ])
        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))
        assert [root for root, _ in parsed.values()] == [named]


# -- Verdicts ----------------------------------------------------------------

class TestVerdicts:
    def test_nothing_found(self, tmp_path):
        report = scan_installs(launcher_log=tmp_path / "none.log", drives=[])
        assert report.verdict == VERDICT_NONE
        assert report.active is None

    def test_single_install_that_is_configured(self, tmp_path):
        root = make_install(tmp_path / "SC")
        report = scan_installs(
            configured_root=root, extra_roots=[root],
            launcher_log=tmp_path / "none.log", drives=[],
        )
        assert report.verdict == VERDICT_SINGLE
        assert report.unused == []

    def test_single_install_but_configured_points_elsewhere(self, tmp_path):
        root = make_install(tmp_path / "SC")
        report = scan_installs(
            configured_root=tmp_path / "Gone" / "StarCitizen", extra_roots=[root],
            launcher_log=tmp_path / "none.log", drives=[],
        )
        assert report.verdict == VERDICT_SINGLE_ELSEWHERE
        assert report.configured is None

    def test_single_leftover_install(self, tmp_path):
        """#385 review: the leftover check only guarded this branch at first
        -- covering it here so a later edit that drops it is caught."""
        root = make_install(tmp_path / "SC", game_data=False)
        report = scan_installs(
            configured_root=root, extra_roots=[root],
            launcher_log=tmp_path / "none.log", drives=[],
        )
        assert report.verdict == VERDICT_SINGLE_LEFTOVER

    def test_multiple_installs_but_nothing_configured_yet(self, tmp_path):
        """#385 review: this used to fall through to VERDICT_MISMATCH --
        same_path(None, launcher_root) is False, indistinguishable from a
        real disagreement -- a false alarm for a user who simply never set
        a path yet."""
        a = make_install(tmp_path / "A" / "StarCitizen", version="4.9.188.23497")
        b = make_install(tmp_path / "B" / "StarCitizen", version="4.8.3.12122953")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", a)])
        report = scan_installs(extra_roots=[a, b], launcher_log=log, drives=[])
        assert report.verdict == VERDICT_UNCONFIGURED
        assert report.configured is None

    def test_match_but_the_agreed_install_is_a_leftover(self, tmp_path):
        """#385 review: configured and launcher agreeing isn't "nothing to
        fix" when the install they agree on has no game data -- this used to
        report VERDICT_MATCH regardless."""
        leftover = make_install(tmp_path / "New" / "StarCitizen", game_data=False)
        other = make_install(tmp_path / "Old" / "StarCitizen", version="4.8.3.12122953")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", leftover)])
        report = scan_installs(
            configured_root=leftover, extra_roots=[leftover, other],
            launcher_log=log, drives=[],
        )
        assert report.verdict == VERDICT_MATCH_LEFTOVER

    def test_two_installs_configured_matches_the_launcher(self, tmp_path):
        played = make_install(tmp_path / "New" / "StarCitizen", version="4.9.188.23497")
        old = make_install(tmp_path / "Old" / "StarCitizen", version="4.8.3.12122953")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", played)])
        report = scan_installs(
            configured_root=played, extra_roots=[old, played],
            launcher_log=log, drives=[],
        )
        assert report.verdict == VERDICT_MATCH
        assert report.active.root == played
        assert [i.root for i in report.unused] == [old]

    def test_mismatch_is_flagged_when_configured_is_not_the_launchers(self, tmp_path):
        """The bug this feature exists for: apply succeeds, validation passes,
        and nothing changes in game because the launcher starts elsewhere."""
        played = make_install(tmp_path / "New" / "StarCitizen", version="4.9.188.23497")
        stale = make_install(
            tmp_path / "Old" / "StarCitizen", version="4.8.3.12122953",
            applied_language="english", stamp="2.3.0",
        )
        log = launcher_log(tmp_path / "log.log", [
            ("2026-07-11 14:47:35.478", stale),
            ("2026-08-14 09:12:01.001", played),
        ])
        report = scan_installs(
            configured_root=stale, extra_roots=[stale, played],
            launcher_log=log, drives=[],
        )
        assert report.verdict == VERDICT_MISMATCH
        assert report.launcher_root == played
        assert report.configured.root == stale
        # The evidence a user needs: the stale one is where we've been writing.
        assert report.configured.is_smart_citizen_applied
        assert not report.active.is_smart_citizen_applied

    def test_unknown_active_when_the_launcher_log_is_unavailable(self, tmp_path):
        newer = make_install(tmp_path / "New" / "StarCitizen", version="4.9.188.23497")
        older = make_install(tmp_path / "Old" / "StarCitizen", version="4.8.3.12122953")
        report = scan_installs(
            configured_root=older, extra_roots=[older, newer],
            launcher_log=tmp_path / "absent.log", drives=[],
        )
        assert report.verdict == VERDICT_UNKNOWN_ACTIVE
        assert report.launcher_root is None
        assert not report.launcher_log_read

    def test_launcher_wins_over_build_recency_when_ranking(self, tmp_path):
        """Build dates are the fallback signal; an explicit launcher mention
        outranks them even for an older build."""
        launcher_install = make_install(tmp_path / "A" / "StarCitizen", version="4.8.0.1")
        newer_build = make_install(tmp_path / "B" / "StarCitizen", version="4.9.999.9")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", launcher_install)])
        report = scan_installs(
            extra_roots=[newer_build, launcher_install], launcher_log=log, drives=[],
        )
        assert report.active.root == launcher_install


class TestUnusedReporting:
    """Installs driven by neither the launcher nor Smart Citizen: what the
    user explicitly asked to be told about."""

    def test_unused_excludes_the_active_and_configured_installs(self, tmp_path):
        played = make_install(tmp_path / "Played" / "StarCitizen")
        configured = make_install(tmp_path / "Configured" / "StarCitizen")
        orphan = make_install(tmp_path / "Orphan" / "StarCitizen")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", played)])
        report = scan_installs(
            configured_root=configured, extra_roots=[played, configured, orphan],
            launcher_log=log, drives=[],
        )
        assert [i.root for i in report.unused] == [orphan]

    def test_reclaimable_size_sums_the_unused_game_data(self, tmp_path):
        played = make_install(tmp_path / "Played" / "StarCitizen")
        orphan = make_install(tmp_path / "Orphan" / "StarCitizen")
        make_install(orphan, "PTU")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", played)])
        report = scan_installs(
            configured_root=played, extra_roots=[played, orphan],
            launcher_log=log, drives=[],
        )
        unused, = report.unused
        assert unused.total_game_data_size == sum(
            c.game_data_size for c in unused.channels
        )


# -- Deep scan ---------------------------------------------------------------

class TestDeepScan:
    def test_finds_an_install_at_a_custom_path(self, tmp_path):
        root = make_install(tmp_path / "Games" / "Mine" / "StarCitizen")
        found, cancelled = scanner.deep_scan_roots(drives=[str(tmp_path)])
        assert root in found and not cancelled

    def test_stops_descending_once_an_install_is_found(self, tmp_path):
        root = make_install(tmp_path / "SC")
        nested = make_install(root / "LIVE" / "Nested" / "StarCitizen")
        found, _ = scanner.deep_scan_roots(drives=[str(tmp_path)])
        assert root in found and nested not in found

    def test_respects_the_depth_bound(self, tmp_path):
        deep = make_install(tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "SC")
        found, _ = scanner.deep_scan_roots(drives=[str(tmp_path)], max_depth=3)
        assert deep not in found

    def test_prunes_the_skip_list(self, tmp_path):
        hidden = make_install(tmp_path / "Windows" / "StarCitizen")
        found, _ = scanner.deep_scan_roots(drives=[str(tmp_path)])
        assert hidden not in found

    def test_cancel_stops_the_walk(self, tmp_path):
        make_install(tmp_path / "Games" / "StarCitizen")
        found, cancelled = scanner.deep_scan_roots(
            drives=[str(tmp_path)], should_cancel=lambda: True
        )
        assert cancelled and found == []

    def test_scan_installs_marks_a_cancelled_deep_scan(self, tmp_path):
        report = scan_installs(
            launcher_log=tmp_path / "none.log", drives=[str(tmp_path)],
            deep=True, should_cancel=lambda: True,
        )
        assert report.deep_scanned and report.cancelled


# -- Contracts ---------------------------------------------------------------

class TestSharedContracts:
    def test_app_settings_channels_track_the_scanner(self):
        """AppSettings.AVAILABLE_CHANNELS is built from SC_CHANNELS; the named
        CHANNEL_* constants must keep naming the same values in the same
        order (settings.py can't own the list — install_scanner has to stay
        importable without PyQt6)."""
        from src.utils.settings import AppSettings

        assert AppSettings.AVAILABLE_CHANNELS == SC_CHANNELS
        assert (
            AppSettings.CHANNEL_LIVE,
            AppSettings.CHANNEL_PTU,
            AppSettings.CHANNEL_EPTU,
            AppSettings.CHANNEL_HOTFIX,
            AppSettings.CHANNEL_TECH_PREVIEW,
        ) == SC_CHANNELS

    def test_apply_stamp_marker_matches_the_writer(self):
        """The watermark is written by main_window._stamp_frontend_version; if
        that text ever changes, install detection of 'we applied here' goes
        quietly blind."""
        source = (
            Path(__file__).resolve().parent.parent / "src" / "gui" / "main_window.py"
        ).read_text(encoding="utf-8")
        assert APPLY_STAMP_MARKER in source

    @pytest.mark.parametrize("version,expected_greater", [
        ("4.9.188.23497", "4.8.3.12122953"),
        ("4.10.0.1", "4.9.999.9"),
        ("4.9.188.23497", ""),
    ])
    def test_version_sort_key_orders_builds(self, version, expected_greater):
        assert version_sort_key(version) > version_sort_key(expected_greater)

    def test_version_sort_key_tolerates_junk(self):
        assert version_sort_key("not.a.version") < version_sort_key("1.0.0")

    def test_channel_dirs_on_a_file_is_empty_not_an_error(self, tmp_path):
        target = tmp_path / "file.txt"
        target.write_text("x", encoding="utf-8")
        assert channel_dirs(target) == []

    def test_sources_record_where_each_install_came_from(self, tmp_path):
        root = make_install(tmp_path / "StarCitizen")
        log = launcher_log(tmp_path / "log.log", [("2026-08-14 09:12:01.001", root)])
        report = scan_installs(configured_root=root, launcher_log=log, drives=[])
        install, = report.installs
        assert scanner.SOURCE_CONFIGURED in install.sources
        assert scanner.SOURCE_LAUNCHER in install.sources

    def test_same_path_ignores_case_and_separators(self, tmp_path):
        assert scanner.same_path(r"C:\Games\SC", "C:/GAMES/sc")
        assert not scanner.same_path(r"C:\Games\SC", r"C:\Games\Other")
        assert not scanner.same_path(None, r"C:\Games\SC")
        assert not scanner.same_path("", "")

    def test_normcase_key_dedups_the_same_install_found_twice(self, tmp_path):
        root = make_install(tmp_path / "SC")
        report = scan_installs(
            configured_root=str(root).upper(), extra_roots=[root],
            launcher_log=tmp_path / "none.log", drives=[],
        )
        assert report.count == 1


class TestProgressLabelElision:
    r"""Regression: the drive-scan progress dialog grew to most of the screen
    width. QProgressDialog resizes to fit its label and never shrinks back, so
    one long path (``E:\Anime\...``) stretched it for the rest of the scan."""

    def test_short_paths_pass_through_untouched(self):
        from src.gui.workers import elide_middle
        assert elide_middle(r"E:\Anime\01. Love") == r"E:\Anime\01. Love"

    def test_long_paths_are_capped(self):
        from src.gui.workers import elide_middle
        long_path = "E:\\Games\\" + "\\".join(f"nested{i}" for i in range(20))
        out = elide_middle(long_path)
        assert len(out) <= 56
        assert "..." in out

    def test_keeps_the_drive_and_the_current_folder(self):
        """Both ends carry the information that reads as progress."""
        from src.gui.workers import elide_middle
        long_path = "E:\\Games\\" + ("deep\\" * 30) + "CurrentFolder"
        out = elide_middle(long_path)
        assert out.startswith("E:\\")
        assert out.endswith("CurrentFolder")

    def test_boundary_length_is_not_elided(self):
        from src.gui.workers import elide_middle
        exact = "x" * 56
        assert elide_middle(exact) == exact
        assert len(elide_middle("x" * 57)) == 56

    def test_a_limit_too_small_for_head_and_tail_still_respects_it(self):
        """#385 review: keep/head/tail went negative below limit=3, and a
        negative tail-slice index (``text[-0:]``) returns the whole string
        instead of eliding anything -- the one caller always passes the
        default 56, but this is a public, generically-named helper."""
        from src.gui.workers import elide_middle
        long_text = "x" * 100
        for limit in (0, 1, 2, 3, 4, 5):
            out = elide_middle(long_text, limit=limit)
            assert len(out) <= max(limit, 3), (limit, out)


class TestFixedDrives:
    def test_returns_plausible_drive_roots(self):
        drives = scanner.fixed_drives()
        assert all(os.path.splitdrive(d)[0] and d.endswith("\\") for d in drives)
        # Every dev/CI box running this has a system drive.
        assert drives
