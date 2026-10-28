"""#330 follow-up: toggle_favorite's removal path for stranded favorites.

#329/#330 restricted favoriting to ship/vehicle NAME rows, but favorites made
on description rows by older builds keep the prefix on custom_value (still
applied to the game text) while losing the star click and the context-menu
affordance. toggle_favorite now sheds a stranded prefix from any row; adding
stays name-row only. Driven on a lightweight stub self (no QApplication),
same pattern as test_ui_mode's _apply_ui_mode tests.
"""
import pytest

from src.gui.main_window import MainWindow
from src.models.string_model import StringEntry
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


def _entry(key, category="Ships", original="v", custom=""):
    return StringEntry(
        key=key,
        source_file="global",
        category=category,
        original_value=original,
        custom_value=custom,
        status="Modified" if custom else "Unmodified",
    )


class _ModelStub:
    def __init__(self):
        self.changed = []

    def notify_entry_changed(self, idx):
        self.changed.append(idx)


class _Stub:
    """Carries just what toggle_favorite touches."""

    def __init__(self, entries):
        self.entries = entries
        # The stock base source the rows come from: a cleared row's status
        # is read against it (status_without_override).
        self.default_values = {e.key: e.original_value for e in entries}
        self._model = _ModelStub()

    def _entry_index_for_row(self, row):
        return row

    def toggle(self, row=0):
        MainWindow.toggle_favorite(self, row)


@pytest.fixture(autouse=True)
def star_prefix(monkeypatch):
    monkeypatch.setattr(AppSettings, "get_favorite_prefix", staticmethod(lambda: "*"))


def test_stranded_description_prefix_is_removable():
    stub = _Stub([_entry("vehicle_DescANVL_Carrack", original="Lore", custom="*Lore")])
    stub.toggle()
    assert stub.entries[0].custom_value == ""
    assert stub.entries[0].status == "Unmodified"
    assert stub._model.changed == [0]


def test_stranded_removal_keeps_a_real_custom_edit():
    stub = _Stub(
        [_entry("vehicle_DescANVL_Carrack", original="Stock", custom="*My lore")]
    )
    stub.toggle()
    assert stub.entries[0].custom_value == "My lore"
    assert stub.entries[0].status == "Modified"


def test_stranded_removal_works_outside_the_ships_category():
    stub = _Stub(
        [_entry("item_NameSHLD_Aspirum", category="Components", original="Aspirum", custom="*Aspirum")]
    )
    stub.toggle()
    assert stub.entries[0].custom_value == ""


def test_description_without_prefix_cannot_be_favorited():
    stub = _Stub([_entry("vehicle_DescANVL_Carrack", original="Lore")])
    stub.toggle()
    assert stub.entries[0].custom_value == ""
    assert stub._model.changed == []


def test_name_row_add_and_remove_still_work():
    stub = _Stub([_entry("vehicle_NameANVL_Carrack", original="Carrack")])
    stub.toggle()
    assert stub.entries[0].custom_value == "*Carrack"
    assert stub.entries[0].status == "Modified"
    stub.toggle()
    assert stub.entries[0].custom_value == ""
    assert stub.entries[0].status == "Unmodified"


def test_removing_a_favourite_from_an_enhanced_name_reads_enhanced():
    """The row's value comes from the enhancements, so with the favourite
    gone it reads as a load would show it, not Unmodified (#531)."""
    entry = _entry("vehicle_NameANVL_Carrack", original="Carrack [S3]", custom="*Carrack [S3]")
    entry.source_file = AppSettings.SOURCE_ENHANCEMENTS
    stub = _Stub([entry])
    stub.toggle()
    assert stub.entries[0].custom_value == ""
    assert stub.entries[0].status == "Enhanced"


def test_empty_prefix_never_touches_non_name_rows(monkeypatch):
    """startswith('') is True for everything; the stranded path must not turn
    that degenerate prefix into a value-clearing no-op on description rows."""
    monkeypatch.setattr(AppSettings, "get_favorite_prefix", staticmethod(lambda: ""))
    stub = _Stub([_entry("vehicle_DescANVL_Carrack", original="Lore", custom="Lore")])
    stub.toggle()
    assert stub.entries[0].custom_value == "Lore"
    assert stub._model.changed == []


def test_out_of_range_row_is_a_noop():
    stub = _Stub([])
    stub.toggle(5)
    assert stub._model.changed == []
