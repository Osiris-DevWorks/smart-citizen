"""ConfigTab install-scan lifecycle guards, all #385 review findings.

Three real bugs, all from concurrency windows the deep scan opened up (it's
slow by design -- a whole-drive walk -- with its own Cancel button, which is
exactly what makes "another call lands before the first one finishes"
reachable):

* Re-scanning before a just-cancelled worker's own `finished` arrives
  reassigns `self._dupe_worker` to the new one. `_on_install_scan_finished`
  used to read `self._dupe_worker` (not "the worker that actually just
  finished") and call `.wait()` on it -- the wrong, still-running worker. A
  custom-`run()` QThread ignores `.quit()`, so `.wait()` blocked the GUI
  thread for the whole new scan.
* Cancel, then close the results dialog, still leaves the cancelled worker
  running. Its late `finished` used to unconditionally build and `.exec()`
  a brand new modal dialog the user had already explicitly dismissed.
* `_check_other_installs` itself had no re-entry guard, and the dialog's own
  "Scan all drives" button stays enabled for the whole deep scan (`set_report`
  only touches it once a report arrives) -- so a second click while one was
  already running spawned a second worker, and the first one's `finished`
  hit the stale-worker check above and returned before ever closing its own
  progress dialog. Left it orphaned on screen for the life of the app.

The `_on_install_scan_finished` fix passes the specific worker a `finished`
connection belongs to as an explicit parameter (bound at `.connect()` time
via a lambda default arg), rather than relying on `self._dupe_worker` or
`QObject.sender()`. The `_check_other_installs` fix is a plain guard at the
top of the method. Both are directly testable with plain stub objects, no
QApplication, no real QThread, no Qt signal emission at all -- driven on a
lightweight stub self, same pattern as test_favorite_toggle_stranded.py /
test_ui_mode.py.
"""
import pytest

from src.gui.config_tab import ConfigTab

pytestmark = pytest.mark.unit


class _FakeWorker:
    def __init__(self, *args, **kwargs):
        # *args/**kwargs: also stands in for a real InstallScanWorker(deep=,
        # parent=) construction in TestReentrantScanGuard below.
        self.quit_called = False
        self.wait_called = False
        self.started = False
        self.progress_pct = _FakeSignal()
        self.error = _FakeSignal()
        self.finished = _FakeSignal()

    def quit(self):
        self.quit_called = True

    def wait(self):
        self.wait_called = True

    def start(self):
        self.started = True


class _FakeProgress:
    def __init__(self, *args, **kwargs):
        # *args/**kwargs: also stands in for a real AnimatedProgressDialog(...)
        # construction in TestReentrantScanGuard below.
        self.closed = False
        self.canceled = _FakeSignal()

    def close(self):
        self.closed = True

    def set_progress(self, *args, **kwargs):
        pass

    def setMaximumWidth(self, _width):
        pass


class _FakeButton:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


class _FakeDialog:
    def __init__(self, visible):
        self._visible = visible
        self.refreshed_with = None

    def isVisible(self):
        return self._visible

    def set_report(self, report):
        self.refreshed_with = report


class _FakeSignal:
    def connect(self, _slot):
        pass


class _Report:
    """Only the field this handler reads."""

    def __init__(self, cancelled=False):
        self.cancelled = cancelled


class _Stub:
    """Carries just what _on_install_scan_finished touches."""

    def __init__(self, current_worker, dialog=None):
        self._dupe_worker = current_worker
        self._dupe_progress = _FakeProgress()
        self._dupe_check_btn = _FakeButton()
        if dialog is not None:
            self._dupe_dialog = dialog

    def finish(self, report, worker):
        ConfigTab._on_install_scan_finished(self, report, worker)

    def _use_install_root(self, root):
        pass  # only ever connected, never invoked, in these tests

    def _on_install_scan_error(self, message):
        pass  # only ever connected, never invoked, in these tests


class TestStaleWorkerNeverTouchesCurrentState:
    def test_stale_worker_is_torn_down_but_current_state_left_alone(self):
        current = _FakeWorker()  # a newer scan, started after cancel
        stale = _FakeWorker()    # the cancelled scan whose finished arrives late
        stub = _Stub(current_worker=current)

        stub.finish(_Report(cancelled=True), stale)

        # The stale worker itself is cleaned up...
        assert stale.quit_called and stale.wait_called
        # ...but the CURRENT worker is never touched: this is the exact bug
        # -- .wait() on a still-running worker would freeze the GUI.
        assert not current.quit_called
        assert not current.wait_called
        # Nothing else about "current" scan state was reset either.
        assert stub._dupe_worker is current
        assert not stub._dupe_progress.closed
        assert stub._dupe_check_btn.enabled is None

    def test_current_worker_is_recognized_and_cleaned_up_normally(self):
        """Guard against overcorrecting: a scan that IS current must still
        tear down its own worker/progress/button state as before. Cancelled
        + no open dialog keeps this on the early-return path so it doesn't
        also need a real Qt dialog -- that path is covered separately."""
        worker = _FakeWorker()
        stub = _Stub(current_worker=worker)
        progress = stub._dupe_progress

        stub.finish(_Report(cancelled=True), worker)

        assert worker.quit_called and worker.wait_called
        assert stub._dupe_worker is None
        assert progress.closed
        assert stub._dupe_check_btn.enabled is True


class TestCancelledScanDoesNotReopenADismissedDialog:
    def test_cancelled_with_no_open_dialog_does_not_build_one(self):
        """No _dupe_dialog attribute at all == the user already closed it
        (ConfigTab sets it back to None after dialog.exec() returns)."""
        worker = _FakeWorker()
        stub = _Stub(current_worker=worker)  # no dialog attribute
        progress = stub._dupe_progress

        # Would raise (importing/constructing a real DuplicateInstallDialog,
        # which needs a QApplication) if the guard failed to return first.
        stub.finish(_Report(cancelled=True), worker)

        assert stub._dupe_worker is None
        assert progress.closed

    def test_cancelled_with_a_still_open_dialog_refreshes_in_place(self):
        """A deep scan cancelled while its OWN results dialog is still open
        (not yet dismissed) must still refresh that dialog, not suppress it
        -- suppression only applies once there's nowhere left to show it."""
        worker = _FakeWorker()
        dialog = _FakeDialog(visible=True)
        stub = _Stub(current_worker=worker, dialog=dialog)
        report = _Report(cancelled=True)

        stub.finish(report, worker)

        assert dialog.refreshed_with is report

    def test_not_cancelled_with_no_open_dialog_does_build_one(self, monkeypatch):
        """Guard against overcorrecting: a normal (non-cancelled) finish with
        no dialog open must still reach the build-fresh-dialog path, not get
        swallowed by the cancelled check.

        Patches the class the method's local import resolves to, rather than
        constructing a real QDialog -- this file has no QApplication, and a
        Qt widget built without one can misbehave in ways a Python exception
        wouldn't safely catch.
        """
        built = []

        class _FakeDuplicateInstallDialog:
            def __init__(self, report, parent):
                built.append(report)
                self.install_selected = _FakeSignal()
                self.deep_scan_requested = _FakeSignal()

            def exec(self):
                pass

        monkeypatch.setattr(
            "src.gui.duplicate_install_dialog.DuplicateInstallDialog",
            _FakeDuplicateInstallDialog,
        )
        worker = _FakeWorker()
        stub = _Stub(current_worker=worker)  # no dialog attribute
        report = _Report(cancelled=False)

        stub.finish(report, worker)

        assert built == [report], "the cancelled check must not have short-circuited this path"


class TestReentrantScanGuard:
    """_check_other_installs: a scan already running must reject a second call.

    #385 review: the dialog's own "Scan all drives" button stays enabled for
    the whole deep scan (`set_report` only touches it once a report arrives),
    and the deep walk is slow by design -- exactly the window a second click
    needs. Without a guard, a second call reassigned self._dupe_worker /
    self._dupe_progress to the new scan, and the first worker's `finished`
    handler then hit the stale-worker identity check above and returned
    before ever closing its own progress dialog -- an orphaned progress
    window left on screen for the life of the app.
    """

    def test_a_running_scan_blocks_a_second_call(self):
        running = _FakeWorker()
        stub = _Stub(current_worker=running)

        ConfigTab._check_other_installs(stub, deep=False)

        # The guard returns before anything else runs -- not even the
        # button gets touched.
        assert stub._dupe_check_btn.enabled is None
        assert stub._dupe_worker is running

    def test_no_scan_running_proceeds_past_the_guard(self, monkeypatch):
        """Guard against overcorrecting: a fresh call with nothing running
        must still reach the scan-launching code, not get swallowed by the
        guard meant for the busy case.

        Patches the classes the method's local import resolves to, same
        technique as test_not_cancelled_with_no_open_dialog_does_build_one
        above -- no QApplication in this file, so the real
        AnimatedProgressDialog/InstallScanWorker must not get constructed.
        """
        monkeypatch.setattr("src.gui.workers.AnimatedProgressDialog", _FakeProgress)
        monkeypatch.setattr("src.gui.workers.InstallScanWorker", _FakeWorker)
        stub = _Stub(current_worker=None)

        ConfigTab._check_other_installs(stub, deep=False)

        assert stub._dupe_check_btn.enabled is False
        assert isinstance(stub._dupe_worker, _FakeWorker)
        assert stub._dupe_worker.started