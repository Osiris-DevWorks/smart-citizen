"""The branding labels must never absorb spare vertical height.

A QLabel defaults to a Preferred vertical policy, which lets it grow. In
Simple mode the view stack is capped (so the hidden Advanced page can't
reserve height nothing is using), which means the stack cannot take spare
height itself. Qt then handed it to whatever else could grow, and that was
these two labels: measured on a maximised window, the title and tagline each
ballooned from their 35px and 15px hints to 343px, leaving the title stranded
at the top with a few hundred pixels of nothing before the tagline.

The fix is a Fixed vertical policy on both. It is one declarative line in
setup_ui, so without this test a regression that dropped it would reinstate
the reported bug with the whole rest of the suite still green.

This is one of only two test files that build a real MainWindow (see also
tests/test_tab_scrollbar_placement.py). It is worth the cost here because the
bug is a property of the assembled window: the stub used elsewhere in
tests/test_ui_mode.py has no branding labels and no content layout to
distribute height through, so it cannot observe this at all. Settings,
user-data and cache directories are all redirected to tmp_path so the
construction touches nothing real.

The ``window`` fixture below is module-scoped for the same reason
tests/test_tab_scrollbar_placement.py's is: see tests/gui_window.py for why
building one per test destabilised the whole run. Keep it that way rather
than reverting to a function-scoped fixture per test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QSizePolicy  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import AppSettings  # noqa: E402
from tests.gui_window import build_main_window, retire_main_window  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """A real MainWindow in Simple mode, fully redirected to a tmp dir.

    Module-scoped on purpose, matching
    tests/test_tab_scrollbar_placement.py: building one per test (there are
    three in this file) tripled this file's contribution to the real
    MainWindow count kept alive for the rest of the run in
    tests/gui_window.py's ``_LIVE_WINDOWS``, which is exactly the exposure
    that module warns destabilises the suite.

    ``show()`` + ``resize(1200, 1000)`` happen once here, not per-test (#390
    review): Qt's ``resize()`` is a no-op when the target size already
    matches the current size, so a second test resizing to the same value
    doesn't re-settle anything -- it silently reads state a prior test
    already established, coupling two tests that should be independent.
    Settling once here, before any test runs, matches
    tests/test_tab_scrollbar_placement.py's own fixture. Safe for both
    labels' ``sizeHint()`` either way: neither has word wrap on, so the hint
    is intrinsic to font/text, not window geometry.

    MonkeyPatch.context() rather than the bare ``monkeypatch`` fixture for
    the same reason as tests/test_tab_scrollbar_placement.py: it is
    module-scoped so the function-scoped fixture can't be used, and the
    context manager's undo runs even if construction raises.
    """
    tmp = tmp_path_factory.mktemp("branding_labels")
    with pytest.MonkeyPatch.context() as patch:
        win = build_main_window(tmp, patch, AppSettings.UI_MODE_SIMPLE)
        win.show()
        win.resize(1200, 1000)
        for _ in range(8):
            qapp.processEvents()
        yield win
        retire_main_window(win)


def _labels(win):
    return (win.title_label, win.tagline_label)


def test_branding_labels_have_a_fixed_height_policy(window):
    for label in _labels(window):
        assert label.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed


def test_branding_labels_do_not_grow_with_the_window(window):
    """The behaviour, not just the policy: at a tall window (the fixture's
    1200x1000) neither label may exceed the height of its own text."""
    for label in _labels(window):
        assert label.height() == label.sizeHint().height()


def test_tagline_stays_directly_under_the_title(window):
    """The visible symptom was the pair being torn apart, so pin the gap to
    the layout's own spacing rather than an arbitrary tolerance."""
    spacing = window._content_widget.layout().spacing()
    title, tagline = _labels(window)
    gap = tagline.y() - (title.y() + title.height())
    assert gap == spacing
