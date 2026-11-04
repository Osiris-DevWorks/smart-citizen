"""Static coverage guard for the #247 i18n sweep.

Scans every ``src/gui/*.py`` file, and ``src/utils/pak_extractor.py`` (its
extraction errors carry user-ready messages built with tr(), #482), for
``tr("some.key")`` call sites and asserts each key actually resolves against
``languages/english/ui.json`` —
present, and not an empty leaf that would silently fall back to the bare
key string. Catches the exact class of bug #247 was filed over: a literal
that looks translated (wrapped in ``tr()``) but whose key was never added
to the English base, so it renders as the raw dotted key instead of text.

Purely static (regex + JSON, no Qt import), so it runs without pytest-qt
and isn't subject to the GUI-code test exemption — there's no widget to
instantiate here, just a source/data consistency check.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import i18n  # noqa: E402

# english_ui (tests/conftest.py): the real English ui.json, whatever language
# another test module left active.
pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.usefixtures("english_ui")]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUI_DIR = _REPO_ROOT / "src" / "gui"
# Raises user-ready messages built with tr() on the worker thread (#482).
_PAK_EXTRACTOR = _REPO_ROOT / "src" / "utils" / "pak_extractor.py"
_SCANNED_FILES = sorted(_GUI_DIR.glob("*.py")) + [_PAK_EXTRACTOR]

# Matches tr("dotted.key") / tr('dotted.key', ...) — deliberately simple
# (a literal string first arg), same shape every call site in src/gui/
# actually uses. A dynamically-built key (an f-string or a variable) can't
# be statically resolved and is intentionally not matched.
_TR_CALL_RE = re.compile(r"""\btr\(\s*["']([a-zA-Z0-9_.]+)["']""")


def _tr_keys_in_file(path: Path) -> set[str]:
    return set(_TR_CALL_RE.findall(path.read_text(encoding="utf-8")))


def test_every_gui_file_has_at_least_one_tr_call():
    # Sanity check the scan itself isn't silently matching nothing — every
    # widget file in this repo is i18n'd to some degree.
    gui_files = list(_GUI_DIR.glob("*.py"))
    assert gui_files, "expected src/gui/*.py files to exist"
    files_with_tr = [f for f in gui_files if _tr_keys_in_file(f)]
    assert len(files_with_tr) >= 5


def test_pak_extractor_is_scanned_and_has_tr_calls():
    # Its keys were unchecked before #482, and its free-space messages are
    # built from several keys, so a scan that matched nothing there would
    # hide a missing one.
    assert _PAK_EXTRACTOR in _SCANNED_FILES
    assert "extract.no_space_drive" in _tr_keys_in_file(_PAK_EXTRACTOR)


@pytest.mark.parametrize("py_file", _SCANNED_FILES, ids=lambda p: p.name)
def test_tr_call_sites_resolve_to_real_keys(py_file: Path):
    keys = _tr_keys_in_file(py_file)
    if not keys:
        pytest.skip(f"{py_file.name} has no static tr() call sites")
    unresolved = sorted(k for k in keys if i18n.tr(k) == k)
    assert not unresolved, (
        f"{py_file.name} calls tr() with key(s) missing (or blank) in "
        f"languages/english/ui.json: {unresolved}"
    )
