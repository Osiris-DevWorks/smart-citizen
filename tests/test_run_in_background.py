"""#483: Run in Background for the DataForge extraction, and the job lock that
makes a usable window safe while a job runs.

Esc or the X on the DataForge dialog asks Stop, Run in Background or Cancel
(the question itself is in test_extraction_stop.py's TestStopPrompt). With the
window usable during a run, and with a generation whose dialog was hidden,
changing what the job depends on used to pull it out from under the run: a
cache folder change deleted the cache the run had just built, a language or
channel switch generated from a cache being wiped, Apply Category Changes
renamed INIs in the folder a generation was writing, and Import Settings or an
update started a second copy beside one still finishing. Now one job runs at a
time (a global.ini extraction, a DataForge extraction or a generation), and
while any of them runs, shown or not, the Config tab's game, data and cache
folders, channel, language, Map Language File, global.ini Extract, install
scan, Import Settings and Check for Updates, the Enhancements tab's Apply
Category Changes, Save Tag Changes and Generate Enhancements and the Simple
page's button are locked with the reason shown. The finished slot also checks
the run still matches the settings before it clears the old cache or chains
generation, as the net behind the lock, and the startup questions a job
would make unsafe (the post-import Apply Now, the OneDrive warning's Move)
are put off and asked again once it is over.

The lock is checked on a real MainWindow (tests/gui_window.py), and the cases
from the issue on the real methods with a MagicMock self.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import src.gui.main_window as main_window  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.i18n import tr  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from tests.gui_window import build_main_window, retire_main_window  # noqa: E402

pytestmark = pytest.mark.unit

REASON = tr("extract.locked_while_job_runs")
JOBS = ["_p4k_worker", "_forge_worker", "_enhancements_worker"]


# ── The lock on a real window ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("run_in_background")
    with pytest.MonkeyPatch.context() as patch:
        win = build_main_window(tmp, patch, AppSettings.UI_MODE_ADVANCED)
        yield win
        for attr in JOBS:
            setattr(win, attr, None)
        win._refresh_job_lock()
        retire_main_window(win)


def _config_controls(win) -> list:
    tab = win.config_tab
    return tab._job_locked_controls() + [tab._dupe_check_btn, tab._check_updates_btn]


class TestTheLock:
    @pytest.mark.parametrize("job", JOBS)
    def test_any_running_job_locks_what_it_depends_on(self, window, job):
        """Whichever of the three jobs runs, the Config tab's locations, the
        category Apply and the Simple page's button are locked with the
        reason shown, and all come back when it ends."""
        tab, enh, simple = window.config_tab, window.enhancements_tab, window.simple_page
        setattr(window, job, object())
        try:
            window._refresh_job_lock()
            assert [w for w in _config_controls(window) if w.isEnabled()] == []
            assert not tab._job_lock_label.isHidden()
            assert tab._job_lock_label.text() == REASON
            assert not enh._apply_categories_btn.isEnabled()
            assert enh._apply_categories_btn.toolTip() == REASON
            assert not enh._apply_tag_btn.isEnabled()
            assert enh._apply_tag_btn.toolTip() == REASON
            assert not simple.generate_apply_btn.isEnabled()
            assert simple.generate_apply_btn.toolTip() == REASON
        finally:
            setattr(window, job, None)
            window._refresh_job_lock()
        assert [w for w in _config_controls(window) if not w.isEnabled()] == []
        assert tab._job_lock_label.isHidden()
        assert enh._apply_categories_btn.toolTip() == tr("enhancements.apply_categories_tooltip")
        assert enh._apply_tag_btn.toolTip() != REASON
        assert simple.generate_apply_btn.isEnabled()
        assert simple.generate_apply_btn.toolTip() != REASON

    def test_the_controls_locked_are_the_ones_a_job_depends_on(self, window):
        tab = window.config_tab
        assert set(map(id, tab._job_locked_controls())) == set(map(id, [
            tab.game_path_input, tab._game_browse_btn, tab.channel_combo,
            tab.language_combo, tab._map_lang_btn,
            tab.data_dir_input, tab._data_browse_btn, tab._data_reset_btn,
            tab.cache_dir_input, tab._cache_browse_btn, tab._cache_reset_btn,
            tab._extract_btn, tab._import_settings_btn,
        ]))

    def test_a_simple_run_alone_keeps_its_own_tooltip(self, window):
        """Busy before its job has started, without the job's reason."""
        btn = window.simple_page.generate_apply_btn
        window._simple_run_active = True
        try:
            window._refresh_job_lock()
            assert not btn.isEnabled()
            assert btn.toolTip() != REASON
        finally:
            window._end_simple_run()
        assert btn.isEnabled()

    def test_ending_a_simple_run_keeps_the_page_busy_while_a_job_runs(self, window):
        """A Stop answered after the run had finished ends the Simple run while
        generation carries on: the page must not look ready then."""
        btn = window.simple_page.generate_apply_btn
        window._simple_run_active = True
        window._enhancements_worker = object()
        try:
            window._end_simple_run()
            assert window._simple_run_active is False
            assert not btn.isEnabled()
        finally:
            window._enhancements_worker = None
            window._refresh_job_lock()
        assert btn.isEnabled()


class TestTheConfigTabsOwnBusyStates:
    def test_an_update_check_keeps_its_button_off_after_the_lock(self, window):
        tab = window.config_tab
        tab.set_check_updates_enabled(False)          # a check is running
        try:
            tab.set_data_locations_locked(True, REASON)
            tab.set_data_locations_locked(False)
            assert not tab._check_updates_btn.isEnabled()
            tab.set_data_locations_locked(True, REASON)
            tab.set_check_updates_enabled(True)       # the check ends during a job
            assert not tab._check_updates_btn.isEnabled()
        finally:
            tab.set_check_updates_enabled(True)
            tab.set_data_locations_locked(False)
        assert tab._check_updates_btn.isEnabled()

    def test_an_install_scan_keeps_its_button_off_after_the_lock(self, window):
        tab = window.config_tab
        tab._dupe_worker = object()                   # a scan is running
        tab._dupe_check_btn.setEnabled(False)
        try:
            tab.set_data_locations_locked(True, REASON)
            tab.set_data_locations_locked(False)
            assert not tab._dupe_check_btn.isEnabled()
        finally:
            tab._dupe_worker = None
            tab._refresh_locked_controls()
        assert tab._dupe_check_btn.isEnabled()

    def test_the_game_folder_is_not_saved_while_locked(self, window, tmp_path):
        """An install scan that finished during a job could save one through
        its results dialog: _save_game_path refuses while locked."""
        tab = window.config_tab
        before = AppSettings.get_sc_install_root()
        shown = tab.game_path_input.text()
        tab.set_data_locations_locked(True, REASON)
        try:
            tab.game_path_input.setText(str(tmp_path))
            assert tab._save_game_path() is False
            assert AppSettings.get_sc_install_root() == before
        finally:
            tab.set_data_locations_locked(False)
            tab.game_path_input.setText(shown)

    def test_the_data_folder_is_not_changed_while_locked(self, window, monkeypatch, tmp_path):
        """The OneDrive warning's Move reaches _save_data_dir through
        change_data_dir_to, without the locked field, and a running global.ini
        extraction then wrote base.ini into the folder being left. The window's
        data folder slot and the move prompt are swapped for recorders, so a
        change that got through fails here instead of reloading the shared
        window or opening a box."""
        tab = window.config_tab
        before = AppSettings.get_user_data_dir()
        changed = []

        def record(path):
            changed.append(path)

        monkeypatch.setattr(tab, "_maybe_migrate_data", MagicMock())
        tab.data_dir_changed.disconnect(window._on_data_dir_changed)
        tab.data_dir_changed.connect(record)
        tab.set_data_locations_locked(True, REASON)
        try:
            tab.change_data_dir_to(str(tmp_path / "new"))
            assert AppSettings.get_user_data_dir() == before
            assert tab.data_dir_input.text() == os.path.normpath(str(before))
            assert changed == []
            assert not (tmp_path / "new").exists()
            tab._maybe_migrate_data.assert_not_called()
        finally:
            tab.set_data_locations_locked(False)
            if AppSettings.get_user_data_dir() != before:
                AppSettings.set_user_data_dir(before)
            tab.data_dir_input.setText(os.path.normpath(str(before)))
            tab.data_dir_changed.disconnect(record)
            tab.data_dir_changed.connect(window._on_data_dir_changed)

    def test_an_install_picked_during_a_job_says_why_and_changes_nothing(
            self, window, monkeypatch, tmp_path):
        """A scan that finished during a job: Use was refused, but the box
        blamed a drive that disconnected and the field kept the unsaved root,
        which the next click away from it saved."""
        import src.gui.config_tab as config_tab
        box = MagicMock()
        monkeypatch.setattr(config_tab, "QMessageBox", box)
        tab = window.config_tab
        before = AppSettings.get_sc_install_root()
        shown = tab.game_path_input.text()
        dialog = MagicMock()
        tab._dupe_dialog = dialog
        tab.set_data_locations_locked(True, REASON)
        try:
            tab._use_install_root(str(tmp_path))
            box.warning.assert_called_once_with(tab, tr("config.dupe_use_failed_title"), REASON)
            assert tab.game_path_input.text() == shown
            assert AppSettings.get_sc_install_root() == before
            dialog.accept.assert_not_called()   # still open, to pick again later
        finally:
            tab.set_data_locations_locked(False)
            tab._dupe_dialog = None
            tab.game_path_input.setText(shown)


class TestTheEnhancementsTabsChanges:
    @staticmethod
    def _pending_change(tab):
        key, box = next(iter(tab._enhancements_checkboxes.items()))
        box.setChecked(not box.isChecked())
        return key, box

    def test_locked_with_a_change_pending_and_back_after(self, window):
        tab = window.enhancements_tab
        _key, box = self._pending_change(tab)
        try:
            assert tab._apply_categories_btn.isEnabled()
            tab.set_changes_locked(True, REASON)
            assert not tab._apply_categories_btn.isEnabled()
            box.setChecked(box.isChecked())           # another tick changes nothing
            tab._on_category_checkbox_changed()
            assert not tab._apply_categories_btn.isEnabled()
            tab.set_changes_locked(False)
            assert tab._apply_categories_btn.isEnabled()
        finally:
            box.setChecked(not box.isChecked())
            tab.set_changes_locked(False)
        assert not tab._apply_categories_btn.isEnabled()

    def test_a_locked_apply_changes_nothing(self, window):
        """Issue case 10: it renamed INIs to and from .disabled in the folder a
        generation writes, and started a reload that read the set mid-run."""
        tab = window.enhancements_tab
        key, box = self._pending_change(tab)
        saved = AppSettings.get_enhancement_category_enabled(key)
        # The window's reload is swapped for a recorder, so an apply that got
        # through fails here instead of reloading the shared window.
        reloads = []

        def record():
            reloads.append(True)

        tab.merge_requested.disconnect(window.perform_merge_and_reload)
        tab.merge_requested.connect(record)
        tab.set_changes_locked(True, REASON)
        try:
            tab._apply_category_changes()
            assert AppSettings.get_enhancement_category_enabled(key) == saved
            assert reloads == []
        finally:
            tab.set_changes_locked(False)
            AppSettings.set_enhancement_category_enabled(key, saved)
            tab.merge_requested.disconnect(record)
            tab.merge_requested.connect(window.perform_merge_and_reload)
            box.setChecked(not box.isChecked())

    def test_save_tag_changes_locked_with_tags_unsaved_and_back_after(self, window):
        tab = window.enhancements_tab
        was_dirty = tab._tag_dirty
        tab._mark_tag_dirty()
        try:
            assert tab._apply_tag_btn.isEnabled()
            tab.set_changes_locked(True, REASON)
            assert not tab._apply_tag_btn.isEnabled()
            assert tab._apply_tag_btn.toolTip() == REASON
            tab._mark_tag_dirty()                     # another tag edit
            assert not tab._apply_tag_btn.isEnabled()
            assert tab._apply_tag_btn.toolTip() == REASON
            tab.set_changes_locked(False)
            assert tab._apply_tag_btn.isEnabled()
            assert tab._apply_tag_btn.toolTip() == tr("enhancements.tag_enabled_tooltip")
        finally:
            tab.set_changes_locked(False)
            tab._set_tag_btn_dirty(was_dirty)

    def test_generate_stays_off_through_a_change_made_while_locked(self, window):
        """A category tick or a setting changed during a job lit Generate again
        in full red, and its click saved the Tag Builder pages before the
        one-job rule refused the run. It stays off with the reason, or with the
        running job's own message, and comes back after."""
        tab = window.enhancements_tab
        btn = tab._generate_enhancements_btn
        was_dirty = tab._enhancements_dirty
        tab.set_changes_locked(True, REASON)
        try:
            tab._mark_enhancements_dirty()
            assert not btn.isEnabled()
            assert btn.toolTip() == REASON
            tab.set_operation_running("running")
            tab._mark_enhancements_dirty()
            assert not btn.isEnabled()
            assert btn.toolTip() == "running"
            # The run ends while the lock holds (another job still runs): its
            # message goes with it, and the lock reason is back.
            tab.set_operation_idle()
            tab._mark_enhancements_dirty()
            assert not btn.isEnabled()
            assert btn.toolTip() == REASON
            tab.set_changes_locked(False)
            assert btn.isEnabled()
            assert btn.toolTip() == tr("enhancements.generate_enabled_tooltip")
        finally:
            tab.set_changes_locked(False)
            tab._set_generate_btn_dirty(was_dirty)

    def test_a_locked_save_tag_changes_saves_and_asks_nothing(self, window, monkeypatch):
        """It saved the tags, turned itself off and asked for a regeneration
        that one job at a time refused, so the tags never reached the INIs."""
        tab = window.enhancements_tab
        was_dirty = tab._tag_dirty
        saved = MagicMock()
        monkeypatch.setattr(tab, "_persist_tag_builder_state", saved)
        runs = []

        def record():
            runs.append(True)

        tab.enhancements_pipeline_requested.disconnect(window._run_enhancements_pipeline)
        tab.enhancements_pipeline_requested.connect(record)
        tab._mark_tag_dirty()
        tab.set_changes_locked(True, REASON)
        try:
            tab._apply_tag_builder()
            saved.assert_not_called()
            assert runs == []
            assert tab._tag_dirty is True
        finally:
            tab.set_changes_locked(False)
            tab.enhancements_pipeline_requested.disconnect(record)
            tab.enhancements_pipeline_requested.connect(window._run_enhancements_pipeline)
            tab._set_tag_btn_dirty(was_dirty)


def _reddest(button) -> QColor:
    """The most strongly red pixel of the button as drawn: its text when it
    is lit by the dirty-tracking colour."""
    image = button.grab().toImage()
    best, best_score = QColor(), 0
    for x in range(image.width()):
        for y in range(image.height()):
            colour = QColor(image.pixel(x, y))
            score = colour.red() - max(colour.green(), colour.blue())
            if score > best_score:
                best, best_score = colour, score
    return best


def _stand_out(button) -> tuple:
    """How far the button, as its window shows it, stands out from the window
    background: the mean colour distance of its pixels (the fill, which covers
    most of them) and the largest (the label's ink). Taken from the window, so
    a see-through dimmed colour is read over what is behind it. Not the most
    common colour: the style draws the fill as a gradient, and shades it a
    little when disabled with no dimming at all. Measured, busy over ready:
    the mean 0.44 with the :disabled rule and 0.92 with the fill undimmed,
    the largest 0.5 with it and 1.0 with the text undimmed."""
    window = button.window()
    bg = window.palette().window().color()
    image = window.grab(QRect(button.mapTo(window, QPoint(0, 0)), button.size())).toImage()
    distances = []
    for x in range(image.width()):
        for y in range(image.height()):
            c = QColor(image.pixel(x, y))
            distances.append(((c.red() - bg.red()) ** 2 + (c.green() - bg.green()) ** 2
                              + (c.blue() - bg.blue()) ** 2) ** 0.5)
    return sum(distances) / len(distances), max(distances)


def _dimmed_but_red(lit: QColor, locked: QColor) -> bool:
    return (locked.isValid() and locked.red() > max(locked.green(), locked.blue())
            and locked.red() < lit.red())


class TestLitButtonsDimWhileLocked:
    """A stylesheet colour outlives setEnabled(False), so a lit button a job
    had locked still looked ready to click. Locked, it keeps a dimmed red, so
    the pending change still shows, and the tooltip or the Config tab's lock
    label says why; unlocked, it is full red again."""

    def test_save_tag_changes(self, window):
        tab = window.enhancements_tab
        was_dirty = tab._tag_dirty
        tab._mark_tag_dirty()
        try:
            lit = _reddest(tab._apply_tag_btn)
            tab.set_changes_locked(True, REASON)
            assert _dimmed_but_red(lit, _reddest(tab._apply_tag_btn))
            tab.set_changes_locked(False)
            assert _reddest(tab._apply_tag_btn).name() == lit.name()
        finally:
            tab.set_changes_locked(False)
            tab._set_tag_btn_dirty(was_dirty)

    def test_generate_enhancements(self, window):
        tab = window.enhancements_tab
        was_dirty = tab._enhancements_dirty
        tab._set_generate_btn_dirty(True)
        try:
            lit = _reddest(tab._generate_enhancements_btn)
            tab.set_operation_running(tr("enhancements.extracting_dataforge_tooltip"))
            assert _dimmed_but_red(lit, _reddest(tab._generate_enhancements_btn))
        finally:
            tab.set_operation_idle()   # ends the run, its message with it
            tab._set_generate_btn_dirty(was_dirty)

    @pytest.mark.parametrize("dirty", [True, False], ids=["red", "green"])
    def test_the_simple_pages_button(self, qapp, monkeypatch, dirty):
        """Issue case 6's look: busy, the Simple page's fill and text dim too.
        They are stylesheet colours, so they outlived setEnabled(False), and
        with Run in Background a Simple user sat through the run looking at a
        button that seemed ready while every click was dropped.

        The theme is pinned to the default, whose label is black: the ink
        reading takes the pixel farthest from the window, which is the label
        only when it contrasts with the window more than the fill does. The
        Light theme's white label does not, and the test would otherwise read
        whatever theme the developer has saved."""
        from src.gui import theme
        from src.gui.simple_mode_widget import SimpleModeWidget
        monkeypatch.setattr(AppSettings, "get_theme", staticmethod(lambda: theme.DEFAULT_THEME))
        assert theme.get_button_text_color() == "black"
        page = SimpleModeWidget()
        page.resize(800, 500)
        page.show()
        qapp.processEvents()
        try:
            page.set_apply_dirty(dirty)
            ready_fill, ready_ink = _stand_out(page.generate_apply_btn)
            page.set_busy(True, REASON)
            busy_fill, busy_ink = _stand_out(page.generate_apply_btn)
            assert busy_fill < 0.7 * ready_fill   # measured 0.44, 0.92 undimmed
            assert busy_ink < 0.7 * ready_ink     # measured 0.5, 1.0 undimmed
            page.set_busy(False)
            assert _stand_out(page.generate_apply_btn) == pytest.approx((ready_fill, ready_ink))
        finally:
            page.close()
            page.deleteLater()

    def test_the_config_tabs_extract(self, window):
        tab = window.config_tab
        was_lit = bool(tab._extract_btn.styleSheet())
        tab._set_extract_btn_needs_update(True)
        try:
            lit = _reddest(tab._extract_btn)
            tab.set_data_locations_locked(True, REASON)
            assert _dimmed_but_red(lit, _reddest(tab._extract_btn))
            tab.set_data_locations_locked(False)
            assert _reddest(tab._extract_btn).name() == lit.name()
        finally:
            tab.set_data_locations_locked(False)
            tab._set_extract_btn_needs_update(was_lit)


# ── The strings ──────────────────────────────────────────────────────────────

_STRINGS = [("extract", key) for key in (
    "dataforge_running_body", "dataforge_background_btn", "dataforge_settings_changed",
    "locked_while_job_runs",
    # Generation's own Stop / Run in Background / Cancel question.
    "generation_running_title", "generation_running_body", "generation_stopping",
)] + [("status_bar", "enhancement_generation_stopped")]


class TestEveryLanguage:
    @pytest.fixture(scope="class")
    def languages(self):
        import json
        root = Path(__file__).resolve().parent.parent / "languages"
        return {f.parent.name: json.loads(f.read_text(encoding="utf-8"))
                for f in sorted(root.glob("*/ui.json"))}

    def test_each_text_is_there_english_in_ht_the_rest_in_at(self, languages):
        assert "english" in languages
        for language, strings in languages.items():
            for section, key in _STRINGS:
                node = strings[section][key]
                if language == "english":
                    assert node["ht"] and node["at"] == "", key
                else:
                    assert node["ht"] == "" and node["at"], f"{language} {key}"

    @pytest.mark.parametrize("key", ["dataforge_running_body", "generation_running_body"])
    def test_the_question_offers_the_background(self, languages, key):
        """Each question names the third choice, as its English text does."""
        english = languages["english"]["extract"][key]["ht"]
        assert "background" in english and "Stop" in english


# ── The cases from the issue, on the real methods ────────────────────────────

def _stub(**attrs):
    me = MagicMock()
    me._close_committed = False
    for attr in JOBS:
        setattr(me, attr, None)
    me._forge_progress_dialog = None
    me._enhancements_progress_dialog = None
    me._p4k_progress = None
    me._simple_run_active = False
    me._after_unfinished_generation = None
    me._WORKERS_STOPPED_ON_CLOSE = MainWindow._WORKERS_STOPPED_ON_CLOSE
    me._working_folder_deleters = []
    me._job_running = lambda: MainWindow._job_running(me)
    me._end_dataforge_run = lambda: MainWindow._end_dataforge_run(me)
    me._closing_would_wait = lambda: MainWindow._closing_would_wait(me)
    for name, value in attrs.items():
        setattr(me, name, value)
    return me


class TestTheFinishedRunChecksItsSettings:
    """Issue cases 1 and 3, the net behind the lock: a run whose cache folder
    or channel changed while it went on neither drains the old-cache cleanup
    (which could name the folder it just filled) nor chains generation (from a
    cache it never wrote)."""

    @pytest.fixture
    def settings(self, monkeypatch, tmp_path):
        state = {"channel": "LIVE", "base": tmp_path / "Cache"}
        monkeypatch.setattr(main_window.AppSettings, "get_active_channel",
                            staticmethod(lambda: state["channel"]))
        monkeypatch.setattr(main_window.AppSettings, "get_dataforge_cache_base",
                            staticmethod(lambda: state["base"]))
        return state

    @staticmethod
    def _run(settings):
        worker = MagicMock(channel=settings["channel"], cache_base=settings["base"],
                           in_background=False, stopped=False)
        dialog = MagicMock(name="dialog")
        me = _stub(_forge_worker=worker, _forge_progress_dialog=dialog)
        me._dataforge_run_matches_settings = (
            lambda w: MainWindow._dataforge_run_matches_settings(me, w))
        return worker, dialog, me

    def test_a_run_whose_settings_held_goes_on_as_before(self, settings):
        worker, _dialog, me = self._run(settings)
        MainWindow._on_dataforge_extract_finished(me, True, worker)
        me._cleanup_pending_old_cache.assert_called_once_with()
        me._run_enhancements_generation.assert_called_once_with(background=False)

    def test_the_folder_is_compared_as_windows_does(self, settings):
        """Case and spelling differences are the same folder on Windows."""
        worker, _dialog, me = self._run(settings)
        settings["base"] = Path(str(settings["base"]).upper() + "\\.")
        MainWindow._on_dataforge_extract_finished(me, True, worker)
        me._run_enhancements_generation.assert_called_once_with(background=False)

    @pytest.mark.parametrize("change", ["cache folder", "channel"])
    def test_a_changed_setting_skips_the_cleanup_and_generation(self, settings, tmp_path, change):
        worker, dialog, me = self._run(settings)
        if change == "cache folder":
            settings["base"] = tmp_path / "Other"
        else:
            settings["channel"] = "PTU"
        MainWindow._on_dataforge_extract_finished(me, True, worker)
        me._cleanup_pending_old_cache.assert_not_called()
        me._run_enhancements_generation.assert_not_called()
        me.statusBar().showMessage.assert_called_with(tr("extract.dataforge_settings_changed"))
        me.enhancements_tab.set_operation_idle.assert_called_once_with(success=False)
        me._end_simple_run.assert_called_once_with()
        dialog.close.assert_called_once_with()
        assert me._forge_progress_dialog is None


class TestOneJobAtATime:
    @pytest.mark.parametrize("job", ["_p4k_worker", "_enhancements_worker"])
    def test_no_dataforge_extraction_beside_another_job(self, monkeypatch, job):
        """Issue case 7: an extraction started beside a generation wiped the
        cache the generator was reading."""
        made = MagicMock()
        monkeypatch.setattr(main_window, "DataForgeExtractWorker", made)
        me = _stub(**{job: object()})
        MainWindow._run_dataforge_extraction(me)
        made.assert_not_called()
        assert me._forge_worker is None
        me.statusBar().showMessage.assert_called_once_with(REASON)

    @pytest.mark.parametrize("job", ["_forge_worker", "_enhancements_worker"])
    def test_no_global_ini_extraction_beside_another_job(self, monkeypatch, job):
        made = MagicMock()
        monkeypatch.setattr(main_window, "P4kExtractWorker", made)
        me = _stub(**{job: object()})
        assert MainWindow._run_p4k_extraction(me) is False
        made.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)

    @pytest.mark.parametrize("job", ["_p4k_worker", "_forge_worker"])
    def test_no_generation_beside_an_extraction(self, monkeypatch, job):
        made = MagicMock()
        monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", made)
        me = _stub(**{job: object()})
        assert MainWindow._run_enhancements_generation(me) is False
        made.assert_not_called()

    def test_no_pipeline_beside_a_global_ini_extraction(self):
        """And it says why: Generate is only greyed out for the other two jobs."""
        me = _stub(_p4k_worker=object())
        MainWindow._run_enhancements_pipeline(me)
        me._run_enhancements_generation.assert_not_called()
        me._run_dataforge_extraction.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)

    def test_the_post_import_apply_is_asked_after_a_running_job(self, monkeypatch):
        """The startup sync just before it can start a global.ini extraction.
        An Apply Now would be refused then, and the choice was lost with the
        flag: the question is put off instead, Import Settings' flag kept."""
        settings = MagicMock()
        settings.get_post_import_apply_pending.return_value = True
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _stub(_p4k_worker=object())
        MainWindow._maybe_prompt_post_import_apply(me)
        box.assert_not_called()
        settings.set_post_import_apply_pending.assert_not_called()
        me._ask_after_the_job.assert_called_once_with(me._maybe_prompt_post_import_apply)
        me._run_enhancements_pipeline.assert_not_called()

    @pytest.mark.parametrize("job_starts", [True, False])
    def test_an_apply_now_after_a_job_started_is_asked_again(self, monkeypatch, job_starts):
        """The sync can also start one while the question is open. Apply Now
        then marked a Simple run whose pipeline was refused, and the Simple
        page stayed busy for good. It puts the question off again now, with
        the flag back, so the choice is not lost."""
        settings = MagicMock()
        settings.get_post_import_apply_pending.return_value = True
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        box.return_value.clickedButton.return_value = box.return_value.addButton.return_value
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _stub()
        if job_starts:
            box.return_value.exec.side_effect = lambda: setattr(me, "_p4k_worker", object())
        MainWindow._maybe_prompt_post_import_apply(me)
        box.return_value.exec.assert_called_once_with()
        if job_starts:
            flags = settings.set_post_import_apply_pending.call_args_list
            assert flags == [call(False), call(True)]
            me._ask_after_the_job.assert_called_once_with(me._maybe_prompt_post_import_apply)
            assert me._simple_run_active is False
            me._run_enhancements_pipeline.assert_not_called()
            me.statusBar().showMessage.assert_called_once_with(REASON)
        else:
            assert settings.set_post_import_apply_pending.call_args_list == [call(False)]
            me._ask_after_the_job.assert_not_called()
            assert me._simple_run_active is True
            me._run_enhancements_pipeline.assert_called_once_with()

    @pytest.mark.parametrize("job", JOBS)
    def test_the_startup_enhancements_question_waits_for_the_job(self, monkeypatch, job):
        """Its Generate would be refused. A global.ini extraction's reload
        asks again when it ends."""
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _stub(**{job: object()}, _enhancements_prompt_answer=None)
        MainWindow._check_enhancements_freshness(me)
        me._show_enhancement_category_dialog.assert_not_called()
        me._run_enhancements_pipeline.assert_not_called()
        assert me._enhancements_prompt_answer is None

    @pytest.mark.parametrize("job", ["_p4k_worker", "_forge_worker"])
    def test_a_language_switch_during_an_extraction_loads_the_prose(
            self, monkeypatch, tmp_path, job):
        """Issue case 2: the switch's own generation read a cache being wiped
        and stamped it current. The language selector is locked meanwhile;
        behind it, the switch loads the prose and leaves generation to the
        extraction's own chain. A cache is there, so only the extraction
        keeps the switch from generating. The method reads the cache folder
        without making it (#494), so that getter is the one patched: patching
        the creating one left the method on its no-cache branch, and the test
        passed with the guard removed."""
        from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH
        (tmp_path / DATAFORGE_RECORDS_SUBPATH).mkdir(parents=True)
        monkeypatch.setattr(main_window.AppSettings, "get_dataforge_cache_leaf",
                            staticmethod(lambda *args, **kwargs: tmp_path))
        me = _stub(**{job: object()})
        me._language_enhancements_fresh = lambda language: False
        MainWindow._reload_with_language_enhancements(me, "german")
        me._run_enhancements_generation.assert_not_called()
        me.enhancements_tab.mark_enhancements_clean.assert_not_called()
        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))

    @pytest.mark.parametrize("job", JOBS)
    def test_simple_mode_asks_nothing_while_a_job_runs(self, monkeypatch, job):
        """Issue case 6: the page's clicks were dropped silently. It shows busy
        now, and a click that still arrives asks nothing, whichever job runs:
        the global.ini extraction is the one the old check missed."""
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _stub(**{job: object()})
        MainWindow._run_simple_apply(me)
        box.question.assert_not_called()
        me._run_enhancements_pipeline.assert_not_called()


class TestRelaunchesWaitForTheJob:
    """Issue case 11: Import Settings' restart and the update installer start
    a new copy while this one may still be finishing a job. Both buttons are
    locked (TestTheLock); these are the nets behind them."""

    def test_import_settings_does_nothing_while_a_job_runs(self, monkeypatch):
        dialogs = MagicMock()
        monkeypatch.setattr(main_window, "QFileDialog", dialogs)
        me = _stub(_enhancements_worker=object())
        MainWindow._handle_import_settings(me)
        dialogs.getOpenFileName.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)

    @pytest.mark.parametrize("running", [True, False])
    def test_an_update_waits_for_the_job(self, monkeypatch, running):
        update_dialog = MagicMock()
        update_dialog.return_value.choice = update_dialog.CHOICE_UPDATE
        monkeypatch.setattr(main_window, "UpdateDialog", update_dialog)
        me = _stub(_forge_worker=object() if running else None)
        MainWindow._on_update_available(me, "9.9.9", "https://example.invalid", "",
                                        "https://example.invalid/setup.exe", 1)
        if running:
            me._start_update_download.assert_not_called()
            me.statusBar().showMessage.assert_called_once_with(REASON)
            me._continue_startup_after_update_gate.assert_called_once_with()
        else:
            me._start_update_download.assert_called_once()

    def test_import_settings_waits_for_a_background_delete(self, monkeypatch):
        """A finished DataForge run's working folder is deleted in the
        background and locks nothing, but closing waits for that delete with
        the window hidden, so the restart waits for it as it does for a job."""
        dialogs = MagicMock()
        monkeypatch.setattr(main_window, "QFileDialog", dialogs)
        me = _stub(_working_folder_deleters=[object()])
        MainWindow._handle_import_settings(me)
        dialogs.getOpenFileName.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)

    def test_an_update_waits_for_a_background_delete(self, monkeypatch):
        update_dialog = MagicMock()
        update_dialog.return_value.choice = update_dialog.CHOICE_UPDATE
        monkeypatch.setattr(main_window, "UpdateDialog", update_dialog)
        me = _stub(_working_folder_deleters=[object()])
        MainWindow._on_update_available(me, "9.9.9", "https://example.invalid", "",
                                        "https://example.invalid/setup.exe", 1)
        me._start_update_download.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)
        me._continue_startup_after_update_gate.assert_called_once_with()

    def test_a_delete_is_not_a_job(self):
        """_job_running stays workers only: a generation is meant to run
        beside a delete, and a new DataForge run waits for one on its own
        thread."""
        me = _stub(_working_folder_deleters=[object()])
        assert MainWindow._job_running(me) is False
        assert MainWindow._closing_would_wait(me) is True

    def test_nothing_running_waits_for_nothing(self):
        assert MainWindow._closing_would_wait(_stub()) is False

    def test_the_two_relaunches_ask_the_one_question(self):
        """Both sites go through _closing_would_wait: a relaunch added later
        that asks _job_running alone would let a delete hold the close."""
        import ast
        import inspect
        import textwrap

        for method in (MainWindow._on_update_available, MainWindow._handle_import_settings):
            tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
            called = {node.func.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
            assert "_closing_would_wait" in called, method.__name__
            assert "_job_running" not in called, method.__name__


class TestGenerationInTheBackground:
    @pytest.fixture
    def made(self, monkeypatch):
        workers = []

        def make_worker(**kwargs):
            workers.append(MagicMock(name="generation"))
            return workers[-1]

        monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", make_worker)
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        return workers

    def test_it_runs_without_a_dialog(self, monkeypatch, made):
        dialogs = MagicMock()
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", dialogs)
        me = _stub()
        assert MainWindow._run_enhancements_generation(me, background=True) is True
        dialogs.assert_not_called()
        assert me._enhancements_progress_dialog is None
        worker = made[0]
        worker.progress.connect.assert_called_once_with(me.statusBar().showMessage)
        worker.progress_pct.connect.assert_not_called()
        worker.start.assert_called_once_with()

    def test_a_leftover_extraction_dialog_is_closed_not_reused(self, monkeypatch, made):
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        leftover = MagicMock(name="extraction dialog")
        me = _stub(_forge_progress_dialog=leftover)
        MainWindow._run_enhancements_generation(me, background=True)
        leftover.close.assert_called_once_with()
        assert me._forge_progress_dialog is None
        assert me._enhancements_progress_dialog is None

    def test_closing_stops_it_without_a_dialog(self):
        """Issue case 4: closing during the background chain. The generation's
        stop is #477's, and it needs no dialog to detach."""
        generation = MagicMock(name="generation")
        generation.isRunning.return_value = True
        generation.wait.return_value = True
        me = _stub(_enhancements_worker=generation)
        MainWindow._stop_workers_for_close(me)
        generation.requestInterruption.assert_called_once_with()
        assert me._enhancements_worker is None
        me.hide.assert_called_once_with()


class TestTheLockFollowsEveryJob:
    """_refresh_job_lock runs as each job starts (its worker already set) and
    as it ends (its worker already cleared), so the lock never lags a job."""

    @staticmethod
    def _recording(me) -> list:
        seen = []
        me._refresh_job_lock.side_effect = lambda: seen.append(
            tuple(getattr(me, attr) is not None for attr in JOBS))
        return seen

    def test_the_dataforge_extraction(self, monkeypatch):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "DataForgeExtractWorker", MagicMock())
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        me = _stub()
        seen = self._recording(me)
        MainWindow._run_dataforge_extraction(me)
        assert seen == [(False, True, False)]
        worker = me._forge_worker
        MainWindow._on_dataforge_extract_finished(me, False, worker)
        assert seen[-1] == (False, False, False)

    def test_the_global_ini_extraction(self, monkeypatch):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "P4kExtractWorker", MagicMock())
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        me = _stub(_after_unfinished_p4k_extraction=None)
        seen = self._recording(me)
        assert MainWindow._run_p4k_extraction(me) is True
        assert seen == [(True, False, False)]
        MainWindow._on_p4k_extract_finished(me, False, me._p4k_worker)
        assert seen[-1] == (False, False, False)

    def test_generation(self, monkeypatch):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", MagicMock())
        monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
        me = _stub()
        seen = self._recording(me)
        assert MainWindow._run_enhancements_generation(me) is True
        assert seen == [(False, False, True)]
        MainWindow._on_enhancements_generation_finished(me, False, me._enhancements_worker)
        assert seen[-1] == (False, False, False)

    def test_a_simple_run_starts_busy_before_its_job(self, monkeypatch):
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        box = MagicMock()
        box.question.return_value = box.StandardButton.Yes
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _stub()
        order = []
        me._refresh_job_lock.side_effect = lambda: order.append(("lock", me._simple_run_active))
        me._run_enhancements_pipeline.side_effect = lambda: order.append(("pipeline", None))
        MainWindow._run_simple_apply(me)
        assert order == [("lock", True), ("pipeline", None)]


class TestTheOneDriveWarningWaitsForTheJob:
    """The startup sync just before the warning can start a global.ini
    extraction, and Move then changed the data folder under it: base.ini
    landed in the folder being left, and the new folder's extraction was
    refused. The warning is put off until the job is over and asked again
    (the Config tab refusing the change is the net, TestTheConfigTabsOwnBusyStates)."""

    @pytest.fixture
    def warning(self, monkeypatch, tmp_path):
        settings = MagicMock()
        settings.get_onedrive_warning_dismissed.return_value = False
        settings.get_user_data_dir.return_value = tmp_path / "OneDrive" / "Smart Citizen"
        monkeypatch.setattr(main_window, "AppSettings", settings)
        import src.utils.onedrive as onedrive
        monkeypatch.setattr(onedrive, "is_onedrive_path", lambda path: True)
        monkeypatch.setattr(onedrive, "suggest_local_data_dir", lambda: tmp_path / "Local")
        box = MagicMock()   # both buttons are one mock, so the click is Move
        box.return_value.clickedButton.return_value = box.return_value.addButton.return_value
        monkeypatch.setattr(main_window, "QMessageBox", box)
        dont_warn = MagicMock()
        dont_warn.return_value.isChecked.return_value = True
        import PyQt6.QtWidgets as widgets
        monkeypatch.setattr(widgets, "QCheckBox", dont_warn)
        return settings, box, tmp_path / "Local"

    def test_put_off_while_a_job_runs(self, warning):
        _settings, box, _local = warning
        me = _stub(_p4k_worker=object())
        MainWindow._maybe_warn_onedrive_data_dir(me)
        box.assert_not_called()
        me._ask_after_the_job.assert_called_once_with(me._maybe_warn_onedrive_data_dir)
        me.config_tab.change_data_dir_to.assert_not_called()

    def test_a_move_after_a_job_started_is_asked_again(self, warning):
        """Without keeping its 'don't warn again', so it comes back."""
        settings, box, _local = warning
        me = _stub()
        box.return_value.exec.side_effect = lambda: setattr(me, "_p4k_worker", object())
        MainWindow._maybe_warn_onedrive_data_dir(me)
        me.config_tab.change_data_dir_to.assert_not_called()
        me._ask_after_the_job.assert_called_once_with(me._maybe_warn_onedrive_data_dir)
        settings.set_onedrive_warning_dismissed.assert_not_called()
        me.statusBar().showMessage.assert_called_once_with(REASON)

    def test_with_no_job_the_move_goes_ahead(self, warning):
        settings, _box, local = warning
        me = _stub()
        MainWindow._maybe_warn_onedrive_data_dir(me)
        me.config_tab.change_data_dir_to.assert_called_once_with(str(local))
        settings.set_onedrive_warning_dismissed.assert_called_once_with(True)
        me._ask_after_the_job.assert_not_called()


class TestQuestionsPutOffUntilTheJobEnds:
    """_ask_after_the_job keeps a startup question a running job put off, and
    the load that ends the job asks it again (its queue is the last step of
    both load paths, test_default_owned_blueprints.py)."""

    @staticmethod
    def _me(**attrs):
        me = _stub(**{"_loader_worker": None, "_asks_after_the_job": [], **attrs})
        me._ask_after_the_job = lambda ask: MainWindow._ask_after_the_job(me, ask)
        me._ASK_AFTER_MODAL_RETRY_MS = MainWindow._ASK_AFTER_MODAL_RETRY_MS
        return me

    @pytest.fixture
    def modal(self, monkeypatch):
        """Stands in for whether a modal box is open, and records the timer."""
        state = {"box": object()}
        monkeypatch.setattr(main_window, "QApplication",
                            MagicMock(activeModalWidget=lambda: state["box"]))
        timer = MagicMock()
        monkeypatch.setattr(main_window, "QTimer", timer)
        return state, timer

    def test_a_modal_box_puts_them_off_a_moment(self, modal):
        """Asked while a box was open, a question opened on top of it, inside
        its event loop: the new-blueprints summary a load's report opens, or
        closeEvent's prompt before the close is final. The flush looks again
        shortly instead, never at once, and asks once the box has gone."""
        state, timer = modal
        me = self._me()
        ask = MagicMock()
        me._asks_after_the_job = [ask]
        MainWindow._flush_asks_after_the_job(me)
        ask.assert_not_called()
        assert me._asks_after_the_job == [ask]
        timer.singleShot.assert_called_once_with(
            MainWindow._ASK_AFTER_MODAL_RETRY_MS, me._flush_asks_after_the_job)
        assert MainWindow._ASK_AFTER_MODAL_RETRY_MS > 0
        state["box"] = None
        MainWindow._flush_asks_after_the_job(me)
        ask.assert_called_once_with()

    def test_a_close_answered_in_the_prompt_asks_nothing_after(self, modal):
        """The prompt closes because the close went ahead: nothing is asked
        on the way out, where an Apply Now would start a run the exit stops."""
        state, _timer = modal
        me = self._me()
        ask = MagicMock()
        me._asks_after_the_job = [ask]
        MainWindow._flush_asks_after_the_job(me)
        state["box"] = None
        me._close_committed = True
        MainWindow._flush_asks_after_the_job(me)
        ask.assert_not_called()

    def test_one_put_off_again_during_the_flush_stays_put_off(self, monkeypatch):
        """The OneDrive warning is asked first, and its Move can start a
        global.ini extraction (the data folder change's freshness check). The
        post-import question asked next then puts itself off again, and must
        stay put off to be asked after that job, not be dropped."""
        settings = MagicMock()
        settings.get_post_import_apply_pending.return_value = True
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = self._me()
        asked = []

        def move_starts_an_extraction():
            asked.append("onedrive")
            me._p4k_worker = object()

        def post_import():
            asked.append("post-import")
            MainWindow._maybe_prompt_post_import_apply(me)

        me._maybe_prompt_post_import_apply = post_import
        me._asks_after_the_job = [move_starts_an_extraction, post_import]
        MainWindow._flush_asks_after_the_job(me)
        assert asked == ["onedrive", "post-import"]
        box.assert_not_called()
        assert me._asks_after_the_job == [post_import]

    def test_each_is_put_off_once(self):
        me = self._me()
        ask = MagicMock()
        me._ask_after_the_job(ask)
        me._ask_after_the_job(ask)
        assert me._asks_after_the_job == [ask]

    def test_asked_once_nothing_is_going(self):
        me = self._me()
        first, second = MagicMock(), MagicMock()
        me._asks_after_the_job = [first, second]
        MainWindow._flush_asks_after_the_job(me)
        first.assert_called_once_with()
        second.assert_called_once_with()
        assert me._asks_after_the_job == []

    @pytest.mark.parametrize("going", JOBS + ["_loader_worker", "_simple_run_active",
                                              "_close_committed"])
    def test_not_while_anything_is_going_or_the_window_closes(self, going):
        me = self._me(**{going: object()})
        ask = MagicMock()
        me._asks_after_the_job = [ask]
        MainWindow._flush_asks_after_the_job(me)
        ask.assert_not_called()
        assert me._asks_after_the_job == [ask]

    def test_a_load_queues_them_only_when_one_waits(self, monkeypatch):
        timer = MagicMock()
        monkeypatch.setattr(main_window, "QTimer", timer)
        me = self._me()
        MainWindow._queue_asks_after_the_job(me)
        timer.singleShot.assert_not_called()
        me._asks_after_the_job = [MagicMock()]
        MainWindow._queue_asks_after_the_job(me)
        timer.singleShot.assert_called_once_with(0, me._flush_asks_after_the_job)

    def test_a_put_off_question_is_asked_after_the_job(self, monkeypatch):
        """On the real methods: put off while a global.ini extraction runs,
        asked once it and its load are over, then gone."""
        settings = MagicMock()
        settings.get_post_import_apply_pending.return_value = True
        monkeypatch.setattr(main_window, "AppSettings", settings)
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = self._me(_p4k_worker=object())
        me._maybe_prompt_post_import_apply = (
            lambda: MainWindow._maybe_prompt_post_import_apply(me))
        me._maybe_prompt_post_import_apply()
        box.assert_not_called()
        me._p4k_worker = None
        MainWindow._flush_asks_after_the_job(me)
        box.return_value.exec.assert_called_once_with()
        assert me._asks_after_the_job == []
