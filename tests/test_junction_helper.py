"""tests/junction.py makes a junction, and refuses to skip silently in CI.

Three test files make a Windows junction through ``make_junction``. These
cover what it does: a real junction that leads to its target, made first when
it is missing, and the two ways it can go wrong, Windows refusing the junction
or a link that does not lead to a folder. Either one skips the test, except
under CI, where it fails.
"""

import os
import stat
import sys

import pytest

from tests.junction import make_junction

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows only"),
]


@pytest.fixture(params=[False, True], ids=["local", "under CI"])
def ci(request, monkeypatch):
    """Runs a test without CI set and again with it, whatever this run has."""
    if request.param:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    return request.param


def _outcome(link, target):
    """What ``make_junction`` did: ``("made", None)``, ``("skip", why)`` or
    ``("fail", why)``. A skip is caught too, so a helper that skips where it
    should fail (or the reverse) fails the test instead of being skipped."""
    try:
        make_junction(link, target)
        return "made", None
    except pytest.skip.Exception as skipped:
        return "skip", skipped.msg
    except pytest.fail.Exception as failed:
        return "fail", failed.msg


def test_a_junction_leads_to_its_target(tmp_path, ci):
    """Made the same way with or without CI. The target is made when it is
    missing, the link is a junction (not a symlink), and a file written
    through it lands in the target."""
    target = tmp_path / "real" / "folder"
    link = tmp_path / "link"
    assert _outcome(link, target) == ("made", None)
    assert target.is_dir()
    assert os.lstat(link).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    (link / "file.txt").write_text("x", encoding="utf-8")
    assert (target / "file.txt").read_text(encoding="utf-8") == "x"


def test_windows_refusing_the_junction_skips_or_fails_under_ci(tmp_path, ci):
    """A real refusal: the link's name is already a folder (ERROR_ALREADY_EXISTS,
    checked by number so the test reads the same in any Windows language)."""
    link = tmp_path / "link"
    link.mkdir()
    kind, why = _outcome(link, tmp_path / "real")
    assert kind == ("fail" if ci else "skip")
    assert why.startswith("cannot make a junction here: ")
    assert "[WinError 183]" in why


def test_a_link_that_does_not_lead_to_a_folder_skips_or_fails_under_ci(
    tmp_path, monkeypatch, ci
):
    """Windows reported no error but left no folder at the link."""
    import _winapi

    monkeypatch.setattr(_winapi, "CreateJunction", lambda target, link: None)
    link = tmp_path / "link"
    kind, why = _outcome(link, tmp_path / "real")
    assert kind == ("fail" if ci else "skip")
    assert why == f"cannot make a junction here: {link} does not lead to a folder"
