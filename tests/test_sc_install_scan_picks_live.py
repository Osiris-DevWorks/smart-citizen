r"""The install scan must not pick an abandoned Star Citizen folder (#370).

A user's DataForge extraction hung for 30 minutes on every run. The chain of
symptoms pointed everywhere except the cause: unforge stalling, memory at 99%,
a 114 MB Game.dcb where healthy installs carry a 330 MB Game2.dcb. The build
manifest they sent matched two working installs byte for byte, so their game
looked fine. Verify Files in the RSI launcher changed nothing.

It changed nothing because the launcher was verifying the install it manages,
and Smart Citizen was reading a different one. A leftover
``D:\Program Files\Roberts Space Industries\StarCitizen`` still had a valid
channel folder, so the scan accepted it and returned, and their real install at
``E:\Roberts Space Industries\StarCitizen`` was never looked at.

Two things caused that, and both are the scan's fault rather than the user's:

* it returned its first hit instead of comparing candidates, and
* the iteration is drive-major over a subpath list whose first entry is
  ``Program Files\...``, so an orphan on an earlier drive beats the real
  install on a later one every time.

Newest Data.p4k now wins, because an abandoned install's archive is frozen at
whenever it stopped being patched while the live one moves with every update.
Among installs that hold a current copy of the active channel, that channel's
own Data.p4k decides, so a library that only holds another channel cannot take
the pick (see ``TestScanUsesLauncherLog`` in ``test_sc_install_root.py``). The
tests here pass LIVE as the active channel, which is what the scan does for
most players. Every candidate is logged either way: the heuristic can still be
wrong, and a log naming the alternatives is what turns this into a one-line
diagnosis instead of the thread it took.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import _p4k_mtimes, _pick_live_sc_install  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _install(root: Path, channel: str = "LIVE", *, mtime: float | None = None) -> str:
    """Build a folder shaped like a real install: a channel dir with a p4k."""
    p4k = root / channel / "Data.p4k"
    p4k.parent.mkdir(parents=True, exist_ok=True)
    p4k.write_bytes(b"\0")
    if mtime is not None:
        import os
        os.utime(p4k, (mtime, mtime))
    return str(root)


def test_newest_p4k_wins_over_scan_order(tmp_path):
    """#370 reduced to its essentials: the orphan is found first, the live
    install is found later, and the live one has to win anyway."""
    orphan = _install(tmp_path / "D_ProgramFiles", mtime=1_000_000)
    live = _install(tmp_path / "E_RSI", mtime=2_000_000)
    # scan order puts the orphan first, exactly as the drive-major walk does
    assert _pick_live_sc_install([orphan, live], channel="LIVE") == live


def test_single_candidate_is_returned_unchanged(tmp_path):
    """The overwhelmingly common case must not change behaviour at all."""
    only = _install(tmp_path / "solo")
    assert _pick_live_sc_install([only], channel="LIVE") == only


def test_scan_order_breaks_ties(tmp_path):
    """Equal timestamps fall back to the order the scan produced, so a machine
    where the heuristic cannot discriminate behaves exactly as before. The
    names run against alphabetical order, so a sort by path would show."""
    scanned_first = _install(tmp_path / "z_first", mtime=5_000_000)
    scanned_second = _install(tmp_path / "a_second", mtime=5_000_000)
    assert _pick_live_sc_install([scanned_first, scanned_second], channel="LIVE") == scanned_first


def test_candidate_without_a_readable_p4k_loses(tmp_path):
    """A folder with a channel dir but no usable Data.p4k scores zero, so a
    real install always outranks it rather than the walk order deciding."""
    empty = str(tmp_path / "empty")
    (tmp_path / "empty" / "LIVE").mkdir(parents=True)
    real = _install(tmp_path / "real", mtime=9_000_000)
    assert _pick_live_sc_install([empty, real], channel="LIVE") == real


def test_newest_across_channels_not_just_live(tmp_path):
    """A PTU player keeps that channel current while LIVE goes stale. With no
    current copy of the active channel to go by, a root is ranked by its newest
    Data.p4k in any channel, not by LIVE alone and not by its stalest channel
    (which would invert the comparison)."""
    mixed = tmp_path / "mixed"
    _install(mixed, "PTU", mtime=8_000_000)
    _install(mixed, "EPTU", mtime=1_000_000)
    even = tmp_path / "even"
    _install(even, "PTU", mtime=5_000_000)
    _install(even, "EPTU", mtime=5_000_000)
    # Neither holds LIVE, and the scan order puts the wrong one first.
    assert _pick_live_sc_install([str(even), str(mixed)], channel="LIVE") == str(mixed)


def test_multiple_candidates_are_all_logged(tmp_path, caplog):
    """The diagnostic half. Even a wrong pick is recoverable in minutes if the
    log names what else was on the machine."""
    orphan = _install(tmp_path / "orphan", mtime=1_000_000)
    live = _install(tmp_path / "live", mtime=2_000_000)
    with caplog.at_level(logging.WARNING):
        _pick_live_sc_install([orphan, live], channel="LIVE")
    logged = "\n".join(r.message for r in caplog.records)
    assert orphan in logged and live in logged
    assert "Config tab" in logged


def test_single_candidate_does_not_warn(tmp_path, caplog):
    """One install is not ambiguous, so it must not produce a warning a user
    would reasonably read as a problem."""
    with caplog.at_level(logging.WARNING):
        _pick_live_sc_install([_install(tmp_path / "solo")], channel="LIVE")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_unreadable_root_scores_zero_rather_than_raising(tmp_path):
    """A disconnected network drive or a path that vanished mid-scan must not
    take the whole detection down with it."""
    gone = str(tmp_path / "does-not-exist")
    real = _install(tmp_path / "real", mtime=9_000_000)
    assert set(_p4k_mtimes(gone).values()) == {0.0}
    assert _pick_live_sc_install([gone, real], channel="LIVE") == real
