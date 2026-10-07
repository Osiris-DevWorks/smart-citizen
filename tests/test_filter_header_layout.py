"""FilterHeaderView's label/filter split must survive transient layout passes.

The header draws column labels on top and a row of QLineEdit filters below,
splitting at ``QHeaderView.sizeHint().height()``. That value momentarily
reports 0 during transient layout passes, and a model reset (any reload:
Apply Enhancements, a merge, a language change) is one of them.

Reading it right then placed every filter editor at y=0, directly on top of
the column labels, and nothing put them back: the only recovery path was
``sectionResized``, so a reload that happened to produce identical column
widths left the filter row covering the header until the user resized
something by hand. Reported from a real first run of Generate Enhancements.

``_label_row_height()`` caches the last non-zero height and every consumer
(editor placement, label painting, the filter-band tint, and the mouse
y-gate) goes through it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PyQt6.QtGui import QStandardItemModel  # noqa: E402
from PyQt6.QtWidgets import QApplication, QHeaderView, QTableView  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.gui.filter_header import FilterHeaderView  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

COLUMNS = ["Category", "Key", "Default", "Current"]


@pytest.fixture
def header(qapp):
    table = QTableView()
    table.setModel(QStandardItemModel(3, len(COLUMNS)))
    hdr = FilterHeaderView(COLUMNS, table, skip_columns={0})
    table.setHorizontalHeader(hdr)
    table.resize(800, 300)
    table.show()
    QApplication.processEvents()
    yield hdr
    table.close()


def _editor_ys(hdr):
    return {e.y() for e in hdr._filters if e is not None}


def test_editors_sit_below_the_labels(header):
    label_h = header._label_row_height()
    assert label_h > 0
    assert _editor_ys(header) == {label_h}


def test_label_height_survives_a_collapsed_size_hint(header, monkeypatch):
    """The bug: sizeHint collapses to 0 mid-reset, the editors are placed at
    y=0 over the labels, and nothing moves them back."""
    good = header._label_row_height()
    assert good > 0

    monkeypatch.setattr(QHeaderView, "sizeHint", lambda self: type(self.size())(0, 0))
    assert header._label_row_height() == good      # falls back, never 0

    header._position_editors()
    assert _editor_ys(header) == {good}            # not {0}


def test_position_editors_is_a_noop_before_a_real_height(qapp, monkeypatch):
    """Never seen a real height yet: lay nothing out rather than stack the
    editors on the labels."""
    table = QTableView()
    table.setModel(QStandardItemModel(3, len(COLUMNS)))
    monkeypatch.setattr(QHeaderView, "sizeHint", lambda self: type(self.size())(0, 0))
    hdr = FilterHeaderView(COLUMNS, table, skip_columns={0})
    assert hdr._label_row_height() == 0
    hdr._position_editors()                        # must not raise
    table.close()


def test_editors_track_a_column_resize(header):
    """Each filter box stays exactly as wide as the column it filters."""
    header.resizeSection(1, 260)
    QApplication.processEvents()
    editor = header._filters[1]
    assert editor.x() == header.sectionPosition(1) - header.offset()
    assert editor.width() == header.sectionSize(1)
    assert editor.y() == header._label_row_height()


def test_editors_keep_their_row_through_a_model_reset(header):
    """The reported repro: a reload must not leave the filter row on top of
    the column names."""
    label_h = header._label_row_height()
    table = header.parent()
    table.model().setRowCount(50)          # emits a reset through the header
    QApplication.processEvents()
    assert _editor_ys(header) == {label_h}


def test_skipped_columns_have_no_editor(header):
    assert header._filters[0] is None
    assert all(e is not None for e in header._filters[1:])


# ── Horizontal-scroll hook ──────────────────────────────────────────────────
#
# The editors follow a horizontal scroll by hooking the view's scrollbar.
# Binding that QScrollBar once at construction would go dead if the view ever
# swapped it, so the hook re-checks from updateGeometries. The rebind then had
# a bug of its own: setHorizontalScrollBar *destroys* the bar it replaces, so
# disconnecting the old one raises RuntimeError ("wrapped C/C++ object ... has
# been deleted"), which a TypeError-only guard let escape straight out of a Qt
# layout callback. Swapping the bar is the exact case the rebind exists for,
# so it turned a silent degradation into a crash.

def test_scroll_hook_survives_the_view_swapping_its_scrollbar(header):
    from PyQt6.QtWidgets import QScrollBar

    table = header.parent()
    old = header._scroll_bar
    assert old is not None

    table.setHorizontalScrollBar(QScrollBar())   # destroys the old bar
    QApplication.processEvents()

    header.updateGeometries()                    # must not raise
    assert header._scroll_bar is table.horizontalScrollBar()
    assert header._scroll_bar is not old


def test_editors_follow_a_scroll_on_the_replacement_scrollbar(header):
    """Rebinding is only worth anything if the new bar actually drives the
    editors."""
    from PyQt6.QtWidgets import QScrollBar

    table = header.parent()
    table.setHorizontalScrollBar(QScrollBar())
    QApplication.processEvents()
    header.updateGeometries()

    for column in range(header.count()):
        header.resizeSection(column, 400)        # force real overflow
    QApplication.processEvents()

    bar = table.horizontalScrollBar()
    bar.setValue(bar.maximum())
    QApplication.processEvents()

    editor = header._filters[1]
    assert editor.x() == header.sectionPosition(1) - header.offset()
