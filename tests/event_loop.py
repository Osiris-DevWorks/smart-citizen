"""Run the Qt event loop until something holds (a helper module, not a test
file, like gui_window.py).

A worker on a real thread reaches a slot on the GUI thread through a queued
connection, which only the event loop delivers, so a test that waits for such
a slot runs the loop meanwhile. test_applied_state_worker.py,
test_extraction_stop.py, test_live_blueprint_log_worker.py and
test_pending_cache_cleanup.py each had a copy of this loop (perf proposal
review: the third copy is the signal to extract).
Import it as ``from tests.event_loop import pump_until``. It runs the session
``qapp``'s loop (tests/conftest.py), so a test that pumps requests ``qapp``.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication


def pump_until(predicate, seconds: float = 10.0) -> bool:
    """Run the event loop until *predicate()* holds, for up to *seconds*.

    Returns whether it held, asked once more at the deadline. A caller
    asserts on the result, or ignores it to let queued slots run."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
