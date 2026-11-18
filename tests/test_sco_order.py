"""The SCO drawer's Order section (3.1.0, ``src/gui/sco_order.py``), offscreen
with settings in ``tmp_profile``: search, add, one line per item, the summary
at the top, quality sliders, Clear's second click, Watch, the saved order."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QSlider  # noqa: E402

from src.gui.sco_order import OrderSection  # noqa: E402
from src.utils.i18n import tr  # noqa: E402
from src.utils.mining_catalog import CraftingIndex  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit]

RIFLE = {
    "k": "rifle",
    "n": "Test Rifle",
    "c": "Rifles",
    "s": [
        {"n": "Frame", "mat": "tungsten", "u": "scu", "q": 0.06, "min": 0, "m": [["int", 0]]},
        {"n": "Cabling", "mat": "gold", "u": "scu", "q": 0.02, "min": 300, "m": []},
    ],
    "p": [],
}
ARMOR = {
    "k": "armor",
    "n": "Test Armor",
    "c": "Armor",
    "s": [{"n": "Plate", "mat": "gold", "u": "scu", "q": 0.5, "min": 0, "m": []}],
    "p": [],
}


def _index() -> CraftingIndex:
    index = CraftingIndex()
    index.materials = {
        "tungsten": {"names": ["Tungsten"], "items": []},
        "gold": {"names": ["Gold"], "items": []},
    }
    index.blueprints = [ARMOR, RIFLE]
    index.stats = {"int": "Integrity"}
    index.curves = [{"s": [[0, 500, 0.9, 1.0], [500, 1000, 1.0, 1.1]], "add": False}]
    return index


@pytest.fixture
def section(qapp, tmp_profile):
    widget = OrderSection()
    widget.set_catalog(_index(), {}, lambda info: "")
    yield widget
    widget.deleteLater()


def _summary_rows(section):
    tree = section._summary_tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_no_data_says_so_and_keeps_the_saved_order(qapp, tmp_profile):
    AppSettings.set_sco_order([{"key": "rifle", "count": 2}])
    widget = OrderSection()
    widget.set_catalog(CraftingIndex(), {}, lambda info: "")
    assert widget._status.text() and widget.lines() == []
    widget.add(RIFLE)  # nothing to add to: no catalog yet
    assert AppSettings.get_sco_order() == [{"key": "rifle", "count": 2}]
    widget.set_catalog(_index(), {}, lambda info: "")
    assert [(line.key, line.count) for line in widget.lines()] == [("rifle", 2)]
    assert not widget._status.text()


def test_search_and_add_one_line_per_item(section):
    section.search.setText("test")
    results = section._results
    assert [results.item(i).text() for i in range(results.count())] == ["Test Armor", "Test Rifle"]
    section._on_result_clicked(results.item(1))
    assert section.search.text() == ""
    section.add(RIFLE)
    section.add(ARMOR)
    assert [(line.key, line.count) for line in section.lines()] == [("rifle", 2), ("armor", 1)]
    assert len(section._cards) == 2
    assert section._summary_toggle.text() == "Order summary: 2 items, 3 crafts"
    # Saved as the order changes.
    assert [row["key"] for row in AppSettings.get_sco_order()] == ["rifle", "armor"]


def test_summary_is_above_the_lines(section):
    layout = section._summary_toggle.parentWidget().layout()
    order = [layout.indexOf(w) for w in (section._summary_toggle, section.search)]
    assert order[0] < order[1]


def test_summary_totals_and_bands(section):
    section.add(RIFLE, 2)
    section.add(ARMOR)
    assert _summary_rows(section) == ["Gold: 54 cSCU", "Tungsten: 12 cSCU"]
    gold = section._summary_tree.topLevelItem(0)
    assert [gold.child(i).text(0) for i in range(gold.childCount())] == ["Quality 500+: 54 cSCU"]
    assert "Test Armor, Test Rifle" in gold.toolTip(0)
    section._toggle_volume()
    assert _summary_rows(section) == ["Gold: 0.54 SCU", "Tungsten: 0.12 SCU"]
    assert AppSettings.get_sco_order_volume() == "scu"


def test_slider_sets_quality_and_shows_the_bonus(section):
    section.add(RIFLE)
    card = section._cards[0]
    card._toggle.click()
    sliders = card.findChildren(QSlider)
    assert [s.minimum() for s in sliders] == [0, 300]
    assert all(s.focusPolicy() == Qt.FocusPolicy.NoFocus for s in sliders)
    sliders[0].setValue(1000)
    sliders[0].sliderReleased.emit()
    assert section.lines()[0].q == [1000, 500]
    assert AppSettings.get_sco_order()[0]["q"] == [1000, 500]
    assert "Integrity" in card._total_bonus.text() and "+10%" in card._total_bonus.text()


def test_count_buttons_and_remove(section):
    section.add(RIFLE)
    card = section._cards[0]
    card._step(1)
    assert section.lines()[0].count == 2
    card._step(-5)
    assert section.lines()[0].count == 1
    card.removed.emit("rifle")
    assert section.lines() == [] and section._cards == []


def test_clear_needs_a_second_click(section):
    section.add(RIFLE)
    section._clear_btn.click()
    assert section.lines() and section._clear_btn.text() == tr("sco.order_clear_confirm")
    section._clear_btn.click()
    assert section.lines() == [] and AppSettings.get_sco_order() == []
    assert section._clear_btn.text() == tr("sco.order_clear")


def test_watch_asks_for_the_order_minerals(section):
    seen = []
    section.watch_requested.connect(seen.append)
    section.add(RIFLE)
    section._watch_btn.click()
    assert seen and seen[0] == {"tungsten", "gold"}


def test_copy_puts_the_order_on_the_clipboard(section):
    section.add(RIFLE)
    section._copy_btn.click()
    text = QApplication.clipboard().text()
    assert "1 x Test Rifle" in text and "Tungsten: 6 cSCU" in text


def test_not_owned_is_marked(section):
    section.add(RIFLE)
    card = section._cards[0]
    assert card._owned.text() == tr("sco.order_not_owned")
    section.set_owned({"test rifle"})
    assert not section._cards[0]._owned.isVisibleTo(section._cards[0])


def test_only_the_search_takes_the_keyboard(section):
    from PyQt6.QtWidgets import QWidget

    section.add(RIFLE)
    section._cards[0]._toggle.click()
    takers = [
        w
        for w in section.findChildren(QWidget)
        if w.focusPolicy() != Qt.FocusPolicy.NoFocus
        and w is not section.search
        and not section.search.isAncestorOf(w)
    ]
    assert takers == []
