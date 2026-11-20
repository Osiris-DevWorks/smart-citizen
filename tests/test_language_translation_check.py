"""The startup check for a newer community translation (#579).

A language switch downloads the selected language's global.ini, but nothing
else did, so after a game patch the table kept the old translation. Each
start now fetches it again in the background (a conditional request, URL
sources only) and, when a new file came down, empties that language's
enhancements stamp and reloads through the language switch's own path.

The real MainWindow methods run on a MagicMock self, as in
test_run_in_background.py, with the worker and AppSettings faked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.gui import main_window as mw  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.unit

URL = "https://example.invalid/german/global.ini"


class FakeWorker:
    made: list = []

    def __init__(self, source, dest):
        self.source, self.dest = source, dest
        self.changed = False
        self.started = False
        self.finished = MagicMock()
        FakeWorker.made.append(self)

    def start(self):
        self.started = True

    def quit(self):
        pass

    def wait(self, *_):
        return True

    def isRunning(self):
        return False


@pytest.fixture
def env(monkeypatch, tmp_path):
    FakeWorker.made = []
    state = {"language": "german", "url": URL, "invalidated": [], "sources": []}
    dest = tmp_path / "lang" / "german" / "base.ini"
    S = mw.AppSettings
    monkeypatch.setattr(mw, "LanguageBaseDownloadWorker", FakeWorker)
    monkeypatch.setattr(S, "get_selected_language", staticmethod(lambda: state["language"]))
    monkeypatch.setattr(S, "get_language_base_url", staticmethod(lambda lang: state["url"]))
    monkeypatch.setattr(S, "get_base_ini_path", staticmethod(lambda lang=None: dest))
    monkeypatch.setattr(S, "get_enhancements_dir", staticmethod(lambda lang=None: dest.parent))
    monkeypatch.setattr(S, "invalidate_enhancements_stamp",
                        staticmethod(lambda folder: state["invalidated"].append(folder)))
    monkeypatch.setattr(S, "set_source_path",
                        staticmethod(lambda name, path: state["sources"].append((name, path))))
    monkeypatch.setattr(mw.QTimer, "singleShot", staticmethod(lambda *a, **k: None))

    win = MagicMock()
    win._close_committed = False
    win._lang_check_worker = None
    win._lang_dl_worker = None
    win._loader_worker = None
    win._simple_run_active = False
    win._job_running.return_value = False
    asks = []
    win._ask_after_the_job.side_effect = asks.append
    win._on_language_translation_checked = (
        lambda *a: MainWindow._on_language_translation_checked(win, *a))
    state.update(win=win, asks=asks, dest=dest)
    return state


def _start(env):
    MainWindow._check_language_translation_at_startup(env["win"])
    return FakeWorker.made[-1] if FakeWorker.made else None


def _finish(env, worker, ok=True, changed=True):
    worker.changed = changed
    if changed:
        env["dest"].parent.mkdir(parents=True, exist_ok=True)
        env["dest"].write_text("k=v\n", encoding="utf-8")
    MainWindow._on_language_translation_checked(env["win"], worker, "german", env["dest"], ok)


class TestWhatIsChecked:
    def test_a_url_source_is_fetched_in_the_background(self, env):
        worker = _start(env)
        assert worker is not None and worker.started
        assert worker.source == URL and worker.dest == env["dest"]
        assert env["win"]._lang_check_worker is worker

    def test_english_checks_nothing(self, env):
        env["language"] = "english"
        assert _start(env) is None

    @pytest.mark.parametrize("source", ["", r"C:\Games\korean\global.ini"])
    def test_no_url_or_a_local_file_checks_nothing(self, env, source):
        env["url"] = source
        assert _start(env) is None

    def test_not_while_a_switch_downloads_or_closing(self, env):
        env["win"]._lang_dl_worker = object()
        assert _start(env) is None
        env["win"]._lang_dl_worker = None
        env["win"]._close_committed = True
        assert _start(env) is None

    def test_the_startup_gate_runs_it(self):
        import inspect
        src = inspect.getsource(MainWindow._continue_startup_after_update_gate)
        assert "self._check_language_translation_at_startup()" in src


class TestWhatAChangeDoes:
    def test_an_unchanged_file_changes_nothing(self, env):
        worker = _start(env)
        _finish(env, worker, changed=False)
        assert env["win"]._lang_check_worker is None
        assert env["invalidated"] == [] and env["asks"] == []
        env["win"]._reload_with_language_enhancements.assert_not_called()

    def test_a_failed_fetch_changes_nothing(self, env):
        worker = _start(env)
        _finish(env, worker, ok=False, changed=False)
        assert env["invalidated"] == [] and env["asks"] == []

    def test_a_new_file_makes_the_set_stale_and_reloads(self, env):
        worker = _start(env)
        _finish(env, worker)
        assert env["invalidated"] == [env["dest"].parent]
        env["win"].enhancements_tab.refresh_enhancements_dirty_state.assert_called_once()
        assert len(env["asks"]) == 1
        env["asks"].pop()()
        assert env["sources"] == [(mw.AppSettings.SOURCE_GLOBAL, str(env["dest"]))]
        env["win"]._reload_with_language_enhancements.assert_called_once_with("german")

    def test_the_reload_waits_for_a_load_or_a_job(self, env):
        worker = _start(env)
        _finish(env, worker)
        reload_with_it = env["asks"].pop()
        env["win"]._job_running.return_value = True
        reload_with_it()
        assert env["asks"] == [reload_with_it]
        env["win"]._reload_with_language_enhancements.assert_not_called()
        env["win"]._job_running.return_value = False
        env["asks"].pop()()
        env["win"]._reload_with_language_enhancements.assert_called_once_with("german")

    def test_a_language_switch_meanwhile_drops_it(self, env):
        worker = _start(env)
        env["language"] = "french"
        _finish(env, worker)
        assert env["invalidated"] == [] and env["asks"] == []

    def test_a_switch_after_the_download_drops_the_reload(self, env):
        worker = _start(env)
        _finish(env, worker)
        env["language"] = "french"
        env["asks"].pop()()
        env["win"]._reload_with_language_enhancements.assert_not_called()

    def test_closing_drops_it(self, env):
        worker = _start(env)
        env["win"]._close_committed = True
        _finish(env, worker)
        assert env["asks"] == []

    def test_a_released_worker_is_ignored(self, env):
        worker = _start(env)
        env["win"]._lang_check_worker = None
        _finish(env, worker)
        assert env["asks"] == []
