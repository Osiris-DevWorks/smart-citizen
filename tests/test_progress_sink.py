"""Tests for src.utils.progress_sink.ProgressSink."""
import threading

from utils.progress_sink import ProgressSink


def test_advance_accumulates():
    sink = ProgressSink(total=3, min_interval=0.0)
    sink.advance(message="a")
    sink.advance(message="b")
    assert sink.snapshot() == (2, 3, "b")


def test_callback_invoked_with_latest_state():
    events: list[tuple[int, int, str]] = []
    sink = ProgressSink(callback=lambda c, t, m: events.append((c, t, m)),
                        total=2, min_interval=0.0)
    sink.advance(message="phase1")
    sink.advance(message="phase2")
    sink.flush()
    assert events[-1] == (2, 2, "phase2")


def test_callback_throttled_below_min_interval():
    events: list[tuple[int, int, str]] = []
    sink = ProgressSink(callback=lambda c, t, m: events.append((c, t, m)),
                        total=100, min_interval=1.0)
    for i in range(50):
        sink.advance()
    # Completion still forces an emit via the `done` branch; before completion,
    # rapid calls collapse to a single emission.
    assert len(events) <= 2


def test_completion_forces_emit_even_when_throttled():
    events: list[tuple[int, int, str]] = []
    sink = ProgressSink(callback=lambda c, t, m: events.append((c, t, m)),
                        total=2, min_interval=10.0)
    sink.advance()
    sink.advance(message="done")
    assert events[-1] == (2, 2, "done")


def test_thread_safety_under_contention():
    sink = ProgressSink(total=1000, min_interval=0.0)

    def worker():
        for _ in range(100):
            sink.advance()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    completed, total, _ = sink.snapshot()
    assert completed == 1000
    assert total == 1000


def test_callback_exceptions_are_swallowed():
    def bad_callback(c, t, m):
        raise RuntimeError("intentional")
    sink = ProgressSink(callback=bad_callback, total=1, min_interval=0.0)
    # Must not raise — exceptions in the callback should not break the worker.
    sink.advance()


def test_set_total_emits_with_force():
    events: list[tuple[int, int, str]] = []
    sink = ProgressSink(callback=lambda c, t, m: events.append((c, t, m)),
                        total=0, min_interval=10.0)
    sink.set_total(5)
    assert events[-1] == (0, 5, "")


def test_no_callback_is_noop():
    sink = ProgressSink(total=3, min_interval=0.0)
    sink.advance()
    sink.advance()
    assert sink.snapshot()[:2] == (2, 3)
