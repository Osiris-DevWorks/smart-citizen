"""The guided tour is the same in every language: each translated
``tutorial.*`` section has the steps of ``assets/tutorial.json`` in the same
order and with the same step numbers, and the Config tab's Settings Backup
and Star Citizen Tools boxes have steps of their own."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent
_NUMBER = re.compile(r"^(\d+)\.\s")


def _english_steps() -> list[dict]:
    return json.loads((ROOT / "assets" / "tutorial.json").read_text(encoding="utf-8"))["steps"]


def _translated_languages() -> list[str]:
    return sorted(
        path.parent.name for path in (ROOT / "languages").glob("*/ui.json")
        if "tutorial" in json.loads(path.read_text(encoding="utf-8"))
    )


def _number(title: str):
    match = _NUMBER.match(title)
    return int(match[1]) if match else None


def test_some_languages_translate_the_tour():
    assert len(_translated_languages()) >= 10


@pytest.mark.parametrize("language", _translated_languages())
def test_a_translated_tour_matches_the_english_one(language):
    english = _english_steps()
    tour = json.loads((ROOT / "languages" / language / "ui.json")
                      .read_text(encoding="utf-8"))["tutorial"]
    assert list(tour) == [step["id"] for step in english]
    for step in english:
        title = tour[step["id"]]["title"]["at"]
        assert _number(title) == _number(step["title"]), (step["id"], title)


def test_the_tour_covers_settings_backup_and_star_citizen_tools():
    from src.gui.main_window import MainWindow

    ids = [step["id"] for step in _english_steps()]
    assert ids[ids.index("cfg_tools") + 1:ids.index("cfg_tools") + 3] == [
        "cfg_backup", "cfg_sc_tools"]
    backup, sc_tools = object(), object()
    stub = SimpleNamespace(config_tab=SimpleNamespace(_backup_group=backup,
                                                      _sc_tools_group=sc_tools))
    wiring = MainWindow._tutorial_step_wiring(stub)
    assert wiring["cfg_backup"]["target"]() is backup
    assert wiring["cfg_sc_tools"]["target"]() is sc_tools
