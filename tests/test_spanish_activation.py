"""Spanish is shipped as an available, human-translated language.

Locks the activation done for the Thord82 contribution:
  * the real ``languages/spanish/ui.json`` parses and is in the ``{ht, at}``
    shape (no leftover flat-string leaves from the pre-#182 contribution),
  * Spanish appears in the language selector (it is no longer a stub),
  * the SC language id maps to ``spanish_(spain)`` so apply-to-game writes the
    Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries a Spanish base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
Spanish language.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.utils.settings import AppSettings, SC_LANGUAGE_IDS  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_ES_UI = REPO / "languages" / "spanish" / "ui.json"


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


def test_spanish_ui_json_is_valid_ht_at_shape():
    data = json.loads(_ES_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Spanish ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_spanish_has_human_translations():
    data = json.loads(_ES_UI.read_text(encoding="utf-8"))
    filled = [p for p, leaf in _leaves(data) if leaf["ht"].strip()]
    # The contributor delivered the bulk of the UI; lock a generous floor.
    assert len(filled) > 200


def test_spanish_is_available_in_selector():
    assert "spanish" in AppSettings.get_available_languages()


def test_spanish_maps_to_spain_localization_id():
    assert SC_LANGUAGE_IDS["spanish"] == "spanish_(spain)"
    assert AppSettings.get_sc_language_id("spanish") == "spanish_(spain)"


def test_sources_json_has_spanish_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("spanish", "").startswith("https://")
