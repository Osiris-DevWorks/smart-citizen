"""A generation cut off by a close or a crash is offered again at the next start.

The startup check used to ask only whether each enabled enhancement INI
existed. A generation cut off part-way (the window closed, the app crashed, a
write failed) left every INI there, old or new, while the set as a whole was
neither, and the next start stayed quiet. Now:

* EnhancementsGeneratorWorker captures its folder, the DataForge build key and
  the tag fingerprint when its run starts, empties ``.dataforge_stamp`` just
  before the generator's ``main()`` and writes both stamps after it returns,
  the DataForge one last.
* ``_check_enhancements_freshness`` also asks when every file is there but the
  selected language's stamp does not match the current build, and only when
  the DataForge cache is fresh (an outdated cache is the dataforge_outdated
  question's, a never-extracted one has nothing to generate from). The
  dialog then says "out of date" instead of counting missing categories.
* The answer holds for the rest of the session: Skip is never turned into a
  run by a later call (the one after a global.ini extraction used to run the
  pipeline silently), and it is recorded before the dialog opens, so a call
  delivered by the dialog's own event loop starts nothing. A channel or
  data-folder change forgets it. There is no memory on disk: the question
  comes back at every start until the set is generated.
* The Generate button, the language switch and the startup check share one
  definition of "current" (AppSettings.enhancements_built_from_current_
  dataforge), and switching back to English honors its stamp too. A
  finished run re-reads the button from disk, so a stamp that could not be
  written keeps it lit.
* A switch's regeneration is its launch: it clears the Generate button, and
  the language picked loads whatever becomes of the run, also when it fails
  or cannot start.

Real AppSettings on a temp QSettings file and data folder, with the DataForge
cache folder and Data.p4k pointed at a temp tree through a mutable holder.
MainWindow methods run on a MagicMock self, as tests/test_extraction_stop.py
does. The worker runs synchronously with a fake generator module. Offscreen Qt
via the session ``qapp`` fixture, no pytest-qt.
"""
from __future__ import annotations

import ast
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from PyQt6.QtCore import QSettings, Qt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Same import path main_window and workers use, so the patches below reach the
# class they see (see the note in tests/test_ui_mode.py about the dual
# pythonpath).
import src.gui.main_window as main_window  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.workers import EnhancementsGeneratorWorker  # noqa: E402
from src.utils.i18n import tr  # noqa: E402
from src.utils.pak_extractor import (  # noqa: E402
    DATAFORGE_LOOKUPS_SUBPATH, DATAFORGE_RECORDS_SUBPATH,
    P4K_MTIME_STAMP, P4K_SIZE_STAMP,
)
from src.utils.atomic_io import atomic_write_text  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import tag_config_fingerprint  # noqa: E402
from tests.gui_window import build_main_window, retire_main_window  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_MODULE_NAME = "generate_enhancements_ini_worker"


# ── The disk ────────────────────────────────────────────────────────────────

class _Disk:
    """Where AppSettings finds the DataForge cache and Data.p4k. Mutable, so a
    test (or a fake generator mid-run) can repoint them."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.forge = tmp_path / "forge"
        self.p4k = tmp_path / "game" / "LIVE" / "Data.p4k"
        self.forge_error: OSError | None = None

    def forge_dir(self) -> Path:
        if self.forge_error is not None:
            raise self.forge_error
        return self.forge

    def extract(self, forge: Path | None = None, *, outdated: bool = False) -> str:
        """Write a cache like a finished extraction of the current Data.p4k,
        and return its build key. *outdated* records another size, as a game
        patch leaves it."""
        forge = forge or self.forge
        shutil.rmtree(forge, ignore_errors=True)
        records = forge / DATAFORGE_RECORDS_SUBPATH / "entities"
        records.mkdir(parents=True)
        (records / "x.xml").write_text("<x/>", encoding="utf-8")
        stat = self.p4k.stat()
        (forge / P4K_MTIME_STAMP).write_text(str(stat.st_mtime), encoding="utf-8")
        size = stat.st_size + 1 if outdated else stat.st_size
        (forge / P4K_SIZE_STAMP).write_text(str(size), encoding="utf-8")
        return AppSettings.get_dataforge_build_key(forge)

    def never_extracted(self) -> None:
        shutil.rmtree(self.forge, ignore_errors=True)
        self.forge.mkdir(parents=True)


@pytest.fixture
def disk(qapp, tmp_path, monkeypatch):
    """A fresh DataForge cache and a whole English set built from it."""
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    AppSettings.set_user_data_dir(tmp_path / "data")
    state = _Disk(tmp_path)
    for getter in ("get_dataforge_cache_dir", "get_dataforge_cache_leaf"):
        monkeypatch.setattr(AppSettings, getter, staticmethod(lambda: state.forge_dir()))
    monkeypatch.setattr(AppSettings, "get_p4k_path", staticmethod(lambda: state.p4k))
    state.p4k.parent.mkdir(parents=True)
    state.p4k.write_bytes(b"p4k")
    state.extract()
    _write_set("english")
    _stamp("english", "current")
    return state


def _enabled_files() -> list[str]:
    return sorted(AppSettings.get_enabled_enhancement_categories())


def _write_set(language: str) -> None:
    """The language's base.ini and every enabled INI, as a generation left
    them."""
    base = AppSettings.get_base_ini_path(language)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text("k=v\n", encoding="utf-8")
    enh_dir = AppSettings.get_enhancements_dir(language)
    for key in _enabled_files():
        (enh_dir / AppSettings.ENHANCEMENTS_FILES[key]).write_text(
            "; generated\n", encoding="utf-8")


def _stamp(language: str, state: str) -> None:
    """Set *language*'s .dataforge_stamp: "current", "older" or "empty"."""
    if state == "current":
        AppSettings.set_enhancements_stamp(AppSettings.get_dataforge_build_key(), language)
    elif state == "older":
        AppSettings.set_enhancements_stamp("1600000000.0", language)
    else:
        # What a run cut off after it started leaves.
        AppSettings.invalidate_enhancements_stamp(AppSettings.get_enhancements_dir(language))


# ── The startup check, on a stub self ───────────────────────────────────────

def _window(answer=None, **attrs):
    """A MagicMock self for _check_enhancements_freshness. *answer* is what
    the category dialog returns: a set (Generate) or None (Skip)."""
    me = MagicMock()
    me._close_committed = False
    # No job is running (#483): the real check over the real job list, since
    # a MagicMock's own answer is truthy and its own list is empty.
    me._p4k_worker = None
    me._enhancements_worker = None
    me._forge_worker = None
    me._WORKERS_STOPPED_ON_CLOSE = MainWindow._WORKERS_STOPPED_ON_CLOSE
    me._job_running = lambda: MainWindow._job_running(me)
    me._enhancements_prompt_answer = None
    # A staticmethod read off the class is a plain function, as
    # tests/test_extraction_stop.py does for _detach_progress_dialog.
    me._out_of_date_build_key = MainWindow._out_of_date_build_key
    me._show_enhancement_category_dialog.return_value = answer
    for name, value in attrs.items():
        setattr(me, name, value)
    return me


def _generate():
    return AppSettings.get_enabled_enhancement_categories()


def _check(me) -> None:
    MainWindow._check_enhancements_freshness(me)


def _asked(me) -> bool:
    return me._show_enhancement_category_dialog.called


@pytest.fixture(scope="module")
def new_window(qapp, tmp_path_factory):
    """One real MainWindow, built as a new session builds it, so the state
    MainWindow.__init__ leaves is read from the real thing rather than from
    _window(). Built on its own settings (tests/gui_window.py), which are
    undone before any test here runs, and retired at once: it is never
    shown, so no startup work runs."""
    tmp = tmp_path_factory.mktemp("new_window")
    with pytest.MonkeyPatch.context() as patch:
        window = build_main_window(tmp, patch, AppSettings.UI_MODE_ADVANCED)
        retire_main_window(window)
    return window


class TestStartupCheck:
    def test_a_cut_off_generation_prompts_at_the_next_start(self, disk):
        _stamp("english", "empty")
        me = _window(answer=_generate())
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)
        me._run_enhancements_pipeline.assert_called_once_with()
        assert me._enhancements_prompt_answer is True

    def test_an_older_build_stamp_prompts(self, disk):
        _stamp("english", "older")
        me = _window()
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)
        me._run_enhancements_pipeline.assert_not_called()

    def test_a_matching_stamp_stays_quiet(self, disk):
        me = _window()
        _check(me)
        assert not _asked(me)
        assert me._enhancements_prompt_answer is None

    def test_an_outdated_cache_is_left_to_the_refresh_prompt(self, disk):
        """The dataforge_outdated question covers it. Asking this one too
        would stack two questions, or ask again after that one was declined."""
        disk.extract(outdated=True)
        _stamp("english", "older")
        me = _window()
        _check(me)
        assert not _asked(me)

    def test_a_never_extracted_cache_stays_quiet(self, disk):
        """Build key "unknown": there is nothing to generate from. The folder
        exists (the fixture makes it), so the gate must be
        freshness, not the folder."""
        disk.never_extracted()
        _stamp("english", "empty")
        me = _window()
        _check(me)
        assert not _asked(me)

    def test_an_unreachable_cache_folder_stays_quiet(self, disk, caplog):
        """A cache folder override on a drive that is offline."""
        _stamp("english", "older")
        disk.forge_error = OSError("drive E: is not ready")
        me = _window()
        with caplog.at_level(logging.WARNING, logger=main_window.logger.name):
            _check(me)
        assert not _asked(me)
        assert "out of date" in caplog.text

    def test_missing_files_keep_the_missing_wording(self, disk):
        _stamp("english", "empty")
        enh_dir = AppSettings.get_enhancements_dir()
        (enh_dir / AppSettings.ENHANCEMENTS_FILES["journal"]).unlink()
        me = _window()
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            ["journal"], out_of_date=False)

    def test_the_selected_language_stamp_is_read(self, disk):
        """German selected: its own stamp decides, not English's."""
        _write_set("german")
        AppSettings.set_selected_language("german")
        _stamp("english", "current")
        _stamp("german", "empty")
        me = _window()
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)

        _stamp("english", "empty")
        _stamp("german", "current")
        me = _window()
        _check(me)
        assert not _asked(me)

    @pytest.mark.parametrize("running", ["_enhancements_worker", "_forge_worker"])
    def test_a_running_worker_suppresses_the_prompt(self, disk, running):
        _stamp("english", "empty")
        me = _window(**{running: MagicMock()})
        _check(me)
        assert not _asked(me)
        me._run_enhancements_pipeline.assert_not_called()


class TestTheAnswerHoldsForTheSession:
    def test_skip_holds_for_the_session(self, disk):
        """B1: a later call (the one after a global.ini extraction, say) used
        to run the pipeline silently after a Skip, possibly a multi-minute
        DataForge extraction the user had just declined."""
        _stamp("english", "empty")
        me = _window(answer=None)
        _check(me)
        assert me._enhancements_prompt_answer is False
        me._show_enhancement_category_dialog.reset_mock()

        _check(me)

        assert not _asked(me)
        me._run_enhancements_pipeline.assert_not_called()

    def test_skip_holds_for_missing_files_too(self, disk):
        enh_dir = AppSettings.get_enhancements_dir()
        (enh_dir / AppSettings.ENHANCEMENTS_FILES["journal"]).unlink()
        me = _window(answer=None)
        _check(me)
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once()
        me._run_enhancements_pipeline.assert_not_called()

    def test_generate_then_a_later_check_runs_it_again(self, disk):
        """Generate's saved selections run again without a second question
        while the set is still out of date (a run that failed, then a
        global.ini extraction)."""
        _stamp("english", "empty")
        me = _window(answer=_generate())
        _check(me)
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once()
        assert me._run_enhancements_pipeline.call_count == 2

    def test_a_check_from_inside_the_open_dialog_starts_nothing(self, disk):
        """The dialog's event loop can deliver another load, and its check
        must neither ask again nor start the pipeline behind the question."""
        _stamp("english", "empty")
        me = _window()
        seen_inside = []

        def dialog(*_args, **_kwargs):
            if not seen_inside:
                seen_inside.append(me._enhancements_prompt_answer)
                _check(me)   # delivered while the dialog is open
                seen_inside.append(me._run_enhancements_pipeline.call_count)
            return _generate()

        me._show_enhancement_category_dialog.side_effect = dialog
        _check(me)

        assert seen_inside == [False, 0]
        me._show_enhancement_category_dialog.assert_called_once()
        me._run_enhancements_pipeline.assert_called_once_with()

    def test_a_new_window_has_not_asked_yet(self, new_window):
        """Decision 2 rests on MainWindow.__init__ starting the answer at None
        ("not asked"). False would read as a Skip already given, so no start
        would ask again, about missing files (#363) either."""
        assert new_window._enhancements_prompt_answer is None

    def test_a_built_window_stays_out_of_the_real_install(self, qapp, tmp_path):
        """build_main_window points the game install into its temp folder.
        With nothing saved, the install would come from the old installer's
        registry key or a scan of the common install folders, which on a
        developer's PC find their real game, and MainWindow.__init__ then
        runs ensure_user_cfg_language on that channel's real user.cfg. Both
        fallbacks are made to fail here, so reaching either fails the test."""
        def _reached(*_args, **_kwargs):
            raise AssertionError("the window looked for the real install")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(AppSettings, "_read_legacy_installer_sc_directory",
                          staticmethod(_reached))
            patch.setattr("src.utils.settings._scan_common_sc_install_locations", _reached)
            window = build_main_window(tmp_path, patch, AppSettings.UI_MODE_ADVANCED)
            try:
                install = Path(AppSettings.get_game_install_path())
                assert tmp_path in install.parents
                assert not (install / "user.cfg").exists()
            finally:
                retire_main_window(window)

    def test_skip_asks_again_next_launch(self, disk, new_window):
        """Decision 2: no memory on disk. A Skip lasts for its session only,
        and the next start asks again until the set is generated. The next
        launch starts from the answer a real new window holds."""
        _stamp("english", "empty")
        enh_dir = AppSettings.get_enhancements_dir()
        before = sorted(p.name for p in enh_dir.iterdir())
        _check(_window(answer=None))
        assert sorted(p.name for p in enh_dir.iterdir()) == before

        next_launch = _window(
            answer=None, _enhancements_prompt_answer=new_window._enhancements_prompt_answer)
        _check(next_launch)

        next_launch._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)

    @pytest.mark.parametrize("answer", [False, True])
    @pytest.mark.parametrize("change", ["channel", "data folder"])
    def test_a_channel_or_data_folder_change_forgets_the_answer(
        self, monkeypatch, change, answer
    ):
        """Another channel or data folder is another set: a Skip must not
        silence its question, and a Generate must not run its pipeline
        without asking."""
        monkeypatch.setattr(main_window, "AppSettings", MagicMock())
        me = _window(_enhancements_prompt_answer=answer)
        if change == "channel":
            MainWindow._on_channel_changed(me, "PTU")
        else:
            MainWindow._on_data_dir_changed(me, "E:/SC data")
        assert me._enhancements_prompt_answer is None


class TestOutOfDateDialog:
    """The real dialog, with exec() answering Skip."""

    @pytest.fixture
    def shown(self, qapp, disk, monkeypatch):
        from PyQt6.QtWidgets import QDialog, QWidget

        class Parent(QWidget):
            def __init__(self):
                super().__init__()
                self.enhancements_tab = MagicMock()

        parent = Parent()
        dialogs = []

        def fake_exec(dialog):
            dialogs.append(dialog)
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)

        def show(file_keys, out_of_date):
            answer = MainWindow._show_enhancement_category_dialog(
                parent, file_keys, out_of_date=out_of_date)
            return answer, dialogs[-1]

        yield show
        parent.deleteLater()
        qapp.processEvents()

    @staticmethod
    def _texts(dialog):
        from PyQt6.QtWidgets import QCheckBox, QLabel
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        boxes = {w.text(): w.isChecked() for w in dialog.findChildren(QCheckBox)}
        return labels, boxes

    def test_the_outdated_dialog_says_out_of_date(self, shown):
        answer, dialog = shown(_enabled_files(), out_of_date=True)
        assert answer is None
        labels, boxes = self._texts(dialog)
        assert tr("extract.outdated_categories_body") in labels
        assert tr("extract.outdated_categories_body") != "extract.outdated_categories_body"
        # Every enabled category is offered, ticked, with its plain label.
        assert boxes == {label: True for label in AppSettings.ENHANCEMENT_LABELS.values()}
        missing = {tr("extract.missing_category_label", label=label)
                   for label in AppSettings.ENHANCEMENT_LABELS.values()}
        assert not missing & set(boxes)

    def test_the_missing_dialog_keeps_its_count_and_suffix(self, shown):
        """Control for the test above: missing mode is unchanged."""
        _answer, dialog = shown(["journal"], out_of_date=False)
        labels, boxes = self._texts(dialog)
        assert tr("extract.outdated_categories_body") not in labels
        assert tr("extract.missing_categories_body", count=1,
                  noun=tr("extract.category_singular")) in labels
        journal = AppSettings.ENHANCEMENT_LABELS["journal"]
        assert boxes[tr("extract.missing_category_label", label=journal)] is True
        assert boxes[AppSettings.ENHANCEMENT_LABELS["ships"]] is False


# ── The worker ──────────────────────────────────────────────────────────────

class _FakeGenerator:
    """Stands in for scripts/generate_enhancements_ini.py, loaded by the
    worker through importlib."""

    def __init__(self):
        self.calls = []
        self.loads = 0
        self.during_main = None    # called inside main()
        self.during_load = None    # called inside the module load
        self.load_error = None     # raised by the module load

    def main(self, base_ini, forge_dir, **kwargs):
        self.calls.append((base_ini, forge_dir, kwargs))
        if self.during_main is not None:
            self.during_main()


class _Loader(importlib.abc.Loader):
    def __init__(self, generator):
        self.generator = generator

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.generator.loads += 1
        if self.generator.during_load is not None:
            self.generator.during_load()
        if self.generator.load_error is not None:
            raise self.generator.load_error
        module.main = self.generator.main


@pytest.fixture
def generator(monkeypatch):
    fake = _FakeGenerator()
    report = MagicMock()
    report.errors = []
    report.summary_line.return_value = "0 patches"
    monkeypatch.setattr("src.utils.dataforge_patcher.apply_patches",
                        MagicMock(return_value=report))
    real = importlib.util.spec_from_file_location

    def spec_from_file_location(name, *args, **kwargs):
        if name == _MODULE_NAME:
            return importlib.machinery.ModuleSpec(name, _Loader(fake))
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec_from_file_location)
    yield fake
    sys.modules.pop(_MODULE_NAME, None)


def _run_worker(language=None):
    worker = EnhancementsGeneratorWorker(tag_configs={}, annotate_mission_descs=True,
                                         language=language)
    finished, errors = [], []
    worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
    worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    worker.run()
    return finished, errors


def _stamp_files(folder: Path) -> dict[str, str]:
    found = {}
    for name in (AppSettings.ENHANCEMENTS_STAMP_NAME, AppSettings.TAG_CONFIG_STAMP_NAME):
        if (folder / name).exists():
            found[name] = (folder / name).read_text(encoding="utf-8")
    return found


class TestTheWorkerStamps:
    def test_the_stamp_is_empty_while_main_runs_and_written_after(self, disk, generator):
        key = AppSettings.get_dataforge_build_key()
        seen = []
        generator.during_main = lambda: seen.append(AppSettings.get_enhancements_stamp())

        finished, errors = _run_worker()

        assert (finished, errors) == ([True], [])
        assert seen == [""]
        assert AppSettings.get_enhancements_stamp() == key
        assert AppSettings.get_tag_config_stamp() == tag_config_fingerprint({}, True)
        _base, forge_dir, kwargs = generator.calls[0]
        assert forge_dir == disk.forge
        assert kwargs["english_base_ini_path"] == AppSettings.get_base_ini_path("english")

    def test_a_run_that_fails_inside_main_leaves_no_stamp_and_the_next_start_prompts(
        self, disk, generator
    ):
        def fail():
            raise RuntimeError("disk full while writing")

        generator.during_main = fail
        finished, errors = _run_worker()

        assert finished == [False] and errors == ["disk full while writing"]
        assert AppSettings.get_enhancements_stamp() == ""
        me = _window()
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)

    def test_a_failure_before_main_keeps_the_old_stamp(self, disk, generator):
        """A failure in the module load (or the patches) never reached the
        INIs, so it must not cost a question at the next start."""
        key = AppSettings.get_enhancements_stamp()
        generator.load_error = SyntaxError("broken generator")

        finished, _errors = _run_worker()

        assert finished == [False]
        assert generator.calls == []
        assert AppSettings.get_enhancements_stamp() == key
        me = _window()
        _check(me)
        assert not _asked(me)

    def test_a_successful_run_ends_the_prompts(self, disk, generator):
        """Not a loop: a cut-off set is asked about, Generate runs it, and the
        start after that is quiet."""
        _stamp("english", "empty")
        first = _window(answer=_generate())
        _check(first)
        first._run_enhancements_pipeline.assert_called_once_with()

        finished, _errors = _run_worker()   # what the pipeline starts

        assert finished == [True]
        next_launch = _window()
        _check(next_launch)
        assert not _asked(next_launch)

    def test_the_stamps_go_where_the_run_started(self, disk, generator, tmp_path):
        """B2: the folder and key were read when the run ended, so a data
        folder or cache folder change during a hidden run stamped a set this
        run never wrote."""
        started_dir = AppSettings.get_enhancements_dir()
        started_key = AppSettings.get_dataforge_build_key()
        expected_tag = tag_config_fingerprint({}, True)

        def repoint():
            AppSettings.set_user_data_dir(tmp_path / "other-data")
            disk.forge = tmp_path / "other-forge"
            disk.extract()
            (disk.forge / P4K_MTIME_STAMP).write_text("another-build", encoding="utf-8")

        generator.during_main = repoint
        finished, _errors = _run_worker()

        assert finished == [True]
        new_dir = AppSettings.get_enhancements_dir()
        assert new_dir != started_dir
        assert AppSettings.get_dataforge_build_key() != started_key
        assert _stamp_files(started_dir) == {
            AppSettings.ENHANCEMENTS_STAMP_NAME: started_key,
            AppSettings.TAG_CONFIG_STAMP_NAME: expected_tag,
        }
        assert _stamp_files(new_dir) == {}

    def test_the_dataforge_stamp_is_written_last(self, disk, generator, monkeypatch):
        """It certifies the whole set, so nothing may follow it."""
        order = []
        for name in ("set_tag_config_stamp", "set_enhancements_stamp",
                     "invalidate_enhancements_stamp"):
            real = getattr(AppSettings, name)

            def spy(*args, _name=name, _real=real, **kwargs):
                order.append(_name)
                return _real(*args, **kwargs)

            monkeypatch.setattr(AppSettings, name, staticmethod(spy))
        generator.during_main = lambda: order.append("main")

        _run_worker()

        assert order == ["invalidate_enhancements_stamp", "main",
                         "set_tag_config_stamp", "set_enhancements_stamp"]

    def test_old_temp_files_are_swept_at_the_start(self, disk, generator):
        """Only a hard kill between a temp and its swap leaves one."""
        enh_dir = AppSettings.get_enhancements_dir()
        lookups = disk.forge / DATAFORGE_LOOKUPS_SUBPATH
        lookups.mkdir()
        aged = time.time() - 11 * 60
        old_ini, old_pickle = enh_dir / ".sc-oldini1.tmp", lookups / ".sc-oldpkl1.tmp"
        young = enh_dir / ".sc-young01.tmp"
        for path in (old_ini, old_pickle, young):
            path.write_bytes(b"partial")
        for path in (old_ini, old_pickle):
            os.utime(path, (aged, aged))
        seen = []
        generator.during_main = lambda: seen.append(
            (old_ini.exists(), old_pickle.exists(), young.exists()))

        _run_worker()

        assert seen == [(False, False, True)]


# ── The worker, stopped by a close ──────────────────────────────────────────

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
_WORKERS_LOGGER = "src.gui.workers"


class GenerationStopped(Exception):
    """The fake generator's stop. The worker loads the real script afresh for
    every run, so it tells the script's GenerationStopped apart by its name,
    and a class of the same name stands in for it here
    (test_the_stop_is_known_by_the_generators_own_name pins the name)."""


def _wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the stop request")
        time.sleep(0.01)


def _should_cancel(generator):
    """What the worker handed the generator's main() as should_cancel."""
    return generator.calls[-1][2]["should_cancel"]


def _stop_while_running(reached: threading.Event, holder: dict):
    """Start the worker on a real thread, and request the stop once *reached*
    is set. requestInterruption() before start() is dropped, and
    isInterruptionRequested() is False in a synchronous run(), so these tests
    need a started thread. It is always waited for, also when a test fails."""
    worker = holder["worker"] = EnhancementsGeneratorWorker(
        tag_configs={}, annotate_mission_descs=True)
    finished, errors = [], []
    worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
    worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    try:
        assert reached.wait(5)
        worker.requestInterruption()
        assert worker.wait(5000)
    finally:
        worker.requestInterruption()
        worker.wait(5000)
    return worker, finished, errors


def _records(caplog, level):
    return [r.getMessage() for r in caplog.records
            if r.levelno == level and r.name == _WORKERS_LOGGER]


def _ini_bytes(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in folder.glob("*.ini")}


class TestTheWorkerStops:
    """Closing asks the worker to stop. The generator's main() stops between
    jobs and never during its writes (tests/test_generation_writes.py), and
    the worker reports a stop as no failure: finished(False), no error
    signal and nothing at ERROR, which would fire the global error dialog on
    a window that is closing."""

    def test_a_stop_inside_main_is_quiet_and_leaves_the_stamp_empty(
        self, disk, generator, caplog
    ):
        enh_dir = AppSettings.get_enhancements_dir()
        before = _ini_bytes(enh_dir)
        reached, holder = threading.Event(), {}

        def stop_at_the_next_job_boundary():
            reached.set()
            _wait_for(_should_cancel(generator))
            raise GenerationStopped("before the ships generator")

        generator.during_main = stop_at_the_next_job_boundary
        with caplog.at_level(logging.INFO, logger=_WORKERS_LOGGER):
            worker, finished, errors = _stop_while_running(reached, holder)

        assert (finished, errors) == ([False], [])
        assert worker.stopped is True
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert _records(caplog, logging.WARNING) == []
        assert ("Enhancements generation stopped (before the ships generator)"
                in _records(caplog, logging.INFO))
        assert _ini_bytes(enh_dir) == before
        # main() had begun, so the set reads as out of date: the next start
        # offers to generate it again.
        assert AppSettings.get_enhancements_stamp() == ""
        me = _window()
        _check(me)
        me._show_enhancement_category_dialog.assert_called_once_with(
            _enabled_files(), out_of_date=True)

    def test_a_failure_after_a_stop_is_quiet_too(self, disk, generator, caplog):
        """A failure on the way out of a stop belongs to the stop, as for the
        extraction workers (#471)."""
        reached, holder = threading.Event(), {}

        def fail_after_the_stop():
            reached.set()
            _wait_for(_should_cancel(generator))
            raise OSError("a file still held")

        generator.during_main = fail_after_the_stop
        with caplog.at_level(logging.INFO, logger=_WORKERS_LOGGER):
            worker, finished, errors = _stop_while_running(reached, holder)

        assert (finished, errors) == ([False], [])
        assert worker.stopped is True
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert _records(caplog, logging.WARNING) == [
            "Enhancements generation ended with an error after a stop: a file still held"
        ]

    @pytest.mark.parametrize("stopped_during", ["the sweep", "the patches", "the module load"])
    def test_a_stop_before_main_keeps_the_old_stamp(
        self, disk, generator, monkeypatch, stopped_during
    ):
        """Stopped before the generator's main(): each step before it is
        followed by a check, so the steps after the one the stop landed in
        never run, the generator never starts, the INIs and the stamp are
        untouched, and the next start asks nothing."""
        key = AppSettings.get_enhancements_stamp()
        enh_dir = AppSettings.get_enhancements_dir()
        before = _ini_bytes(enh_dir)
        reached, holder = threading.Event(), {}
        report = MagicMock()
        report.errors = []
        report.summary_line.return_value = "0 patches"
        patched = []

        def until_stopped(*_args):
            reached.set()
            _wait_for(holder["worker"].isInterruptionRequested)

        def patches(*args, **kwargs):
            patched.append(1)
            if stopped_during == "the patches":
                until_stopped()
            return report

        monkeypatch.setattr("src.utils.dataforge_patcher.apply_patches", patches)
        if stopped_during == "the sweep":
            monkeypatch.setattr("src.gui.workers.sweep_stale_temps", until_stopped)
        elif stopped_during == "the module load":
            generator.during_load = until_stopped
        worker, finished, errors = _stop_while_running(reached, holder)

        assert (finished, errors) == ([False], [])
        assert worker.stopped is True
        assert len(patched) == (0 if stopped_during == "the sweep" else 1)
        assert generator.loads == (1 if stopped_during == "the module load" else 0)
        assert generator.calls == []
        assert AppSettings.get_enhancements_stamp() == key
        assert _ini_bytes(enh_dir) == before
        me = _window()
        _check(me)
        assert not _asked(me)

    def test_a_stop_during_the_writes_still_certifies(self, disk, generator):
        """main() ignores a stop once its writes have begun and returns with
        the whole set written, so the run stamps it as usual."""
        key = AppSettings.get_dataforge_build_key()
        _stamp("english", "older")
        reached, holder = threading.Event(), {}

        def stopped_while_writing():
            reached.set()
            _wait_for(_should_cancel(generator))   # the stop lands mid-write

        generator.during_main = stopped_while_writing
        worker, finished, errors = _stop_while_running(reached, holder)

        assert (finished, errors) == ([True], [])
        assert worker.stopped is False
        assert AppSettings.get_enhancements_stamp() == key
        assert AppSettings.get_tag_config_stamp() == tag_config_fingerprint({}, True)

    def test_the_worker_hands_main_its_stop_check(self, disk, generator):
        worker = EnhancementsGeneratorWorker(tag_configs={}, annotate_mission_descs=True)
        worker.run()
        assert _should_cancel(generator) == worker.isInterruptionRequested

    def test_the_stop_is_known_by_the_generators_own_name(self):
        """The worker matches the script's stop by its class name, so the two
        must not drift apart."""
        tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        assert GenerationStopped.__name__ in classes
        bases = [b.id for b in classes[GenerationStopped.__name__].bases if isinstance(b, ast.Name)]
        # Not a RuntimeError, which an `except RuntimeError` could swallow.
        assert bases == ["Exception"]


# ── The Generate button and the language switch agree ───────────────────────

def _set_cache(disk, cache: str) -> None:
    if cache == "fresh":
        disk.extract()
    elif cache == "outdated":
        disk.extract(outdated=True)
    else:
        disk.never_extracted()


def _startup_asks() -> bool:
    me = _window()
    _check(me)
    return _asked(me)


# English's stamp while German's is each of these: current while German's is
# stale, empty while German's is current. A check that read English's stamp
# would then give the opposite answer.
_ENGLISH_AGAINST_GERMAN = {"empty": "current", "older": "current", "current": "empty"}


@pytest.mark.parametrize("language", ["english", "german"])
@pytest.mark.parametrize("cache", ["fresh", "outdated", "none"])
def test_startup_prompt_implies_a_lit_generate_button(disk, cache, language):
    """After a Skip, Generate used to sit grey over the set the startup check
    had just called out of date, the same class of bug #363 fixed for tags.
    Both read the selected language's stamp: with German selected, English's
    is set the other way round (_ENGLISH_AGAINST_GERMAN)."""
    from src.gui.enhancements_tab import EnhancementsTab

    if language != AppSettings.DEFAULT_LANGUAGE:
        _write_set(language)
        AppSettings.set_selected_language(language)
    tab = EnhancementsTab()
    seen = {}
    for stamp in ("empty", "older", "current"):
        _set_cache(disk, cache)
        _stamp(language, stamp)
        if language != AppSettings.DEFAULT_LANGUAGE:
            _stamp(AppSettings.DEFAULT_LANGUAGE, _ENGLISH_AGAINST_GERMAN[stamp])
        asks, lit = _startup_asks(), tab._compute_initial_enhancements_dirty()
        seen[stamp] = (asks, lit)
        assert lit or not asks, f"asked at startup but Generate is grey: {stamp}, {cache}"
    if cache == "fresh":
        # Not vacuous: the fresh cache asks for the two stale stamps, and a
        # matching set leaves both quiet and grey.
        assert seen == {"empty": (True, True), "older": (True, True),
                        "current": (False, False)}
    else:
        # The cache itself lights the button, and the check leaves it to the
        # refresh prompt or to a first extraction.
        assert all(seen[s] == (False, True) for s in seen)


def test_nothing_enabled_is_never_asked_about(disk):
    """Every category turned off, and a stamp left empty (or from before a
    game patch and a re-extraction): there is nothing to generate. The
    startup check and the Generate button each have their own gate for this,
    or the user would get an empty "out of date" dialog at every start and a
    lit button with nothing to do."""
    from src.gui.enhancements_tab import EnhancementsTab

    _stamp("english", "empty")
    # Control: with the categories on, this stamp asks and lights.
    assert _startup_asks() is True
    assert EnhancementsTab()._compute_initial_enhancements_dirty() is True

    for key in AppSettings.ENHANCEMENT_CATEGORY_FILES:
        AppSettings.set_enhancement_category_enabled(key, False)
    tab = EnhancementsTab()
    assert not AppSettings.get_enabled_enhancement_categories()
    assert not any(cb.isChecked() for cb in tab._enhancements_checkboxes.values())

    assert _startup_asks() is False
    assert tab._compute_initial_enhancements_dirty() is False


@pytest.mark.parametrize("stamp_written", [True, False])
def test_a_run_whose_stamp_was_not_written_keeps_generate_lit(
    disk, generator, monkeypatch, stamp_written
):
    """set_enhancements_stamp only logs a failed write (a backup tool or a
    scanner holding .dataforge_stamp past the writer's retries), so the run
    still finishes as a success. The launch had cleared Generate, and the
    finish used to leave it grey over a set the next start asks about. It is
    re-read from disk on a success now, and stays lit."""
    from src.gui.enhancements_tab import EnhancementsTab

    tab = EnhancementsTab()
    assert tab._generate_enhancements_btn.isEnabled() is False   # current to begin with
    if not stamp_written:
        def held(path, text, **kwargs):
            if Path(path).name == AppSettings.ENHANCEMENTS_STAMP_NAME and text:
                raise PermissionError(13, "held by another program", str(path))
            atomic_write_text(path, text, **kwargs)

        monkeypatch.setattr("src.utils.settings.atomic_write_text", held)
    tab.mark_enhancements_clean()    # what launching the run does (#292)

    finished, errors = _run_worker()

    assert (finished, errors) == ([True], [])
    assert AppSettings.enhancements_built_from_current_dataforge() is stamp_written
    me = MagicMock()
    me.enhancements_tab = tab
    me._close_committed = False
    me._simple_run_active = False
    me._enhancements_progress_dialog = None
    me._after_unfinished_generation = None
    MainWindow._on_enhancements_generation_finished(me, True, me._enhancements_worker)
    assert tab._generate_enhancements_btn.isEnabled() is not stamp_written
    assert tab._enhancements_dirty is not stamp_written


@pytest.mark.parametrize("changed_mid_run", [True, False])
def test_a_successful_run_keeps_a_change_made_while_it_ran(disk, changed_mid_run):
    """The finished run's re-read from disk only ever lights Generate. A
    change made while the run went on, here a global.ini extraction that
    finished behind it (mark_enhancements_dirty), keeps the button lit after
    a success, though the set on disk is current. Re-deriving the button
    from disk alone would turn it grey and drop that change. The control,
    with nothing changed, goes grey."""
    from src.gui.enhancements_tab import EnhancementsTab

    tab = EnhancementsTab()
    assert tab._generate_enhancements_btn.isEnabled() is False   # current to begin with
    tab.mark_enhancements_clean()    # what launching the run does (#292)
    tab.set_operation_running(tr("enhancements.generating_enhancements_tooltip"))
    if changed_mid_run:
        tab.mark_enhancements_dirty()

    tab.set_operation_idle(True)

    assert tab._compute_initial_enhancements_dirty() is False    # the set itself is current
    assert tab._generate_enhancements_btn.isEnabled() is changed_mid_run
    assert tab._enhancements_dirty is changed_mid_run


def test_a_tick_not_yet_saved_does_not_keep_generate_lit_after_a_run(disk):
    """A run generates the saved categories, not the ticked ones: a tick
    counts only once the category Apply button saves it. The finished run's
    re-read judges the saved set, so a ticked but unsaved category, whose
    file the run never writes, does not leave Generate lit after every run
    (each click would start another full run that ends the same way). The
    control shows the live ticks would have called it dirty."""
    from src.gui.enhancements_tab import EnhancementsTab

    key = next(iter(AppSettings.ENHANCEMENT_CATEGORY_FILES))
    AppSettings.set_enhancement_category_enabled(key, False)
    enh_dir = AppSettings.get_enhancements_dir()
    for filename in EnhancementsTab._files_for_category(key):
        (enh_dir / filename).unlink(missing_ok=True)
    tab = EnhancementsTab()
    assert tab._generate_enhancements_btn.isEnabled() is False    # the saved set is current

    tab._enhancements_checkboxes[key].setChecked(True)    # ticked, not applied
    assert AppSettings.get_enhancement_category_enabled(key) is False
    assert tab._compute_initial_enhancements_dirty() is True      # control: the live ticks
    tab.mark_enhancements_clean()    # what launching the run does (#292)
    tab.set_operation_running(tr("enhancements.generating_enhancements_tooltip"))

    tab.set_operation_idle(True)

    assert tab._generate_enhancements_btn.isEnabled() is False
    assert tab._enhancements_dirty is False


def test_startup_and_the_language_switch_agree(disk):
    for state in ("empty", "older", "current", "missing"):
        _write_set("english")
        _stamp("english", "current" if state == "missing" else state)
        if state == "missing":
            enh_dir = AppSettings.get_enhancements_dir()
            (enh_dir / AppSettings.ENHANCEMENTS_FILES["journal"]).unlink()
        fresh = MainWindow._language_enhancements_fresh(MagicMock(), "english")
        assert _startup_asks() is (not fresh), state


class TestLanguageEnhancementsFresh:
    @pytest.mark.parametrize("stamp, fresh", [
        ("current", True), ("empty", False), ("older", False),
    ])
    def test_the_stamp_decides(self, disk, stamp, fresh):
        _stamp("english", stamp)
        assert MainWindow._language_enhancements_fresh(MagicMock(), "english") is fresh

    def test_a_missing_file_is_stale(self, disk):
        enh_dir = AppSettings.get_enhancements_dir()
        (enh_dir / AppSettings.ENHANCEMENTS_FILES["journal"]).unlink()
        assert MainWindow._language_enhancements_fresh(MagicMock(), "english") is False

    def test_no_categories_is_fresh(self, disk):
        _stamp("english", "empty")
        for key in AppSettings.ENHANCEMENT_CATEGORY_FILES:
            AppSettings.set_enhancement_category_enabled(key, False)
        assert MainWindow._language_enhancements_fresh(MagicMock(), "english") is True

    def test_another_languages_stamp_does_not_vouch(self, disk):
        _write_set("german")
        _stamp("german", "empty")
        assert MainWindow._language_enhancements_fresh(MagicMock(), "german") is False
        assert MainWindow._language_enhancements_fresh(MagicMock(), "english") is True


# ── G: switching back to English ────────────────────────────────────────────

def _switching_self():
    me = MagicMock()
    # No extraction is running: a MagicMock's truthy default would read as
    # one, and the switch then loads the prose without regenerating (#483).
    me._p4k_worker = None
    me._forge_worker = None
    me._language_enhancements_fresh = (
        lambda language: MainWindow._language_enhancements_fresh(me, language))
    me._reload_with_language_enhancements = (
        lambda language: MainWindow._reload_with_language_enhancements(me, language))
    return me


class TestSwitchingBackToEnglish:
    """English used to load straight away on a switch, so an English set left
    on an older build (a re-extraction made while another language was
    selected regenerates only that language) loaded as if it were fresh."""

    def test_switching_to_english_regenerates_stale_english(self, disk):
        _stamp("english", "older")
        me = _switching_self()
        MainWindow._apply_language_base_source(me, "english")
        me._run_enhancements_generation.assert_called_once()
        assert me._run_enhancements_generation.call_args.kwargs["language"] == "english"
        me._show_loading_progress.assert_not_called()
        assert AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL) == str(
            AppSettings.get_base_ini_path("english"))

    def test_switching_to_a_current_english_just_loads(self, disk):
        me = _switching_self()
        MainWindow._apply_language_base_source(me, "english")
        me._run_enhancements_generation.assert_not_called()
        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))

    def test_switching_to_english_without_a_base_ini_just_loads(self, disk):
        _stamp("english", "older")
        AppSettings.get_base_ini_path("english").unlink()
        me = MagicMock()
        MainWindow._apply_language_base_source(me, "english")
        me._reload_with_language_enhancements.assert_not_called()
        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))


# ── The switch's own regeneration ───────────────────────────────────────────

class _StubGenerationWorker:
    """Stands in for EnhancementsGeneratorWorker in _run_enhancements_generation.
    Nothing runs: a test calls the finished slot itself."""

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


def _regenerating_self(monkeypatch, **attrs):
    """_switching_self, also running the real _run_enhancements_generation
    with the worker and its dialog stubbed. Returns it and the workers made."""
    made = []

    def make_worker(**kwargs):
        made.append(_StubGenerationWorker(**kwargs))
        return made[-1]

    monkeypatch.setattr(main_window, "EnhancementsGeneratorWorker", make_worker)
    monkeypatch.setattr(main_window, "AnimatedProgressDialog", MagicMock())
    me = _switching_self()
    me._close_committed = False
    me._enhancements_worker = None
    me._forge_progress_dialog = None
    me._simple_run_active = False
    me._error_dialog_showing = False
    me._after_error_dialog = None
    me._after_unfinished_generation = None
    me._run_enhancements_generation = (
        lambda **kwargs: MainWindow._run_enhancements_generation(me, **kwargs))
    for name, value in attrs.items():
        setattr(me, name, value)
    return me, made


def _finish(me, success: bool, worker) -> None:
    MainWindow._on_enhancements_generation_finished(me, success, worker)


class TestTheSwitchRegeneration:
    """A switch to a language whose set is stale regenerates it before the
    reload (English too, since G). The run is the switch's launch, and the
    switch leaves its reload to it, so whatever becomes of the run, the
    language picked loads."""

    @pytest.mark.parametrize("success", [True, False])
    def test_the_run_settles_the_generate_button(self, disk, monkeypatch, success):
        """The switch lights Generate for the stale set (_on_language_changed
        re-derives it), and the run clears it at launch, as
        _run_enhancements_pipeline does (#292). It used to stay red over the
        set a successful run had just made current. A failure relights it."""
        from src.gui.enhancements_tab import EnhancementsTab

        _stamp("english", "older")
        tab = EnhancementsTab()
        tab.refresh_enhancements_dirty_state()    # what the switch does first
        assert tab._generate_enhancements_btn.isEnabled() is True
        me, made = _regenerating_self(monkeypatch, enhancements_tab=tab)

        MainWindow._apply_language_base_source(me, "english")

        assert len(made) == 1 and made[0].kwargs["language"] == "english"
        assert tab._generate_enhancements_btn.isEnabled() is False   # running
        if success:
            _stamp("english", "current")    # what a finished run writes last
        _finish(me, success, made[0])
        assert tab._generate_enhancements_btn.isEnabled() is not success
        assert tab._enhancements_dirty is not success

    def test_a_successful_run_reloads_once_with_its_enhancements(self, disk, monkeypatch):
        _stamp("english", "older")
        me, made = _regenerating_self(monkeypatch)
        MainWindow._apply_language_base_source(me, "english")
        me.statusBar().showMessage.assert_called_with(
            tr("dialogs.language_generating_enhancements", language="english"))
        me._show_loading_progress.assert_not_called()

        _finish(me, True, made[0])

        me._show_loading_progress.assert_called_once_with(
            tr("progress.reloading_with_enhancements"))
        assert me._after_unfinished_generation is None

    def test_a_failed_run_still_loads_the_language(self, disk, monkeypatch):
        """A failure used to only set the status bar, leaving the table in the
        previous language under the new selection."""
        _stamp("english", "older")
        me, made = _regenerating_self(monkeypatch)
        MainWindow._apply_language_base_source(me, "english")

        _finish(me, False, made[0])

        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))
        assert me._after_unfinished_generation is None

    @pytest.mark.parametrize("closing", [False, True])
    def test_a_failed_runs_reload_waits_for_its_error_dialog(
        self, disk, monkeypatch, closing
    ):
        """The run's failure is logged at ERROR, and the finished slot runs
        inside that error dialog's event loop. The reload waits for the
        dialog to close rather than opening the loading dialog over it, and
        is dropped if the window closed meanwhile."""
        _stamp("english", "older")
        me, made = _regenerating_self(monkeypatch)
        me._suppressed_error_count = 0
        me._last_error_dialog_time = 0.0
        me._ERROR_DIALOG_COOLDOWN_SEC = MainWindow._ERROR_DIALOG_COOLDOWN_SEC
        MainWindow._apply_language_base_source(me, "english")
        inside = []

        def exec_():
            # The run's finished, delivered while the dialog is open.
            _finish(me, False, made[0])
            inside.append(me._show_loading_progress.call_count)
            me._close_committed = closing

        box_class = MagicMock()
        box_class.return_value.exec.side_effect = exec_
        monkeypatch.setattr(main_window, "QMessageBox", box_class)

        MainWindow._show_error_dialog(me, "Enhancements generation error: boom", "")

        assert inside == [0]
        if closing:
            me._show_loading_progress.assert_not_called()
        else:
            me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))
        assert me._after_error_dialog is None

    def test_a_switch_while_a_generation_runs_loads_at_once(self, disk, monkeypatch):
        """A hidden generation already running refuses the start, and nothing
        else would reload this switch: the language loads at once with the
        set it has, and the status bar does not claim a regeneration."""
        _stamp("english", "older")
        running = _StubGenerationWorker()
        me, made = _regenerating_self(monkeypatch, _enhancements_worker=running)

        MainWindow._apply_language_base_source(me, "english")

        assert made == []
        assert me._enhancements_worker is running
        me._show_loading_progress.assert_called_once_with(tr("dialogs.merging_sources"))
        claimed = call(tr("dialogs.language_generating_enhancements", language="english"))
        assert claimed not in me.statusBar().showMessage.call_args_list

    def test_a_refused_start_leaves_the_button_to_the_running_generation(
        self, disk, monkeypatch
    ):
        """The switch clears Generate before it tries to start. When the start
        is refused, the generation already running re-reads the selected
        language's set from disk as it ends, so the button comes back lit for
        the stale set it did not generate."""
        from src.gui.enhancements_tab import EnhancementsTab

        _stamp("english", "older")
        tab = EnhancementsTab()
        running = _StubGenerationWorker()
        tab.set_operation_running("another language's generation")
        me, made = _regenerating_self(monkeypatch, enhancements_tab=tab,
                                      _enhancements_worker=running)

        MainWindow._apply_language_base_source(me, "english")
        assert made == []
        assert tab._generate_enhancements_btn.isEnabled() is False

        _finish(me, True, running)
        assert tab._generate_enhancements_btn.isEnabled() is True

    def test_a_switch_while_closing_loads_nothing(self, disk, monkeypatch):
        """Closing (#471): nothing new may start, a reload included."""
        _stamp("english", "older")
        me, made = _regenerating_self(monkeypatch, _close_committed=True)

        MainWindow._apply_language_base_source(me, "english")

        assert made == []
        me._show_loading_progress.assert_not_called()

    def test_only_the_switch_run_carries_the_reload(self, disk, monkeypatch):
        """Every run sets the fallback, so a run of another kind (Generate,
        the pipeline) never inherits one, and its failure loads nothing."""
        me, made = _regenerating_self(monkeypatch, _after_unfinished_generation=MagicMock())

        assert MainWindow._run_enhancements_generation(me) is True
        assert me._after_unfinished_generation is None
        _finish(me, False, made[0])

        me._show_loading_progress.assert_not_called()
