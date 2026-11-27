"""The Ships per type dropdown on the Enhancements tab (3.1.0).

Beside the Hostiles box, it sets how many ships each type lists under a
mission's Ship types: 4, 8 (the default), 16, 32, 64, 128 or All. A bigger
type lists (n - 2) / 2 ships at each end and counts the rest. These lock the
setting, the dropdown's place, wording and greying, and that the window hands
the choice to the generator. The text itself is in ``test_mission_ships.py``.
"""

from __future__ import annotations

import pytest

from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

CHOICES = ["4", "8", "16", "32", "64", "128", "all"]


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    AppSettings.set_user_data_dir(tmp_path / "data")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestSetting:
    def test_eight_by_default_and_saved(self, json_backend):
        assert AppSettings.get_ships_per_type() == "8"
        AppSettings.set_ships_per_type("all")
        assert AppSettings.get_ships_per_type() == "all"
        AppSettings.set_ships_per_type(16)
        assert AppSettings.get_ships_per_type() == "16"

    def test_anything_else_reads_and_saves_as_eight(self, json_backend):
        json_backend.setValue(AppSettings.SHIPS_PER_TYPE, "12")
        assert AppSettings.get_ships_per_type() == "8"
        AppSettings.set_ships_per_type("256")
        assert json_backend.value(AppSettings.SHIPS_PER_TYPE) == "8"

    def test_the_old_simple_or_all_choice_is_left_behind(self, json_backend):
        # Everyone starts at 8 after the update, whatever they had picked.
        json_backend.setValue("mission_field/hostiles_detail", "all")
        assert AppSettings.get_ships_per_type() == "8"

    def test_a_settings_backup_carries_it(self):
        defaults = AppSettings.profile_default_values()
        assert defaults[AppSettings.SHIPS_PER_TYPE] == "8"


class TestDropdown:
    def _tab(self):
        from src.gui.enhancements_tab import EnhancementsTab

        return EnhancementsTab()

    def test_its_label_and_it_sit_right_after_the_hostiles_box(self, qapp, json_backend):
        tab = self._tab()
        box = tab._mission_field_checkboxes["spawns"]
        layout = box.parentWidget().layout()
        row = next(
            layout.itemAt(i).layout()
            for i in range(layout.count())
            if layout.itemAt(i).layout() is not None
            and layout.itemAt(i).layout().indexOf(box) >= 0
        )
        assert row.indexOf(tab._ships_per_type_label) == row.indexOf(box) + 1
        assert row.indexOf(tab._ships_per_type_combo) == row.indexOf(box) + 2
        assert tab._ships_per_type_label.text() == "Ships per type"

    def test_its_choices_and_default(self, qapp, json_backend):
        combo = self._tab()._ships_per_type_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "4", "8", "16", "32", "64", "128", "All",
        ]
        assert [combo.itemData(i) for i in range(combo.count())] == CHOICES
        assert combo.currentData() == "8"

    def test_a_choice_saves_and_lights_generate(self, qapp, json_backend):
        tab = self._tab()
        tab.mark_enhancements_clean()
        tab._ships_per_type_combo.setCurrentIndex(CHOICES.index("all"))
        assert AppSettings.get_ships_per_type() == "all"
        assert tab._enhancements_dirty is True

    def test_the_saved_choice_is_shown(self, qapp, json_backend):
        AppSettings.set_ships_per_type("32")
        assert self._tab()._ships_per_type_combo.currentData() == "32"

    def test_greyed_out_while_hostiles_is_unticked(self, qapp, json_backend):
        tab = self._tab()
        box = tab._mission_field_checkboxes["spawns"]
        widgets = (tab._ships_per_type_label, tab._ships_per_type_combo)
        assert all(w.isEnabled() for w in widgets)
        box.setChecked(False)
        assert not any(w.isEnabled() for w in widgets)
        box.setChecked(True)
        assert all(w.isEnabled() for w in widgets)

    def test_greyed_out_from_the_start_when_hostiles_was_unticked(
        self, qapp, json_backend
    ):
        AppSettings.set_mission_detail_field("spawns", False)
        tab = self._tab()
        assert not tab._ships_per_type_combo.isEnabled()
        assert not tab._ships_per_type_label.isEnabled()

    def test_a_language_switch_translates_it(self, qapp, json_backend):
        from src.utils.i18n import set_language

        tab = self._tab()
        set_language("german")
        try:
            tab.retranslate_ui()
            combo = tab._ships_per_type_combo
            assert tab._ships_per_type_label.text() == "Schiffe pro Typ"
            assert combo.itemText(0) == "4"
            assert combo.itemText(combo.count() - 1) == "Alle"
        finally:
            set_language("english")
            tab.retranslate_ui()


class TestHandedToTheGenerator:
    def test_the_worker_passes_it_on(self):
        from src.gui.workers import EnhancementsGeneratorWorker

        worker = EnhancementsGeneratorWorker(ships_per_type="all")
        assert worker.ships_per_type == "all"
        assert EnhancementsGeneratorWorker().ships_per_type == "8"

    def test_the_window_reads_the_setting(self):
        import ast
        import inspect

        from src.gui import main_window

        tree = ast.parse(inspect.getsource(main_window))
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "EnhancementsGeneratorWorker"
        ]
        assert calls, "no EnhancementsGeneratorWorker(...) call found"
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            assert "ships_per_type" in kw
            assert ast.unparse(kw["ships_per_type"]) == "AppSettings.get_ships_per_type()"
