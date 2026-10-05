"""Safe construction of a real ``MainWindow`` for tests.

Most GUI tests here drive a small widget, or the real unbound method against a
lightweight stub (see tests/test_ui_mode.py). A couple of properties can only
be observed on the fully assembled window, though, and building one in-process
turned out to have three separate ways of taking the whole pytest run down.
Each was found by hitting it, so they live here rather than being rediscovered
by whoever writes the third such file:

* ``showEvent`` kicks off the real startup work, including the
  ``AppUpdateCheckWorker`` network thread. That raced teardown and killed the
  process with a heap corruption (0xc0000374, faulthandler naming the thread).
  ``_maybe_start_first_run_tutorial`` is stubbed out to prevent it.
* ``MainWindow`` installs an error-dialog handler on the ROOT logger, which
  outlives the window. A later log record fires a Qt signal at it, and an
  ERROR record tries to open a modal dialog with nobody to dismiss it, hanging
  the session at exit. It has to be detached on the way out.
* Destroying a ``MainWindow`` mid-session is unsafe full stop. It owns timers,
  a model and a child tree Qt goes on touching, and ``close()`` +
  ``deleteLater()`` crashed roughly 1 run in 4 with an access violation;
  draining ``DeferredDelete`` explicitly made it 3 in 6. Windows are hidden
  and kept alive for the process instead, held in ``_LIVE_WINDOWS`` so
  Python's garbage collector can't delete the C++ object by the back door.
  That only holds while the run's one QApplication lives, which
  tests/conftest.py guarantees. Before it did, each GUI module's own app was
  destroyed at the end of that module and took these windows with it, and
  once the first app was gone PyQt6 could no longer tell when Qt deleted a
  child it had created itself (see the ``qapp`` fixture in tests/conftest.py).

Settings, user-data and cache directories are all redirected into the caller's
tmp path, so construction touches nothing real.

Prefer the stub in tests/test_ui_mode.py where it can observe what you need;
reach for this only when the behaviour is a property of the whole window.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from src.utils.settings import AppSettings

# Every window built by the tests, kept alive for the whole session. See the
# third bullet above: dropping the last reference is itself the crash.
_LIVE_WINDOWS: list = []


def build_main_window(tmp_dir, patch, mode: str):
    """Build a real MainWindow redirected entirely into ``tmp_dir``.

    ``patch`` is a MonkeyPatch whose undo is guaranteed by the caller (use
    ``pytest.MonkeyPatch.context()`` for a module-scoped fixture; the built-in
    ``monkeypatch`` fixture is fine for a function-scoped one). It must not be
    a bare ``pytest.MonkeyPatch()`` with ``undo()`` called after a ``yield``:
    a failure during construction would then skip the undo and leave the
    settings backend redirected for every later test in the session.
    """
    shared = QSettings(str(tmp_dir / "reg.ini"), QSettings.Format.IniFormat)
    patch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    AppSettings.set_user_data_dir(tmp_dir / "data")
    AppSettings.set_cache_dir(tmp_dir / "cache")
    AppSettings.set_ui_mode(mode)

    from src.gui.main_window import MainWindow

    patch.setattr(MainWindow, "_maybe_start_first_run_tutorial",
                  lambda self: None)

    window = MainWindow()
    _LIVE_WINDOWS.append(window)
    return window


def retire_main_window(window) -> None:
    """Detach the root-logger handler and hide the window. Never destroys it."""
    handler = getattr(window, "_error_dialog_handler", None)
    if handler is not None:
        logging.getLogger().removeHandler(handler)
    window.hide()
    QApplication.processEvents()
