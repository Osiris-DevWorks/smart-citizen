"""Tests for _matches_applied_output (#387) and _refresh_apply_dirty_after_
reload (#397 follow-up): the Apply button should start green, not
unconditionally red, when the currently loaded state already matches what's
on disk in the game's global.ini -- and that has to hold after EVERY reload,
not just the very first one at startup.

The comparison walks stock_dict's own keys, not merged_dict's, because
merge_ini_files (the real writer) only ever overwrites a key present in its
structure-preservation source file -- a key merged_dict carries that
stock_dict lacks is never actually written, so it must never influence this
result, or a profile with such a key would show a false "dirty" on every
launch even immediately after a genuine apply.
"""
from __future__ import annotations

import pytest

from src.gui.main_window import MainWindow, _matches_applied_output, _user_cfg_language_matches

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


class _Stub:
    """Carries just what _refresh_apply_dirty_after_reload touches."""

    def __init__(self, already_applied: bool, session_has_unapplied_edit: bool = True):
        self._already_applied = already_applied
        self._session_has_unapplied_edit = session_has_unapplied_edit
        self.dirty_calls: list[bool] = []

    def _entries_already_applied(self) -> bool:
        return self._already_applied

    def _set_apply_btn_dirty(self, dirty: bool) -> None:
        self.dirty_calls.append(dirty)

    def refresh(self) -> None:
        MainWindow._refresh_apply_dirty_after_reload(self)


class TestRefreshApplyDirtyAfterReload:
    """#397 follow-up: Simple mode's one-button flow reloads immediately
    after a successful apply_to_game() (to refresh the hidden Advanced
    view), and that reload's own dirty-marking used to blindly undo what
    apply_to_game() had just correctly cleared -- both the button color and
    the exit-time "unapplied changes" warning. This is the fix: defer to
    the same authoritative check on every reload, not just the first.
    """

    def test_clears_dirty_and_the_session_flag_when_already_applied(self):
        stub = _Stub(already_applied=True, session_has_unapplied_edit=True)
        stub.refresh()
        assert stub.dirty_calls == [False]
        assert stub._session_has_unapplied_edit is False

    def test_stays_dirty_and_leaves_the_session_flag_alone_when_not_applied(self):
        """Guard against overcorrecting: a genuinely dirty reload (e.g. just
        regenerated enhancements, not yet applied) must still show red, and
        must not clear a session flag that a real earlier edit set."""
        stub = _Stub(already_applied=False, session_has_unapplied_edit=True)
        stub.refresh()
        assert stub.dirty_calls == [True]
        assert stub._session_has_unapplied_edit is True

    def test_clean_reload_does_not_touch_an_already_false_session_flag(self):
        stub = _Stub(already_applied=True, session_has_unapplied_edit=False)
        stub.refresh()
        assert stub._session_has_unapplied_edit is False
