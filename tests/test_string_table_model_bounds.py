"""Regression test for issue #110.

StringTableModel.entry_for_row must not raise IndexError on an out-of-range
row. The view can briefly query stale rows after a failed/empty load (first
run before extraction, when the loader raises "No sources configured"), which
crashed with `IndexError: list index out of range` in flags()/entry_for_row().

Uses StringTableModel.__new__ to exercise the pure bounds logic without a
QApplication, keeping the suite Qt-free (widgets/workers are manually tested
per tests/CLAUDE.md). entry_for_row touches only the two plain list attrs, so
bypassing the QObject constructor is safe here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.string_table_model import StringTableModel  # noqa: E402
from src.models.string_model import StringEntry  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _model(entries, filtered):
    m = StringTableModel.__new__(StringTableModel)  # bypass QObject init (no QApplication)
    m._entries = entries
    m._filtered_indices = filtered
    return m


def _entry() -> StringEntry:
    return StringEntry(
        key="vehicle_NameX",
        source_file="global",
        category="Ships",
        original_value="X",
        custom_value="",
        status="Unmodified",
    )


def test_empty_model_returns_none_instead_of_indexerror():
    m = _model([], [])
    assert m.entry_for_row(0) is None
    assert m.entry_for_row(5) is None
    assert m.entry_for_row(-1) is None


def test_in_range_row_returns_entry():
    e = _entry()
    m = _model([e], [0])
    assert m.entry_for_row(0) is e


def test_just_out_of_range_returns_none():
    e = _entry()
    m = _model([e], [0])
    assert m.entry_for_row(1) is None


def test_negative_control_raw_index_would_raise():
    """Negative control for #110: the raw index entry_for_row used to do
    (``self._filtered_indices[row]``) still raises IndexError on an empty
    model — proving the danger is real — while the guarded entry_for_row
    neutralizes it by returning None."""
    m = _model([], [])
    with pytest.raises(IndexError):
        _ = m._filtered_indices[0]
    assert m.entry_for_row(0) is None
