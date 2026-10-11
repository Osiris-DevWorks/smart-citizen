"""The Tag Builder freshness check has to run at startup, not only on a
channel switch (#363).

Reported as: the "annotate component tags in mission descriptions" checkbox
reads enabled, but the annotations are absent in game. Turning it off, letting
the regeneration finish, and turning it back on fixes it — which is a strange
shape for a settings bug, because the setting was already the value the user
wanted both before and after.

It isn't a settings bug. The value was always right; what was never checked is
whether the *generated INIs on disk* were built from it. Three staleness
signals exist, and only two of them were consulted at launch:

    DataForge cache vs Data.p4k        checked at startup
    enhancement output files missing   checked at startup
    tag config vs the config the       ONLY on a channel switch
      INIs were generated from

That third one is where the annotate toggle lives.
``refresh_tag_builder_dirty_state()`` implements it correctly — light Save Tag
Changes when the recorded stamp is missing or differs from the live config —
but ``setup_ui`` ended with an unconditional ``_set_tag_btn_dirty(False)``, so
launch asserted "clean" instead of asking. With the output files present and
the DataForge cache current, Generate Enhancements sat grey too (it asks "does
the file exist", not "was it built from this config"), leaving both buttons
grey over stale output and no indication anything was wrong.

Cycling the checkbox worked because ``_mark_tag_dirty`` is a blind "the user
touched a control" flag, not a comparison: the cycle forged the dirty state
that the startup check should have derived. test_cycling_the_checkbox_never_
changed_the_config pins that, since it is the whole reason the workaround
looked like it was re-registering a setting.

Every install upgraded from before the stamp existed has no stamp at all (it
and the annotate flag joining the fingerprint landed in the same commit), so
the missing-stamp case below is not an edge case — it is what every upgrading
user gets on first launch.

Needs a real QApplication for the widgets, so it uses the offscreen Qt platform
like tests/test_ui_mode.py rather than pytest-qt (not a dev dep).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PyQt6.QtCore import QSettings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Same import path src/gui/enhancements_tab.py uses, so patching
# AppSettings.settings affects the exact class the tab sees (see the note in
# tests/test_ui_mode.py about the dual pythonpath).
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import tag_config_fingerprint  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Redirect the settings store AND the user data dir.

    The data dir matters here specifically: the tag-config stamp is a file
    under ``get_enhancements_dir()``, which derives from the data-dir setting
    rather than from the settings object. Patching only ``settings`` would
    leave these tests reading the developer's own install and passing or
    failing on whether it happens to hold a matching stamp.
    """
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))
    AppSettings.set_user_data_dir(tmp_path / "data")
    return tmp_path


def _new_tab():
    from src.gui.enhancements_tab import EnhancementsTab
    return EnhancementsTab()


def _stamp_for(annotate: bool) -> None:
    """Record the stamp a successful generation would leave for the persisted
    tag configs combined with *annotate*."""
    AppSettings.set_tag_config_stamp(
        tag_config_fingerprint(AppSettings.get_all_tag_configs(), annotate)
    )


def _stamp_matching_live_config() -> None:
    _stamp_for(AppSettings.get_tag_annotate_mission_descs())


def _seed_generated_output() -> None:
    """Put generated INIs on disk, so there is output a tag-config change can
    actually invalidate.

    Every check below needs this: being stale requires something that *can* be
    stale, and with no output the button stays grey by design (see
    test_no_generated_output_means_nothing_can_be_stale). Writes the whole
    ENHANCEMENTS_FILES set rather than picking the enabled ones, so the tests
    don't quietly depend on which categories default to on.

    Writes into get_enhancements_dir(), which is where the generator puts them
    and where the app looks. That is the same path as get_cache_dir() for
    English and cache/lang/{language} for everything else, so seeding the
    channel root instead would have made the non-English tests below pass for
    the wrong reason.
    """
    enh_dir = AppSettings.get_enhancements_dir()
    enh_dir.mkdir(parents=True, exist_ok=True)
    for filename in AppSettings.ENHANCEMENTS_FILES.values():
        (enh_dir / filename).write_text("; generated\n", encoding="utf-8")


# ── The startup check ───────────────────────────────────────────────────────

def test_missing_stamp_lights_the_button_at_construction(qapp, isolated_settings):
    """What every install upgraded from before the stamp existed looks like:
    INIs on disk, nothing recording what they were built from. Unknowable
    reads as stale, matching the rule the channel-switch path already used."""
    _seed_generated_output()
    assert AppSettings.get_tag_config_stamp() == ""
    assert _new_tab()._tag_dirty is True


def test_stale_stamp_lights_the_button_at_construction(qapp, isolated_settings):
    _seed_generated_output()
    AppSettings.set_tag_config_stamp("built-from-some-older-config")
    assert _new_tab()._tag_dirty is True


def test_matching_stamp_leaves_the_button_clean_at_construction(
        qapp, isolated_settings):
    """The other half of the contract, and the one that keeps this fix from
    being "light the button always": when the INIs really were generated from
    the live config there is nothing to do and the button stays grey."""
    _seed_generated_output()
    _stamp_matching_live_config()
    assert _new_tab()._tag_dirty is False


def test_annotate_toggle_alone_makes_the_output_stale(qapp, isolated_settings):
    """The reported symptom, reduced to one setting.

    The INIs were generated while annotation was off; the checkbox now reads
    on (its default). Nothing else differs. That difference alone has to reach
    the button, because it is the only thing standing between the user and
    annotations that silently never appear in game.
    """
    _seed_generated_output()
    _stamp_for(annotate=False)
    tab = _new_tab()
    assert tab._annotate_mission_descs_cb.isChecked() is True
    assert tab._tag_dirty is True


def test_no_generated_output_means_nothing_can_be_stale(qapp, isolated_settings):
    """The bound on the whole check: being stale requires something that can
    *be* stale.

    A brand-new install has no stamp, which reads as "unknowable" and would
    otherwise light the button before the user has done anything wrong. There
    are no INIs to be out of date, and Generate Enhancements is already lit for
    the missing files, so a second red button would be noise.
    """
    assert AppSettings.get_tag_config_stamp() == ""      # nothing generated
    assert _new_tab()._tag_dirty is False


# ── Non-English languages ───────────────────────────────────────────────────
#
# get_enhancements_dir() is get_cache_dir() for English but
# cache/lang/{language} for everything else, and the generator writes the INIs
# (and the stamp beside them) into that per-language dir. Every check here
# therefore has to use get_enhancements_dir(); reading the channel root answers
# for English no matter which language is selected.
#
# These went unwritten first time round and the whole fix was inert for
# non-English users as a result: the output-exists gate found nothing under the
# channel root, concluded "nothing can be stale", and returned before ever
# reading the stamp. Every other test in this file runs at English, where the
# two paths coincide, so none of them could see it.

def test_stale_stamp_lights_the_button_on_a_non_english_language(
        qapp, isolated_settings):
    AppSettings.set_selected_language("german")
    assert AppSettings.get_enhancements_dir() != AppSettings.get_cache_dir(), (
        "precondition: the per-language dir must differ from the channel root, "
        "or this test collapses into the English case and proves nothing"
    )
    _seed_generated_output()
    AppSettings.set_tag_config_stamp("built-from-some-older-config")

    assert _new_tab()._tag_dirty is True


def test_english_output_does_not_vouch_for_another_language(
        qapp, isolated_settings):
    """The precise failure: English enhancements exist, German ones do not.

    Both the output-exists gate and the Generate Enhancements check used to
    read the channel root, so English's files answered for German. The gate
    said "there is output, so staleness is meaningful" and Generate said
    "everything is present, nothing to do", neither of which is true of the
    language actually selected.
    """
    _seed_generated_output()                    # English, at the channel root
    AppSettings.set_selected_language("german")  # ...which has nothing generated

    tab = _new_tab()
    assert tab._enhancements_output_exists() is False
    assert tab._compute_initial_enhancements_dirty() is True


def test_status_dots_and_generate_button_agree_on_a_non_english_language(
        qapp, isolated_settings):
    """The category dots sit directly beside the Generate Enhancements button,
    so they have to answer the same question about the same directory.

    Making only the button language-aware left the two contradicting each
    other outright: with English enhancements generated and German selected,
    every dot rendered green ("all present", read from the channel root where
    English lives) while the button was simultaneously lit ("work to do",
    correctly reading the empty per-language dir). Consistently wrong at least
    agreed; half-fixed did not.
    """
    _seed_generated_output()                     # English, at the channel root
    AppSettings.set_selected_language("german")   # ...which has nothing generated

    tab = _new_tab()
    tab.refresh_enhancements_status()
    tab.refresh_enhancements_dirty_state()

    green = sum(
        "#4caf50" in dot.styleSheet()
        for dot in tab._enhancements_status_labels.values()
    )
    assert green == 0, (
        "dots report English's files while the button reports German's; "
        "they must read the same directory"
    )
    assert tab._generate_enhancements_btn.isEnabled() is True


def test_category_toggle_renames_the_selected_language_not_english(
        qapp, isolated_settings):
    """_apply_category_changes MUTATES files, so reading the channel root did
    more than answer the wrong question.

    A user on German unticking a category renamed the ENGLISH INIs to
    .disabled and back, while the German files the checkbox appears to control
    were never touched: the toggle silently did nothing for them and quietly
    vandalised English along the way.
    """
    english_dir = AppSettings.get_cache_dir()
    _seed_generated_output()                      # English, at the channel root
    AppSettings.set_selected_language("german")
    _seed_generated_output()                      # ...and German, in its own dir
    german_dir = AppSettings.get_enhancements_dir()
    assert german_dir != english_dir

    tab = _new_tab()
    key = next(k for k, cb in tab._enhancements_checkboxes.items() if cb.isChecked())
    filenames = tab._files_for_category(key)
    tab._enhancements_checkboxes[key].setChecked(False)
    tab._apply_category_changes()

    for fn in filenames:
        assert (german_dir / (fn + ".disabled")).exists(), f"{fn} not disabled for german"
        assert not (german_dir / fn).exists()
        assert (english_dir / fn).exists(), f"english {fn} must be untouched"
        assert not (english_dir / (fn + ".disabled")).exists()


def test_category_toggle_survives_a_stale_disabled_file(qapp, isolated_settings):
    """Windows rename() fails when the target exists, and a stale .disabled is
    reachable: anyone who hit the bug above has an orphaned one, and
    regenerating recreates the active file beside it. The rename then raised,
    got swallowed by the OSError handler, and the toggle appeared to do
    nothing at all."""
    _seed_generated_output()
    enh_dir = AppSettings.get_enhancements_dir()

    tab = _new_tab()
    key = next(k for k, cb in tab._enhancements_checkboxes.items() if cb.isChecked())
    filenames = tab._files_for_category(key)
    for fn in filenames:                          # the orphan from the old bug
        (enh_dir / (fn + ".disabled")).write_text("; stale\n", encoding="utf-8")

    tab._enhancements_checkboxes[key].setChecked(False)
    tab._apply_category_changes()

    for fn in filenames:
        assert not (enh_dir / fn).exists(), f"{fn} should have been disabled"
        assert (enh_dir / (fn + ".disabled")).read_text(encoding="utf-8") != "; stale\n", (
            "the stale orphan should have been replaced by the real file, "
            "not left in place with the rename silently failing"
        )


def test_export_settings_keeps_the_button_lit_when_output_is_behind(
        qapp, isolated_settings):
    """flush_pending_tag_edits (Export Settings) persists on-screen edits
    *without* regenerating, so it must not clear the button.

    It used to, which threw away a correct signal the user had already been
    shown: edit the Tag Builder, click Export Settings, and the edits landed in
    settings while the INIs kept the old config — the same stale-output-behind-
    a-grey-button end state as launch and import.
    """
    _seed_generated_output()
    _stamp_matching_live_config()
    tab = _new_tab()
    assert tab._tag_dirty is False                       # in sync to begin with

    tab._annotate_mission_descs_cb.setChecked(            # an unsaved edit
        not tab._annotate_mission_descs_cb.isChecked()
    )
    assert tab._tag_dirty is True

    tab.flush_pending_tag_edits()                         # Export Settings
    assert tab._tag_dirty is True, (
        "the edit is saved but the INIs were never regenerated, so the user "
        "still needs to act"
    )


def test_startup_state_agrees_with_the_freshness_check(qapp, isolated_settings):
    """The bug stated as an invariant: launch must not contradict the app's own
    definition of stale.

    Before the fix, constructing the tab and then running the freshness check
    flipped the button — the startup state and the check disagreed, and only
    a channel switch ever ran the check to settle it. Asserting they agree
    catches a regression whichever side of the pair drifts.
    """
    _seed_generated_output()
    for stamp in ("", "built-from-some-older-config"):
        AppSettings.set_tag_config_stamp(stamp)
        tab = _new_tab()
        at_construction = tab._tag_dirty
        tab.refresh_tag_builder_dirty_state()
        assert at_construction is tab._tag_dirty, (
            f"startup state contradicts the freshness check for stamp {stamp!r}"
        )

    _stamp_matching_live_config()
    tab = _new_tab()
    at_construction = tab._tag_dirty
    tab.refresh_tag_builder_dirty_state()
    assert at_construction is tab._tag_dirty


def test_cycling_the_checkbox_never_changed_the_config(qapp, isolated_settings):
    """Documents why the reporter's workaround appeared to re-register the
    setting: it didn't. An off/on cycle lands on the identical config, so the
    button lighting up afterwards was purely ``_mark_tag_dirty`` firing on the
    toggle — a blind "user touched something" flag. The startup check now
    reaches the same conclusion without needing to be poked."""
    _seed_generated_output()
    _stamp_for(annotate=False)
    tab = _new_tab()
    before = tab._live_tag_config_fingerprint()

    tab._annotate_mission_descs_cb.setChecked(False)
    tab._annotate_mission_descs_cb.setChecked(True)

    assert tab._live_tag_config_fingerprint() == before
    assert tab._tag_dirty is True


# ── Re-deriving after a generation run ──────────────────────────────────────
#
# _apply_tag_builder and the Generate click handler both clear the button the
# moment they *launch* a run, before the worker has done anything. The stamp
# is only written on success, so a failed run used to leave the button grey
# over INIs the tag config never reached. MainWindow's finished handler now
# re-derives it, the same way set_operation_idle already does for the Generate
# button (which it does not cover).
#
# Driven on a lightweight stand-in `self` with the real unbound method, per
# tests/test_ui_mode.py — constructing a whole MainWindow pulls in the full
# startup pipeline. The enhancements_tab is a real one, since its button state
# is the thing under test.

class _StubWorker:
    def quit(self):
        pass

    def wait(self):
        pass


class _StubStatusBar:
    def showMessage(self, *_args, **_kwargs):
        pass


class _StubWindow:
    """Only the attributes _on_enhancements_generation_finished touches."""

    def __init__(self, tab):
        self.enhancements_tab = tab
        self._enhancements_progress_dialog = None
        self._enhancements_worker = _StubWorker()
        self._simple_run_active = False

    def statusBar(self):
        return _StubStatusBar()

    def _show_loading_progress(self, *_args):
        pass

    def _end_simple_run(self):
        pass


def _finish_generation(tab, success: bool):
    from src.gui.main_window import MainWindow
    MainWindow._on_enhancements_generation_finished(_StubWindow(tab), success)


def test_failed_generation_relights_the_optimistically_cleared_button(
        qapp, isolated_settings):
    _seed_generated_output()
    AppSettings.set_tag_config_stamp("built-from-some-older-config")
    tab = _new_tab()
    assert tab._tag_dirty is True

    tab._set_tag_btn_dirty(False)        # what launching a run does
    _finish_generation(tab, success=False)

    assert tab._tag_dirty is True, (
        "a failed run leaves the stamp untouched, so the button has to come "
        "back for a retry rather than sitting grey over stale INIs"
    )


def test_language_switch_re_derives_both_freshness_buttons(qapp, isolated_settings):
    """Both buttons are per-language — enhancement INIs live in the language's
    own dir and the tag-config stamp sits beside them — so a language switch
    has to recompute them or they keep showing the previous language's verdict.

    _on_channel_changed already does exactly this pair of calls; language
    switching had never been wired up to match. A wiring test rather than a
    state one: the state logic is covered above, what was missing is the call.
    """
    from src.gui.main_window import MainWindow

    called = []

    class _RecordingTab:
        def refresh_enhancements_dirty_state(self):
            called.append("enhancements")

        def refresh_tag_builder_dirty_state(self):
            called.append("tag_builder")

    class _Window:
        _loader_worker = None
        enhancements_tab = _RecordingTab()

        def retranslate_ui(self):
            pass

        def statusBar(self):
            return type("_Bar", (), {"showMessage": lambda *a, **k: None})()

        def _apply_language_base_source(self, language):
            pass

    MainWindow._on_language_changed(_Window(), "english")

    assert called == ["enhancements", "tag_builder"]


def test_successful_generation_leaves_the_button_clean(qapp, isolated_settings):
    """The non-regression half: a run that really did write a matching stamp
    must settle the button, not re-light it."""
    _seed_generated_output()
    AppSettings.set_tag_config_stamp("built-from-some-older-config")
    tab = _new_tab()
    assert tab._tag_dirty is True

    _stamp_matching_live_config()        # what a successful worker writes
    _finish_generation(tab, success=True)

    assert tab._tag_dirty is False
