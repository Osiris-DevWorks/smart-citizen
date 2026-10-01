"""Korean is shipped as an available, AI-translated, bring-your-own-file
language (#367).

Locks the activation done for the Korean language addition:
  * the real ``languages/korean/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Korean ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the Korean
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * Korean appears in the language selector (it is not a stub),
  * the SC language id maps to ``korean_(south_korea)`` — one of the
    official CIG Localization slots, so apply-to-game writes the
    Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries no URL for Korean — deliberately
    blank. The Star Citizen Korean Localization Project's license forbids
    redistributing their ``global.ini``, so unlike every other language here
    Korean has nothing to bundle. A user maps their own locally-obtained
    copy via the Config tab's Map Language File dialog (#367 also added
    local-file support there, on top of the URL-only download it already
    had: ``LanguageBaseDownloadWorker`` now copies a local path instead of
    downloading when the mapped source isn't an ``http(s)://`` URL. That
    QThread worker has no automated coverage — manual smoke testing is the
    path, per ``tests/CLAUDE.md``).

These guard against a key bump or a revert silently breaking the shipped
Korean language. Mirrors ``test_german_activation.py`` / ``test_japanese_activation.py``,
with the sources.json assertion inverted since Korean is BYO-only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from utils.settings import AppSettings, SC_LANGUAGE_IDS  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_KO_UI = REPO / "languages" / "korean" / "ui.json"
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


def test_korean_ui_json_is_valid_ht_at_shape():
    data = json.loads(_KO_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Korean ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_korean_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_KO_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    # AI-only language: ht empty everywhere (needs-review marker), at non-empty
    # so nothing falls back to raw English in the UI.
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


def test_korean_covers_full_english_key_universe():
    en = {p for p, _ in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    ko = {p for p, _ in _leaves(json.loads(_KO_UI.read_text(encoding="utf-8")))}
    missing = sorted(en - ko)
    assert not missing, f"Korean is missing keys English already has: {missing[:10]}"
    # No extras either (outside tutorial.*, which is language-only by design —
    # English carries no tutorial section). A stray extra key usually means
    # ui.json was translated against a newer/different English snapshot than
    # this branch's actual key set.
    extra = sorted(p for p in (ko - en) if not p.startswith("tutorial."))
    assert not extra, f"Korean has keys English on this branch doesn't have: {extra[:10]}"


# extract.missing_categories_body's {noun} carries just the bare noun
# ("카테고리") in Korean — Korean doesn't inflect a noun's number after a
# numeral, so category_singular / category_plural are identical, and the
# "is/are missing" clause + {count} live directly in the body template
# instead of being folded into {noun} the way German/Italian do it. No
# token is dropped; same {count}/{noun} set as the English source.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_korean_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    ko = {p: leaf for p, leaf in _leaves(json.loads(_KO_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in ko:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        ko_tokens = set(_PLACEHOLDER.findall(ko[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - ko_tokens != allowed_drop or ko_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(ko_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_korean_translates_the_guided_tour():
    data = json.loads(_KO_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "Korean guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_korean_is_available_in_selector():
    assert "korean" in AppSettings.get_available_languages()


def test_korean_maps_to_south_korea_localization_id():
    assert SC_LANGUAGE_IDS["korean"] == "korean_(south_korea)"
    assert AppSettings.get_sc_language_id("korean") == "korean_(south_korea)"


def test_sources_json_has_no_korean_url():
    """#367: Korean is deliberately bring-your-own-file — the community
    source's license forbids redistribution, so there is no bundled URL to
    ship, unlike every other language in sources.json."""
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("korean", "") == ""


def test_korean_docs_exist():
    lang_dir = REPO / "languages" / "korean"
    for filename in ("HELP.md", "ABOUT.md", "LEGAL.md", "FAQ.md"):
        assert (lang_dir / filename).exists(), f"languages/korean/{filename} is missing"
