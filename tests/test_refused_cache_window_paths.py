"""#494: what the main window does when the active channel's DataForge cache
folder cannot be made, partway through a session.

The Enhancements tab and the window read the cache status through
``get_dataforge_cache_dir()``, which creates the folder. Here the tab is built
on LIVE, whose cache is there, then the channel is PTU, whose cache folder
Windows refuses: the cache folder above both denies new folders (as a switch
to a channel never extracted, under a folder Controlled folder access guards,
leaves it). Each of these used to stop halfway with the crash dialog: a
channel switch after repointing the sources (the table kept LIVE's strings
and the close-time autosave wrote them into PTU's user.ini), the reload
after it at its DataForge refresh check (with Data.p4k there), a language
switch after changing the language (the tab half translated), a data folder
change after moving the data, a language reload, the category dialog's
Generate on the first load, the Enhancements tab's Apply, and the slots that
end an extraction or a generation. Each now runs to the end, and nothing of
PTU's cache folder is made.

MainWindow runs on a stub self (a MagicMock, as in test_extraction_stop.py)
with the real Enhancements tab, the real settings paths (``tmp_profile``) and a
real refusal (``tests/unusable_folder.py``). Offscreen Qt through ``qapp``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6 import QtWidgets

import src.gui.main_window as main_window
from src.gui.main_window import MainWindow
from src.utils import i18n
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from tests.unusable_folder import new_folders_denied

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def ptu_refused(tmp_profile, qapp, english_ui):
    """The Enhancements tab built on LIVE, whose cache is there, then PTU
    active with the cache folder above both denying new folders. Yields the
    tab and that folder."""
    from src.gui.enhancements_tab import EnhancementsTab

    base = tmp_profile / "cache"
    (base / "LIVE" / "cache" / "dataforge").mkdir(parents=True)
    AppSettings.set_cache_dir(base)
    tab = EnhancementsTab()
    AppSettings.set_active_channel("PTU")
    with new_folders_denied(base):
        yield tab, base
        assert [p.name for p in base.iterdir()] == ["LIVE"], "PTU's cache folder was made"


def _window(tab):
    me = MagicMock()
    me.enhancements_tab = tab
    me._close_committed = False
    me._forge_worker = None
    me._enhancements_worker = None
    me._loader_worker = None
    me._loading_progress = None
    me._enhancements_progress_dialog = None
    me._forge_progress_dialog = None
    me._simple_run_active = False
    me._p4k_worker = None
    # The real one-job-at-a-time test (#483), reading the workers above: a
    # MagicMock's truthy default would read as a job running.
    me._WORKERS_STOPPED_ON_CLOSE = MainWindow._WORKERS_STOPPED_ON_CLOSE
    me._job_running = lambda: MainWindow._job_running(me)
    return me


def _reads_not_extracted(tab) -> None:
    assert tab._forge_status_label.text() == tr("enhancements.forge_status_not_extracted")


class TestSwitchesCompleteWithUnusableCache:
    def test_a_channel_switch_reaches_the_reload(self, ptu_refused):
        tab, _base = ptu_refused
        me = _window(tab)
        me._enhancements_prompt_answer = False
        me._check_p4k_freshness.return_value = False

        MainWindow._on_channel_changed(me, "PTU")

        _reads_not_extracted(tab)
        assert tab._generate_enhancements_btn.isEnabled()
        me._check_p4k_freshness.assert_called_once()
        me._reload_after_channel_switch.assert_called_once_with("PTU")
        assert me._enhancements_prompt_answer is None

    def test_the_reload_after_a_channel_switch_asks_nothing_about_the_cache(
        self, ptu_refused, tmp_profile, monkeypatch
    ):
        """The reload first asks whether the channel's DataForge cache is out
        of date (``_maybe_prompt_dataforge_refresh``), which reads the cache
        folder once Data.p4k and the two tools are there. PTU's cache folder
        is not there, so it reads as never extracted: no prompt, no
        extraction, and the reload follows."""
        tab, _base = ptu_refused
        (tmp_profile / "StarCitizen" / "PTU" / "Data.p4k").write_bytes(b"p4k")
        tools = tmp_profile / "tools"
        tools.mkdir()
        for name in ("unp4k.exe", "unforge.exe"):
            (tools / name).write_bytes(b"x")   # never run, only looked for
        monkeypatch.setattr(AppSettings, "get_unp4k_exe_path",
                            staticmethod(lambda: tools / "unp4k.exe"))
        monkeypatch.setattr(AppSettings, "get_unforge_exe_path",
                            staticmethod(lambda: tools / "unforge.exe"))
        assert AppSettings.get_p4k_path().exists()
        box = MagicMock()
        monkeypatch.setattr(main_window, "QMessageBox", box)
        me = _window(tab)
        me._maybe_prompt_dataforge_refresh = (
            lambda: MainWindow._maybe_prompt_dataforge_refresh(me))

        MainWindow._reload_after_channel_switch(me, "PTU")

        box.question.assert_not_called()
        me._run_dataforge_extraction.assert_not_called()
        me.perform_merge_and_reload.assert_called_once_with()

    def test_a_language_switch_reaches_the_new_base_source(self, ptu_refused):
        """The tab's own retranslation runs (the window's cascade to it), so
        the Tag Builder, translated after the forge status, is German too."""
        tab, _base = ptu_refused
        me = _window(tab)
        me.retranslate_ui.side_effect = tab.retranslate_ui

        MainWindow._on_language_changed(me, "german")

        assert i18n._current_lang == "german"
        assert tab._tag_builder_group_box.title() == tr("enhancements.tag_builder_group")
        _reads_not_extracted(tab)
        me._apply_language_base_source.assert_called_once_with("german")

    def test_a_data_folder_change_reaches_the_reload(self, ptu_refused, tmp_profile):
        tab, _base = ptu_refused
        me = _window(tab)
        me._check_p4k_freshness.return_value = False
        data_dir = str(tmp_profile / "data")

        MainWindow._on_data_dir_changed(me, data_dir)

        _reads_not_extracted(tab)
        me._check_p4k_freshness.assert_called_once()
        me._reload_after_data_dir_change.assert_called_once_with(data_dir)

    @pytest.mark.parametrize("stamped", [False, True], ids=["no stamp", "stamped"])
    def test_a_language_reload_loads_the_prose(self, ptu_refused, stamped):
        """Stale or missing enhancements with no cache to generate them from:
        the language's prose loads without stat overlays. A stamp is compared
        with the build key, which reads the cache folder too."""
        tab, _base = ptu_refused
        if stamped:
            AppSettings.set_enhancements_stamp("1700000000.0", "german")
        me = _window(tab)
        me._language_enhancements_fresh = (
            lambda language: MainWindow._language_enhancements_fresh(me, language))

        MainWindow._reload_with_language_enhancements(me, "german")

        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))
        me._run_enhancements_generation.assert_not_called()

    def test_the_category_dialogs_generate_starts_the_pipeline(
        self, ptu_refused, tmp_profile, monkeypatch
    ):
        """The first load asks which missing enhancements to generate. Its
        Generate refreshes the tab, then starts the pipeline, and the load
        finishes (``_initial_load_done``). The dialog is shown to run once,
        so a change that starts the pipeline without it fails here instead
        of passing without testing the dialog, and so is the tab's real
        refresh, before the pipeline starts, so a change that drops it fails
        too."""
        tab, _base = ptu_refused
        AppSettings.get_base_ini_path().parent.mkdir(parents=True, exist_ok=True)
        AppSettings.get_base_ini_path().write_text("k=v\n", encoding="utf-8")
        (tmp_profile / "StarCitizen" / "PTU" / "Data.p4k").write_bytes(b"p4k")

        class Generate(QtWidgets.QDialog):
            def __init__(self, parent=None):
                super().__init__()   # the stub window is no QWidget

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(QtWidgets, "QDialog", Generate)
        monkeypatch.setattr(main_window, "QTimer", MagicMock())
        me = _window(tab)
        me._check_enhancements_after_loading = True
        me._enhancements_prompt_answer = None
        me._reload_follows_clean_apply = False
        me._initial_load_done = False
        me._snapshot_pending_user_edits.return_value = {}
        me._restore_pending_user_edits.return_value = 0
        me._check_enhancements_freshness = lambda: MainWindow._check_enhancements_freshness(me)
        me._out_of_date_build_key = lambda: MainWindow._out_of_date_build_key(me)
        dialogs = []

        def category_dialog(keys, **kwargs):
            dialogs.append(keys)
            return MainWindow._show_enhancement_category_dialog(me, keys, **kwargs)

        me._show_enhancement_category_dialog = category_dialog
        refreshes = []   # at each refresh, whether the pipeline had started
        real_refresh = tab.refresh_enhancements_status

        def refresh_enhancements_status():
            refreshes.append(me._run_enhancements_pipeline.called)
            return real_refresh()

        monkeypatch.setattr(tab, "refresh_enhancements_status", refresh_enhancements_status)

        MainWindow._on_loading_finished(me, [], {}, [])

        assert len(dialogs) == 1
        assert refreshes == [False]
        _reads_not_extracted(tab)
        me._run_enhancements_pipeline.assert_called_once_with()
        assert me._initial_load_done is True

    def test_the_enhancements_apply_asks_for_one_reload(self, ptu_refused, slot_errors):
        tab, _base = ptu_refused
        reloads = []
        tab.merge_requested.connect(lambda: reloads.append(1))
        checkbox = next(iter(tab._enhancements_checkboxes.values()))
        checkbox.setChecked(not checkbox.isChecked())

        tab._apply_categories_btn.click()

        assert slot_errors == []
        assert reloads == [1]
        _reads_not_extracted(tab)


class _Worker:
    stopped = False
    in_background = False

    def __init__(self):
        self.calls = []

    def quit(self):
        self.calls.append("quit")

    def wait(self, *args):
        self.calls.append("wait")
        return True

    def take_working_folder(self):
        return None   # no working folder kept (perf proposal)

    def deleteLater(self):
        self.calls.append("deleteLater")


class TestRunEndingSlotsWithUnusableCache:
    """The slots that end a DataForge extraction or a generation refresh the
    tab's cache status. A failed extraction that took the cache folder with
    it (it is wiped before the new cache is made), a channel whose folder
    was never made, or a drive pulled during a run reach them with no cache
    folder, and the folder above it may refuse a new one."""

    @pytest.mark.parametrize("success", [True, False])
    def test_an_extraction_ends_without_raising(self, ptu_refused, success):
        tab, _base = ptu_refused
        worker = _Worker()
        me = _window(tab)
        me._forge_worker = worker

        MainWindow._on_dataforge_extract_finished(me, success, worker)

        assert worker.calls == ["quit", "wait", "deleteLater"]
        assert me._forge_worker is None
        _reads_not_extracted(tab)
        assert me._run_enhancements_generation.called is success
        if not success:
            me._end_simple_run.assert_called_once_with()
            assert tab._generate_enhancements_btn.isEnabled()

    def test_a_failed_generation_ends_without_raising(self, ptu_refused):
        tab, _base = ptu_refused
        me = _window(tab)
        worker = MagicMock()
        me._enhancements_worker = worker
        me._after_unfinished_generation = None

        MainWindow._on_enhancements_generation_finished(me, False, worker)

        assert me._enhancements_worker is None
        _reads_not_extracted(tab)
        assert tab._generate_enhancements_btn.isEnabled()
        me._end_simple_run.assert_called_once_with()
        me.statusBar().showMessage.assert_called_with(
            tr("status_bar.enhancement_generation_failed"))
