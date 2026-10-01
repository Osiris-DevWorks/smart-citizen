"""Tests for the "is the loaded state already applied?" check that lets the
Apply button read green instead of unconditionally red (#387, #397, #398).

Three layers, all driven without constructing the whole window:

* Pure functions: ``_matches_applied_output`` (the comparison),
  ``_user_cfg_language_matches``, ``_merge_for_apply`` (the merge Apply to
  Game and the check share), ``_compute_already_applied`` (what the
  background worker runs).
* ``MainWindow._apply_merge_inputs``: the main-thread snapshot of everything
  the merge reads.
* The check's lifecycle on ``MainWindow`` (start, stale-result handling,
  one-thread-at-a-time reruns, settling on close), driven on a lightweight
  stand-in ``self`` with a fake worker so no thread is involved.

The comparison walks stock_dict's own keys, not merged_dict's, because
merge_ini_files (the real writer) only ever overwrites a key present in its
structure-preservation source file -- a key merged_dict carries that
stock_dict lacks is never actually written, so it must never influence this
result, or a profile with such a key would show a false "dirty" on every
launch even immediately after a genuine apply.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.gui.main_window as main_window
from src.gui.main_window import (
    MainWindow,
    _ApplyMergeInputs,
    _AppliedStateSnapshot,
    _compute_already_applied,
    _matches_applied_output,
    _merge_for_apply,
    _user_cfg_language_matches,
)
from src.utils.settings import AppSettings
from src.utils.version import get_version

pytestmark = pytest.mark.unit


class TestMatchesAppliedOutput:
    def test_empty_stock_dict_is_vacuously_true(self):
        assert _matches_applied_output({}, {}, {}) is True

    def test_untouched_stock_values_match(self):
        """No overrides in merged_dict: applied_dict must equal stock as-is."""
        stock = {"a": "1", "b": "2"}
        applied = {"a": "1", "b": "2"}
        assert _matches_applied_output(stock, {}, applied) is True

    def test_stale_stock_value_on_disk_is_dirty(self):
        """Nothing overrides "a", but the on-disk value has drifted from
        stock (e.g. a stock update since the last apply) -- needs re-apply."""
        stock = {"a": "1"}
        applied = {"a": "stale"}
        assert _matches_applied_output(stock, {}, applied) is False

    def test_applied_override_already_matches(self):
        """merged_dict overrides "a"; the file already has that override."""
        stock = {"a": "1"}
        merged = {"a": "overridden"}
        applied = {"a": "overridden"}
        assert _matches_applied_output(stock, merged, applied) is True

    def test_applied_override_not_yet_written_is_dirty(self):
        """merged_dict overrides "a", but the file still has the stock
        value -- a real apply would change it."""
        stock = {"a": "1"}
        merged = {"a": "overridden"}
        applied = {"a": "1"}
        assert _matches_applied_output(stock, merged, applied) is False

    def test_merged_key_outside_stock_is_ignored(self):
        """merge_ini_files never writes a key stock_dict doesn't have --
        such a key in merged_dict must not affect the verdict either way."""
        stock = {"a": "1"}
        merged = {"a": "1", "enhancement_only_key": "something new"}
        applied = {"a": "1"}  # the extra key was never written
        assert _matches_applied_output(stock, merged, applied) is True

    def test_missing_key_in_applied_file_is_dirty(self):
        stock = {"a": "1"}
        applied = {}  # key absent from the file entirely
        assert _matches_applied_output(stock, {}, applied) is False

    def test_mixed_stock_keys_some_overridden_some_not(self):
        stock = {"a": "1", "b": "2", "c": "3"}
        merged = {"b": "overridden"}
        applied = {"a": "1", "b": "overridden", "c": "3"}
        assert _matches_applied_output(stock, merged, applied) is True

        # Flip one stock-passthrough key stale -> dirty.
        applied_stale = {"a": "1", "b": "overridden", "c": "STALE"}
        assert _matches_applied_output(stock, merged, applied_stale) is False


class TestUserCfgLanguageMatches:
    """#398 review: _entries_already_applied's file-content comparison alone
    missed a real bug. Switching the language selector in Smart Citizen's
    UI never touches user.cfg by itself (only window init and apply-to-game
    time do) -- so switching back to a language that was fully applied in
    the past, with no merge change since, read as "already applied" purely
    on content, even while user.cfg's g_language still pointed at whatever
    language was applied most recently. Green AND disabled, with Apply (the
    only thing that fixes g_language) now unreachable.
    """

    def test_matching_language_is_true(self):
        assert _user_cfg_language_matches("french", "french_(france)") is True

    def test_mismatched_language_is_false(self):
        """The exact bug: selected language is French, but user.cfg still
        has German from whatever was applied most recently."""
        assert _user_cfg_language_matches("french", "german_(germany)") is False

    def test_case_insensitive_match(self):
        """user.cfg's own parser is case-insensitive on the value (see
        ensure_user_cfg_language) -- this comparison must be too, or a
        cosmetic case difference alone would falsely show dirty forever."""
        assert _user_cfg_language_matches("french", "French_(France)") is True

    def test_missing_user_cfg_value_is_false(self):
        """No g_language line in user.cfg at all (fresh install, never
        applied) -- must not match, since nothing has actually applied yet."""
        assert _user_cfg_language_matches("french", None) is False

    def test_unmapped_language_falls_back_to_itself(self):
        """A selected_language not in SC_LANGUAGE_IDS (shouldn't happen in
        practice, but _entries_already_applied must not crash on it) falls
        back to comparing the raw value, same as SC_LANGUAGE_IDS.get's own
        default-to-key behavior everywhere else it's used."""
        assert _user_cfg_language_matches("klingon", "klingon") is True
        assert _user_cfg_language_matches("klingon", "english") is False

def _inputs(**overrides) -> _ApplyMergeInputs:
    values = dict(
        user_overrides={}, discarded_new_keys=frozenset(), owned=set(),
        enclosings=(), bp_header=None,
    )
    values.update(overrides)
    return _ApplyMergeInputs(**values)


class TestMergeForApply:
    """The one merge Apply to Game and the background check both run, so the
    check can never compute different content than a real apply writes."""

    def test_user_overrides_win_over_every_source(self):
        sources = {"global": {"a": "stock"}, "enhancements": {"a": "enhanced"}}
        merged = _merge_for_apply(
            sources, ["global", "enhancements"], _inputs(user_overrides={"a": "mine"}),
        )
        assert merged["a"] == "mine"

    def test_later_sources_override_earlier_ones(self):
        sources = {"global": {"a": "stock"}, "enhancements": {"a": "enhanced"}}
        merged = _merge_for_apply(sources, ["global", "enhancements"], _inputs())
        assert merged["a"] == "enhanced"

    def test_discarded_new_keys_are_dropped_from_the_enhancements_source(self):
        sources = {
            "global": {"a": "stock"},
            "enhancements": {"a": "enhanced", "new_key": "discovered"},
        }
        merged = _merge_for_apply(
            sources, ["global", "enhancements"],
            _inputs(discarded_new_keys=frozenset({"new_key"})),
        )
        assert "new_key" not in merged
        assert merged["a"] == "enhanced"

    def test_new_keys_are_kept_when_nothing_is_discarded(self):
        sources = {"global": {"a": "stock"}, "enhancements": {"new_key": "discovered"}}
        merged = _merge_for_apply(sources, ["global", "enhancements"], _inputs())
        assert merged["new_key"] == "discovered"

    def test_stripping_only_touches_the_enhancements_source(self):
        """A discarded key that the stock source also has must keep its stock
        value: only the enhancements copy is dropped."""
        sources = {
            "global": {"new_key": "stock has it too"},
            "enhancements": {"new_key": "discovered"},
        }
        merged = _merge_for_apply(
            sources, ["global", "enhancements"],
            _inputs(discarded_new_keys=frozenset({"new_key"})),
        )
        assert merged["new_key"] == "stock has it too"

    def test_owned_weave_is_skipped_when_nothing_is_owned(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "src.utils.owned_items.apply_owned_to_value",
            lambda value, *a, **k: calls.append(value) or value,
        )
        _merge_for_apply({"global": {"a": "x"}}, ["global"], _inputs())
        assert calls == []

    def test_owned_weave_receives_the_snapshot_arguments(self, monkeypatch):
        seen = []

        def fake(value, owned, enclosings=None, bp_header=None):
            seen.append((value, owned, enclosings, bp_header))
            return value + "!"

        monkeypatch.setattr("src.utils.owned_items.apply_owned_to_value", fake)
        merged = _merge_for_apply(
            {"global": {"a": "x"}}, ["global"],
            _inputs(owned={"Item"}, enclosings=(("[", "]"),), bp_header="BP"),
        )
        assert seen == [("x", {"Item"}, (("[", "]"),), "BP")]
        assert merged["a"] == "x!"

    def test_frontend_version_chip_is_stamped_only_when_the_key_exists(self):
        with_key = _merge_for_apply(
            {"global": {"Frontend_PU_Version": "Alpha 4.0"}}, ["global"], _inputs(),
        )
        assert with_key["Frontend_PU_Version"].endswith(
            f"Localizations Enhanced with Smart Citizen v{get_version()}"
        )
        without_key = _merge_for_apply({"global": {"a": "x"}}, ["global"], _inputs())
        assert "Frontend_PU_Version" not in without_key

    def test_modified_journal_entries_are_stamped_and_stock_ones_are_not(self):
        sources = {"global": {"journal_a_body": "stock a", "journal_b_body": "stock b"}}
        merged = _merge_for_apply(
            sources, ["global"], _inputs(user_overrides={"journal_a_body": "mine"}),
        )
        assert merged["journal_a_body"].endswith(f"[Edited with Smart Citizen v{get_version()}]")
        assert merged["journal_b_body"] == "stock b"


class _Entry:
    def __init__(self, key, custom_value="", status="Unmodified"):
        self.key = key
        self.custom_value = custom_value
        self.status = status


class _InputsWindow:
    """Carries just what _apply_merge_inputs touches."""

    _apply_merge_inputs = MainWindow._apply_merge_inputs
    _build_apply_merged_dict = MainWindow._build_apply_merged_dict

    def __init__(self, entries, bp_header=None):
        self.entries = entries
        self._header = bp_header

    def _bp_header(self):
        return self._header


@pytest.fixture
def settings(monkeypatch):
    state = {"include_new": True, "owned": set(), "tag_configs": {"cfg": 1}, "tag_config_reads": 0}

    def get_all_tag_configs():
        state["tag_config_reads"] += 1
        return state["tag_configs"]

    monkeypatch.setattr(AppSettings, "get_include_new_lines", staticmethod(lambda: state["include_new"]))
    monkeypatch.setattr(AppSettings, "get_owned_items", staticmethod(lambda: set(state["owned"])))
    monkeypatch.setattr(AppSettings, "get_all_tag_configs", staticmethod(get_all_tag_configs))
    return state


class TestApplyMergeInputs:
    """The main-thread snapshot the merge (and the worker) runs from."""

    def test_overrides_come_only_from_entries_with_a_custom_value(self, settings):
        window = _InputsWindow([_Entry("a", "x"), _Entry("b", ""), _Entry("c", "y")])
        assert window._apply_merge_inputs().user_overrides == {"a": "x", "c": "y"}

    def test_nothing_is_discarded_when_discovered_items_are_included(self, settings):
        settings["include_new"] = True
        window = _InputsWindow([_Entry("new", "", "New")])
        assert window._apply_merge_inputs().discarded_new_keys == frozenset()

    def test_new_entries_without_an_override_are_discarded_when_excluded(self, settings):
        settings["include_new"] = False
        window = _InputsWindow([
            _Entry("new_plain", "", "New"),
            _Entry("new_edited", "mine", "New"),
            _Entry("old_plain", "", "Unmodified"),
        ])
        inputs = window._apply_merge_inputs()
        assert inputs.discarded_new_keys == frozenset({"new_plain"})
        assert inputs.user_overrides == {"new_edited": "mine"}

    def test_tag_configs_are_not_read_when_nothing_is_owned(self, settings):
        window = _InputsWindow([])
        inputs = window._apply_merge_inputs()
        assert inputs.owned == set()
        assert inputs.enclosings == ()
        assert settings["tag_config_reads"] == 0

    def test_owned_items_pull_enclosings_from_the_tag_configs(self, settings, monkeypatch):
        settings["owned"] = {"Item"}
        passed = []

        def fake_enclosings(tag_configs):
            passed.append(tag_configs)
            return (("[", "]"),)

        monkeypatch.setattr("src.utils.owned_items.enclosings_from_tag_configs", fake_enclosings)
        inputs = _InputsWindow([])._apply_merge_inputs()
        assert inputs.owned == {"Item"}
        assert inputs.enclosings == (("[", "]"),)
        assert passed == [{"cfg": 1}]

    def test_blueprint_header_is_captured(self, settings):
        assert _InputsWindow([], bp_header="Blueprints")._apply_merge_inputs().bp_header == "Blueprints"

    def test_apply_to_game_merges_exactly_what_the_snapshot_would(self, settings):
        """_build_apply_merged_dict (apply_to_game's entry) is the pure merge
        over the same snapshot the background check uses."""
        window = _InputsWindow([_Entry("a", "mine")])
        sources = {"global": {"a": "stock", "b": "stock"}}
        via_window = window._build_apply_merged_dict({"global": dict(sources["global"])}, ["global"])
        direct = _merge_for_apply(
            {"global": dict(sources["global"])}, ["global"], window._apply_merge_inputs(),
        )
        assert via_window == direct
        assert via_window["a"] == "mine"


class TestComputeAlreadyApplied:
    """What AppliedStateWorker runs: the same verdict the synchronous check
    used to give, from a snapshot instead of live window state."""

    STOCK = {"a": "stock a", "b": "stock b"}

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        channel = tmp_path / "LIVE"
        channel.mkdir()
        (channel / "user.cfg").write_text("g_language = french_(france)\n", encoding="utf-8")
        applied = tmp_path / "global.ini"
        loads = []

        def fake_load():
            loads.append(1)
            return {"global": dict(self.STOCK)}, ["global"], {}

        monkeypatch.setattr(main_window, "load_sources_from_settings", fake_load)
        parses = []
        real_parse = main_window.parse_ini_file

        def counting_parse(path, *a, **k):
            parses.append(path)
            return real_parse(path, *a, **k)

        monkeypatch.setattr(main_window, "parse_ini_file", counting_parse)
        return type("Env", (), {
            "channel": channel, "applied": applied, "loads": loads, "parses": parses,
        })

    def _write_applied(self, env, mapping):
        env.applied.write_text("".join(f"{k}={v}\n" for k, v in mapping.items()), encoding="utf-8")

    def _snapshot(self, env, overrides=None, language="french"):
        return _AppliedStateSnapshot(
            merge_inputs=_inputs(user_overrides=overrides or {}),
            target_path=env.applied,
            channel_path=str(env.channel),
            selected_language=language,
        )

    def test_true_when_content_and_g_language_both_match(self, env):
        self._write_applied(env, self.STOCK)
        assert _compute_already_applied(self._snapshot(env)) is True

    def test_false_when_nothing_has_been_applied_yet(self, env):
        assert _compute_already_applied(self._snapshot(env)) is False
        assert env.loads == []  # no point re-reading every source

    def test_false_when_no_stock_base_is_loaded(self, env, monkeypatch):
        self._write_applied(env, self.STOCK)
        monkeypatch.setattr(main_window, "load_sources_from_settings", lambda: ({"global": {}}, ["global"], {}))
        assert _compute_already_applied(self._snapshot(env)) is False

    def test_false_when_the_applied_content_is_stale(self, env):
        self._write_applied(env, {"a": "old", "b": "stock b"})
        assert _compute_already_applied(self._snapshot(env)) is False

    def test_a_snapshot_override_is_expected_in_the_applied_file(self, env):
        self._write_applied(env, {"a": "mine", "b": "stock b"})
        assert _compute_already_applied(self._snapshot(env, overrides={"a": "mine"})) is True
        self._write_applied(env, self.STOCK)
        assert _compute_already_applied(self._snapshot(env, overrides={"a": "mine"})) is False

    def test_false_when_user_cfg_points_at_another_language(self, env):
        """Content matches, but switching language in the UI never touches
        user.cfg, so the game would still load the other language."""
        self._write_applied(env, self.STOCK)
        (env.channel / "user.cfg").write_text("g_language = german_(germany)\n", encoding="utf-8")
        assert _compute_already_applied(self._snapshot(env)) is False

    def test_false_when_user_cfg_is_missing(self, env):
        self._write_applied(env, self.STOCK)
        (env.channel / "user.cfg").unlink()
        assert _compute_already_applied(self._snapshot(env)) is False

    def test_stopping_early_skips_the_expensive_steps(self, env):
        self._write_applied(env, self.STOCK)
        assert _compute_already_applied(self._snapshot(env), should_stop=lambda: True) is False
        assert env.parses == []  # never got as far as parsing the applied file

    def test_stopping_after_the_parse_is_honoured_too(self, env):
        """A stop requested during the applied-file parse must not be
        overridden by a content match that finished a moment later."""
        self._write_applied(env, self.STOCK)
        answers = iter([False, False, True])
        assert _compute_already_applied(self._snapshot(env), should_stop=lambda: next(answers)) is False
        assert len(env.parses) == 1


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self):
        if not self.callbacks:
            raise TypeError("nothing connected")
        self.callbacks.clear()

    def emit(self, value):
        for callback in list(self.callbacks):
            callback(value)


class _FakeWorker:
    """Stands in for AppliedStateWorker: records what MainWindow does with it
    and lets a test decide when, and with what, the check finishes."""

    instances: list = []

    def __init__(self, compute, snapshot, token):
        self.compute = compute
        self.snapshot = snapshot
        self.token = token
        self.result = False
        self.started = False
        self.interrupted = False
        self.waits_to_finish = True
        self.finished = _FakeSignal()
        _FakeWorker.instances.append(self)

    def start(self):
        self.started = True

    def requestInterruption(self):
        self.interrupted = True

    def wait(self, timeout=None):
        # Once interrupted, a stuck worker finishes too unless a test says otherwise.
        return self.waits_to_finish

    def finish(self, result):
        """The thread finishing and delivering its verdict to the GUI thread."""
        self.result = result
        self.finished.emit(result)


class _Window:
    """Carries just what the already-applied check touches, with the real
    MainWindow methods bound onto it."""

    _refresh_apply_dirty_after_reload = MainWindow._refresh_apply_dirty_after_reload
    _invalidate_applied_check = MainWindow._invalidate_applied_check
    _launch_applied_state_check = MainWindow._launch_applied_state_check
    _on_applied_state_ready = MainWindow._on_applied_state_ready
    _apply_applied_state_verdict = MainWindow._apply_applied_state_verdict
    _settle_applied_state_check = MainWindow._settle_applied_state_check
    _mark_apply_dirty = MainWindow._mark_apply_dirty
    _mark_applied = MainWindow._mark_applied

    def __init__(self):
        self._applied_state_worker = None
        self._applied_check_token = 0
        self._applied_check_rerun_pending = False
        self._initial_load_done = True
        self._session_has_unapplied_edit = True
        self.dirty_calls: list[bool] = []
        self.snapshots_taken = 0
        self.fail_snapshot = False

    def _apply_merge_inputs(self):
        if self.fail_snapshot:
            raise RuntimeError("snapshot failed")
        self.snapshots_taken += 1
        return "merge-inputs"

    def _set_apply_btn_dirty(self, dirty: bool) -> None:
        self.dirty_calls.append(dirty)


@pytest.fixture
def window(monkeypatch):
    _FakeWorker.instances = []
    monkeypatch.setattr(main_window, "AppliedStateWorker", _FakeWorker)
    monkeypatch.setattr(AppSettings, "get_global_ini_path", staticmethod(lambda: Path("applied.ini")))
    monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: "C:/SC/LIVE"))
    monkeypatch.setattr(AppSettings, "get_selected_language", staticmethod(lambda: "french"))
    return _Window()


class TestAppliedStateLifecycle:
    """The check runs off the GUI thread, so the window has to cope with
    results that arrive late. Whatever changed the state in the meantime (an
    edit, a successful apply, a newer reload) already set the right button
    state and must keep it."""

    def test_a_reload_starts_one_check_from_a_fresh_snapshot(self, window):
        window._refresh_apply_dirty_after_reload()
        (worker,) = _FakeWorker.instances
        assert worker.started
        assert worker.compute is _compute_already_applied
        assert worker.snapshot == _AppliedStateSnapshot(
            merge_inputs="merge-inputs", target_path=Path("applied.ini"),
            channel_path="C:/SC/LIVE", selected_language="french",
        )
        assert worker.token == window._applied_check_token
        assert window._applied_state_worker is worker

    def test_already_applied_turns_green_and_clears_the_session_flag(self, window):
        window._refresh_apply_dirty_after_reload()
        _FakeWorker.instances[0].finish(True)
        assert window.dirty_calls == [False]
        assert window._session_has_unapplied_edit is False
        assert window._applied_state_worker is None

    def test_not_applied_stays_red_and_leaves_the_session_flag_alone(self, window):
        """A genuinely dirty reload (e.g. just regenerated enhancements, not
        yet applied) must still show red, and must not clear a session flag a
        real earlier edit set."""
        window._refresh_apply_dirty_after_reload()
        _FakeWorker.instances[0].finish(False)
        assert window.dirty_calls == [True]
        assert window._session_has_unapplied_edit is True

    def test_an_edit_during_the_check_discards_its_verdict(self, window):
        """The snapshot predates the edit, so a green verdict computed from it
        would hide the pending change. _mark_apply_dirty, and a successful
        apply, both go through _invalidate_applied_check."""
        window._refresh_apply_dirty_after_reload()
        window._invalidate_applied_check()
        _FakeWorker.instances[0].finish(True)
        assert window.dirty_calls == []
        assert window._session_has_unapplied_edit is True

    def test_a_reload_mid_check_interrupts_it_and_reruns_from_a_newer_snapshot(self, window):
        window._refresh_apply_dirty_after_reload()
        first = _FakeWorker.instances[0]
        window._refresh_apply_dirty_after_reload()

        assert first.interrupted
        assert len(_FakeWorker.instances) == 1  # one thread at a time
        assert window.snapshots_taken == 1

        first.finish(True)  # the superseded check reports back
        assert window.dirty_calls == []  # its verdict is stale
        assert len(_FakeWorker.instances) == 2
        assert window.snapshots_taken == 2  # the rerun snapshots newer state
        second = _FakeWorker.instances[1]
        assert second.started
        assert second.token == window._applied_check_token

        second.finish(True)
        assert window.dirty_calls == [False]

    def test_several_reloads_mid_check_collapse_into_one_rerun(self, window):
        for _ in range(4):
            window._refresh_apply_dirty_after_reload()
        _FakeWorker.instances[0].finish(False)
        assert len(_FakeWorker.instances) == 2

    def test_a_snapshot_that_cannot_be_taken_falls_back_to_red(self, window):
        window.fail_snapshot = True
        window._refresh_apply_dirty_after_reload()
        assert _FakeWorker.instances == []
        assert window.dirty_calls == [True]


class TestSettleOnClose:
    """closeEvent lets a running check finish: the thread must be gone before
    exit, and its verdict decides whether the unapplied-changes warning shows
    (a reload sets that flag provisionally, so closing right after a clean
    apply would otherwise warn about changes that don't exist)."""

    def test_nothing_running_is_a_no_op(self, window):
        window._settle_applied_state_check()
        assert window.dirty_calls == []

    def test_a_verdict_that_finishes_in_time_is_applied(self, window):
        window._refresh_apply_dirty_after_reload()
        worker = _FakeWorker.instances[0]
        worker.result = True
        window._settle_applied_state_check()
        assert window.dirty_calls == [False]
        assert window._session_has_unapplied_edit is False
        assert window._applied_state_worker is None
        worker.finished.emit(True)  # Qt still delivers the signal it had queued
        assert window.dirty_calls == [False]  # ...and it must not apply the verdict twice

    def test_a_queued_rerun_is_not_started_while_closing(self, window):
        window._refresh_apply_dirty_after_reload()
        window._refresh_apply_dirty_after_reload()  # rerun now pending
        window._settle_applied_state_check()
        assert len(_FakeWorker.instances) == 1
        assert window._applied_state_worker is None

    def test_a_late_signal_after_settling_cannot_start_another_run(self, window):
        """Qt can still deliver a result that was already queued when the
        signal got disconnected. It must not start a new thread mid-shutdown."""
        window._refresh_apply_dirty_after_reload()
        window._refresh_apply_dirty_after_reload()  # rerun now pending
        worker = _FakeWorker.instances[0]
        window._settle_applied_state_check()
        window._on_applied_state_ready(worker, True)  # the late delivery
        assert len(_FakeWorker.instances) == 1

    def test_a_stale_verdict_is_not_applied(self, window):
        window._refresh_apply_dirty_after_reload()
        _FakeWorker.instances[0].result = True
        window._invalidate_applied_check()
        window._settle_applied_state_check()
        assert window.dirty_calls == []

    def test_a_check_that_stops_after_being_interrupted_is_not_applied(self, window):
        window._refresh_apply_dirty_after_reload()
        worker = _FakeWorker.instances[0]
        worker.result = True
        answers = iter([False, True])  # misses the first deadline, finishes once interrupted
        worker.wait = lambda timeout=None: next(answers)
        window._settle_applied_state_check()
        assert worker.interrupted
        assert window.dirty_calls == []  # an interrupted verdict is unknown
        assert window._applied_state_worker is None

    def test_a_check_that_will_not_stop_keeps_its_reference(self, window):
        """Dropping the last Python reference to a running QThread destroys
        it mid-run, so keep it and let the process deal with the straggler."""
        window._refresh_apply_dirty_after_reload()
        worker = _FakeWorker.instances[0]
        worker.waits_to_finish = False
        window._settle_applied_state_check()
        assert worker.interrupted
        assert window._applied_state_worker is worker
        assert window.dirty_calls == []


class TestEntryPointsKeepTheCheckHonest:
    """The events that change the answer after a snapshot was taken must
    actually invalidate an in-flight check. The lifecycle tests above call
    _invalidate_applied_check directly; these prove the real entry points do."""

    def test_an_edit_marks_red_and_discards_an_in_flight_verdict(self, window):
        window._refresh_apply_dirty_after_reload()
        window._mark_apply_dirty()  # what any table edit does
        _FakeWorker.instances[0].finish(True)
        assert window.dirty_calls == [True]  # the edit's red, not the stale green
        assert window._session_has_unapplied_edit is True

    def test_a_successful_apply_discards_a_stale_red_verdict(self, window):
        """A check that started before the apply computes "not applied" from
        pre-apply state; letting that land would flip the fresh green back."""
        window._refresh_apply_dirty_after_reload()
        window._mark_applied()
        _FakeWorker.instances[0].finish(False)
        assert window.dirty_calls == [False]
        assert window._session_has_unapplied_edit is False

    def test_an_edit_before_the_first_load_finishes_is_not_a_session_edit(self, window):
        window._initial_load_done = False
        window._session_has_unapplied_edit = False
        window._mark_apply_dirty()
        assert window.dirty_calls == [True]
        assert window._session_has_unapplied_edit is False


def _loading_self(clean_reload: bool):
    """A MagicMock standing in for MainWindow, so the real
    _on_loading_finished can run and its call order can be inspected."""
    me = MagicMock()
    me._loading_progress = None
    me._loader_worker = None
    me._snapshot_pending_user_edits.return_value = {}
    me._restore_pending_user_edits.return_value = 0
    me._check_enhancements_after_loading = False
    me._reload_follows_clean_apply = clean_reload
    return me


def _call_names(me):
    return [call[0] for call in me.mock_calls]


class TestReloadAfterACleanApply:
    """Simple mode applies and then reloads. The reload marks everything dirty
    and the background check then re-confirms it, which used to paint the
    button red for the seconds the check takes. The restore has to happen
    before control returns to the event loop, so it must sit right after the
    dirty-marking and before anything that can spin a nested loop."""

    def test_a_clean_reload_restores_green_straight_after_the_dirty_marking(self, monkeypatch):
        monkeypatch.setattr(main_window, "QTimer", MagicMock())
        me = _loading_self(clean_reload=True)
        MainWindow._on_loading_finished(me, [], {}, [])

        names = _call_names(me)
        assert names[names.index("_recompute_owned") + 1] == "_set_apply_btn_dirty"
        me._set_apply_btn_dirty.assert_called_once_with(False)
        assert me._reload_follows_clean_apply is False  # one-shot
        assert names.index("_set_apply_btn_dirty") < names.index("_refresh_apply_dirty_after_reload")

    def test_an_ordinary_reload_leaves_the_button_to_the_dirty_marking(self, monkeypatch):
        monkeypatch.setattr(main_window, "QTimer", MagicMock())
        me = _loading_self(clean_reload=False)
        MainWindow._on_loading_finished(me, [], {}, [])

        names = _call_names(me)
        assert "_set_apply_btn_dirty" not in names
        assert names.index("_recompute_owned") < names.index("_refresh_apply_dirty_after_reload")

    def test_every_reload_requests_a_check(self, monkeypatch):
        monkeypatch.setattr(main_window, "QTimer", MagicMock())
        for clean in (True, False):
            me = _loading_self(clean_reload=clean)
            MainWindow._on_loading_finished(me, [], {}, [])
            me._refresh_apply_dirty_after_reload.assert_called_once_with()


def _generation_self(simple: bool, apply_cleans: bool):
    me = MagicMock()
    me._enhancements_progress_dialog = None
    me._simple_run_active = simple
    me._apply_dirty = True
    me._reload_follows_clean_apply = False

    def fake_apply():
        if apply_cleans:
            me._apply_dirty = False

    me.apply_to_game.side_effect = fake_apply
    return me


class TestSimpleFlowFlagsTheCleanReload:
    """Only the Simple-mode apply-then-reload sequence is known to be a
    refresh of just-applied state, so only it sets the one-shot flag."""

    def test_a_successful_simple_apply_flags_the_reload(self):
        me = _generation_self(simple=True, apply_cleans=True)
        MainWindow._on_enhancements_generation_finished(me, True)
        me.apply_to_game.assert_called_once_with()
        assert me._reload_follows_clean_apply is True

    def test_a_failed_or_cancelled_apply_does_not(self):
        me = _generation_self(simple=True, apply_cleans=False)
        MainWindow._on_enhancements_generation_finished(me, True)
        assert me._reload_follows_clean_apply is False

    def test_a_manual_generate_does_not_apply_or_flag(self):
        me = _generation_self(simple=False, apply_cleans=True)
        MainWindow._on_enhancements_generation_finished(me, True)
        me.apply_to_game.assert_not_called()
        assert me._reload_follows_clean_apply is False

    def test_a_failed_generation_does_not_flag(self):
        me = _generation_self(simple=True, apply_cleans=True)
        MainWindow._on_enhancements_generation_finished(me, False)
        me.apply_to_game.assert_not_called()
        assert me._reload_follows_clean_apply is False


class TestCloseEventSettlesTheCheck:
    """The verdict of a still-running check decides whether the unapplied-
    changes warning is shown, so closing has to settle it first, not after."""

    @staticmethod
    def _closing_self(order, unapplied):
        me = MagicMock()
        me._session_has_unapplied_edit = unapplied
        me._suppress_user_ini_autosave = False
        me._loader_worker = None
        me._user_resized_columns = False
        me.entries = []
        me._settle_applied_state_check.side_effect = lambda: order.append("settle")
        return me

    def test_the_check_is_settled_before_the_warning_decision(self, monkeypatch):
        order = []
        box = MagicMock()
        monkeypatch.setattr(
            main_window, "QMessageBox",
            MagicMock(side_effect=lambda *a, **k: order.append("warn") or box),
        )
        for setter in ("set_window_state", "set_window_geometry", "set_string_column_widths"):
            monkeypatch.setattr(AppSettings, setter, staticmethod(lambda *a, **k: None))

        MainWindow.closeEvent(self._closing_self(order, unapplied=True), MagicMock())

        assert order == ["settle", "warn"]

    def test_the_check_is_settled_even_when_there_is_nothing_to_warn_about(self, monkeypatch):
        order = []
        for setter in ("set_window_state", "set_window_geometry", "set_string_column_widths"):
            monkeypatch.setattr(AppSettings, setter, staticmethod(lambda *a, **k: None))

        MainWindow.closeEvent(self._closing_self(order, unapplied=False), MagicMock())

        assert order == ["settle"]
