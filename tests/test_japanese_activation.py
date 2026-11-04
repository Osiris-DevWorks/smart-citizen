"""Japanese is shipped as an available, AI-translated language (#301).

Locks the activation done for the Japanese language addition:
  * the real ``languages/japanese/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Japanese ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the Japanese
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * Japanese appears in the language selector (it is not a stub),
  * the SC language id maps to ``japanese_(japan)`` so apply-to-game writes the
    Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries a Japanese base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
Japanese language.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.utils.settings import AppSettings, SC_LANGUAGE_IDS  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_JA_UI = REPO / "languages" / "japanese" / "ui.json"
_EN_UI = REPO / "languages" / "english" / "ui.json"
_PLACEHOLDER = re.compile(r"\{[^}]+\}")


def _leaves(node, prefix=""):
    """Yield (dotpath, leaf) for every translation leaf in the tree."""
    for k, v in node.items():
        if k == "_comment":
            continue
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and ("ht" in v or "at" in v):
            yield p, v
        elif isinstance(v, dict):
            yield from _leaves(v, p)


def test_japanese_ui_json_is_valid_ht_at_shape():
    data = json.loads(_JA_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Japanese ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_japanese_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_JA_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    # AI-only language: ht empty everywhere (needs-review marker), at non-empty
    # so nothing falls back to raw English in the UI.
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


# dialogs.suppressed_errors_suffix's {plural} is deliberately dropped: the
# token is only ever filled with a hardcoded English "s" suffix
# (main_window.py), which has no equivalent in Japanese -- nouns don't
# inflect for number, so there's no suffix pluralization to append it to.
# German drops the same token for the analogous reason (its "Fehler" is
# already invariant); str.format ignores unused kwargs, so a dropped
# placeholder in the string is harmless.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_japanese_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    ja = {p: leaf for p, leaf in _leaves(json.loads(_JA_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in ja:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        ja_tokens = set(_PLACEHOLDER.findall(ja[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - ja_tokens != allowed_drop or ja_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(ja_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_japanese_translates_the_guided_tour():
    data = json.loads(_JA_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "Japanese guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_japanese_is_available_in_selector():
    assert "japanese" in AppSettings.get_available_languages()


def test_japanese_maps_to_japan_localization_id():
    assert SC_LANGUAGE_IDS["japanese"] == "japanese_(japan)"
    assert AppSettings.get_sc_language_id("japanese") == "japanese_(japan)"


def test_sources_json_has_japanese_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("japanese", "").startswith("https://")
