"""MainWindow._repair_foreign_owned_names: settings wiring + defensiveness.

The actual recovery decision (repair_foreign_owned_names in owned_items.py)
is Qt-free/settings-free and tested directly in
tests/test_foreign_editor_blueprint_names.py. This file covers only what that
pure function can't: the MainWindow method's own two responsibilities --
reading/writing AppSettings.owned_items correctly around it, and never
letting a failure inside the repair step escape as an exception, since it
runs unconditionally from _rebuild_blueprint_metadata on every load and a
load that already succeeded must not get reported as failed over an
ancillary cleanup step breaking (review follow-up on #372/PR #375).

Driven on a lightweight stand-in ``self`` (the real unbound method), not a
constructed MainWindow -- same reasoning and pattern as tests/test_ui_mode.py:
building the whole window pulls in the full startup pipeline and there's no
pytest-qt in dev deps to drive it safely.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PyQt6.QtCore import QSettings  # noqa: E402

from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


class _Stub:
    """Carries only what _repair_foreign_owned_names touches on self."""

    def __init__(self, known_item_names):
        self._known_item_names = known_item_names


def test_repairs_and_persists_using_known_item_names(isolated_settings):
    """The catalogue it reads from self must be _known_item_names -- the
    wide "every real item" set -- not the narrower Blueprint Tracker one,
    per the review finding this file exists to lock in."""
    from src.gui.main_window import MainWindow

    AppSettings.set_owned_items({"Cascade", "Ind/1/B Colossus"})
    stub = _Stub(known_item_names={"Cascade", "Colossus"})

    MainWindow._repair_foreign_owned_names(stub)

    assert AppSettings.get_owned_items() == {"Cascade", "Colossus"}


def test_uses_known_item_names_not_the_narrower_bp_item_names(isolated_settings):
    """The review finding this file exists for: the method must read
    self._known_item_names (the wide "every real item" set), not self.
    _bp_item_names (mission-reward-eligible names only). 'Fierell Cascade'
    stands in for a real, separately-owned item with no current mission
    reward -- present in a correctly-built _known_item_names (see
    test_foreign_editor_blueprint_names.py's known_item_names tests), absent
    from _bp_item_names. Reading the wrong attribute here would fold it into
    'Cascade' and drop it, exactly like the pre-fix incident."""
    from src.gui.main_window import MainWindow

    AppSettings.set_owned_items({"Cascade", "Fierell Cascade"})
    stub = _Stub(known_item_names={"Cascade", "Fierell Cascade"})

    MainWindow._repair_foreign_owned_names(stub)

    assert AppSettings.get_owned_items() == {"Cascade", "Fierell Cascade"}


def test_empty_catalogue_is_a_noop_and_writes_nothing(isolated_settings, monkeypatch):
    from src.gui.main_window import MainWindow

    AppSettings.set_owned_items({"Ind/1/B Colossus"})
    calls = []
    monkeypatch.setattr(AppSettings, "set_owned_items", lambda names: calls.append(names))
    stub = _Stub(known_item_names=set())

    MainWindow._repair_foreign_owned_names(stub)

    assert calls == []


def test_already_clean_owned_set_writes_nothing(isolated_settings, monkeypatch):
    """No repair needed -> no settings write, so a normal load costs one set
    comparison, not a redundant persist on every launch."""
    from src.gui.main_window import MainWindow

    AppSettings.set_owned_items({"Colossus"})
    calls = []
    monkeypatch.setattr(AppSettings, "set_owned_items", lambda names: calls.append(names))
    stub = _Stub(known_item_names={"Colossus"})

    MainWindow._repair_foreign_owned_names(stub)

    assert calls == []


def test_a_failure_in_the_repair_step_does_not_propagate(isolated_settings, monkeypatch):
    """If repair_foreign_owned_names ever raises, the exception must stop
    here -- not bubble up into perform_merge_and_reload's caller, which would
    misreport an already-successful load as a merge failure."""
    from src.gui.main_window import MainWindow
    import src.utils.owned_items as owned_items

    AppSettings.set_owned_items({"Ind/1/B Colossus"})

    def _boom(owned, catalogue):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(owned_items, "repair_foreign_owned_names", _boom)
    stub = _Stub(known_item_names={"Colossus"})

    MainWindow._repair_foreign_owned_names(stub)  # must not raise

    # Untouched: the failed repair must not have partially written anything.
    assert AppSettings.get_owned_items() == {"Ind/1/B Colossus"}


def test_a_failure_is_logged(isolated_settings, monkeypatch, caplog):
    import logging

    from src.gui.main_window import MainWindow
    import src.utils.owned_items as owned_items

    AppSettings.set_owned_items({"Ind/1/B Colossus"})
    monkeypatch.setattr(
        owned_items, "repair_foreign_owned_names",
        lambda owned, catalogue: (_ for _ in ()).throw(RuntimeError("simulated")),
    )
    stub = _Stub(known_item_names={"Colossus"})

    with caplog.at_level(logging.ERROR, logger="src.gui.main_window"):
        MainWindow._repair_foreign_owned_names(stub)

    assert any("repair failed" in rec.message.lower() for rec in caplog.records)
