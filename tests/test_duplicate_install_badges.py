"""DuplicateInstallDialog._badges: card labels must not contradict the verdict (#385 review).

Real bugs found reviewing #385, all in a method with no prior automated
coverage:

* The configured-install badge rendered red (the "proven wrong" color)
  whenever the verdict was ``VERDICT_UNKNOWN_ACTIVE`` -- the launcher log
  was simply unreadable, nothing was proven wrong, and the verdict banner's
  own color for that state is warn/orange, not red. The badge disagreed
  with the banner right above it.
* ``ScanReport.active``/``.unused`` fall back to the top-ranked-by-recency
  install when there is no launcher-log evidence, but ``_badges`` checked
  only the literal ``launcher_root`` with no such fallback -- so the
  recency-guessed active install got an "Unused" badge while the dialog's
  own summary line (built from ``report.unused``) excluded it from the
  count of unused installs. Same dialog, same install, disagreeing labels.
* A second-round fix (leftover badge/banner) had the exact same
  never-tested shape as the first: the banner's color for a leftover verdict
  moved from warn to bad, and nothing here asserted on either color, so a
  regression in the opposite direction would have shipped unnoticed too.
* ``_card_buttons()`` checked "is this the configured install" before "is
  this a leftover", so a configured-and-leftover install's disabled Use
  button showed the reassuring "already uses this install" tooltip instead
  of surfacing the actual no-game-data problem.

Drives the real ``DuplicateInstallDialog`` headlessly (QT_QPA_PLATFORM=
offscreen), same pattern as tests/test_mission_titles_page_dirty_signal.py
and tests/test_restore_backup.py -- no pytest-qt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.gui.duplicate_install_dialog import DuplicateInstallDialog  # noqa: E402
from src.utils.install_scanner import (  # noqa: E402
    ScanReport,
    ScChannel,
    ScInstall,
    VERDICT_MATCH_LEFTOVER,
    VERDICT_SINGLE_LEFTOVER,
    VERDICT_UNKNOWN_ACTIVE,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _channel(name="LIVE", has_data=True):
    return ScChannel(
        name=name, path=Path("x"), has_game_data=has_data, game_data_size=0,
        game_data_mtime=None, markers=(), version="", branch="", build_date="",
        applied_languages=(), applied_mtime=None, applied_stamp_version="",
        user_cfg_language="",
    )


def _install(root):
    return ScInstall(root=Path(root), channels=[_channel()])


def _leftover_install(root):
    return ScInstall(root=Path(root), channels=[_channel(has_data=False)])


def _dialog(qapp, report):
    return DuplicateInstallDialog(report)


class TestConfiguredBadgeUnderUnprovenVerdicts:
    def test_configured_install_badge_is_warn_not_bad_when_launcher_log_unavailable(self, qapp):
        configured = _install(r"C:\A")
        other = _install(r"D:\B")
        report = ScanReport(
            installs=[configured, other], configured_root=r"C:\A", launcher_root=None,
        )
        assert report.verdict == VERDICT_UNKNOWN_ACTIVE

        dialog = _dialog(qapp, report)
        badges = dialog._badges(configured, report)

        assert len(badges) == 1
        assert "#f44336" not in badges[0], f"still rendering red: {badges}"
        assert "#ff9800" in badges[0], f"expected warn/orange: {badges}"

    def test_configured_install_badge_stays_ok_when_it_genuinely_matches(self, qapp):
        """Guard against overcorrecting: a real match must still render green."""
        configured = _install(r"C:\A")
        report = ScanReport(
            installs=[configured], configured_root=r"C:\A", launcher_root=r"C:\A",
        )
        dialog = _dialog(qapp, report)
        badges = dialog._badges(configured, report)
        assert any("#4caf50" in b for b in badges), f"expected ok/green: {badges}"

    def test_configured_install_badge_stays_bad_on_a_real_mismatch(self, qapp):
        """Guard against overcorrecting: a proven mismatch must still render red."""
        configured = _install(r"C:\A")
        launcher_install = _install(r"D:\B")
        report = ScanReport(
            installs=[configured, launcher_install],
            configured_root=r"C:\A", launcher_root=r"D:\B",
        )
        dialog = _dialog(qapp, report)
        badges = dialog._badges(configured, report)
        assert any("#f44336" in b for b in badges), f"expected bad/red: {badges}"


class TestUnusedBadgeMatchesReportUnused:
    def test_recency_guessed_active_install_is_not_tagged_unused(self, qapp):
        """report.active's fallback (top-ranked install, no launcher evidence)
        must be excluded from the Unused badge the same way report.unused
        already excludes it from the summary count."""
        a = _install(r"C:\A")
        b = _install(r"D:\B")
        report = ScanReport(installs=[a, b], configured_root=None, launcher_root=None)
        assert report.verdict == VERDICT_UNKNOWN_ACTIVE
        assert report.active.root == a.root  # top of the (unranked-here) list
        assert b in report.unused and a not in report.unused

        dialog = _dialog(qapp, report)
        badges_a = dialog._badges(a, report)
        assert not any("Not in use" in b for b in badges_a), f"guessed-active install tagged unused: {badges_a}"

    def test_the_other_install_still_gets_tagged_unused(self, qapp):
        """Guard against overcorrecting: a real spare install must still be flagged."""
        a = _install(r"C:\A")
        b = _install(r"D:\B")
        report = ScanReport(installs=[a, b], configured_root=None, launcher_root=None)
        dialog = _dialog(qapp, report)
        badges_b = dialog._badges(b, report)
        assert any("Not in use" in b for b in badges_b), f"expected unused badge: {badges_b}"


class TestLeftoverBadgeMatchesBanner:
    """Both leftover verdicts render bad/red -- a leftover is proven unusable,
    not merely unproven, so it gets the same color as a real mismatch."""

    def test_single_leftover_configured_badge_is_bad(self, qapp):
        leftover = _leftover_install(r"C:\A")
        report = ScanReport(
            installs=[leftover], configured_root=r"C:\A", launcher_root=None,
        )
        assert report.verdict == VERDICT_SINGLE_LEFTOVER

        dialog = _dialog(qapp, report)
        badges = dialog._badges(leftover, report)
        assert any("#f44336" in b for b in badges), f"expected bad/red: {badges}"
        assert not any("#ff9800" in b for b in badges), f"still rendering warn: {badges}"

    def test_match_leftover_configured_badge_is_bad(self, qapp):
        leftover = _leftover_install(r"C:\A")
        other = _install(r"D:\B")
        report = ScanReport(
            installs=[leftover, other], configured_root=r"C:\A", launcher_root=r"C:\A",
        )
        assert report.verdict == VERDICT_MATCH_LEFTOVER

        dialog = _dialog(qapp, report)
        badges = dialog._badges(leftover, report)
        assert any("#f44336" in b for b in badges), f"expected bad/red: {badges}"


class TestUseButtonTooltipPrefersLeftoverOverAlreadyConfigured:
    def test_configured_and_leftover_shows_the_leftover_warning(self, qapp):
        """#385 review: the button checked "already configured" before
        "leftover", so this case showed the reassuring already-configured
        tooltip instead of surfacing the no-game-data problem."""
        leftover = _leftover_install(r"C:\A")
        report = ScanReport(
            installs=[leftover], configured_root=r"C:\A", launcher_root=None,
        )
        dialog = _dialog(qapp, report)
        row = dialog._card_buttons(leftover, report)
        use_btn = row.itemAt(row.count() - 1).widget()
        assert not use_btn.isEnabled()
        assert "Data.p4k" in use_btn.toolTip(), f"expected the leftover tooltip: {use_btn.toolTip()!r}"

    def test_configured_but_not_leftover_still_shows_already_configured(self, qapp):
        """Guard against overcorrecting: a genuinely fine configured install
        must keep its own, different disabled-reason tooltip."""
        configured = _install(r"C:\A")
        report = ScanReport(
            installs=[configured], configured_root=r"C:\A", launcher_root=r"C:\A",
        )
        dialog = _dialog(qapp, report)
        row = dialog._card_buttons(configured, report)
        use_btn = row.itemAt(row.count() - 1).widget()
        assert not use_btn.isEnabled()
        assert "already uses this install" in use_btn.toolTip().lower()
