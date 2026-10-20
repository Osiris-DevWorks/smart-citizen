"""get_available_languages() hides untranslated stub languages.

A languages/<lang>/ui.json that exists but carries no translation keys (only
a `_comment`, like the Spanish placeholder) must not appear in the selector:
selecting it would render the whole UI in English and read as broken. English
(the base) is always offered, even if its own file were a stub.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _make_lang(root: Path, name: str, ui: dict) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "ui.json").write_text(json.dumps(ui), encoding="utf-8")


@pytest.fixture
def langs_root(tmp_path, monkeypatch):
    root = tmp_path / "languages"
    root.mkdir()
    monkeypatch.setattr(AppSettings, "get_languages_dir", staticmethod(lambda: root))
    return root


def test_untranslated_stub_is_hidden(langs_root):
    _make_lang(langs_root, "english", {"toolbar": {"apply": "Apply"}})
    _make_lang(langs_root, "french", {"toolbar": {"apply": "Appliquer"}})
    _make_lang(langs_root, "spanish", {"_comment": "TODO: translate"})  # stub

    avail = AppSettings.get_available_languages()
    assert "spanish" not in avail
    assert avail == ["english", "french"]


def test_english_always_offered_even_if_its_own_file_is_a_stub(langs_root):
    _make_lang(langs_root, "english", {"_comment": "base lives in code"})
    assert AppSettings.get_available_languages() == ["english"]


def test_missing_ui_json_is_hidden(langs_root):
    _make_lang(langs_root, "english", {"toolbar": {"apply": "Apply"}})
    (langs_root / "german").mkdir()  # folder with no ui.json at all

    avail = AppSettings.get_available_languages()
    assert "german" not in avail
    assert avail == ["english"]


def test_nested_only_comment_counts_as_empty(langs_root):
    _make_lang(langs_root, "english", {"toolbar": {"apply": "Apply"}})
    # A file with structure but no real strings (only comments) is still empty.
    _make_lang(langs_root, "italian", {"_comment": "wip", "toolbar": {"_comment": "wip"}})

    assert "italian" not in AppSettings.get_available_languages()
