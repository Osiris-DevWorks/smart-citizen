"""Pending category ticks count (#532).

On the Enhancements tab a category tick used to count only once the small
Apply button under the checkboxes saved it. Generate Enhancements built the
saved set, Apply Enhancements wrote it (and read green against it), and
leaving the tab quietly put the tick back. A user who unticked Commodities and
went straight to Generate and Apply Enhancements kept the Commodities tags in
game. The Tag Builder had the same trap until #215.

Now generation, Apply Enhancements, Export Settings and Preview Apply save
pending ticks first (EnhancementsTab.apply_pending_category_changes), leaving
the tab keeps them, closing without using them drops them, and a pending tick
keeps Apply Enhancements red. A tick lights Generate too, and ticks put back
put it back as it was. The tab
tests use a real EnhancementsTab on redirected settings, as
tests/test_tag_config_staleness_startup.py does. Some window tests drive the
real unbound methods on a stub, as tests/test_enhancements_stale_startup.py
does, and the rest build a real MainWindow (tests/gui_window.py).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QSettings

from src.gui import main_window
from src.gui.main_window import MainWindow
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from tests.gui_window import build_main_window, retire_main_window

pytestmark = [pytest.mark.unit, pytest.mark.regression]

COMMODITIES = "commodities"


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Redirect the settings store and the user data dir, which the
    enhancement files live under."""
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    AppSettings.set_user_data_dir(tmp_path / "data")
    return tmp_path


def _seed_generated_output() -> None:
    """Every enhancement INI on disk, as a past Generate leaves them."""
    enh_dir = AppSettings.get_enhancements_dir()
    enh_dir.mkdir(parents=True, exist_ok=True)
    for filename in AppSettings.ENHANCEMENTS_FILES.values():
        (enh_dir / filename).write_text("; generated\n", encoding="utf-8")


def _new_tab():
    from src.gui.enhancements_tab import EnhancementsTab
    return EnhancementsTab()


def _commodity_files(tab) -> list:
    return tab._files_for_category(COMMODITIES)


def _reloads(tab) -> list:
    """Every merge_requested the tab emits, which MainWindow answers with a
    reload."""
    emitted = []
    tab.merge_requested.connect(lambda: emitted.append(True))
    return emitted


class TestTheTabSavesPendingTicks:
    def test_a_pending_untick_is_saved_with_its_files_disabled(self, qapp, isolated_settings):
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        assert tab._apply_categories_btn.isEnabled() is True

        assert tab.apply_pending_category_changes(reload=False) is True

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False
        enh_dir = AppSettings.get_enhancements_dir()
        for fn in _commodity_files(tab):
            assert not (enh_dir / fn).exists()
            assert (enh_dir / (fn + ".disabled")).exists()
        assert tab._apply_categories_btn.isEnabled() is False
        assert reloads == []

    def test_a_pending_tick_is_saved_with_its_files_restored(self, qapp, isolated_settings):
        _seed_generated_output()
        enh_dir = AppSettings.get_enhancements_dir()
        AppSettings.set_enhancement_category_enabled(COMMODITIES, False)
        tab = _new_tab()
        for fn in _commodity_files(tab):
            (enh_dir / fn).rename(enh_dir / (fn + ".disabled"))
        tab._enhancements_checkboxes[COMMODITIES].setChecked(True)

        assert tab.apply_pending_category_changes(reload=False) is True

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        for fn in _commodity_files(tab):
            assert (enh_dir / fn).exists()
            assert not (enh_dir / (fn + ".disabled")).exists()

    def test_the_reload_follows_unless_turned_off(self, qapp, isolated_settings):
        """As the category Apply button does, so the table shows the new
        set. Generation turns it off: its finished run reloads anyway."""
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)

        assert tab.apply_pending_category_changes() is True
        assert reloads == [True]

    def test_nothing_pending_saves_and_reloads_nothing(self, qapp, isolated_settings):
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        before = sorted(p.name for p in AppSettings.get_enhancements_dir().iterdir())

        assert tab.apply_pending_category_changes() is False

        assert reloads == []
        assert sorted(p.name for p in AppSettings.get_enhancements_dir().iterdir()) == before
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True

    def test_a_tick_put_back_is_not_pending(self, qapp, isolated_settings):
        """Unticked and ticked again before anything ran: nothing differs
        from the saved set, so nothing is saved."""
        _seed_generated_output()
        tab = _new_tab()
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)
        box.setChecked(True)
        assert tab._apply_categories_btn.isEnabled() is False
        assert tab.apply_pending_category_changes() is False

    def test_the_category_apply_button_still_saves_and_reloads(self, qapp, isolated_settings):
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)

        tab._apply_category_changes()

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False
        assert reloads == [True]
        assert tab._apply_categories_btn.isEnabled() is False


class _StubGenerationWorker:
    """Stands in for EnhancementsGeneratorWorker: records what it was given,
    runs nothing."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.progress, self.progress_pct = MagicMock(), MagicMock()
        self.error, self.finished = MagicMock(), MagicMock()

    def start(self):
        pass

    def quit(self):
        pass

    def wait(self, *_args):
        return True

    def deleteLater(self):
        pass


def _generating_window(monkeypatch, tab):
    made = []

    def make_worker(**kwargs):
        made.append(_StubGenerationWorker(**kwargs))
        return made[-1]

    monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", make_worker)
    monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
    me = MagicMock()
    me.enhancements_tab = tab
    me._close_committed = False
    me._enhancements_worker = None
    # No extraction running either: one job runs at a time (#483).
    me._p4k_worker = None
    me._forge_worker = None
    me._forge_progress_dialog = None
    return me, made


class TestGenerationBuildsTheTicksOnScreen:
    def test_an_untick_not_yet_saved_is_left_out_of_the_run(
            self, qapp, isolated_settings, monkeypatch):
        """The reported case: Commodities unticked, then straight to
        Generate. The run used to build the saved set, Commodities with it."""
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        me, made = _generating_window(monkeypatch, tab)

        assert MainWindow._run_enhancements_generation(me) is True

        [worker] = made
        assert "commodity_crafting" not in worker.kwargs["categories"]
        assert worker.kwargs["categories"] == AppSettings.get_enabled_enhancement_categories()
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False
        assert reloads == [], "the finished run reloads, so no second reload here"

    @pytest.mark.parametrize("pending", [True, False])
    def test_a_failed_run_that_saved_ticks_reloads_the_table(
            self, qapp, isolated_settings, monkeypatch, pending):
        """Only a successful run reloads by itself. One that saved a pending
        untick (its files renamed) and then failed would leave the table,
        and Apply's colour, on the old set, so it reloads once."""
        _seed_generated_output()
        tab = _new_tab()
        if pending:
            tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        me, made = _generating_window(monkeypatch, tab)
        me._error_dialog_showing = False
        assert MainWindow._run_enhancements_generation(me) is True

        MainWindow._on_enhancements_generation_finished(me, False, made[0])

        assert me.perform_merge_and_reload.call_count == (1 if pending else 0)

    @pytest.mark.parametrize("pending", [True, False])
    def test_a_launch_that_saved_ticks_marks_apply_dirty(
            self, qapp, isolated_settings, monkeypatch, pending):
        """The saved set no longer matches the game, and an already-applied
        check that read the old set must not turn Apply green during the
        run. Marking Apply dirty drops its verdict."""
        _seed_generated_output()
        tab = _new_tab()
        if pending:
            tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        me, made = _generating_window(monkeypatch, tab)

        assert MainWindow._run_enhancements_generation(me) is True

        assert me._mark_apply_dirty.call_count == (1 if pending else 0)

    def test_a_launch_that_saves_a_tick_leaves_generate_clean(
            self, qapp, isolated_settings, monkeypatch):
        """Saving a tick that turns a category on keeps Generate lit, but the
        run builds it, so the launch leaves Generate clean."""
        _seed_generated_output()
        AppSettings.set_enhancement_category_enabled(COMMODITIES, False)
        tab = _new_tab()
        tab.mark_enhancements_clean()    # what the pipeline does first (#292)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(True)
        me, _made = _generating_window(monkeypatch, tab)

        assert MainWindow._run_enhancements_generation(me) is True

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert tab._enhancements_dirty is False

    def test_a_run_given_its_categories_leaves_pending_ticks_alone(
            self, qapp, isolated_settings, monkeypatch):
        """No caller passes its categories today. This pins the parameter."""
        _seed_generated_output()
        tab = _new_tab()
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        me, made = _generating_window(monkeypatch, tab)

        assert MainWindow._run_enhancements_generation(me, categories={"ship_descs"}) is True

        assert made[0].kwargs["categories"] == {"ship_descs"}
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert tab._apply_categories_btn.isEnabled() is True


class _Box:
    """QMessageBox stand-in for the real-window tests: every question answered
    Yes, nothing shown."""

    class StandardButton:
        Yes, No = 1, 2

    @staticmethod
    def question(*_args, **_kwargs):
        return _Box.StandardButton.Yes

    warning = information = critical = question


def _seed_strings(user_text: str):
    """A base.ini and user.ini for the active channel, with the sources
    pointed at them."""
    base = AppSettings.get_base_ini_path()
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text("k_one=Stock one\nk_two=Stock two\n", encoding="utf-8")
    AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(base))
    user_ini = AppSettings.get_user_ini_path()
    user_ini.parent.mkdir(parents=True, exist_ok=True)
    user_ini.write_text(user_text, encoding="utf-8")
    AppSettings.set_source_path(AppSettings.SOURCE_USER, str(user_ini))
    return user_ini


def _seed_p4k() -> None:
    """A Data.p4k, which the category question needs before it asks."""
    p4k = AppSettings.get_p4k_path()
    p4k.parent.mkdir(parents=True, exist_ok=True)
    p4k.write_bytes(b"")


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, slot_errors):
    """A real MainWindow (tests/gui_window.py), its boxes answered. A slot
    that raises (a tick's signal, a click) fails the test (slot_errors)."""
    win = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
    monkeypatch.setattr(main_window, "QMessageBox", _Box)
    try:
        yield win
        assert slot_errors == []
    finally:
        retire_main_window(win)


class TestApplyWritesTheTicksOnScreen:
    def test_pending_ticks_are_saved_after_user_ini_and_before_the_sources(
            self, tmp_path, monkeypatch):
        """Apply Enhancements re-reads the enabled categories from settings,
        so pending ticks are saved, with the table reloaded, before the
        sources. After user.ini is saved, so the reload reads the table's
        own overrides back."""
        order = []

        class FakeMessageBox:
            class StandardButton:
                Yes, No = 1, 2

            @staticmethod
            def critical(*args, **kwargs):
                order.append("failed")

            warning = information = critical

        def sources_read():
            order.append("sources")
            raise RuntimeError("stop here")

        import src.utils.user_ini_manager as user_ini_manager
        monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
        monkeypatch.setattr(main_window, "load_sources_from_settings", sources_read)
        monkeypatch.setattr(user_ini_manager, "save_user_ini",
                            lambda entries, path: order.append("user.ini") or 0)
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(tmp_path)))
        monkeypatch.setattr(AppSettings, "get_user_ini_path",
                            staticmethod(lambda: tmp_path / "user.ini"))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda: tmp_path / "game" / "global.ini"))
        me = MagicMock()
        me.entries = [object()]
        me.enhancements_tab.apply_pending_category_changes.side_effect = (
            lambda **kwargs: order.append(("categories", kwargs)) or True)

        assert MainWindow.apply_to_game(me) is False

        assert order == ["user.ini", ("categories", {}), "sources", "failed"]

    def test_a_reset_override_stays_out_of_the_game(self, window, tmp_path, monkeypatch):
        """The review's case on a real window: an override reset in memory,
        then a pending untick and Apply Enhancements. With the snapshot from
        before #531, saving the tick (and its reload) ahead of user.ini
        brought the override back from the old file, and Apply saved it and
        wrote it into the game. The reload fix keeps the reset through that
        reload too, so this passes in either order. The order itself is
        test_pending_ticks_are_saved_after_user_ini_and_before_the_sources."""
        game = tmp_path / "game" / "global.ini"
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(game.parent)))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda language=None: game))
        user_ini = _seed_strings("k_one=Mine\n")
        window.perform_merge_and_reload()
        row = next(r for r in range(window._model.rowCount())
                   if window.entries[window._entry_index_for_row(r)].key == "k_one")
        window.reset_to_original(row)
        window.enhancements_tab._enhancements_checkboxes[COMMODITIES].setChecked(False)

        assert window.apply_to_game() is True

        assert "k_one" not in user_ini.read_text(encoding="utf-8")
        assert "k_one=Stock one" in game.read_text(encoding="utf-8-sig")
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False


class TestAPendingTickLightsApply:
    """Apply Enhancements saves pending ticks first, so a pending tick is a
    change it would write: it must not stay green and greyed out."""

    def test_an_untick_turns_a_green_apply_red_and_ticking_back_checks_again(
            self, window, monkeypatch):
        checks = []
        monkeypatch.setattr(window, "_refresh_apply_dirty_after_reload",
                            lambda: checks.append("check"))
        _seed_strings("k_one=Mine\n")
        window.perform_merge_and_reload()    # the first load
        checks.clear()
        window._initial_load_done = True
        window._apply_applied_state_verdict(True)    # the game matches
        assert window.apply_btn.isEnabled() is False
        box = window.enhancements_tab._enhancements_checkboxes[COMMODITIES]

        box.setChecked(False)

        assert window.apply_btn.isEnabled() is True
        assert window._session_has_unapplied_edit is True, "closing offers Apply Now"
        assert checks == []
        box.setChecked(True)
        assert checks == ["check"], "ticks put back leave the colour to the check"

    @pytest.mark.parametrize("state", ["nothing loaded", "a load running", "closing"])
    def test_ticks_put_back_start_no_check_then(self, window, monkeypatch, state):
        """As after a blueprint scan: with nothing loaded there is nothing to
        check, a load that is running checks after its own reload, and a
        check started while closing is a thread the close no longer waits
        for."""
        checks = []
        monkeypatch.setattr(window, "_refresh_apply_dirty_after_reload",
                            lambda: checks.append("check"))
        if state != "nothing loaded":
            _seed_strings("k_one=Mine\n")
            window.perform_merge_and_reload()
            checks.clear()
        if state == "a load running":
            monkeypatch.setattr(window, "_loader_worker", object())
        elif state == "closing":
            monkeypatch.setattr(window, "_close_committed", True)
        box = window.enhancements_tab._enhancements_checkboxes[COMMODITIES]

        box.setChecked(False)
        box.setChecked(True)

        assert checks == []

    def test_a_check_cannot_turn_apply_green_over_a_pending_tick(self, window, monkeypatch):
        """The check merges the saved set, so it cannot see the tick."""
        monkeypatch.setattr(window, "_refresh_apply_dirty_after_reload", lambda: None)
        box = window.enhancements_tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)

        window._apply_applied_state_verdict(True)
        assert window.apply_btn.isEnabled() is True

        box.setChecked(True)
        window._apply_applied_state_verdict(True)
        assert window.apply_btn.isEnabled() is False    # control: nothing pending


def _generate_lit(tab) -> bool:
    return tab._generate_enhancements_btn.isEnabled()


class TestGenerateFollowsTheTicks:
    """A tick lights Generate, and ticks put back put it back as it was
    before the first one, unless another change lit it meanwhile. It used to
    stay lit, as if something had changed, while Apply Enhancements went back
    to green (the user's test of the first build). Every path that sets the
    button keeps that record up to date."""

    def test_the_users_steps_on_a_real_window(self, window, monkeypatch):
        """Apply Enhancements green and Generate grey, then a category
        unticked and ticked again: both go back."""
        monkeypatch.setattr(window, "_refresh_apply_dirty_after_reload",
                            lambda: window._apply_applied_state_verdict(True))
        _seed_strings("k_one=Mine\n")
        window.perform_merge_and_reload()    # the first load
        window._initial_load_done = True
        window._apply_applied_state_verdict(True)
        tab = window.enhancements_tab
        tab.mark_enhancements_clean()
        box = tab._enhancements_checkboxes[COMMODITIES]

        box.setChecked(False)
        assert window.apply_btn.isEnabled() is True
        assert _generate_lit(tab) is True
        box.setChecked(True)

        assert window.apply_btn.isEnabled() is False
        assert _generate_lit(tab) is False

    @pytest.mark.parametrize("lit_before", [False, True])
    def test_ticks_put_back_put_generate_back(self, qapp, isolated_settings, lit_before):
        tab = _new_tab()
        if lit_before:
            tab.mark_enhancements_dirty()
        else:
            tab.mark_enhancements_clean()
        other = next(key for key in tab._enhancements_checkboxes if key != COMMODITIES)
        commodities = tab._enhancements_checkboxes[COMMODITIES]
        second = tab._enhancements_checkboxes[other]
        commodities.setChecked(False)
        second.setChecked(not second.isChecked())
        assert _generate_lit(tab) is True

        commodities.setChecked(True)
        assert _generate_lit(tab) is True, "one tick is still pending"
        second.setChecked(not second.isChecked())

        assert _generate_lit(tab) is lit_before
        assert tab._enhancements_dirty is lit_before

    @pytest.mark.parametrize("change", ["a setting", "a global.ini extraction"])
    def test_another_change_meanwhile_keeps_it_lit(self, qapp, isolated_settings, change):
        tab = _new_tab()
        tab.mark_enhancements_clean()
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)
        if change == "a setting":
            tab._stats_prepend_check.toggle()
        else:
            tab.mark_enhancements_dirty()    # what MainWindow calls after one

        box.setChecked(True)

        assert _generate_lit(tab) is True

    @pytest.mark.parametrize("outcome, lit", [
        ("failed", True), ("left the set out of date", True), ("built a current set", False)])
    def test_a_run_ending_meanwhile_decides_what_comes_back(
            self, qapp, isolated_settings, monkeypatch, outcome, lit):
        """A tick made while a run goes on. A run that failed, or left the
        set out of date, lights Generate for another go, so putting the tick
        back keeps it lit."""
        tab = _new_tab()
        monkeypatch.setattr(tab, "_compute_initial_enhancements_dirty",
                            lambda keys=None: outcome == "left the set out of date")
        tab.mark_enhancements_clean()    # the launch (#292)
        tab.set_operation_running("Generating")
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)

        tab.set_operation_idle(outcome != "failed")
        assert _generate_lit(tab) is True, "the tick is still pending"
        box.setChecked(True)

        assert _generate_lit(tab) is lit

    @pytest.mark.parametrize("new_answer", [False, True])
    def test_a_channel_switch_meanwhile_decides_what_comes_back(
            self, qapp, isolated_settings, monkeypatch, new_answer):
        """A switch re-reads the new channel's set. A tick still pending keeps
        Generate lit, and putting it back shows the new channel's answer,
        judged on the saved categories as a finished run's is."""
        tab = _new_tab()
        asked = []

        def answer(keys=None):
            asked.append(keys)
            return new_answer

        monkeypatch.setattr(tab, "_compute_initial_enhancements_dirty", answer)
        tab.mark_enhancements_dirty()    # the old channel needed a run
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)

        tab.refresh_enhancements_dirty_state()

        assert _generate_lit(tab) is True
        assert COMMODITIES in asked[-1], "the saved set, not the ticks on screen"
        box.setChecked(True)
        assert _generate_lit(tab) is new_answer

    def test_a_run_starting_meanwhile_puts_it_back_clean(self, qapp, isolated_settings):
        """A run covers what lit Generate before the tick, so a tick still
        pending when it starts (generation saves it when it starts, after a
        DataForge extraction) comes back to a clean button."""
        tab = _new_tab()
        tab.mark_enhancements_dirty()
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)

        tab.mark_enhancements_clean()
        box.setChecked(True)

        assert _generate_lit(tab) is False

    @pytest.mark.parametrize("lit_before", [False, True])
    def test_a_saved_untick_puts_it_back(self, qapp, isolated_settings, lit_before):
        """An untick only sets its category's files aside, so saving it (Apply
        Enhancements, the category Apply) leaves nothing new to build and
        Generate shows what it showed before. It stayed lit as if a run were
        due, after Apply Now at close too (the user's test)."""
        _seed_generated_output()
        tab = _new_tab()
        if lit_before:
            tab.mark_enhancements_dirty()
        else:
            tab.mark_enhancements_clean()
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        assert _generate_lit(tab) is True

        assert tab.apply_pending_category_changes(reload=False) is True

        assert _generate_lit(tab) is lit_before

    def test_a_saved_tick_keeps_it_lit(self, qapp, isolated_settings):
        """A tick turns a category on whose files may be missing, or set
        aside from an older run, so saving it keeps Generate lit."""
        _seed_generated_output()
        AppSettings.set_enhancement_category_enabled(COMMODITIES, False)
        tab = _new_tab()
        tab.mark_enhancements_clean()
        tab._enhancements_checkboxes[COMMODITIES].setChecked(True)

        assert tab.apply_pending_category_changes(reload=False) is True

        assert _generate_lit(tab) is True

    def test_apply_now_at_close_puts_it_back(self, window, tmp_path, monkeypatch):
        """The user's test on a real window: a category unticked, then Apply
        Now when closing, which runs Apply Enhancements. The untick reaches
        the game, and Generate goes back to grey."""
        game = tmp_path / "game" / "global.ini"
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(game.parent)))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda language=None: game))
        _seed_strings("")
        window.perform_merge_and_reload()
        tab = window.enhancements_tab
        tab.mark_enhancements_clean()
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        assert _generate_lit(tab) is True

        assert window.apply_to_game() is True

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False
        assert _generate_lit(tab) is False

    def test_after_a_revert_the_old_answer_is_gone(self, qapp, isolated_settings):
        """Import Settings and the category question save new categories and
        put the boxes on them, so the answer from before the old ticks no
        longer fits, and Generate stays as it is."""
        tab = _new_tab()
        tab.mark_enhancements_clean()
        box = tab._enhancements_checkboxes[COMMODITIES]
        box.setChecked(False)
        AppSettings.set_enhancement_category_enabled(COMMODITIES, False)    # imported
        tab.revert_category_checkboxes()
        assert _generate_lit(tab) is True

        box.setChecked(True)
        box.setChecked(False)    # back to the saved set

        assert _generate_lit(tab) is True


class TestARunningJobKeepsPendingTicksPending:
    """While an extraction or a generation runs (#483) Apply Category Changes
    is locked, because saving a tick renames INIs in the folder a generation
    writes and reloads mid-run. The paths that save pending ticks for the
    user (Apply Enhancements, Export Settings, Preview Apply) must not get
    round that lock, so they save nothing then and the tick stays pending."""

    def test_a_locked_tab_saves_no_tick_and_reloads_nothing(self, qapp, isolated_settings):
        _seed_generated_output()
        tab = _new_tab()
        reloads = _reloads(tab)
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        tab.set_changes_locked(True, "a job is running")

        assert tab.apply_pending_category_changes() is False

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert tab._enhancements_checkboxes[COMMODITIES].isChecked() is False
        enh_dir = AppSettings.get_enhancements_dir()
        for fn in _commodity_files(tab):
            assert (enh_dir / fn).exists()
            assert not (enh_dir / (fn + ".disabled")).exists()
        assert reloads == []
        tab._apply_category_changes()    # the button's own net, as before
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert reloads == []
        tab.set_changes_locked(False)
        assert tab.apply_pending_category_changes(reload=False) is True    # the control
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is False

    def test_the_lock_and_the_category_apply_button(self, qapp, isolated_settings):
        tab = _new_tab()
        box = tab._enhancements_checkboxes[COMMODITIES]
        other = next(key for key in tab._enhancements_checkboxes if key != COMMODITIES)
        box.setChecked(False)
        assert tab._apply_categories_btn.isEnabled() is True

        tab.set_changes_locked(True, "a job is running")
        assert tab._apply_categories_btn.isEnabled() is False
        tab.revert_category_checkboxes([other])    # a tick pending on another category stays
        assert tab._apply_categories_btn.isEnabled() is False, "still locked"
        box.setChecked(True)
        box.setChecked(False)
        assert tab._apply_categories_btn.isEnabled() is False, "a tick does not unlock it"

        tab.set_changes_locked(False)
        assert tab._apply_categories_btn.isEnabled() is True

    @pytest.mark.parametrize("lit_before", [False, True])
    def test_locking_is_not_a_tick_change(self, qapp, isolated_settings, lit_before):
        """The lock calls the button refresh, not the tick handler, which
        would tell MainWindow the ticks changed and move Generate's record."""
        tab = _new_tab()
        if lit_before:
            tab.mark_enhancements_dirty()
        else:
            tab.mark_enhancements_clean()
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        told = []
        tab.category_ticks_changed.connect(told.append)
        record = tab._generate_dirty_without_ticks
        assert record is lit_before

        tab.set_changes_locked(True, "a job is running")
        tab.set_changes_locked(False)

        assert told == []
        assert tab._generate_dirty_without_ticks is record

    def test_apply_enhancements_keeps_the_tick_and_stays_red(self, window, tmp_path,
                                                             monkeypatch):
        """Apply Enhancements is not locked by a job, so it writes the game
        from the saved set and leaves the tick pending: the button stays red
        and closing still offers Apply Now."""
        game = tmp_path / "game" / "global.ini"
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(game.parent)))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda language=None: game))
        _seed_strings("")
        window.perform_merge_and_reload()
        tab = window.enhancements_tab
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        tab.set_changes_locked(True, "a job is running")

        assert window.apply_to_game() is True

        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert tab._enhancements_checkboxes[COMMODITIES].isChecked() is False
        assert window.apply_btn.isEnabled() is True, "red: the tick is still to be written"
        assert window._session_has_unapplied_edit is True

    def test_apply_enhancements_with_nothing_pending_goes_clean(self, window, tmp_path,
                                                                monkeypatch):
        """The control: with no tick pending, even under the lock, Apply goes
        green as it always did."""
        game = tmp_path / "game" / "global.ini"
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(game.parent)))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda language=None: game))
        _seed_strings("")
        window.perform_merge_and_reload()
        window.enhancements_tab.set_changes_locked(True, "a job is running")

        assert window.apply_to_game() is True

        assert window.apply_btn.isEnabled() is False
        assert window._session_has_unapplied_edit is False


class TestTheCategoryQuestionKeepsOtherTicks:
    def test_a_pending_tick_it_did_not_offer_stays(self, window, monkeypatch):
        """The question also comes after a channel switch or a global.ini
        extraction, and leaving the tab keeps pending ticks now. It saves the
        categories it offered, and used to reset every box to the saved set,
        dropping a tick pending on any other."""
        from PyQt6.QtWidgets import QDialog

        tab = window.enhancements_tab
        pending = tab._enhancements_checkboxes[COMMODITIES]
        pending.setChecked(False)
        offered = next(key for key in AppSettings.ENHANCEMENT_CATEGORY_FILES
                       if key != COMMODITIES)
        monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)

        window._show_enhancement_category_dialog(
            list(AppSettings.ENHANCEMENT_CATEGORY_FILES[offered]))

        assert pending.isChecked() is False
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
        assert tab._apply_categories_btn.isEnabled() is True
        assert AppSettings.get_enhancement_category_enabled(offered) is True
        assert tab._enhancements_checkboxes[offered].isChecked() is True

    def test_the_offered_box_follows_the_answer(self, window, monkeypatch):
        """An offered category the user unticks in the question is saved off,
        and the tab's box follows it, with nothing left pending."""
        from PyQt6.QtWidgets import QCheckBox, QDialog

        tab = window.enhancements_tab
        offered = next(key for key in AppSettings.ENHANCEMENT_CATEGORY_FILES
                       if key != COMMODITIES)
        assert tab._enhancements_checkboxes[offered].isChecked() is True

        def untick_the_offer(dialog):
            for box in dialog.findChildren(QCheckBox):
                box.setChecked(False)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", untick_the_offer)

        window._show_enhancement_category_dialog(
            list(AppSettings.ENHANCEMENT_CATEGORY_FILES[offered]))

        assert AppSettings.get_enhancement_category_enabled(offered) is False
        assert tab._enhancements_checkboxes[offered].isChecked() is False
        assert tab.has_pending_category_changes() is False
        assert tab._apply_categories_btn.isEnabled() is False

    def test_a_pending_untick_is_left_out_of_the_offer(self, window, monkeypatch):
        """The question ticks what it offers, so a category unticked and not
        saved came back ticked and was generated. Left out, it stays
        pending, and the generation that follows saves it off."""
        from PyQt6.QtWidgets import QCheckBox, QDialog

        _seed_strings("")
        _seed_p4k()
        tab = window.enhancements_tab
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        offered = []

        def record_the_offer(dialog):
            offered.extend(box.text() for box in dialog.findChildren(QCheckBox)
                           if box.isChecked())
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", record_the_offer)
        runs = []
        monkeypatch.setattr(window, "_run_enhancements_pipeline", lambda: runs.append(1))

        window._check_enhancements_freshness()

        label = AppSettings.ENHANCEMENT_LABELS[COMMODITIES]
        assert offered and not any(label in text for text in offered)
        assert runs == [1]
        assert tab._enhancements_checkboxes[COMMODITIES].isChecked() is False
        assert tab.has_pending_category_changes() is True

    def test_the_out_of_date_offer_leaves_out_a_pending_untick(self, window, monkeypatch):
        """Every file there, but the set not built from the current DataForge
        build: the offer is every enabled category, ticked. An untick not
        saved yet keeps its files until it is saved, so this is where it is
        left out most often."""
        from PyQt6.QtWidgets import QCheckBox, QDialog, QLabel

        _seed_strings("")
        _seed_p4k()
        _seed_generated_output()
        monkeypatch.setattr(window, "_out_of_date_build_key", lambda: "build-2")
        tab = window.enhancements_tab
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        bodies, offered = [], []

        def record_the_offer(dialog):
            bodies.extend(label.text() for label in dialog.findChildren(QLabel))
            offered.extend(box.text() for box in dialog.findChildren(QCheckBox)
                           if box.isChecked())
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", record_the_offer)
        runs = []
        monkeypatch.setattr(window, "_run_enhancements_pipeline", lambda: runs.append(1))

        window._check_enhancements_freshness()

        assert tr("extract.outdated_categories_body") in bodies
        label = AppSettings.ENHANCEMENT_LABELS[COMMODITIES]
        assert offered and label not in offered
        assert runs == [1]
        assert tab.has_pending_category_changes() is True

    def test_every_box_unticked_asks_nothing(self, window, monkeypatch):
        """Every category unticked and not saved leaves nothing to offer, so
        nothing is asked and no answer is kept for the session."""
        from PyQt6.QtWidgets import QDialog

        _seed_strings("")
        _seed_p4k()
        for box in window.enhancements_tab._enhancements_checkboxes.values():
            box.setChecked(False)
        shown = []
        monkeypatch.setattr(QDialog, "exec",
                            lambda dialog: shown.append(dialog) or QDialog.DialogCode.Accepted)
        runs = []
        monkeypatch.setattr(window, "_run_enhancements_pipeline", lambda: runs.append(1))

        window._check_enhancements_freshness()

        assert shown == [] and runs == []
        assert window._enhancements_prompt_answer is None


class TestPreviewApplyShowsTheTicksOnScreen:
    def test_preview_saves_a_pending_untick_before_it_reads(self, window, monkeypatch):
        """Preview Apply forecasts what Apply Enhancements writes, and Apply
        saves pending ticks first."""
        import src.gui.config_tab as config_tab
        import src.parser.ini_parser as ini_parser

        seen = []
        real = ini_parser.load_sources_from_settings

        def recording():
            seen.append(AppSettings.get_enhancement_category_enabled(COMMODITIES))
            return real()

        monkeypatch.setattr(config_tab, "QMessageBox", _Box)
        monkeypatch.setattr(ini_parser, "load_sources_from_settings", recording)
        window.enhancements_tab._enhancements_checkboxes[COMMODITIES].setChecked(False)

        window.config_tab._preview_btn.click()

        assert seen == [False]
        assert window.enhancements_tab._apply_categories_btn.isEnabled() is False


class TestLeavingTheTabKeepsPendingTicks:
    def test_switching_tabs_and_back_keeps_the_untick(self, window):
        """A real window: leaving the Enhancements tab used to put the tick
        back with no warning. Now it stays, unsaved, with the category Apply
        button still lit."""
        tab = window.enhancements_tab
        box = tab._enhancements_checkboxes[COMMODITIES]
        assert box.isChecked() is True
        window.tabs.setCurrentIndex(window._enhancements_tab_index)
        box.setChecked(False)

        other = 0 if window._enhancements_tab_index != 0 else 1
        window.tabs.setCurrentIndex(other)
        window.tabs.setCurrentIndex(window._enhancements_tab_index)

        assert box.isChecked() is False
        assert tab._apply_categories_btn.isEnabled() is True
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True


def _close(window, monkeypatch, prompts: list) -> None:
    """Close the real window, its unapplied-changes prompt recorded and
    answered Exit Without Applying (the second button closeEvent adds)."""
    def build(*_args):
        box = MagicMock()
        buttons = []
        box.addButton.side_effect = lambda *_a: buttons.append(MagicMock()) or buttons[-1]
        box.clickedButton.side_effect = lambda: buttons[1]
        prompts.append(box)
        return box

    monkeypatch.setattr(main_window, "QMessageBox", MagicMock(side_effect=build))
    event = MagicMock()
    window.closeEvent(event)
    event.accept.assert_called_once()


class TestClosingDropsPendingTicks:
    """A tick counts once Generate or Apply Enhancements has used it, so
    closing without either drops a pending tick and the next start shows the
    saved set: after Exit Without Applying, and with no prompt at all once a
    revert of the game file (Clear Localization, Restore Backup) has cleared
    the close reminder."""

    @pytest.mark.parametrize("prompt", ["exit without applying", "none after a revert"])
    def test_an_untick_is_dropped(self, window, monkeypatch, prompt):
        window._initial_load_done = True    # as after the first load
        tab = window.enhancements_tab
        tab._enhancements_checkboxes[COMMODITIES].setChecked(False)
        assert window._session_has_unapplied_edit is True
        if prompt == "none after a revert":
            window._mark_game_file_changed()    # what both reverts do
        prompts = []

        _close(window, monkeypatch, prompts)

        assert len(prompts) == (1 if prompt == "exit without applying" else 0)
        assert AppSettings.get_enhancement_category_enabled(COMMODITIES) is True
