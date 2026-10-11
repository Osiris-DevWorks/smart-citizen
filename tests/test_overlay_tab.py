"""Overlay tab: SCO switches persist, and the start button mirrors the overlay."""
import pytest

from src.gui.overlay_tab import OverlayTab
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def test_every_option_defaults_on(json_backend):
    assert all(AppSettings.get_sco_option(name) for name in AppSettings.SCO_OPTION_SETTING)


def test_a_checkbox_saves_its_option(qapp, json_backend, tmp_path):
    tab = OverlayTab(tmp_path / "samples")
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    assert set(tab._checks) == set(AppSettings.SCO_OPTION_SETTING)
    tab._checks["scan_decoder"].setChecked(False)
    assert AppSettings.get_sco_option("scan_decoder") is False
    assert AppSettings.get_sco_option("drawer") is True
    assert changed == [True]
    # A new tab reads the saved state back.
    assert not OverlayTab(tmp_path / "samples")._checks["scan_decoder"].isChecked()


def test_start_button_asks_and_set_running_only_mirrors(qapp, json_backend, tmp_path):
    tab = OverlayTab(tmp_path / "samples")
    asked = []
    tab.overlay_toggled.connect(asked.append)
    tab._start_btn.click()
    assert asked == [True]
    tab.set_running(False)   # e.g. the overlay refused to start
    assert asked == [True] and not tab._start_btn.isChecked()


def test_option_defaults_reach_settings_backups(json_backend):
    defaults = AppSettings.profile_default_values()
    for key, default in AppSettings.SCO_OPTION_SETTING.values():
        assert defaults[key] == default


def test_drawer_off_greys_out_its_sections(qapp, json_backend, tmp_path):
    tab = OverlayTab(tmp_path / "samples")
    sections = [n for n in tab._checks if n.startswith("drawer_")]
    assert sections and all(tab._checks[n].isEnabled() for n in sections)
    tab._checks["drawer"].setChecked(False)
    assert not any(tab._checks[n].isEnabled() for n in sections)
    assert all(AppSettings.get_sco_option(n) for n in sections)   # kept, just greyed out


def test_catalog_refresh_reads_only_changed_files(json_backend, tmp_path, monkeypatch):
    """MainWindow feeds the drawer from the English base.ini and the crafting
    index, and skips the re-read while neither file changed."""
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    base = tmp_path / "base.ini"
    base.write_text("Journal_General_Mining_Compendium_Content=Beryl - Yela\n", encoding="utf-8")
    monkeypatch.setattr(AppSettings, "get_base_ini_path", staticmethod(lambda language=None: base))
    monkeypatch.setattr(AppSettings, "get_enhancements_dir", staticmethod(lambda language=None: tmp_path))
    fed = []
    stub = SimpleNamespace(_sco_overlay=SimpleNamespace(
        drawer=SimpleNamespace(set_catalog=lambda m, c: fed.append(sorted(m)))))
    MainWindow._refresh_sco_catalog(stub)
    MainWindow._refresh_sco_catalog(stub)
    assert fed == [["Beryl"]]
    base.write_text("Journal_General_Mining_Compendium_Content=Gold - Yela\n", encoding="utf-8")
    import os
    os.utime(base, ns=(1, 1))
    MainWindow._refresh_sco_catalog(stub)
    assert fed == [["Beryl"], ["Gold"]]
