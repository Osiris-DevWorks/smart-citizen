"""UI string localization (src/utils/i18n.py, 2.0 #30).

Locks the translation contract the whole GUI leans on:

  * ``tr()`` resolves dot-separated paths into the loaded JSON tree.
  * ``set_language()`` always rebuilds from the English base with the target
    language overlaid, so a key missing from a translation falls back to
    English, and a key missing everywhere returns the bare key string
    (``tr()`` never raises; an incomplete ui.json must not crash the app).
  * kwargs interpolate via str.format; bad placeholders degrade to the raw
    string instead of raising.
  * ``_deep_merge`` merges nested sections and lets a scalar overlay replace
    a dict (with a warning) rather than blowing up on malformed files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils import i18n  # noqa: E402

pytestmark = pytest.mark.unit


def _write_lang(root: Path, name: str, data: dict) -> None:
    d = root / "languages" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "ui.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def lang_root(tmp_path, monkeypatch):
    """Point i18n's resource lookup at a tmp languages/ tree and restore the
    module's language state afterwards so other tests see a clean slate."""
    import src.utils.resource_path as resource_path

    monkeypatch.setattr(
        resource_path, "get_resource_path", lambda rel: str(tmp_path / rel)
    )
    saved_lang, saved_strings = i18n._current_lang, i18n._strings
    _write_lang(tmp_path, "english", {
        "toolbar": {"apply_btn": "Apply to Game", "more_btn": "More"},
        "dialogs": {"export_complete": "Exported to {path} ({size} bytes)"},
        "status": {"ready": "Ready"},
        # Placeholder deliberately named "key" — this is the exact shape
        # that used to crash tr() before its own parameter was renamed
        # away from "key" (see TestTr.test_kwarg_named_key_*).
        "strings_tab": {"copied_key": "Copied: {key}"},
    })
    _write_lang(tmp_path, "french", {
        "toolbar": {"apply_btn": "Appliquer au jeu"},
        # dialogs/status sections intentionally absent — must fall back.
    })
    yield tmp_path
    i18n._current_lang, i18n._strings = saved_lang, saved_strings


class TestTr:
    def test_english_dot_path_resolution(self, lang_root):
        i18n.set_language("english")
        assert i18n.tr("toolbar.apply_btn") == "Apply to Game"

    def test_missing_key_returns_bare_key(self, lang_root):
        i18n.set_language("english")
        assert i18n.tr("toolbar.nope") == "toolbar.nope"

    def test_path_through_scalar_returns_bare_key(self, lang_root):
        # "toolbar.apply_btn" is a string; descending further must not raise.
        i18n.set_language("english")
        assert i18n.tr("toolbar.apply_btn.deeper") == "toolbar.apply_btn.deeper"

    def test_kwargs_interpolation(self, lang_root):
        i18n.set_language("english")
        assert (
            i18n.tr("dialogs.export_complete", path="C:/out.zip", size=42)
            == "Exported to C:/out.zip (42 bytes)"
        )

    def test_bad_format_kwargs_degrade_to_raw_string(self, lang_root):
        # Missing placeholder name: return the raw template, never raise.
        i18n.set_language("english")
        assert (
            i18n.tr("dialogs.export_complete", wrong_kwarg=1)
            == "Exported to {path} ({size} bytes)"
        )

    def test_kwarg_named_key_does_not_collide(self, lang_root):
        """Regression guard: tr()'s own first parameter must never be named
        "key" — a loc key is a very natural thing to interpolate into a UI
        message (e.g. "Copied: {key}"), and two real call sites crashed
        with "TypeError: tr() got multiple values for argument 'key'"
        before this was fixed by renaming the parameter to i18n_key."""
        i18n.set_language("english")
        assert i18n.tr("status.ready", key="some_loc_key") == "Ready"

    def test_kwarg_named_key_interpolates_correctly(self, lang_root):
        i18n.set_language("english")
        assert (
            i18n.tr("strings_tab.copied_key", key="item_Name_Foo")
            == "Copied: item_Name_Foo"
        )


class TestSetLanguage:
    def test_overlay_wins_for_translated_keys(self, lang_root):
        i18n.set_language("french")
        assert i18n.tr("toolbar.apply_btn") == "Appliquer au jeu"

    def test_untranslated_key_falls_back_to_english(self, lang_root):
        # french ui.json has toolbar.apply_btn but not toolbar.more_btn or
        # the dialogs/status sections; all must resolve to English.
        i18n.set_language("french")
        assert i18n.tr("toolbar.more_btn") == "More"
        assert i18n.tr("status.ready") == "Ready"

    def test_unknown_language_behaves_as_english(self, lang_root):
        # No german/ui.json: overlay loads {}, English base remains intact.
        i18n.set_language("german")
        assert i18n.tr("toolbar.apply_btn") == "Apply to Game"

    def test_switch_back_to_english_drops_overlay(self, lang_root):
        i18n.set_language("french")
        i18n.set_language("english")
        assert i18n.tr("toolbar.apply_btn") == "Apply to Game"

    def test_corrupt_overlay_degrades_to_english(self, lang_root):
        bad = lang_root / "languages" / "italian"
        bad.mkdir(parents=True)
        (bad / "ui.json").write_text("{not json", encoding="utf-8")
        i18n.set_language("italian")
        assert i18n.tr("toolbar.apply_btn") == "Apply to Game"


class TestLazyDefault:
    def test_tr_before_set_language_loads_english(self, lang_root):
        # Helpers outside the app's startup path (workers' progress strings,
        # tests) must get English text, not bare keys, when set_language was
        # never called.
        i18n._strings = {}
        i18n._current_lang = "english"
        assert i18n.tr("toolbar.apply_btn") == "Apply to Game"


class TestDeepMerge:
    def test_nested_merge_keeps_sibling_keys(self):
        base = {"a": {"x": "1", "y": "2"}, "b": "3"}
        i18n._deep_merge(base, {"a": {"x": "10"}})
        assert base == {"a": {"x": "10", "y": "2"}, "b": "3"}

    def test_scalar_overlay_replaces_dict_without_raising(self):
        # Malformed translation (scalar where base has a section): replace,
        # warn, keep going — i18n must never take the app down.
        base = {"a": {"x": "1"}}
        i18n._deep_merge(base, {"a": "flat"})
        assert base == {"a": "flat"}


# ── #182: human/AI translation leaves {"ht": ..., "at": ...} ─────────────────

@pytest.fixture
def htat_root(tmp_path, monkeypatch):
    """Languages tree whose leaves are {ht, at} objects (the #182 schema)."""
    import src.utils.resource_path as resource_path

    monkeypatch.setattr(
        resource_path, "get_resource_path", lambda rel: str(tmp_path / rel)
    )
    saved_lang, saved_strings = i18n._current_lang, i18n._strings
    _write_lang(tmp_path, "english", {
        "toolbar": {
            "apply_btn": {"ht": "Apply to Game", "at": ""},
            "more_btn": {"ht": "More", "at": ""},
            "help_btn": {"ht": "Help", "at": ""},
        },
    })
    _write_lang(tmp_path, "french", {
        "toolbar": {
            "apply_btn": {"ht": "Appliquer au jeu", "at": ""},   # human
            "more_btn": {"ht": "", "at": "Plus"},                # AI fallback
            "help_btn": {"ht": "", "at": ""},                    # blank -> EN floor
        },
        "tutorial": {"step1": {"ht": "Étape un", "at": ""}},     # EN lacks tutorial
    })
    yield tmp_path
    i18n._current_lang, i18n._strings = saved_lang, saved_strings


class TestHtAtLeafResolution:
    def test_leaf_value_prefers_ht(self):
        assert i18n._leaf_value({"ht": "Bonjour", "at": "Salut"}) == "Bonjour"

    def test_leaf_value_falls_back_to_at_when_ht_blank(self):
        assert i18n._leaf_value({"ht": "", "at": "Salut"}) == "Salut"

    def test_leaf_value_empty_when_both_blank(self):
        assert i18n._leaf_value({"ht": "", "at": ""}) == ""

    def test_leaf_value_accepts_legacy_plain_string(self):
        assert i18n._leaf_value("plain") == "plain"

    def test_is_leaf_distinguishes_leaf_from_section(self):
        assert i18n._is_leaf({"ht": "x", "at": ""})
        assert i18n._is_leaf({"at": "y"})
        assert not i18n._is_leaf({"apply_btn": {"ht": "x", "at": ""}})  # section
        assert not i18n._is_leaf("str")

    def test_tr_prefers_human_translation(self, htat_root):
        i18n.set_language("french")
        assert i18n.tr("toolbar.apply_btn") == "Appliquer au jeu"

    def test_tr_falls_back_to_ai_when_ht_blank(self, htat_root):
        i18n.set_language("french")
        assert i18n.tr("toolbar.more_btn") == "Plus"

    def test_blank_leaf_does_not_override_english_floor(self, htat_root):
        # french has help_btn but both ht/at blank -> keep the English base.
        i18n.set_language("french")
        assert i18n.tr("toolbar.help_btn") == "Help"

    def test_overlay_only_key_is_added(self, htat_root):
        i18n.set_language("french")
        assert i18n.tr("tutorial.step1") == "Étape un"

    def test_tr_on_section_returns_bare_key(self, htat_root):
        i18n.set_language("english")
        assert i18n.tr("toolbar") == "toolbar"


class TestHtAtMerge:
    def test_leaf_is_atomic_replaced_wholesale(self):
        base = {"k": {"ht": "A", "at": ""}}
        i18n._deep_merge(base, {"k": {"ht": "", "at": "B"}})
        assert base == {"k": {"ht": "", "at": "B"}}

    def test_blank_overlay_leaf_skipped_keeps_base(self):
        base = {"k": {"ht": "A", "at": ""}}
        i18n._deep_merge(base, {"k": {"ht": "", "at": ""}})
        assert base == {"k": {"ht": "A", "at": ""}}

    def test_overlay_only_leaf_added(self):
        base = {}
        i18n._deep_merge(base, {"k": {"ht": "", "at": "X"}})
        assert base == {"k": {"ht": "", "at": "X"}}
