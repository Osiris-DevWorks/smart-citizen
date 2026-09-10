"""Turkish is shipped as an available, AI-translated language (#404).

Locks the activation done for the Turkish language addition:
  * the real ``languages/turkish/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Turkish ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the Turkish
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * Turkish appears in the language selector (it is not a stub),
  * the SC language id maps to ``polish_(poland)`` — a BORROWED slot, see
    ``test_turkish_borrows_the_polish_localization_slot`` — so apply-to-game
    writes the Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries a Turkish base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
Turkish language. Mirrors ``test_german_activation.py``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from utils.settings import AppSettings, SC_LANGUAGE_IDS  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_TR_UI = REPO / "languages" / "turkish" / "ui.json"
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


def test_turkish_ui_json_is_valid_ht_at_shape():
    data = json.loads(_TR_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Turkish ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_turkish_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_TR_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    # AI-only language: ht empty everywhere (needs-review marker), at non-empty
    # so nothing falls back to raw English in the UI.
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


def test_turkish_covers_full_english_key_universe():
    en = {p for p, _ in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    tr = {p for p, _ in _leaves(json.loads(_TR_UI.read_text(encoding="utf-8")))}
    missing = sorted(en - tr)
    assert not missing, f"Turkish is missing keys English already has: {missing[:10]}"
    # No extras either (outside tutorial.*, which is language-only by design —
    # English carries no tutorial section). A stray extra key usually means
    # ui.json was translated against a newer/different English snapshot than
    # this branch's actual key set.
    extra = sorted(p for p in (tr - en) if not p.startswith("tutorial."))
    assert not extra, f"Turkish has keys English on this branch doesn't have: {extra[:10]}"


# dialogs.suppressed_errors_suffix's {plural} is deliberately dropped: Turkish
# pluralizes with a vowel-harmony suffix ("hata" / "hatalar") and never after
# a numeral ("3 hata"), so a generic {plural} token has no correct value to
# hold. German, Spanish and Portuguese make the same call for this key
# (str.format ignores unused kwargs, so a dropped placeholder in the string is
# harmless) — see TRANSLATIONS.md's backfill-log precedent.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_turkish_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    tr = {p: leaf for p, leaf in _leaves(json.loads(_TR_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in tr:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        tr_tokens = set(_PLACEHOLDER.findall(tr[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - tr_tokens != allowed_drop or tr_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(tr_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_turkish_translates_the_guided_tour():
    data = json.loads(_TR_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "Turkish guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_turkish_is_available_in_selector():
    assert "turkish" in AppSettings.get_available_languages()


def test_turkish_borrows_the_polish_localization_slot():
    """Turkish maps to ``polish_(poland)``, NOT ``turkish_(turkey)``.

    ``turkish_(turkey)`` is not a ``g_language`` value the game accepts, so
    Turkish has to ride on another official slot. Polish is the host: it is
    unclaimed by our own languages, and Polish needs the same Latin Extended-A
    block Turkish does (ł ą ę ż ź ć ń ś vs ğ ı İ ş), so the game font already
    draws our glyphs. Dymerz's guide borrows ``german_(germany)`` instead,
    which would collide with our own German language — both would write the
    same ``Localization\\german_(germany)\\global.ini``. ``russian_(russia)``
    was the first choice and was rejected: the game does not recognise it. Do
    not "fix" this mapping to a Turkish-looking id (#404).
    """
    assert SC_LANGUAGE_IDS["turkish"] == "polish_(poland)"
    assert AppSettings.get_sc_language_id("turkish") == "polish_(poland)"
    # The borrowed slot must not be shared with any other shipped language.
    owners = [lang for lang, sc_id in SC_LANGUAGE_IDS.items() if sc_id == "polish_(poland)"]
    assert owners == ["turkish"], f"polish_(poland) slot is shared: {owners}"
    # Regression: the game does not recognise russian_(russia) (#404).
    assert "russian_(russia)" not in SC_LANGUAGE_IDS.values()


def test_turkish_user_cfg_gets_the_polish_g_language(tmp_path):
    """Apply-time user.cfg write uses the borrowed slot, not a Turkish id."""
    from src.utils.user_cfg import ensure_user_cfg_language

    with patch("src.utils.user_cfg.AppSettings") as mock_settings:
        mock_settings.get_game_install_path.return_value = str(tmp_path)
        mock_settings.get_active_channel.return_value = "LIVE"
        mock_settings.get_selected_language.return_value = "turkish"
        mock_settings.get_sc_language_id.side_effect = AppSettings.get_sc_language_id
        (tmp_path / "user.cfg").write_text("r_VSync = 1\n", encoding="utf-8")
        assert ensure_user_cfg_language(language="turkish") is True

    content = (tmp_path / "user.cfg").read_text(encoding="utf-8")
    assert "g_language = polish_(poland)" in content
    assert "turkish" not in content


def test_sources_json_has_turkish_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    url = sources.get("turkish", "")
    assert url.startswith("https://")
    assert "turkish_(turkey)" in url, "the Dymerz Turkish pack lives under turkish_(turkey)"


def test_turkish_docs_exist():
    lang_dir = REPO / "languages" / "turkish"
    for filename in ("HELP.md", "ABOUT.md", "LEGAL.md", "FAQ.md"):
        assert (lang_dir / filename).exists(), f"languages/turkish/{filename} is missing"
