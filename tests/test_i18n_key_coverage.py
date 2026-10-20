"""Static coverage guard for the #247 i18n sweep.

Scans every ``src/gui/*.py`` file for ``tr("some.key")`` call sites and
asserts each key actually resolves against ``languages/english/ui.json`` —
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

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUI_DIR = _REPO_ROOT / "src" / "gui"

# Matches tr("dotted.key") / tr('dotted.key', ...) — deliberately simple
# (a literal string first arg), same shape every call site in src/gui/
# actually uses. A dynamically-built key (an f-string or a variable) can't
# be statically resolved and is intentionally not matched.
_TR_CALL_RE = re.compile(r"""\btr\(\s*["']([a-zA-Z0-9_.]+)["']""")


def _tr_keys_in_file(path: Path) -> set[str]:
    return set(_TR_CALL_RE.findall(path.read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch):
    """Force the real English ui.json regardless of any language left active
    by another test module (i18n's module-level state persists across tests
    in the same process)."""
    saved_lang, saved_strings = i18n._current_lang, i18n._strings
    i18n.set_language("english")
    yield
    i18n._current_lang, i18n._strings = saved_lang, saved_strings


def test_every_gui_file_has_at_least_one_tr_call():
    # Sanity check the scan itself isn't silently matching nothing — every
    # widget file in this repo is i18n'd to some degree.
    gui_files = list(_GUI_DIR.glob("*.py"))
    assert gui_files, "expected src/gui/*.py files to exist"
    files_with_tr = [f for f in gui_files if _tr_keys_in_file(f)]
    assert len(files_with_tr) >= 5


@pytest.mark.parametrize("py_file", sorted(_GUI_DIR.glob("*.py")), ids=lambda p: p.name)
def test_tr_call_sites_resolve_to_real_keys(py_file: Path):
    keys = _tr_keys_in_file(py_file)
    if not keys:
        pytest.skip(f"{py_file.name} has no static tr() call sites")
    unresolved = sorted(k for k in keys if i18n.tr(k) == k)
    assert not unresolved, (
        f"{py_file.name} calls tr() with key(s) missing (or blank) in "
        f"languages/english/ui.json: {unresolved}"
    )
