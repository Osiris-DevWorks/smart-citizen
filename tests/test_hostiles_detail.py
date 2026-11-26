"""The Hostiles dropdown on the Enhancements tab (3.1.0).

Beside the Hostiles box, Simple (the default) shortens a pool of more than
10 ships to its type, and All Ship Details lists every ship. These lock the
setting, the dropdown's place, wording and greying, and that the window hands
the choice to the generator. The text itself is in ``test_mission_ships.py``.
"""

from __future__ import annotations

import pytest

from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    AppSettings.set_user_data_dir(tmp_path / "data")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestSetting:
    def test_simple_by_default_and_saved(self, json_backend):
        assert AppSettings.get_hostiles_detail() == "simple"
        AppSettings.set_hostiles_detail("all")
        assert AppSettings.get_hostiles_detail() == "all"

    def test_anything_else_reads_and_saves_as_simple(self, json_backend):
        json_backend.setValue(AppSettings.HOSTILES_DETAIL, "everything")
        assert AppSettings.get_hostiles_detail() == "simple"
        AppSettings.set_hostiles_detail("nonsense")
        assert json_backend.value(AppSettings.HOSTILES_DETAIL) == "simple"

    def test_a_settings_backup_carries_it(self):
        defaults = AppSettings.profile_default_values()
        assert defaults[AppSettings.HOSTILES_DETAIL] == "simple"


class TestDropdown:
    def _tab(self):
        from src.gui.enhancements_tab import EnhancementsTab

        return EnhancementsTab()

    def test_it_sits_right_after_the_hostiles_box(self, qapp, json_backend):
        tab = self._tab()
        box = tab._mission_field_checkboxes["spawns"]
        layout = box.parentWidget().layout()
        row = next(
            layout.itemAt(i).layout()
            for i in range(layout.count())
            if layout.itemAt(i).layout() is not None
            and layout.itemAt(i).layout().indexOf(box) >= 0
        )
        assert row.indexOf(tab._hostiles_detail_combo) == row.indexOf(box) + 1

    def test_its_choices_and_default(self, qapp, json_backend):
        combo = self._tab()._hostiles_detail_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "Simple",
            "All Ship Details",
        ]
        assert [combo.itemData(i) for i in range(combo.count())] == ["simple", "all"]
        assert combo.currentData() == "simple"

    def test_a_choice_saves_and_lights_generate(self, qapp, json_backend):
        tab = self._tab()
        tab.mark_enhancements_clean()
        tab._hostiles_detail_combo.setCurrentIndex(1)
        assert AppSettings.get_hostiles_detail() == "all"
        assert tab._enhancements_dirty is True

    def test_the_saved_choice_is_shown(self, qapp, json_backend):
        AppSettings.set_hostiles_detail("all")
        assert self._tab()._hostiles_detail_combo.currentData() == "all"

    def test_greyed_out_while_hostiles_is_unticked(self, qapp, json_backend):
        tab = self._tab()
        box = tab._mission_field_checkboxes["spawns"]
        combo = tab._hostiles_detail_combo
        assert combo.isEnabled()
        box.setChecked(False)
        assert not combo.isEnabled()
        box.setChecked(True)
        assert combo.isEnabled()

    def test_greyed_out_from_the_start_when_hostiles_was_unticked(
        self, qapp, json_backend
    ):
        AppSettings.set_mission_detail_field("spawns", False)
        assert not self._tab()._hostiles_detail_combo.isEnabled()

    def test_a_language_switch_translates_it(self, qapp, json_backend):
        from src.utils.i18n import set_language

        tab = self._tab()
        set_language("german")
        try:
            tab.retranslate_ui()
            combo = tab._hostiles_detail_combo
            assert [combo.itemText(i) for i in range(combo.count())] == [
                "Einfach",
                "Alle Schiffsdetails",
            ]
        finally:
            set_language("english")
            tab.retranslate_ui()


class TestHandedToTheGenerator:
    def test_the_worker_passes_it_on(self, monkeypatch):
        from src.gui.workers import EnhancementsGeneratorWorker

        worker = EnhancementsGeneratorWorker(hostiles_detail="all")
        assert worker.hostiles_detail == "all"
        assert EnhancementsGeneratorWorker().hostiles_detail == "simple"

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
            assert "hostiles_detail" in kw
            assert (
                ast.unparse(kw["hostiles_detail"])
                == "AppSettings.get_hostiles_detail()"
            )
