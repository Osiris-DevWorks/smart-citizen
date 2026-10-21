"""Russian is shipped as an available, AI-translated language.

Locks the activation done for the Russian language addition:
  * the real ``languages/russian/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Russian ships AI-only: every leaf has an empty ``ht`` (no human
    translator yet) and a non-empty ``at`` — so every key is flagged for a
    future human pass while nothing renders as raw English,
  * every ``{placeholder}`` in the English source survives into the Russian
    ``at`` (a dropped/renamed token would crash ``str.format`` at runtime),
  * the guided tour (``tutorial.*``) is translated,
  * Russian appears in the language selector (it is not a stub),
  * the SC language id maps to ``korean_(south_korea)`` — a BORROWED slot,
    shared with Korean (see ``test_russian_borrows_the_korean_slot``),
  * ``languages/sources.json`` carries a Russian base.ini URL,
  * ``user.cfg`` gets the right ``g_language`` whichever of Russian, Korean
    or English is picked, in any order, since the two share a slot.

Mirrors ``test_turkish_activation.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.settings import AppSettings, SC_LANGUAGE_IDS
from src.utils.user_cfg import ensure_user_cfg_language

REPO = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_RU_UI = REPO / "languages" / "russian" / "ui.json"
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


def test_russian_ui_json_is_valid_ht_at_shape():
    data = json.loads(_RU_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Russian ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_russian_is_ai_only_every_leaf_at_filled_ht_empty():
    data = json.loads(_RU_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    bad_ht = [p for p, leaf in leaves if leaf["ht"].strip()]
    empty_at = [p for p, leaf in leaves if not leaf["at"].strip()]
    assert not bad_ht, f"AI-only language should have empty ht: {bad_ht[:5]}"
    assert not empty_at, f"AI language should have every at filled: {empty_at[:5]}"
    assert len(leaves) > 300


def test_russian_covers_full_english_key_universe():
    en = {p for p, _ in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    ru = {p for p, _ in _leaves(json.loads(_RU_UI.read_text(encoding="utf-8")))}
    missing = sorted(en - ru)
    assert not missing, f"Russian is missing keys English already has: {missing[:10]}"
    extra = sorted(p for p in (ru - en) if not p.startswith("tutorial."))
    assert not extra, f"Russian has keys English on this branch doesn't have: {extra[:10]}"


# Russian may drop {plural} like Turkish/German/Spanish/Portuguese do —
# Russian pluralizes with full word forms, not a suffix token.
_ALLOWED_PLACEHOLDER_DROPS = {
    "dialogs.suppressed_errors_suffix": {"{plural}"},
}


def test_russian_placeholders_match_english_source():
    en = {p: leaf for p, leaf in _leaves(json.loads(_EN_UI.read_text(encoding="utf-8")))}
    ru = {p: leaf for p, leaf in _leaves(json.loads(_RU_UI.read_text(encoding="utf-8")))}
    mismatches = []
    for path, en_leaf in en.items():
        if path not in ru:
            continue
        en_tokens = set(_PLACEHOLDER.findall(en_leaf.get("ht", "")))
        ru_tokens = set(_PLACEHOLDER.findall(ru[path].get("at", "")))
        allowed_drop = _ALLOWED_PLACEHOLDER_DROPS.get(path, set())
        if en_tokens - ru_tokens != allowed_drop or ru_tokens - en_tokens:
            mismatches.append((path, sorted(en_tokens), sorted(ru_tokens)))
    assert not mismatches, f"placeholder drift: {mismatches[:5]}"


def test_russian_translates_the_guided_tour():
    data = json.loads(_RU_UI.read_text(encoding="utf-8"))
    tour = data.get("tutorial", {})
    assert len(tour) >= 19, "Russian guided tour is missing steps"
    for step_id, step in tour.items():
        assert step["title"]["at"].strip(), f"tutorial.{step_id}.title not translated"
        assert step["description"]["at"].strip(), f"tutorial.{step_id}.description not translated"


def test_russian_is_available_in_selector():
    assert "russian" in AppSettings.get_available_languages()


def test_russian_borrows_the_korean_slot():
    """Russian maps to ``korean_(south_korea)``, NOT ``russian_(russia)``.

    ``russian_(russia)`` is not a ``g_language`` value the game accepts, and
    the Korean font is the only in-game font that covers Cyrillic — so all
    Slavic-language community translations ride the Korean slot deliberately.
    Only one of Russian or Korean can be applied at a time — switching
    overwrites the other's global.ini.
    """
    assert SC_LANGUAGE_IDS["russian"] == "korean_(south_korea)"
    assert AppSettings.get_sc_language_id("russian") == "korean_(south_korea)"
    # The slot is shared with Korean — this is expected.
    owners = sorted(
        lang for lang, sc_id in SC_LANGUAGE_IDS.items()
        if sc_id == "korean_(south_korea)"
    )
    assert "korean" in owners
    assert "russian" in owners
    # The game does not recognise russian_(russia) as a g_language value.
    assert "russian_(russia)" not in SC_LANGUAGE_IDS.values()


def _g_language_lines(cfg_text):
    return [ln for ln in cfg_text.splitlines() if ln.strip().lower().startswith("g_language")]


@pytest.fixture
def user_cfg_install(tmp_path):
    """user.cfg in a tmp install, with the selected language settable."""
    with patch("src.utils.user_cfg.AppSettings") as mock_settings:
        mock_settings.get_game_install_path.return_value = str(tmp_path)
        mock_settings.get_active_channel.return_value = "LIVE"
        mock_settings.get_sc_language_id.side_effect = AppSettings.get_sc_language_id
        yield mock_settings, tmp_path / "user.cfg"


def test_russian_user_cfg_gets_the_korean_g_language(user_cfg_install):
    """Apply-time user.cfg write uses the borrowed slot, following the stored
    choice as window start does (no language passed)."""
    settings, cfg = user_cfg_install
    settings.get_selected_language.return_value = "russian"
    cfg.write_text("g_language = english\n", encoding="utf-8")
    assert ensure_user_cfg_language() is True
    lines = _g_language_lines(cfg.read_text(encoding="utf-8"))
    assert lines == ["g_language = korean_(south_korea)"]


@pytest.mark.parametrize("order", [
    ["english", "russian", "korean", "english"],
    ["english", "korean", "russian", "korean", "english"],
])
def test_one_user_cfg_through_english_russian_and_korean(user_cfg_install, order):
    """Russian and Korean share a slot (approved on condition that user.cfg is
    always right). Walking one user.cfg through every switch leaves exactly
    one g_language line with the right value each time, and the user's other
    settings are kept."""
    settings, cfg = user_cfg_install
    cfg.write_text("r_VSync = 1\nsys_MaxFPS = 144\n", encoding="utf-8")
    for language in order:
        settings.get_selected_language.return_value = language
        assert ensure_user_cfg_language() is True
        text = cfg.read_text(encoding="utf-8")
        expected = "english" if language == "english" else "korean_(south_korea)"
        assert _g_language_lines(text) == [f"g_language = {expected}"], (language, text)
        assert "r_VSync = 1" in text and "sys_MaxFPS = 144" in text, (language, text)


def test_russian_sources_json_has_url():
    sources = json.loads(
        (REPO / "languages" / "sources.json").read_text(encoding="utf-8")
    )
    url = sources.get("russian", "")
    assert url, "Russian has no source URL in sources.json"
    assert url.startswith("https://"), f"Russian source URL looks wrong: {url}"
    assert "korean_(south_korea)" in url, "the n1ghter Russian pack lives under korean_(south_korea)"


def test_russian_docs_exist():
    """HELP, ABOUT, LEGAL, and FAQ docs must be present."""
    lang_dir = REPO / "languages" / "russian"
    for name in ("HELP.md", "ABOUT.md", "LEGAL.md", "FAQ.md"):
        p = lang_dir / name
        assert p.exists(), f"Missing {name}"
        assert len(p.read_text(encoding="utf-8")) > 100, f"{name} looks too short"
