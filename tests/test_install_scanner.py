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
* the `SC_CHANNELS` / `AppSettings.AVAILABLE_CHANNELS` sync contract, and
  installer.iss's own copies of the channel and marker lists
"""
from __future__ import annotations

import contextlib
import itertools
import json
import logging
import os
import re
import tracemalloc
from datetime import datetime
from pathlib import Path

import pytest

from src.utils import install_scanner as scanner
from src.utils.install_scanner import (
    APPLY_STAMP_MARKER,
    SC_CHANNEL_MARKERS,
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


@pytest.fixture
def probe_calls(monkeypatch):
    """Every folder ``is_sc_install_root`` is asked about, in order, while the
    real test still answers. The tests that count probes read this list."""
    calls = []
    real = scanner.is_sc_install_root
    monkeypatch.setattr(scanner, "is_sc_install_root", lambda p: calls.append(p) or real(p))
    return calls


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

    def test_a_folder_name_with_an_apostrophe_resolves(self, tmp_path):
        root = make_install(tmp_path / "Dad's Games" / "StarCitizen")
        assert resolve_logged_root(str(root)) == root
        assert resolve_logged_root(f"{root} (type: install") == root

    def test_a_folder_name_with_a_comma_resolves(self, tmp_path):
        root = make_install(tmp_path / "Games, Apps" / "StarCitizen")
        assert resolve_logged_root(str(root)) == root
        assert resolve_logged_root(f"{root} (type: install") == root

    def test_a_quote_or_comma_that_ends_the_path_is_cut_off(self, tmp_path):
        """The launcher's prose sticks to a path as a closing quote or a comma
        too. The whole text is tried first, so a folder name that holds one of
        them stays whole, and the cut only happens when that fails."""
        plain = make_install(tmp_path / "SC")
        odd = make_install(tmp_path / "Dad's Games" / "StarCitizen")
        assert resolve_logged_root(f"{plain}' is missing") == plain
        assert resolve_logged_root(f"{plain}, which is missing") == plain
        assert resolve_logged_root(f"{odd}' is missing") == odd
        assert resolve_logged_root(f"{odd}, which is missing") == odd

    def test_odd_folder_names_survive_a_real_log_line(self, tmp_path):
        apostrophe = make_install(tmp_path / "Dad's Games" / "StarCitizen")
        comma = make_install(tmp_path / "Games, Apps" / "StarCitizen")
        log = launcher_log(tmp_path / "log.log", [
            ("2026-08-14 09:12:01.001", apostrophe),
            ("2026-08-14 09:12:02.002", comma),
        ])
        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))
        assert sorted(root for root, _ in parsed.values()) == sorted([apostrophe, comma])

    def test_a_list_still_splits_when_a_folder_name_holds_a_comma(self, tmp_path):
        """Only a drive path starts a new list entry, so the comma inside
        ``One, Two`` stays part of its folder name."""
        first = make_install(tmp_path / "One, Two" / "StarCitizen")
        second = make_install(tmp_path / "Other" / "StarCitizen")
        log = tmp_path / "log.log"
        log.write_text(
            '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": '
            '"[LauncherSupport::validateNonExistantDirectories] %s,%s"  },'
            % (str(first).replace("\\", "\\\\"), str(second).replace("\\", "\\\\")),
            encoding="utf-8",
        )
        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))
        assert sorted(root for root, _ in parsed.values()) == sorted([first, second])

    def test_a_list_with_spaces_after_the_commas_still_splits(self, tmp_path):
        """A folder name cannot hold a colon, so a drive path always starts a new
        entry, with spaces after the comma before it or without."""
        first = make_install(tmp_path / "One" / "StarCitizen")
        second = make_install(tmp_path / "Two, Three" / "StarCitizen")
        log = tmp_path / "log.log"
        log.write_text(
            '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": '
            '"[LauncherSupport::validateNonExistantDirectories] %s, %s"  },'
            % (str(first).replace("\\", "\\\\"), str(second).replace("\\", "\\\\")),
            encoding="utf-8",
        )
        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))
        assert sorted(root for root, _ in parsed.values()) == sorted([first, second])

    # One log line per call, with the message JSON-escaped the way the launcher
    # writes it (backslashes doubled, a newline as the two characters ``\n``).
    @staticmethod
    def _line(message):
        return (
            '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": %s  },'
            % json.dumps(message)
        )

    @staticmethod
    def _trace(frames=12, *, drive_paths=True, quotes=True):
        """An error stack of *frames* lines with a path in each, one with a drive
        letter or not, and a quote and a comma when *quotes* is set."""
        where = (
            r"C:\Users\me\AppData\Local\Programs\rsi-launcher\resources\app.asar\main.js:1:2"
            if drive_paths
            else "node:internal/process/task_queues:95:5"
        )
        extra = " 'a', 'b'" if quotes else ""
        return "".join(f"\n    at run{n} ({where}){extra}" for n in range(frames))

    def _found(self, message):
        """The install roots the launcher log parser takes out of one line."""
        parsed = parse_launcher_log(self._line(message))
        return sorted(root for root, _ in parsed.values())

    def test_a_line_with_two_quoted_paths_finds_both_installs(self, tmp_path):
        """``copy 'A' to 'B'`` names two install folders. The text between the
        paths used to glue them into one match, and only the first was found.
        Both get the line's own timestamp."""
        first = make_install(tmp_path / "Old Library" / "StarCitizen")
        second = make_install(tmp_path / "New Library" / "StarCitizen")
        line = self._line(f"copy '{first}\\LIVE' to '{second}\\LIVE'")
        parsed = parse_launcher_log(line)
        assert sorted(root for root, _ in parsed.values()) == sorted([first, second])
        assert {stamp for _, stamp in parsed.values()} == {datetime(2026, 8, 14, 9, 12, 1, 1000)}

    @pytest.mark.parametrize(
        "template",
        [
            "copy '{a}\\LIVE' to '{b}\\LIVE'",
            "rename '{a}\\LIVE' -> '{b}\\LIVE'",
            "moving '{a}\\LIVE' and '{b}\\LIVE' now",
            "pair '{a}\\LIVE''{b}\\LIVE'",
            "moving {a}\\LIVE to {b}\\LIVE",
            "moving {a}\\LIVE and {b}\\LIVE",
            "moving {a}\\LIVE - {b}\\LIVE",
            "{a};{b}",
            "{a}; {b}",
        ],
        ids=[
            "copy-to", "node-rename-arrow", "and", "quotes-touching", "bare-to",
            "bare-and", "dash", "semicolon", "semicolon-space",
        ],
    )
    def test_whatever_sits_between_two_paths_neither_is_lost(self, tmp_path, template):
        """Node's file errors read ``rename 'A' -> 'B'``, which is what moving a
        library logs. A folder name cannot hold a colon, so every later drive
        path starts a new entry, whatever separates the two."""
        first = make_install(tmp_path / "Old Library" / "StarCitizen")
        second = make_install(tmp_path / "New Library" / "StarCitizen")
        message = template.format(a=first, b=second)
        assert self._found(message) == sorted([first, second])

    def test_three_paths_in_one_line_are_all_found(self, tmp_path):
        roots = [make_install(tmp_path / name / "StarCitizen") for name in ("One", "Two", "Three")]
        one, two, three = roots
        message = f"move '{one}\\LIVE' to '{two}\\LIVE' and '{three}\\LIVE'"
        assert self._found(message) == sorted(roots)

    @pytest.mark.parametrize(
        "joiner",
        ["\n", "\r\n", "\r", "\t", "\n\n", "\r\n    "],
        ids=["newline", "crlf", "cr", "tab", "blank-line", "crlf-and-indent"],
    )
    def test_a_line_break_between_two_paths_neither_is_lost(self, tmp_path, joiner):
        """The log is JSON, so a line break inside a message is the two
        characters ``\\n`` (``\\r`` and ``\\t`` likewise). The letter of that
        escape sat in front of the next drive letter, so the second path used to
        stay glued to the first."""
        first = make_install(tmp_path / "Old Library" / "StarCitizen")
        second = make_install(tmp_path / "New Library" / "StarCitizen")
        both = sorted([first, second])
        message = f"{first}\\LIVE{joiner}{second}\\LIVE"
        assert len(self._line(message).splitlines()) == 1  # escaped, not a real line break
        assert self._found(message) == both
        assert self._found(f"{first}{joiner}{second}") == both

    def test_folders_named_n_r_and_t_are_not_mistaken_for_a_line_break(self, tmp_path):
        """``\\n``, ``\\r`` and ``\\t`` are also folder names, and a path holds them
        as ``D:\\n\\StarCitizen``. Only a drive path right behind such an escape
        starts an entry, and no folder name can hold the colon that makes one."""
        roots = [make_install(tmp_path / name / "StarCitizen") for name in ("n", "r", "t")]
        one, two, three = roots
        assert self._found(f"copy '{one}\\LIVE' to '{two}\\LIVE'") == sorted([one, two])
        assert self._found(f"{one},{two}, {three}") == sorted(roots)
        assert self._found(f"{three}\\LIVE\n{one}\\LIVE") == sorted([one, three])

    @pytest.mark.parametrize(
        "ending",
        ["\n", "\r\n", "\t", "\n\n", " \r\n"],
        ids=["newline", "crlf", "tab", "two-newlines", "space-crlf"],
    )
    def test_a_message_that_ends_in_a_line_break_still_resolves(self, tmp_path, ending):
        """A message that ends in a line break leaves the escape (``\\n``) on the
        end of the path, so its last folder reads ``n``. Cutting the path at the
        comma found the root in the launcher's own verify line before, and it
        still has to."""
        root = make_install(tmp_path / "Games" / "StarCitizen")
        message = (
            f"[Pipeline] Verifying Star Citizen LIVE at {root} "
            f"(type: verify, forceDP: false){ending}"
        )
        assert self._found(message) == [root]
        assert self._found(f"{root}{ending}") == [root]

    @pytest.mark.parametrize("name", ["n", "r", "t"])
    def test_a_folder_really_named_n_is_tried_before_the_line_break_is_dropped(
        self, tmp_path, name
    ):
        """``...\\n`` at the end of a logged path is a line break or a folder called
        ``n``. The path as logged is tried first, so the folder wins."""
        root = make_install(tmp_path / "StarCitizen Library" / name)
        candidates = list(scanner._logged_path_candidates(str(root)))
        assert candidates[:2] == [str(root), str(root.parent)]
        assert resolve_logged_root(str(root)) == root
        assert self._found(f"at {root}") == [root]

    @pytest.mark.parametrize(
        ("ending", "stages"),
        [
            pytest.param("\\n", ["D:\\Lib\\StarCitizen"], id="newline"),
            pytest.param(
                "\\r\\n", ["D:\\Lib\\StarCitizen\\r", "D:\\Lib\\StarCitizen"], id="crlf"
            ),
            pytest.param(
                " \\r\\n", ["D:\\Lib\\StarCitizen \\r", "D:\\Lib\\StarCitizen"], id="space-crlf"
            ),
            pytest.param(
                "\\n \\n", ["D:\\Lib\\StarCitizen\\n", "D:\\Lib\\StarCitizen"], id="two-breaks"
            ),
        ],
    )
    def test_each_line_break_comes_off_in_turn(self, ending, stages):
        """One escape at a time, with the spaces and separators next to it, and
        each shorter path is a candidate of its own, since the escape may be a
        folder really called n, r or t."""
        logged = "D:\\Lib\\StarCitizen" + ending
        candidates = list(scanner._logged_path_candidates(logged))
        assert candidates[: 1 + len(stages)] == [logged, *stages]

    @pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["newline", "crlf"])
    @pytest.mark.parametrize(
        "parts",
        [("StarCitizen Hub", "t"), ("Hub", "StarCitizen", "n"), ("Lib r", "StarCitizen", "r")],
        ids=["t", "n", "r"],
    )
    def test_a_root_named_n_r_or_t_survives_a_line_break_after_it(
        self, tmp_path, parts, ending
    ):
        """``...\\t\\n`` is a folder called t and then a line break. Taking every
        escape off at once lost the folder along with the break."""
        root = make_install(tmp_path.joinpath(*parts))
        message = f"[Pipeline] Verifying Star Citizen LIVE at {root}{ending}"
        assert self._found(message) == [root]

    def test_a_line_break_after_a_bare_drive_leaves_nothing_to_try(self):
        """``C:`` without a backslash means the current folder on that drive, so
        what is left of ``C:\\n`` once the break is dropped is never probed."""
        assert list(scanner._logged_path_candidates("C:\\n")) == ["C:\\n"]

    def test_a_path_followed_by_a_stack_trace_still_resolves(self, tmp_path):
        """An error can carry its stack in the same string, with quotes, commas
        and more paths in it. Taken as one match, the trace used up the whole
        candidate budget on the walk up from its end, and the install, which sits
        at the front, was never reached."""
        root = make_install(tmp_path / "Library" / "StarCitizen")
        assert self._found(f"{root}\\LIVE, Error: boom{self._trace()}") == [root]

    def test_a_trace_after_two_quoted_paths_does_not_hide_either(self, tmp_path):
        first = make_install(tmp_path / "Old Library" / "StarCitizen")
        second = make_install(tmp_path / "New Library" / "StarCitizen")
        message = f"copy '{first}\\LIVE' to '{second}\\LIVE', Error: boom{self._trace()}"
        assert self._found(message) == sorted([first, second])

    @pytest.mark.parametrize(
        "shape",
        [
            "{root}\\LIVE, Error: boom",
            "{root}, Error: boom",
            "ENOENT, scandir '{root}'",
        ],
        ids=["channel-then-comma", "root-then-comma", "quoted-root"],
    )
    @pytest.mark.parametrize("frames", [12, 40, 200])
    @pytest.mark.parametrize("quotes", [False, True], ids=["plain-frames", "quotes-and-commas"])
    @pytest.mark.parametrize("drive_paths", [True, False], ids=["drive-paths", "no-drive-paths"])
    def test_a_trace_of_any_length_after_the_path_still_resolves(
        self, tmp_path, shape, frames, quotes, drive_paths
    ):
        """The launcher can follow a path with an error and its stack in one
        string. A trace with no drive path in it is one long match, and the cap
        ran out on the walk up from its end before it reached the root, so the
        install was found by neither the quote and comma cuts nor the walk. The
        root is the folder named for the hint, whatever follows it."""
        root = make_install(tmp_path / "Library" / "StarCitizen")
        trace = self._trace(frames, drive_paths=drive_paths, quotes=quotes)
        assert self._found(shape.format(root=root) + trace) == [root]

    @pytest.mark.parametrize("words", [24, 30, 100])
    @pytest.mark.parametrize(
        "shape",
        ["{root} (type: verify, forceDP: false) {prose}", "{root} {prose}"],
        ids=["verify-line", "bare-root"],
    )
    def test_long_prose_after_the_root_still_resolves(self, tmp_path, shape, words):
        """With more words after the name than the budget allows, the word
        trimming used to run out before it got back to the name. It now starts
        at as many words as the budget has room for and ends at the name."""
        root = make_install(tmp_path / "Games" / "StarCitizen")
        prose = " ".join(["word"] * words)
        assert self._found(shape.format(root=root, prose=prose)) == [root]

    @pytest.mark.parametrize("words", [23, 24, 30, 100])
    def test_long_prose_after_a_longer_name_finds_that_install_not_its_neighbour(
        self, tmp_path, words
    ):
        """``StarCitizen Old`` and ``StarCitizen`` are both installs here. However
        long the prose after the first, the trim reaches it before the shorter
        name beside it, which is a different install."""
        library = tmp_path / "Lib5"
        make_install(library / "StarCitizen")
        old = make_install(library / "StarCitizen Old")
        prose = " ".join(f"w{n}" for n in range(words))
        assert self._found(f"Installing at {old} {prose}") == [old]

    @pytest.mark.parametrize(
        "template",
        ["{a};{b};", "{a}; {b};", "dirs={a};{b};", "{a},{b},"],
        ids=["semicolons", "semicolons-spaced", "after-a-key", "commas"],
    )
    def test_a_list_that_ends_in_a_separator_keeps_its_last_entry(self, tmp_path, template):
        first = make_install(tmp_path / "Lib6" / "StarCitizen")
        second = make_install(tmp_path / "Lib7" / "StarCitizen")
        assert self._found(template.format(a=first, b=second)) == sorted([first, second])

    @pytest.mark.parametrize("tail", [";", "; see log", ";;"], ids=["one", "prose", "two"])
    def test_a_semicolon_after_a_root_is_cut_off(self, tmp_path, tail):
        """Like a comma or a quote, a semicolon right after the name ends it, for
        a folder named for the hint and, through the cut at the semicolon, for one
        that is not."""
        root = make_install(tmp_path / "Lib" / "StarCitizen")
        odd = make_install(tmp_path / "Games; Apps" / "StarCitizen")
        game = make_install(tmp_path / "StarCitizen Library" / "Game")
        assert self._found(f"{root}{tail}") == [root]
        assert self._found(f"{odd}{tail}") == [odd]
        assert self._found(f"{game}{tail}") == [game]

    def test_new_paths_stop_being_checked_once_the_probe_budget_is_spent(
        self, tmp_path, monkeypatch, caplog
    ):
        """A log can name far more distinct paths than are worth probing on the
        GUI thread. Once the probes reach the cap, a path the log has not named
        before is skipped, with one debug line, while a path it already checked
        still takes its newer mention."""
        root = make_install(tmp_path / "Lib" / "StarCitizen")
        later = make_install(tmp_path / "Later" / "StarCitizen")
        gone = tmp_path / "Gone" / "StarCitizen"

        def line(minute, message):
            stamp = f"2026-08-14 09:{minute:02d}:00.000"
            return '{ "t":"%s", "[main][info] ": %s  },' % (stamp, json.dumps(message))

        text = "\n".join(
            [line(0, f"Installing at {root}")]
            + [line(1, f"Patched {gone}\\LIVE\\file{n}.dds") for n in range(20)]
            + [line(2, f"Installing at {root}"), line(3, f"Installing at {later}")]
        )
        monkeypatch.setattr(scanner, "_MAX_LOG_PROBES", 5)
        with caplog.at_level(logging.DEBUG, logger=scanner.logger.name):
            parsed = parse_launcher_log(text)
        assert [(found, stamp.minute) for found, stamp in parsed.values()] == [(root, 2)]
        assert sum("not checked" in record.getMessage() for record in caplog.records) == 1

        monkeypatch.undo()
        everything = parse_launcher_log(text)
        assert sorted(found for found, _ in everything.values()) == sorted([root, later])

    def test_the_word_trim_spends_its_budget_and_ends_at_the_first_word(self):
        """Thirty words and nothing else to try: the trim starts at as many words
        as the budget has room for after the whole path and comes down to one, and
        the walk up gets nothing."""
        words = [f"w{n}" for n in range(30)]
        logged = "D:\\Lib\\" + " ".join(words)
        room = self._small_cap() - 1
        trims = ["D:\\Lib\\" + " ".join(words[:count]) for count in range(room, 0, -1)]
        assert list(scanner._logged_path_candidates(logged)) == [logged, *trims]

    def test_the_probe_cap_sits_between_real_runaway_logs_and_contrived_ones(self):
        """A 4 MiB log of rename errors for files in a deleted library takes about
        42,000 probes and must be left alone. Above 150,000 a contrived line
        costs more than about four seconds on the GUI thread."""
        assert 42_000 < scanner._MAX_LOG_PROBES <= 150_000

    def test_no_candidate_is_longer_than_windows_allows(self, tmp_path):
        """Windows takes no path longer than 32,767 characters, so the text past
        that is dropped before anything is cut from it, and a root at the front
        is still found."""
        candidates = list(scanner._logged_path_candidates("C:\\StarCitizen\\" + "a" * 40_000))
        assert candidates and max(len(candidate) for candidate in candidates) <= 32_767
        root = make_install(tmp_path / "Lib" / "StarCitizen")
        assert resolve_logged_root(f"{root}\\LIVE" + ", x" * 20_000) == root

    @pytest.mark.parametrize(("ending", "probes"), [("\\n", 3), ("\\r\\n", 4)])
    def test_each_line_break_on_the_end_costs_one_probe_more(
        self, tmp_path, probe_calls, ending, probes
    ):
        root = make_install(tmp_path / "Library" / "StarCitizen")
        calls = probe_calls
        assert resolve_logged_root(f"{root}\\LIVE{ending}") == root
        assert len(calls) == probes

    def test_an_install_inside_the_hint_folder_install_gives_way_to_it(self, tmp_path):
        """A decision, pinned so it stays one. The folders named for the hint are
        tried before the walk up, so with installs at ``StarCitizen`` and
        ``StarCitizen\\Backup`` the path ``StarCitizen\\Backup\\LIVE`` resolves to
        the outer one, where the nearest root used to win. The launcher always
        names its folder ``StarCitizen`` and never puts a second install inside
        it. The whole path is still tried first."""
        outer = make_install(tmp_path / "StarCitizen")
        inner = make_install(tmp_path / "StarCitizen" / "Backup")
        assert resolve_logged_root(f"{inner}\\LIVE") == outer
        assert resolve_logged_root(str(inner)) == inner

    def test_a_second_path_without_the_hint_is_not_resolved(self, tmp_path):
        """The hint check runs on every entry the split makes, not once per line,
        so an install-shaped folder elsewhere on the same line stays out."""
        named = make_install(tmp_path / "Lib" / "StarCitizen")
        other = make_install(tmp_path / "Elsewhere" / "Game")
        assert self._found(f"copy '{named}\\LIVE' to '{other}\\LIVE'") == [named]
        assert self._found(f"{other},{named}") == [named]

    def test_the_quote_and_comma_cuts_run_last_one_first(self, tmp_path):
        """``X`` and ``X, Y`` are both installs here. The cut at the last comma is
        tried first, so the longer name, the one the text spells out, wins."""
        make_install(tmp_path / "Lib" / "X")
        longer = make_install(tmp_path / "Lib" / "X, Y")
        assert resolve_logged_root(f"{longer}, is missing") == longer

    def test_a_cut_does_not_keep_the_space_in_front_of_a_quote(self, tmp_path):
        """A cut that kept the space before ``' is missing`` would be a folder
        name with a trailing space. Windows drops that space from the last
        folder of a path but not from one in the middle, so such a cut fails
        the install test and the root costs three more probes. The cut comes
        straight after the whole path, with the space gone."""
        root = make_install(tmp_path / "SC")
        logged = f"{root} ' is missing"
        assert list(scanner._logged_path_candidates(logged))[:2] == [logged, str(root)]
        assert resolve_logged_root(logged) == root

    @pytest.mark.parametrize(
        "separator", [";", "; "], ids=["semicolon", "semicolon-space"]
    )
    def test_a_semicolon_between_two_paths_ends_the_first(self, tmp_path, separator):
        """The split takes a semicolon between two paths with it, where one left
        on the earlier path used to lose it. A semicolon in a folder name has no
        drive path after it and stays."""
        odd = make_install(tmp_path / "Games; Apps" / "StarCitizen")
        other = make_install(tmp_path / "Other" / "StarCitizen")
        both = sorted([odd, other])
        assert self._found(f"{other}{separator}{odd}") == both
        assert self._found(f"{odd}{separator}{other}") == both
        assert self._found(f"at {odd}\\LIVE") == [odd]

    @pytest.mark.parametrize("name", ["StarCitizen", "STARCITIZEN", "starcitizen"])
    def test_the_hint_folder_is_found_in_any_case(self, tmp_path, name):
        root = make_install(tmp_path / "Library" / name)
        trace = self._trace(40, drive_paths=False, quotes=True)
        assert self._found(f"{root}\\LIVE, Error: boom{trace}") == [root]

    def test_nested_hint_folders_resolve_to_the_innermost_install(self, tmp_path):
        outer = make_install(tmp_path / "StarCitizen")
        inner = make_install(tmp_path / "StarCitizen" / "StarCitizen")
        trace = self._trace(40, drive_paths=False, quotes=True)
        assert resolve_logged_root(f"{inner}\\LIVE") == inner
        assert resolve_logged_root(f"{outer}\\LIVE") == outer
        assert self._found(f"{inner}\\LIVE, Error: boom{trace}") == [inner]

    def test_nested_hint_folders_fall_back_to_the_outer_install(self, tmp_path):
        """The inner folder here is a shell with no game in it, so the outer
        folder, the next one named for the hint, is the root."""
        outer = make_install(tmp_path / "StarCitizen")
        (outer / "StarCitizen" / "LIVE").mkdir(parents=True)
        trace = self._trace(40, drive_paths=False, quotes=True)
        assert self._found(f"{outer}\\StarCitizen\\LIVE, Error: boom{trace}") == [outer]

    @pytest.mark.parametrize("longer", ["StarCitizen_old", "StarCitizen Old", "StarCitizen-old"])
    def test_a_longer_folder_name_is_not_cut_back_to_the_install_beside_it(
        self, tmp_path, longer
    ):
        """``StarCitizen Old`` is a different folder from the install called
        ``StarCitizen`` next to it. A log that names the first one, with or
        without a trace after it, says nothing about the second."""
        library = tmp_path / "Library"
        make_install(library / "StarCitizen")
        (library / longer / "LIVE").mkdir(parents=True)
        trace = self._trace(40, drive_paths=False, quotes=True)
        assert resolve_logged_root(f"{library}\\{longer}\\LIVE") is None
        assert self._found(f"{library}\\{longer}\\LIVE, Error: boom{trace}") == []

    def test_a_root_not_named_for_the_hint_is_found_when_nothing_long_follows(self, tmp_path):
        """The hint check only needs the text to mention it somewhere, here in the
        library folder. The launcher always creates ``StarCitizen`` itself, so a
        root with another name is rare, and the cuts for the hint do not help it.
        The walk up still reaches it, from a dozen folders down as well. Quoted
        and followed by five ``node:internal`` stack frames or more, it is lost,
        where the release before #445 found it (that match ended at the quote).
        That shape needs a folder the launcher did not make, and is accepted."""
        root = make_install(tmp_path / "StarCitizen Library" / "Game")
        assert self._found(f"{root}\\LIVE") == [root]
        deep = "\\LIVE" + "\\d" * 12 + "\\file.dds"
        assert self._found(f"{root}{deep}") == [root]
        assert self._found(f"copy '{root}\\LIVE' to 'D:\\Elsewhere'") == [root]

    @pytest.mark.parametrize(
        "tail",
        [
            "\\LIVE - required: 110085069 bytes",
            "\\LIVE' to 'D:\\Elsewhere'",
            "' is missing",
            ", Error: boom",
            "\\LIVE\\Data\\Objects\\file1.dds",
            "\\LIVE, " + "x, " * 30,
        ],
        ids=["prose", "quoted-pair", "quote", "comma", "file", "many-commas"],
    )
    def test_the_hint_folder_costs_two_probes_after_any_prose(
        self, tmp_path, probe_calls, tail
    ):
        """The whole path first, then the folder named for the hint: the root. The
        quote and comma cuts and the walk up never get a turn. A line break left
        on the end adds one probe for each escape (see below)."""
        root = make_install(tmp_path / "Library" / "StarCitizen")
        calls = probe_calls
        assert resolve_logged_root(f"{root}{tail}") == root
        assert len(calls) <= 2

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param(
                r"D:\Lib\StarCitizen\LIVE, Error: x", [r"D:\Lib\StarCitizen"], id="folder"
            ),
            pytest.param(
                r"D:\StarCitizen\StarCitizen\LIVE",
                [r"D:\StarCitizen\StarCitizen", r"D:\StarCitizen"],
                id="nested-last-first",
            ),
            pytest.param(r"D:\Lib\STARCITIZEN\LIVE", [r"D:\Lib\STARCITIZEN"], id="any-case"),
            pytest.param(
                r"D:\Lib\StarCitizen_old\LIVE", [r"D:\Lib\StarCitizen_old"], id="longer-name"
            ),
            pytest.param(
                r"D:\Lib\StarCitizen Old\LIVE", [r"D:\Lib\StarCitizen Old"], id="name-with-space"
            ),
            pytest.param(
                r"D:\Lib\StarCitizen, Error: x",
                [r"D:\Lib\StarCitizen", r"D:\Lib\StarCitizen, Error: x"],
                id="comma-after-the-name",
            ),
            pytest.param(
                r"D:\Lib\StarCitizen' is missing",
                [r"D:\Lib\StarCitizen", r"D:\Lib\StarCitizen' is missing"],
                id="quote-after-the-name",
            ),
            pytest.param(
                r"D:\Lib\StarCitizen; see log",
                [r"D:\Lib\StarCitizen", r"D:\Lib\StarCitizen; see log"],
                id="semicolon-after-the-name",
            ),
            pytest.param(r"D:\Lib\MyStarCitizen\LIVE", [], id="hint-inside-a-name"),
            pytest.param(r"D:\Lib\x StarCitizen\LIVE", [], id="hint-after-a-space"),
            pytest.param(r"D:\Lib\LIVE", [], id="no-hint"),
            pytest.param(r"D:/Lib/StarCitizen/LIVE", [r"D:/Lib/StarCitizen"], id="slashes"),
            pytest.param(r"D:\Lib\StarCitizen", [r"D:\Lib\StarCitizen"], id="last-folder"),
        ],
    )
    def test_the_prefixes_that_end_at_a_hint_folder(self, raw, expected):
        assert list(scanner._hint_folder_cuts(raw)) == expected

    def test_the_whole_path_comes_first_and_a_hint_cut_that_equals_it_is_skipped(self):
        assert list(scanner._logged_path_candidates(r"D:\Lib\StarCitizen")) == [
            r"D:\Lib\StarCitizen",
            r"D:\Lib",
        ]
        assert list(scanner._logged_path_candidates(r"D:\Lib\StarCitizen\LIVE"))[:2] == [
            r"D:\Lib\StarCitizen\LIVE",
            r"D:\Lib\StarCitizen",
        ]

    def test_odd_folder_names_survive_a_two_path_line(self, tmp_path):
        """The apostrophe and the comma stay part of their folder names when a
        line names two paths, in either order."""
        apostrophe = make_install(tmp_path / "Dad's Games" / "StarCitizen")
        comma = make_install(tmp_path / "Games, Apps" / "StarCitizen")
        both = sorted([apostrophe, comma])
        assert self._found(f"copy '{apostrophe}\\LIVE' to '{comma}\\LIVE'") == both
        assert self._found(f"copy '{comma}\\LIVE' to '{apostrophe}\\LIVE'") == both
        assert self._found(f"rename '{apostrophe}\\LIVE' -> '{comma}\\LIVE'") == both

    @pytest.mark.parametrize("separator", [",", ", "], ids=["no-spaces", "spaces"])
    def test_a_comma_list_costs_one_probe_per_entry(self, tmp_path, probe_calls, separator):
        """The comma and the spaces after it go with the split, so every entry
        reaches the folder test as a clean path. Entries that kept their comma
        would each cost a failed probe before the cut at it."""
        roots = [
            make_install(tmp_path / name / "StarCitizen")
            for name in ("One", "Two, Three", "Four")
        ]
        calls = probe_calls
        message = "[validateNonExistantDirectories] " + separator.join(str(r) for r in roots)
        assert self._found(message) == sorted(roots)
        assert len(calls) == len(roots)

    @pytest.mark.parametrize(
        ("match", "expected"),
        [
            pytest.param(
                r"C:\a,C:\b\StarCitizen", [r"C:\a", r"C:\b\StarCitizen"], id="comma-list"
            ),
            pytest.param(
                r"C:\a,  C:\b, D:\c", [r"C:\a", r"C:\b", r"D:\c"], id="comma-list-spaces"
            ),
            pytest.param(
                r"F:\Old\LIVE' to 'G:\New\LIVE'",
                [r"F:\Old\LIVE' to '", r"G:\New\LIVE'"],
                id="text-between-stays-on-the-earlier-entry",
            ),
            pytest.param(
                r"F:\Old\LIVE''G:\New\LIVE'", [r"F:\Old\LIVE''", r"G:\New\LIVE'"], id="touching"
            ),
            pytest.param(r"c:\a and d:\b", [r"c:\a and ", r"d:\b"], id="lowercase-drives"),
            pytest.param(
                r"C:\a -> D:\b -> E:\c", [r"C:\a -> ", r"D:\b -> ", r"E:\c"], id="three-paths"
            ),
            pytest.param(
                r"C:\Games, Apps\StarCitizen", [r"C:\Games, Apps\StarCitizen"], id="comma-folder"
            ),
            pytest.param(
                r"C:\Dad's Games\StarCitizen", [r"C:\Dad's Games\StarCitizen"], id="quote-folder"
            ),
            pytest.param(
                r"C:\a\StarCitizen\abc:\x", [r"C:\a\StarCitizen\abc:\x"], id="letter-before-drive"
            ),
            pytest.param(r"C:\a, e:f", [r"C:\a, e:f"], id="no-backslash-is-no-drive"),
            pytest.param(r"C:\a\nC:\b", [r"C:\a\n", r"C:\b"], id="json-newline"),
            pytest.param(r"C:\a\r\nC:\b", [r"C:\a\r\n", r"C:\b"], id="json-crlf"),
            pytest.param(r"C:\a\rC:\b", [r"C:\a\r", r"C:\b"], id="json-cr"),
            pytest.param(r"C:\a\tC:\b", [r"C:\a\t", r"C:\b"], id="json-tab"),
            pytest.param(r"C:\a\nc:\b", [r"C:\a\n", r"c:\b"], id="json-newline-lowercase"),
            pytest.param(
                r"C:\a\nabc:\x", [r"C:\a\nabc:\x"], id="escape-then-word-then-letter"
            ),
            pytest.param(r"C:\a\Ann:\x", [r"C:\a\Ann:\x"], id="n-ending-a-word"),
            pytest.param(r"C:\a\Cart:\x", [r"C:\a\Cart:\x"], id="t-ending-a-word"),
            pytest.param(r"C:\a\Zc:\x", [r"C:\a\Zc:\x"], id="other-letter-after-a-backslash"),
            pytest.param(
                r"C:\n\r\t\StarCitizen", [r"C:\n\r\t\StarCitizen"], id="folders-named-n-r-t"
            ),
            pytest.param(r"C:\a;C:\b", [r"C:\a", r"C:\b"], id="semicolon-list"),
            pytest.param(r"C:\a;  C:\b", [r"C:\a", r"C:\b"], id="semicolon-list-spaces"),
            pytest.param(
                r"C:\Games; Apps\StarCitizen", [r"C:\Games; Apps\StarCitizen"],
                id="semicolon-folder",
            ),
        ],
    )
    def test_the_split_is_before_each_later_drive_path(self, match, expected):
        """The split on its own. It leaves empty pieces (one at the front, since
        every match starts at a drive path, and one after each separator it
        consumes), which the hint check in the parser drops, so they are left
        out of the comparison."""
        entries = scanner._LOG_PATH_LIST_SPLIT_RE.split(match)
        assert [entry for entry in entries if entry] == expected

    def test_many_quotes_or_commas_do_not_starve_the_folder_walk(self, tmp_path):
        """The cuts at a quote or comma have a budget of their own, so a path with
        more of them than the cap still reaches the folder walk, which finds the
        root from the folder the prose is stuck to."""
        root = make_install(tmp_path / "SC")
        assert resolve_logged_root(str(root) + "\\LIVE" + ",x" * 40) == root

    @pytest.mark.parametrize(
        "junk",
        [
            pytest.param("\\".join(["a, 'b"] * 100), id="many-folders-quotes-and-commas"),
            pytest.param("x\\" + " ".join(["w"] * 200), id="many-words"),
            pytest.param("\\".join(["StarCitizen, x"] * 500), id="many-hint-folders"),
            pytest.param("\\".join(["StarCitizen' q"] * 500), id="many-hint-folders-quoted"),
            pytest.param("x" + "\\n" * 100, id="many-line-breaks"),
        ],
    )
    def test_a_long_run_of_junk_after_a_path_costs_a_bounded_number_of_probes(
        self, tmp_path, probe_calls, junk
    ):
        """The cuts, the word trimming and the walk up each work from a budget, so
        a string that is mostly quotes, commas, words and folders (folders named
        for the hint too), and holds no install, cannot turn into thousands of
        stat calls. The junk offers hundreds of candidates, and a few dozen get
        probed."""
        calls = probe_calls
        assert self._found(f"{tmp_path}\\StarCitizen\\{junk}") == []
        assert len(calls) < 100
        # One budget for the whole path and the cuts, another for the words and the walk.
        assert len(calls) <= 2 * scanner._MAX_PATH_CANDIDATES

    def test_the_hint_cuts_and_the_quote_and_comma_cuts_share_one_budget(
        self, tmp_path, probe_calls
    ):
        """Folders named for the hint, and quotes and commas, can each offer
        hundreds of cuts. Together they get one budget, so the whole path, those
        cuts and the walk up cost about one cap's worth of probes, not two."""
        calls = probe_calls
        junk = "\\".join(["StarCitizen_a, 'b"] * 500)
        assert self._found(f"{tmp_path}\\StarCitizen\\{junk}") == []
        assert len(calls) <= scanner._MAX_PATH_CANDIDATES + 5

    @staticmethod
    def _small_cap():
        """The candidate budget, checked first, since a test sizes its input by it."""
        cap = scanner._MAX_PATH_CANDIDATES
        assert 1 < cap <= 100, "the budget is no longer a small number"
        return cap

    def test_the_quote_and_comma_cuts_reach_back_exactly_one_budget(self, monkeypatch):
        """With no folder named for the hint, the whole path takes one place in the
        budget and the cuts the rest, so the first comma of a path with one fewer
        comma than the budget is reached, and with one more it is not. A line
        break on the end makes the path without it a candidate too, and that
        takes a place of its own."""
        target = "D:\\R"
        monkeypatch.setattr(scanner, "is_sc_install_root", lambda p: str(p) == target)
        cap = self._small_cap()
        assert resolve_logged_root(target + ",x" * (cap - 1)) == Path(target)
        assert resolve_logged_root(target + ",x" * cap) is None
        assert resolve_logged_root(target + ",x" * (cap - 2) + "\\n") == Path(target)
        assert resolve_logged_root(target + ",x" * (cap - 1) + "\\n") is None

    def test_the_hint_cuts_reach_back_exactly_one_budget(self, monkeypatch):
        """The path ends in a folder named for the hint, which is the whole path
        and is not offered again, so the budget reaches back through as many
        folders as it holds. The ``a`` folders keep the walk up from getting there
        first. One folder more, and the first is out of reach."""
        target = "D:\\StarCitizen"
        monkeypatch.setattr(scanner, "is_sc_install_root", lambda p: str(p) == target)
        cap = self._small_cap()
        reachable = "D:" + "\\StarCitizen\\a" * (cap - 1) + "\\StarCitizen"
        one_too_many = "D:" + "\\StarCitizen\\a" * cap + "\\StarCitizen"
        assert resolve_logged_root(reachable) == Path(target)
        assert resolve_logged_root(one_too_many) is None

    @staticmethod
    def _peak_bytes(work):
        """Peak bytes Python allocates while *work* runs."""
        if tracemalloc.is_tracing():
            pytest.skip("tracemalloc is already running")
        tracemalloc.start()
        try:
            work()
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    def test_a_hostile_line_keeps_only_the_matches_the_budget_can_use(self):
        """The cut passes take their matches last first and stop at the budget, so
        they keep that many and no more. Holding every match of these commas took
        some 4 MB even after the text is cut to 32,767 characters (40 MB before
        that cut), against under 1 MB now. The hint cuts are called here on the
        whole text, as long as it is. A hundred candidates is more than any budget
        hands out, and stopping there keeps a build that holds everything quick to fail."""
        commas = r"C:\Lib\StarCitizen" + "," * 300_000
        folders = r"C:\x" + "\\StarCitizen" * 100_000

        def every_candidate():
            for _ in itertools.islice(scanner._logged_path_candidates(commas), 100):
                pass

        def the_hint_cuts_a_caller_takes():
            for _ in itertools.islice(scanner._hint_folder_cuts(folders), 100):
                pass

        assert self._peak_bytes(every_candidate) < 2 * 1024 * 1024
        assert self._peak_bytes(the_hint_cuts_a_caller_takes) < 8 * 1024 * 1024

    def test_the_read_budget_is_four_mib(self):
        """A hundred times the size of a real launcher log."""
        assert scanner._LOG_READ_BUDGET_BYTES == 4 * 1024 * 1024

    def _log_lines(self, count, roots):
        """*count* padding lines, then one line per root in *roots*."""
        pad = '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": "padding %s"  },'
        lines = [pad % ("x" * 60) for _ in range(count)]
        for number, root in enumerate(roots):
            escaped = str(root).replace("\\", "\\\\")
            lines.append(
                '{ "t":"2026-08-14 09:13:0%d.000", "[main][info] ": '
                '"Installing at %s (type: install)"  },'
                % (number, escaped)
            )
        return lines

    def test_only_the_end_of_a_huge_log_is_read(self, tmp_path, monkeypatch):
        """First-run detection reads the log on the GUI thread, so only the
        last stretch of it is parsed. The launcher appends, so that is where
        the newest mentions are."""
        old = make_install(tmp_path / "Old" / "StarCitizen")
        new = make_install(tmp_path / "New" / "StarCitizen")
        lines = self._log_lines(0, [old]) + self._log_lines(400, [new])
        log = tmp_path / "log.log"
        log.write_text("\n".join(lines), encoding="utf-8")
        assert log.stat().st_size > 2000

        everything, read = scanner.read_launcher_installs(log)
        assert read
        assert sorted(root for root, _ in everything.values()) == sorted([old, new])

        monkeypatch.setattr(scanner, "_LOG_READ_BUDGET_BYTES", 2000)
        tail, read = scanner.read_launcher_installs(log)
        assert read
        # The old mention sits outside the last 2000 bytes, and the new one inside them.
        assert [root for root, _ in tail.values()] == [new]

    def test_the_line_the_cut_lands_in_is_dropped_not_parsed_half(self, tmp_path, monkeypatch):
        cut = make_install(tmp_path / "Cut" / "StarCitizen")
        last = make_install(tmp_path / "Last" / "StarCitizen")
        lines = self._log_lines(3, [cut, last])
        log = tmp_path / "log.log"
        log.write_text("\n".join(lines), encoding="utf-8")
        # Land the cut five bytes into the line that names *cut*, so the rest of
        # that line, its path included, is still there to be parsed by mistake.
        budget = len(lines[-1].encode()) + 1 + len(lines[-2].encode()) - 5
        monkeypatch.setattr(scanner, "_LOG_READ_BUDGET_BYTES", budget)
        tail, read = scanner.read_launcher_installs(log)
        assert read
        assert [root for root, _ in tail.values()] == [last]

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

    def test_per_file_paths_under_one_install_share_the_folder_walk(
        self, tmp_path, probe_calls
    ):
        """Each per-file path is a distinct raw string, so without a per-folder
        memo every one walks up through the same folders again. First-run
        detection parses on the GUI thread, so that walk has to stay bounded."""
        root = make_install(tmp_path / "StarCitizen")
        files = 40
        lines = [
            '{ "t":"2026-08-14 09:12:01.001", "[main][info] ": "Patched %s"  },'
            % str(root / "LIVE" / "Data" / "Objects" / f"file{i}.dds").replace("\\", "\\\\")
            for i in range(files)
        ]
        calls = probe_calls

        parsed = parse_launcher_log("\n".join(lines))

        assert [found for found, _ in parsed.values()] == [root]
        # One test per file path, plus one per folder on the way up. Without
        # the memo it is five per file path.
        assert len(calls) <= files + 4

    def test_a_missing_drive_is_checked_once_and_nothing_on_it_is_probed(
        self, tmp_path, monkeypatch, probe_calls
    ):
        """#431 review: a log can name a mapped drive that is no longer
        connected, where every probe waits for a network timeout, and first-run
        detection parses on the GUI thread. One check per drive, in any letter
        case, and no probe at all on a drive that is not there."""
        real = make_install(tmp_path / "StarCitizen")
        gone = [
            r"Q:\Games\StarCitizen",
            r"q:\Other\StarCitizen\LIVE\Data.p4k",
            r"Q:\Third\StarCitizen (type: install",
        ]
        log = launcher_log(tmp_path / "log.log", [
            (f"2026-08-14 09:12:0{i}.001", path) for i, path in enumerate(gone + [str(real)])
        ])
        checked_drives = []
        monkeypatch.setattr(
            scanner, "_drive_exists", lambda drive: checked_drives.append(drive) or drive != "Q:"
        )

        parsed = parse_launcher_log(log.read_text(encoding="utf-8"))

        assert [found for found, _ in parsed.values()] == [real]
        assert sorted(checked_drives) == sorted(["Q:", real.drive.upper()])
        assert not [p for p in probe_calls if str(p)[:2].upper() == "Q:"]

    def test_the_drive_check_reads_the_real_drive(self, tmp_path, probe_calls):
        """A letter with no drive behind it at all reads as missing, and the
        drive this test runs on reads as there."""
        import ctypes
        import string

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            pytest.skip("drive letters are a Windows thing")
        in_use = windll.kernel32.GetLogicalDrives()
        free = [
            f"{letter}:" for bit, letter in enumerate(string.ascii_uppercase)
            if bit > 2 and not in_use & (1 << bit)
        ]
        if not free:
            pytest.skip("every drive letter is in use")
        assert scanner._drive_exists(free[-1]) is False
        assert scanner._drive_exists(tmp_path.drive) is True
        log = launcher_log(tmp_path / "log.log", [
            ("2026-08-14 09:12:01.001", free[-1] + r"\Games\StarCitizen"),
        ])
        assert parse_launcher_log(log.read_text(encoding="utf-8")) == {}
        assert probe_calls == []


# -- One folder below each drive's top ---------------------------------------

class TestShallowScan:
    def _found(self, drive):
        return list(scanner.iter_shallow_sc_install_locations([str(drive)]))

    def test_finds_a_library_folder_one_level_down(self, tmp_path):
        rsi = make_install(tmp_path / "Other Games" / "Roberts Space Industries" / "StarCitizen")
        plain = make_install(tmp_path / "Library" / "StarCitizen")
        at_root = make_install(tmp_path / "StarCitizen")
        assert self._found(tmp_path) == [at_root, plain, rsi]

    def test_a_leftover_without_game_data_is_not_picked(self, tmp_path):
        """Nobody chose these folders, so the shell of an old install must not
        be picked for them."""
        make_install(tmp_path / "Old Games" / "StarCitizen", game_data=False)
        assert self._found(tmp_path) == []

    def test_smart_citizen_data_is_not_an_install(self, tmp_path):
        data = tmp_path / "Smart Citizen" / "StarCitizen" / "LIVE"
        data.mkdir(parents=True)
        (data / "user.ini").write_text("k=v\n", encoding="utf-8")
        assert self._found(tmp_path) == []

    def test_game_data_in_any_channel_counts(self, tmp_path):
        """The launcher can keep PTU in a library folder of its own with no LIVE
        in it, and an old LIVE shell can sit beside the real PTU data."""
        ptu_only = make_install(tmp_path / "SC PTU" / "StarCitizen", "PTU")
        mixed = make_install(tmp_path / "Mixed" / "StarCitizen", "LIVE", game_data=False)
        make_install(mixed, "PTU")
        assert self._found(tmp_path) == [mixed, ptu_only]

    def test_hits_are_ordered_by_folder_name_whatever_order_the_drive_lists_them(
        self, tmp_path, monkeypatch
    ):
        """NTFS lists folders by name, but exFAT and FAT32 drives list them in the
        order they were made. The probe sorts them, ignoring case, so a tie in the
        ranking goes the same way on every drive."""
        zeta = make_install(tmp_path / "Zeta" / "StarCitizen")
        alpha = make_install(tmp_path / "alpha" / "StarCitizen")
        real_scandir = os.scandir

        def listed_by_raw_name(path):
            if Path(path) != tmp_path:
                return real_scandir(path)
            with real_scandir(path) as entries:
                return contextlib.nullcontext(sorted(entries, key=lambda e: e.name))

        monkeypatch.setattr(os, "scandir", listed_by_raw_name)
        assert self._found(tmp_path) == [alpha, zeta]

    def test_does_not_go_two_folders_down(self, tmp_path):
        make_install(tmp_path / "Games" / "PC" / "Roberts Space Industries" / "StarCitizen")
        assert self._found(tmp_path) == []

    def test_skips_system_folders(self, tmp_path):
        make_install(tmp_path / "Windows" / "StarCitizen")
        make_install(tmp_path / "$Stash" / "StarCitizen")
        assert self._found(tmp_path) == []

    def test_a_missing_drive_is_skipped(self, tmp_path):
        found = make_install(tmp_path / "Games2" / "StarCitizen")
        drives = [str(tmp_path / "no-such-drive"), str(tmp_path)]
        assert list(scanner.iter_shallow_sc_install_locations(drives)) == [found]

    def test_a_symlinked_top_level_folder_is_not_followed(self, tmp_path):
        """The probe lists a drive's top folders with ``follow_symlinks=False``,
        so a symlink to a library folder (a ``Games`` link to another drive, say)
        is skipped. Following it would report the same install a second time,
        under the link's path. A junction is not a symlink and is followed, which
        first-run detection copes with by counting an install once."""
        real = make_install(tmp_path / "Games" / "StarCitizen")
        try:
            os.symlink(tmp_path / "Games", tmp_path / "Link", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot make a symlink here (it needs a privilege): {exc}")
        assert self._found(tmp_path) == [real]

    def test_a_junction_at_the_top_of_a_drive_is_followed(self, tmp_path):
        """Moving a folder to another drive and leaving a junction behind is
        the usual way to free space, and any account can make one. The probe
        lists it like a folder, so a library only the junction reaches (two
        levels down on the other drive) is still found, under the junction's
        path. First-run detection counts it once with the real folder."""
        import subprocess

        drive = tmp_path / "drive"
        drive.mkdir()
        target = tmp_path / "other" / "Stuff" / "Games"
        make_install(target / "StarCitizen")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(drive / "Games"), str(target)],
            capture_output=True,
            text=True,
        )
        if made.returncode != 0 or not (drive / "Games").exists():
            reason = f"cannot make a junction here: {(made.stdout + made.stderr).strip()}"
            # Any account can make a junction, so on CI this is a broken runner,
            # not a reason to drop the check without a word.
            if os.environ.get("CI"):
                pytest.fail(reason, pytrace=False)
            pytest.skip(reason)
        assert self._found(drive) == [drive / "Games" / "StarCitizen"]


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
    INSTALLER = Path(__file__).resolve().parent.parent / "installer.iss"

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

    def _installer_function(self, name: str) -> str:
        source = self.INSTALLER.read_text(encoding="utf-8")
        match = re.search(rf"^function {name}\(.*?^end;", source, re.M | re.S)
        assert match, f"installer.iss has no function {name}"
        return match.group(0)

    def _installer_const(self, name: str) -> int:
        source = self.INSTALLER.read_text(encoding="utf-8")
        match = re.search(rf"^\s*{name}\s*=\s*(\d+);", source, re.M)
        assert match, f"installer.iss has no const {name}"
        return int(match.group(1))

    def test_installer_channels_track_the_scanner(self):
        """The uninstaller's opt-in wipe (#357) keeps its own channel list,
        because Pascal can't import this module. A channel added here but not
        there would be skipped by both the wipe and its game-file check."""
        body = self._installer_function("ScChannelName")
        names = re.findall(r"^\s*\d+:\s*Result := '([^']+)';", body, re.M)
        names += re.findall(r"else\s+Result := '([^']+)';", body)
        assert tuple(names) == SC_CHANNELS
        assert self._installer_const("ScChannelCount") == len(SC_CHANNELS)

    def test_installer_markers_track_the_scanner(self):
        """HasScGameData refuses to wipe any folder holding one of these. It
        must cover every SC_CHANNEL_MARKERS entry plus its own extras, the
        player data that outlives the game files (USER holds keybinds), and
        ScMarkerCount must reach the last case, or a marker is never checked."""
        body = self._installer_function("HasScGameData")
        cases = re.findall(r"^\s*(\d+):\s*Marker := '([^']+)';", body, re.M)
        assert [int(i) for i, _ in cases] == list(range(len(cases)))
        markers = {m for _, m in cases}
        assert set(SC_CHANNEL_MARKERS) <= markers
        assert {"USER", "ScreenShots", "logbackups", "Game.log"} <= markers
        assert self._installer_const("ScMarkerCount") == len(cases)

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
