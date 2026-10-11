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
    assert AppSettings.get_sco_option("blueprint_drawer") is True
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
