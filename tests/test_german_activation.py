"""German is shipped as an available, AI-translated language (#299).

Locks the activation done for the German language addition:
  * the real ``languages/german/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * German ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the German
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * German appears in the language selector (it is not a stub),
  * the SC language id maps to ``german_(germany)`` so apply-to-game writes
    the Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries a German base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
German language. Mirrors ``test_japanese_activation.py``.
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

_DE_UI = REPO / "languages" / "german" / "ui.json"
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


def test_german_ui_json_is_valid_ht_at_shape():
    data = json.loads(_DE_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "German ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_german_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_DE_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    # AI-only language: ht empty everywhere (needs-review marker), at non-empty
    # so nothing falls back to raw English in the UI.
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


def test_german_covers_full_english_key_universe():
    en = {p for p, _ in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    de = {p for p, _ in _leaves(json.loads(_DE_UI.read_text(encoding="utf-8")))}
    missing = sorted(en - de)
    assert not missing, f"German is missing keys English already has: {missing[:10]}"
    # No extras either (outside tutorial.*, which is language-only by design —
    # English carries no tutorial section). A stray extra key usually means
    # ui.json was translated against a newer/different English snapshot than
    # this branch's actual key set.
    extra = sorted(p for p in (de - en) if not p.startswith("tutorial."))
    assert not extra, f"German has keys English on this branch doesn't have: {extra[:10]}"


# dialogs.suppressed_errors_suffix's {plural} is deliberately dropped: German
# "Fehler" doesn't pluralize by suffix (same word singular and plural), so a
# generic {plural} token has no correct value to hold. Spanish and Portuguese
# make the same call for this key (str.format ignores unused kwargs, so a
# dropped placeholder in the string is harmless) — see TRANSLATIONS.md's
# backfill-log precedent for the same drop across languages.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_german_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    de = {p: leaf for p, leaf in _leaves(json.loads(_DE_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in de:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        de_tokens = set(_PLACEHOLDER.findall(de[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - de_tokens != allowed_drop or de_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(de_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_german_translates_the_guided_tour():
    data = json.loads(_DE_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "German guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_german_is_available_in_selector():
    assert "german" in AppSettings.get_available_languages()


def test_german_maps_to_germany_localization_id():
    assert SC_LANGUAGE_IDS["german"] == "german_(germany)"
    assert AppSettings.get_sc_language_id("german") == "german_(germany)"


def test_sources_json_has_german_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("german", "").startswith("https://")


def test_german_docs_exist():
    lang_dir = REPO / "languages" / "german"
    for filename in ("HELP.md", "ABOUT.md", "LEGAL.md", "FAQ.md"):
        assert (lang_dir / filename).exists(), f"languages/german/{filename} is missing"
