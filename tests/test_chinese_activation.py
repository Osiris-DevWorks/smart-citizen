"""Chinese is shipped as an available, AI-translated language (#300).

Locks the activation done for the Chinese language addition:
  * the real ``languages/chinese/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Chinese ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the Chinese
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * Chinese appears in the language selector (it is not a stub),
  * the SC language id maps to ``chinese_(simplified)`` so apply-to-game
    writes the Localization folder and ``g_language`` the game actually
    loads,
  * ``languages/sources.json`` carries a Chinese base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
Chinese language. Mirrors ``test_german_activation.py``.
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

_CN_UI = REPO / "languages" / "chinese" / "ui.json"
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


def test_chinese_ui_json_is_valid_ht_at_shape():
    data = json.loads(_CN_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Chinese ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_chinese_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_CN_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    # AI-only language: ht empty everywhere (needs-review marker), at non-empty
    # so nothing falls back to raw English in the UI.
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


def test_chinese_covers_full_english_key_universe():
    en = {p for p, _ in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    cn = {p for p, _ in _leaves(json.loads(_CN_UI.read_text(encoding="utf-8")))}
    missing = sorted(en - cn)
    assert not missing, f"Chinese is missing keys English already has: {missing[:10]}"
    # No extras either (outside tutorial.*, which is language-only by design —
    # English carries no tutorial section). A stray extra key usually means
    # ui.json was translated against a newer/different English snapshot than
    # this branch's actual key set.
    extra = sorted(p for p in (cn - en) if not p.startswith("tutorial."))
    assert not extra, f"Chinese has keys English on this branch doesn't have: {extra[:10]}"


# dialogs.suppressed_errors_suffix's {plural} is deliberately dropped: the
# token is only ever filled with a hardcoded English "s" suffix
# (main_window.py), which has no equivalent in Chinese -- there's no suffix
# pluralization to append it to. German drops the same token for the
# analogous reason (its "Fehler" is already invariant); str.format ignores
# unused kwargs, so a dropped placeholder in the string is harmless.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_chinese_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    cn = {p: leaf for p, leaf in _leaves(json.loads(_CN_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in cn:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        cn_tokens = set(_PLACEHOLDER.findall(cn[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - cn_tokens != allowed_drop or cn_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(cn_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_chinese_translates_the_guided_tour():
    data = json.loads(_CN_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "Chinese guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_chinese_is_available_in_selector():
    assert "chinese" in AppSettings.get_available_languages()


def test_chinese_maps_to_simplified_localization_id():
    assert SC_LANGUAGE_IDS["chinese"] == "chinese_(simplified)"
    assert AppSettings.get_sc_language_id("chinese") == "chinese_(simplified)"


def test_sources_json_has_chinese_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("chinese", "").startswith("https://")


def test_chinese_docs_exist():
    lang_dir = REPO / "languages" / "chinese"
    for filename in ("HELP.md", "ABOUT.md", "LEGAL.md", "FAQ.md"):
        assert (lang_dir / filename).exists(), f"languages/chinese/{filename} is missing"
