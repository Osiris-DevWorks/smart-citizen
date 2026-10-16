"""A Windows junction, for the tests that need one.

A junction is a folder that leads to another folder, the usual way to move a
big folder off C:. Four test files make theirs here: ``test_install_scanner``
(a library that only a junction at the top of a drive reaches),
``test_sc_install_root`` (an install moved off C: with a junction left at its
old path), ``test_pending_cache_cleanup`` (a junction to the DataForge cache
in use) and ``test_config_tab_cache_folder`` (a junction typed as the
DataForge cache folder, #494). The first three each used to carry their own
copy of the skip-or-fail block below. The first two made the junction with
cmd's ``mklink /J``, which makes the same junction as
``_winapi.CreateJunction``. ``test_installer_wipe_safety``
makes its own junctions inside its probe's case setup, where a failure is an
error rather than a skip, and does not use this.

``make_junction`` makes one. Any account can, so where Windows refuses it skips
the test, except under CI, where it fails: a broken runner must turn these
checks red, not into skips nobody reads. GitHub Actions sets ``CI=true``, which
``inno_setup.require_iscc`` relies on too.
"""

import os
from pathlib import Path

import pytest


def make_junction(link: Path, target: Path) -> None:
    """Make *link* a junction to *target*, making *target* first when it is
    missing. *link*'s folder must exist and *link* itself must not. Where
    Windows refuses, or the link does not lead to a folder, this skips the
    calling test, or fails it when the ``CI`` environment variable is set."""
    import _winapi  # Windows only, like every test that calls this

    target.mkdir(parents=True, exist_ok=True)
    try:
        _winapi.CreateJunction(str(target), str(link))
        why = "" if link.is_dir() else f"{link} does not lead to a folder"
    except OSError as exc:
        why = str(exc)
    if why:
        reason = f"cannot make a junction here: {why}"
        if os.environ.get("CI"):
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)
