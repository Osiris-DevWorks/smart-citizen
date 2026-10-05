"""Tests for the crash-dump handler installed at app startup.

Pre-1.4.1 the frozen PyInstaller build had no ``sys.excepthook`` wrapping,
so an uncaught exception in the GUI vanished into the swallowed-stderr void
of the no-console build. Users hit the crash, the window disappeared, and
they had nothing to share with a bug report. This module guards against
regressing that behavior.
"""
from __future__ import annotations

import importlib
import logging
import sys
import threading
from pathlib import Path

import pytest

from src.utils import crash_handler
from src.utils.crash_handler import _RingBufferHandler

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def fresh_crash_module(monkeypatch):
    """Reset the module-level install state so each test starts clean.

    ``install_crash_handler`` is idempotent (intentionally) — once installed,
    repeat calls no-op. Tests need a fresh slate to exercise the install
    path, so we monkeypatch the guard flag and restore the original hooks.
    """
    original_sys = sys.excepthook
    original_thread = threading.excepthook
    # The run keeps one QApplication alive throughout (tests/conftest.py), so
    # the real crash dialog would open modally here and hang the test. These
    # tests check the dump and the hook chain. TestCrashDialogWiring checks
    # the dialog call with stubs of its own, which replace this one.
    from src.utils import crash_logger
    monkeypatch.setattr(crash_logger, "show_crash_dialog", lambda *a: None)
    monkeypatch.setattr(crash_handler, "_installed", False)
    monkeypatch.setattr(crash_handler, "_buffer_handler", None)
    monkeypatch.setattr(crash_handler, "_original_excepthook", None)
    monkeypatch.setattr(crash_handler, "_original_threading_excepthook", None)
    yield
    # Drain any handlers the test may have added to the root logger.
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, _RingBufferHandler):
            root.removeHandler(h)
    sys.excepthook = original_sys
    threading.excepthook = original_thread


class TestRingBufferHandler:
    def test_handler_appends_formatted_records(self):
        h = _RingBufferHandler(maxlen=10)
        rec = logging.LogRecord(
            "test.logger", logging.INFO, "test.py", 1, "hello %s", ("world",), None
        )
        h.emit(rec)
        snap = h.snapshot()
        assert len(snap) == 1
        assert "hello world" in snap[0]
        assert "INFO" in snap[0]

    def test_handler_respects_maxlen(self):
        h = _RingBufferHandler(maxlen=3)
        for i in range(10):
            rec = logging.LogRecord(
                "t", logging.INFO, "t.py", 1, f"msg {i}", None, None
            )
            h.emit(rec)
        snap = h.snapshot()
        assert len(snap) == 3, "Old entries must be evicted past maxlen"
        # Most recent 3 are msg 7, 8, 9
        assert "msg 7" in snap[0]
        assert "msg 8" in snap[1]
        assert "msg 9" in snap[2]


class TestInstallCrashHandler:
    def test_install_is_idempotent(self, fresh_crash_module, tmp_path):
        """Calling install twice must not chain hooks. Otherwise re-entry
        from a worker module that imports crash_handler would multiply the
        crash-dump writes and the original-hook calls."""
        crash_handler.install_crash_handler(tmp_path / "logs")
        first_hook = sys.excepthook
        crash_handler.install_crash_handler(tmp_path / "logs")
        assert sys.excepthook is first_hook, "Second install must no-op"

    def test_install_creates_logs_dir_lazily(self, fresh_crash_module, tmp_path):
        """The directory should NOT exist immediately after install — it's
        created on first crash write so a clean install doesn't carry an
        empty ``logs/`` folder."""
        logs_dir = tmp_path / "logs_not_yet"
        assert not logs_dir.exists()
        crash_handler.install_crash_handler(logs_dir)
        assert not logs_dir.exists(), (
            "install_crash_handler must not eagerly create the logs dir"
        )

    def test_main_thread_excepthook_writes_dump(self, fresh_crash_module, tmp_path):
        """A simulated uncaught exception on the main thread writes a dump
        file under the logs directory and contains the traceback."""
        logs_dir = tmp_path / "logs"
        crash_handler.install_crash_handler(logs_dir)

        try:
            raise RuntimeError("synthetic crash for test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        # Fire the installed hook directly — simulating what Python does on
        # an uncaught exception.
        sys.excepthook(exc_type, exc_value, exc_tb)

        dumps = list(logs_dir.glob("crash_*.log"))
        assert len(dumps) == 1, f"Expected 1 crash dump, found {len(dumps)}"
        content = dumps[0].read_text(encoding="utf-8")
        assert "synthetic crash for test" in content
        assert "RuntimeError" in content
        assert "Thread: MainThread" in content
        assert "─── Traceback" in content
        assert "─── Recent log buffer" in content

    def test_keyboardinterrupt_does_not_write_dump(self, fresh_crash_module, tmp_path):
        """Ctrl+C in a dev run isn't a crash. The hook must skip the dump
        write and pass through to the original hook so the standard
        interrupt message still prints."""
        logs_dir = tmp_path / "logs"
        crash_handler.install_crash_handler(logs_dir)

        # Stub the original-hook position so we can verify pass-through.
        called = []
        crash_handler._original_excepthook = lambda *a: called.append(a)
        sys.excepthook = crash_handler._make_main_thread_hook(
            logs_dir, crash_handler._original_excepthook
        )

        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            exc_type, exc_value, exc_tb = sys.exc_info()

        sys.excepthook(exc_type, exc_value, exc_tb)

        assert not logs_dir.exists() or not any(logs_dir.glob("crash_*.log")), (
            "KeyboardInterrupt must not produce a crash dump file"
        )
        assert len(called) == 1, "Original hook must still be called for Ctrl+C"

    def test_threading_excepthook_captures_worker_thread_name(
        self, fresh_crash_module, tmp_path
    ):
        """An uncaught exception in a worker thread (e.g. a QThread that
        re-raises) must produce a dump labeled with the originating thread
        name — that's how the user / triage knows which worker died."""
        logs_dir = tmp_path / "logs"
        crash_handler.install_crash_handler(logs_dir)

        try:
            raise ValueError("boom from worker")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        # ``threading.ExceptHookArgs`` is a namedtuple; build one by hand
        # since we can't trigger a real un-handled worker exception in a
        # pytest run without polluting it.
        class _Args:
            pass

        args = _Args()
        args.exc_type = exc_type
        args.exc_value = exc_value
        args.exc_traceback = exc_tb
        args.thread = threading.Thread(name="EnhancementsGeneratorWorker")

        threading.excepthook(args)

        dumps = list(logs_dir.glob("crash_*.log"))
        assert len(dumps) == 1
        content = dumps[0].read_text(encoding="utf-8")
        assert "Thread: EnhancementsGeneratorWorker" in content
        assert "boom from worker" in content

    def test_original_excepthook_is_called(self, fresh_crash_module, tmp_path):
        """Crash dump is a side-effect; the original ``sys.excepthook`` must
        still fire afterwards so dev runs see tracebacks on stderr and the
        process exit code stays consistent."""
        logs_dir = tmp_path / "logs"

        called: list[tuple] = []

        def stub_original(*args):
            called.append(args)

        sys.excepthook = stub_original
        # Reset install-state so install picks up the stub as 'original'.
        crash_handler._installed = False
        crash_handler.install_crash_handler(logs_dir)

        try:
            raise RuntimeError("after-hook chain test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        sys.excepthook(exc_type, exc_value, exc_tb)
        assert len(called) == 1, "Original excepthook must be invoked after the dump"
        assert called[0][0] is exc_type


class TestCrashDialogWiring:
    """2.0: the main-thread hook shows crash_logger.show_crash_dialog after
    writing the dump. The dialog is best-effort — a broken dialog module must
    never eat the dump or the original-hook chain."""

    def test_dialog_receives_exception_and_dump_path(
        self, fresh_crash_module, tmp_path, monkeypatch
    ):
        from src.utils import crash_logger

        seen: list[tuple] = []
        monkeypatch.setattr(
            crash_logger, "show_crash_dialog", lambda *a: seen.append(a)
        )
        logs_dir = tmp_path / "logs"
        crash_handler.install_crash_handler(logs_dir)

        try:
            raise RuntimeError("dialog wiring test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_tb)

        assert len(seen) == 1, "Dialog must be shown exactly once per crash"
        dlg_type, dlg_value, dlg_path = seen[0]
        assert dlg_type is exc_type and dlg_value is exc_value
        dumps = list(logs_dir.glob("crash_*.log"))
        assert len(dumps) == 1 and dlg_path == dumps[0], (
            "Dialog must point at the dump that was just written"
        )

    def test_broken_dialog_still_writes_dump_and_chains(
        self, fresh_crash_module, tmp_path, monkeypatch
    ):
        from src.utils import crash_logger

        def explode(*_a):
            raise RuntimeError("dialog module is broken")

        monkeypatch.setattr(crash_logger, "show_crash_dialog", explode)

        called: list[tuple] = []
        sys.excepthook = lambda *a: called.append(a)
        crash_handler._installed = False
        logs_dir = tmp_path / "logs"
        crash_handler.install_crash_handler(logs_dir)

        try:
            raise ValueError("crash with broken dialog")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_tb)  # must not raise

        dumps = list(logs_dir.glob("crash_*.log"))
        assert len(dumps) == 1, "Dump must be written even when the dialog raises"
        assert len(called) == 1, "Original hook must still chain after dialog failure"


class TestShowCrashDialog:
    """The real crash_logger.show_crash_dialog, which the tests above stub.

    Its exec() is replaced so nothing blocks: a QApplication exists for the
    whole run (tests/conftest.py), so the real modal dialog would wait for a
    click nobody gives.
    """

    @staticmethod
    def _recording_dialog(monkeypatch):
        from PyQt6 import QtWidgets

        shown = []

        class _RecordingDialog(QtWidgets.QDialog):
            def exec(self):
                shown.append(self)
                return 0

        monkeypatch.setattr(QtWidgets, "QDialog", _RecordingDialog)
        return shown

    def test_no_qapplication_means_no_dialog(self, monkeypatch):
        """A crash before the GUI exists has no app to show a dialog on."""
        from PyQt6 import QtWidgets
        from src.utils import crash_logger

        class _NoApp:
            @staticmethod
            def instance():
                return None

        shown = self._recording_dialog(monkeypatch)
        monkeypatch.setattr(QtWidgets, "QApplication", _NoApp)

        crash_logger.show_crash_dialog(RuntimeError, RuntimeError("early"), Path("x.log"))

        assert shown == []

    def test_dialog_shows_the_error_and_copies_the_dump_path(self, monkeypatch, tmp_path):
        import pyperclip
        from PyQt6.QtWidgets import QLabel, QPushButton, QTextEdit
        from src.utils import crash_logger

        shown = self._recording_dialog(monkeypatch)
        copied = []
        monkeypatch.setattr(pyperclip, "copy", copied.append)
        dump = tmp_path / "logs" / "crash_20261005_120000.log"

        crash_logger.show_crash_dialog(ValueError, ValueError("boom"), dump)

        assert len(shown) == 1, "the dialog must be shown exactly once"
        dlg = shown[0]
        assert dlg.findChild(QTextEdit).toPlainText() == "ValueError: boom"
        assert any(str(dump) in label.text() for label in dlg.findChildren(QLabel))
        copy_btn = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Copy path")
        copy_btn.click()
        assert copied == [str(dump)]

    def test_missing_dump_path_says_so(self, monkeypatch):
        from PyQt6.QtWidgets import QLabel
        from src.utils import crash_logger

        shown = self._recording_dialog(monkeypatch)

        crash_logger.show_crash_dialog(ValueError, ValueError("boom"), None)

        assert any("(could not write crash log)" in label.text()
                   for label in shown[0].findChildren(QLabel))


class TestGetLogsDir:
    """``AppSettings.get_logs_dir`` returns ``{user_data_dir}/logs`` and creates
    the directory lazily. NOT per-channel — crashes can fire before the channel
    context is established (startup migrators, etc.) so the path is rooted at
    the user-data root rather than the channel subdirectory.
    """

    def test_logs_dir_is_user_data_slash_logs(self, monkeypatch, tmp_path):
        from src.utils.settings import AppSettings

        monkeypatch.setattr(
            AppSettings, "get_user_data_dir", staticmethod(lambda: tmp_path)
        )
        logs = AppSettings.get_logs_dir()
        assert logs == tmp_path / "logs"

    def test_logs_dir_is_created_on_first_access(self, monkeypatch, tmp_path):
        from src.utils.settings import AppSettings

        monkeypatch.setattr(
            AppSettings, "get_user_data_dir", staticmethod(lambda: tmp_path)
        )
        target = tmp_path / "logs"
        assert not target.exists()
        AppSettings.get_logs_dir()
        assert target.exists() and target.is_dir()

    def test_logs_dir_is_not_per_channel(self, monkeypatch, tmp_path):
        """The path must NOT include the active channel — crash dumps written
        during startup-migrator failure happen before any channel is settled."""
        from src.utils.settings import AppSettings

        monkeypatch.setattr(
            AppSettings, "get_user_data_dir", staticmethod(lambda: tmp_path)
        )
        # Even if get_active_channel is monkeypatched to something exotic,
        # get_logs_dir must NOT pick it up.
        monkeypatch.setattr(
            AppSettings, "get_active_channel", staticmethod(lambda: "PTU")
        )
        logs = AppSettings.get_logs_dir()
        assert "PTU" not in str(logs)
        assert logs == tmp_path / "logs"


class TestRingBufferHandlerWiring:
    def test_handler_is_attached_to_root_logger(self, fresh_crash_module, tmp_path):
        """Logs emitted anywhere in the app must show up in the ring buffer
        so the crash dump captures the lead-up to the failure."""
        crash_handler.install_crash_handler(tmp_path / "logs")

        logging.getLogger("some.module").warning("lead-up event")

        assert crash_handler._buffer_handler is not None
        snap = crash_handler._buffer_handler.snapshot()
        assert any("lead-up event" in line for line in snap), (
            "Records emitted after install must land in the ring buffer"
        )
