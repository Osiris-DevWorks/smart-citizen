"""tests/inno_setup.py finds Inno Setup's compiler and refuses to skip silently in CI.

Three test files compile with ISCC.exe. Each had its own lookup, which only knew
``Inno Setup 6`` folders, so a runner with Inno Setup 7 skipped them without a
word. These cover the shared lookup (PATH first, then every ``Inno Setup *``
folder under Program Files (x86), Program Files and ``%LOCALAPPDATA%\\Programs``,
newest version first) and the three ways ``require_iscc`` can go: the compiler
is there, it is missing (the test skips) or it is missing under CI (the test
fails).

Nothing here runs a compiler. The "installs" are empty files under ``tmp_path``,
and PATH and the install-location variables are pointed at them.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.inno_setup import find_iscc, require_iscc  # noqa: E402


class _Machine:
    """A machine with no Inno Setup, that can be given some."""

    def __init__(self, tmp_path):
        self.bin = tmp_path / "bin"
        self.pf86 = tmp_path / "pf86"
        self.pf = tmp_path / "pf"
        self.local = tmp_path / "local" / "Programs"

    @staticmethod
    def _write(iscc):
        iscc.parent.mkdir(parents=True, exist_ok=True)
        iscc.write_text("not a compiler", encoding="utf-8")
        return iscc

    def add(self, root, folder):
        """An install of ``root\\folder`` with an ISCC.exe, whose path is returned."""
        return self._write(root / folder / "ISCC.exe")

    def put_on_path(self):
        return self._write(self.bin / "ISCC.exe")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    machine = _Machine(tmp_path)
    machine.bin.mkdir()
    monkeypatch.setenv("PATH", str(machine.bin))
    monkeypatch.setenv("ProgramFiles(x86)", str(machine.pf86))
    monkeypatch.setenv("ProgramFiles", str(machine.pf))
    monkeypatch.setenv("LOCALAPPDATA", str(machine.local.parent))
    monkeypatch.delenv("CI", raising=False)
    return machine


def test_a_machine_without_inno_setup_finds_nothing(machine):
    assert find_iscc() is None


def test_path_beats_every_install_folder(machine):
    on_path = machine.put_on_path()
    machine.add(machine.pf86, "Inno Setup 7")
    assert Path(find_iscc()) == on_path


@pytest.mark.parametrize("root", ["pf86", "pf", "local"])
def test_every_install_location_is_searched(machine, root):
    installed = machine.add(getattr(machine, root), "Inno Setup 6")
    assert Path(find_iscc()) == installed


def test_a_newer_version_in_any_location_beats_an_older_one(machine):
    machine.add(machine.pf86, "Inno Setup 6")
    machine.add(machine.pf86, "Inno Setup 5")
    seven = machine.add(machine.local, "Inno Setup 7")
    assert Path(find_iscc()) == seven


@pytest.mark.parametrize("older, newer", [("9", "10"), ("6", "6.7")])
def test_versions_compare_as_numbers(machine, older, newer):
    machine.add(machine.pf86, f"Inno Setup {older}")
    expected = machine.add(machine.pf86, f"Inno Setup {newer}")
    assert Path(find_iscc()) == expected


def test_one_version_in_two_places_goes_by_location_order(machine):
    machine.add(machine.local, "Inno Setup 6")
    pf = machine.add(machine.pf, "Inno Setup 6")
    assert Path(find_iscc()) == pf
    pf86 = machine.add(machine.pf86, "Inno Setup 6")
    assert Path(find_iscc()) == pf86


def test_a_folder_without_iscc_is_passed_over(machine):
    (machine.pf86 / "Inno Setup 7").mkdir(parents=True)
    six = machine.add(machine.pf86, "Inno Setup 6")
    assert Path(find_iscc()) == six


def test_a_folder_that_is_not_inno_setup_is_ignored(machine):
    machine.add(machine.pf86, "Some Other Tool 7")
    assert find_iscc() is None


def test_a_bracket_in_an_install_location_is_not_read_as_a_pattern(machine, monkeypatch, tmp_path):
    # A profile folder such as C:\Users\Jo[e] must not be taken for a glob pattern.
    root = tmp_path / "br[a]cket"
    installed = machine.add(root, "Inno Setup 6")
    monkeypatch.setenv("ProgramFiles", str(root))
    assert Path(find_iscc()) == installed


def test_a_location_that_is_not_set_is_skipped(machine, monkeypatch):
    machine.add(machine.pf86, "Inno Setup 6")
    monkeypatch.delenv("ProgramFiles")
    monkeypatch.delenv("LOCALAPPDATA")
    assert Path(find_iscc()) == machine.pf86 / "Inno Setup 6" / "ISCC.exe"
    monkeypatch.delenv("ProgramFiles(x86)")
    assert find_iscc() is None


def _outcome():
    """What ``require_iscc`` did: ``("path", the path)``, ``("skip", why)`` or
    ``("fail", why)``. A skip is caught too, so a require that skips where it
    should fail (or the reverse) fails the test instead of being skipped."""
    try:
        return "path", require_iscc()
    except pytest.skip.Exception as skipped:
        return "skip", skipped.msg
    except pytest.fail.Exception as failed:
        return "fail", failed.msg


@pytest.mark.parametrize("ci", [False, True])
def test_require_returns_the_compiler_when_it_is_there(machine, monkeypatch, ci):
    if ci:
        monkeypatch.setenv("CI", "true")
    installed = machine.add(machine.pf86, "Inno Setup 6")
    kind, found = _outcome()
    assert kind == "path"
    assert Path(found) == installed


def test_require_skips_the_test_when_inno_setup_is_missing(machine):
    kind, why = _outcome()
    assert kind == "skip"
    assert "ISCC.exe" in why


def test_require_fails_the_test_under_ci_when_inno_setup_is_missing(machine, monkeypatch):
    monkeypatch.setenv("CI", "true")
    kind, why = _outcome()
    assert kind == "fail"
    assert "ISCC.exe" in why
    assert "CI" in why
