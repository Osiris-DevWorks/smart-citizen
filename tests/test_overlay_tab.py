"""Overlay tab: SCO switches persist, and the start button mirrors the overlay."""
import pytest
from PyQt6.QtCore import Qt

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


def test_options_default_on_but_three_alerts(json_backend):
    # #523's alerts: the glow (the one there was) and the flash start on.
    off = {"alert_color", "alert_bigger", "alert_sound"}
    for name in AppSettings.SCO_OPTION_SETTING:
        assert AppSettings.get_sco_option(name) is (name not in off), name


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


def test_refresh_styles_follows_a_theme_swap(qapp, json_backend, tmp_path, monkeypatch):
    tab = OverlayTab(tmp_path / "samples")
    monkeypatch.setattr("src.gui.overlay_tab.get_button_color", lambda role: "#123456")
    assert "#123456" not in tab._start_btn.styleSheet()
    tab.refresh_styles()
    assert "background-color: #123456" in tab._start_btn.styleSheet()


def test_position_picker_is_a_no_scroll_combo(qapp, json_backend, tmp_path):
    from src.gui.combo_box import NoScrollComboBox
    assert isinstance(OverlayTab(tmp_path / "samples")._position_combo, NoScrollComboBox)


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
    monkeypatch.setattr(AppSettings, "get_enhancements_dir",
                        staticmethod(lambda language=None: tmp_path))
    fed = []
    stub = SimpleNamespace(_sco_catalog_key=None, _sco_overlay=SimpleNamespace(
        drawer=SimpleNamespace(set_catalog=lambda m, c: fed.append(sorted(m)))))
    MainWindow._refresh_sco_catalog(stub)
    MainWindow._refresh_sco_catalog(stub)
    assert fed == [["Beryl"]]
    base.write_text("Journal_General_Mining_Compendium_Content=Gold - Yela\n", encoding="utf-8")
    import os
    os.utime(base, ns=(1, 1))
    MainWindow._refresh_sco_catalog(stub)
    assert fed == [["Beryl"], ["Gold"]]


def test_tour_has_an_overlay_step_on_the_start_button():
    """The guided tour covers the Overlay: tutorial.json lists the step,
    numbered in order, and MainWindow wires it to the tab's start button."""
    import json
    import re
    from pathlib import Path
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    steps = json.loads((Path(__file__).parent.parent / "assets" / "tutorial.json")
                       .read_text(encoding="utf-8"))["steps"]
    ids = [s["id"] for s in steps]
    assert ids.index("overlay") == ids.index("blueprint_tracker") + 1
    numbers = [int(re.match(r"(\d+)\.", s["title"])[1]) for s in steps[1:]]
    assert numbers == list(range(1, len(steps)))
    start_btn = object()
    stub = SimpleNamespace(overlay_tab=SimpleNamespace(_start_btn=start_btn))
    wiring = MainWindow._tutorial_step_wiring(stub)
    assert set(ids) <= set(wiring)
    assert wiring["overlay"]["target"]() is start_btn


def test_drawer_position_picker(qapp, json_backend, tmp_path):
    assert AppSettings.get_sco_drawer_position() == "middle_right"
    tab = OverlayTab(tmp_path / "samples")
    combo = tab._position_combo
    assert combo.count() == len(AppSettings.SCO_DRAWER_POSITIONS) == 8
    assert combo.currentData() == "middle_right"
    assert combo.currentText() == "Middle right"
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    combo.setCurrentIndex(AppSettings.SCO_DRAWER_POSITIONS.index("bottom_center"))
    assert AppSettings.get_sco_drawer_position() == "bottom_center" and changed == [True]
    assert OverlayTab(tmp_path / "samples")._position_combo.currentData() == "bottom_center"
    tab._checks["drawer"].setChecked(False)
    assert not combo.isEnabled()


def test_bad_stored_position_reads_as_default(json_backend):
    json_backend.setValue(AppSettings.SCO_DRAWER_POSITION, "middle_center")
    assert AppSettings.get_sco_drawer_position() == "middle_right"


def test_set_option_mirrors_without_saving_or_emitting(qapp, json_backend, tmp_path):
    tab = OverlayTab(tmp_path / "samples")
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    tab.set_option("scan_decoder", False)   # the drawer's switch already saved it
    assert not tab._checks["scan_decoder"].isChecked()
    assert changed == [] and AppSettings.get_sco_option("scan_decoder") is True


def test_watched_minerals_round_trip(json_backend):
    assert AppSettings.get_sco_watched_minerals() == set()
    AppSettings.set_sco_watched_minerals({"iron", "beryl"})
    assert AppSettings.get_sco_watched_minerals() == {"iron", "beryl"}
    json_backend.setValue(AppSettings.SCO_WATCHED_MINERALS, "not json")
    assert AppSettings.get_sco_watched_minerals() == set()
    assert AppSettings.profile_default_values()[AppSettings.SCO_WATCHED_MINERALS] == "[]"


def test_drawer_scan_decoder_switch_saves_and_mirrors(qapp, json_backend, tmp_path):
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    tab = OverlayTab(tmp_path / "samples")
    applied = []
    stub = SimpleNamespace(overlay_tab=tab, _apply_sco_options=lambda: applied.append(True))
    MainWindow._on_sco_scan_decoder_toggled(stub, False)
    assert AppSettings.get_sco_option("scan_decoder") is False
    assert not tab._checks["scan_decoder"].isChecked() and applied == [True]


class _RecordedWorker:
    started = []

    def __init__(self, log_path, since):
        self.log_path, self.since = log_path, since
        self.blueprints_found = self

    def connect(self, _slot):
        pass

    def start(self):
        _RecordedWorker.started.append(self)


@pytest.mark.parametrize("channel, watched", [
    ("LIVE", True), ("HOTFIX", True), ("PTU", False), ("EPTU", False), ("TECH-PREVIEW", False),
])
def test_live_watch_only_on_scanned_channels(json_backend, tmp_path, monkeypatch, channel, watched):
    """#446: the owned set is shared, so test-server blueprints never reach it."""
    from types import SimpleNamespace

    from src.gui import main_window
    (tmp_path / channel).mkdir()
    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: channel))
    monkeypatch.setattr(AppSettings, "get_channel_install_path",
                        staticmethod(lambda: str(tmp_path / channel)))
    monkeypatch.setattr(main_window, "LiveBlueprintLogWorker", _RecordedWorker)
    _RecordedWorker.started = []
    me = SimpleNamespace(_sco_log_worker=None, _on_sco_blueprints_found=lambda *a: None)
    main_window.MainWindow._start_sco_log_watcher(me)
    assert bool(_RecordedWorker.started) is watched
    assert (me._sco_log_worker is not None) is watched


def test_live_watch_survives_an_unreadable_install_path(json_backend, monkeypatch):
    """Python 3.11's Path.is_dir re-raises access denied; that must not crash."""
    from pathlib import Path
    from types import SimpleNamespace

    from src.gui import main_window

    def denied(self):
        raise PermissionError("denied")

    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))
    monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: "X:/LIVE"))
    monkeypatch.setattr(Path, "is_dir", denied)
    me = SimpleNamespace(_sco_log_worker=None)
    main_window.MainWindow._start_sco_log_watcher(me)
    assert me._sco_log_worker is None


def test_live_watch_leaves_the_scan_watermark_alone(json_backend, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from src.gui import main_window
    me = SimpleNamespace(
        _owned_names_from_log=lambda raw: set(raw), _recompute_owned=lambda: None,
        _sco_overlay=None,
    )
    newest = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    main_window.MainWindow._on_sco_blueprints_found(me, ["Agni"], newest)
    assert "Agni" in AppSettings.get_owned_items()
    for channel in ("LIVE", "HOTFIX", "PTU"):
        assert AppSettings.get_blueprint_log_watermark(channel=channel) is None


def test_alerts_and_text_size_hang_under_the_scan_decoder(qapp, json_backend, tmp_path):
    """#523: the alerts and the text size are the scan label's, so they sit
    indented under its switch and grey out with it, kept as they were."""
    tab = OverlayTab(tmp_path / "samples")
    alerts = [n for n in tab._checks if n.startswith("alert_")]
    assert alerts == ["alert_glow", "alert_flash", "alert_color", "alert_bigger", "alert_sound"]
    assert tab._checks["alert_glow"].text() == "Glow"
    assert tab._alerts_title.text() == "When a watched mineral or salvage is scanned:"
    assert all(tab._checks[n].isEnabled() for n in alerts) and tab._size_combo.isEnabled()
    tab._checks["scan_decoder"].setChecked(False)
    assert not any(tab._checks[n].isEnabled() for n in alerts)
    assert not tab._size_combo.isEnabled() and not tab._alerts_title.isEnabled()
    assert tab._hotkey_edit.isEnabled()                       # the drawer's, not the decoder's
    assert AppSettings.get_sco_option("alert_glow") is True   # kept, just greyed out
    tab._checks["drawer"].setChecked(False)
    assert not tab._hotkey_edit.isEnabled() and not tab._position_combo.isEnabled()


def test_scan_text_size_picker(qapp, json_backend, tmp_path):
    from src.gui.combo_box import NoScrollComboBox

    assert AppSettings.get_sco_label_size() == "medium"
    tab = OverlayTab(tmp_path / "samples")
    combo = tab._size_combo
    assert isinstance(combo, NoScrollComboBox)
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Small", "Medium", "Large", "Extra large"]
    assert combo.currentData() == "medium"
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    combo.setCurrentIndex(AppSettings.SCO_LABEL_SIZES.index("large"))
    assert AppSettings.get_sco_label_size() == "large" and changed == [True]
    assert OverlayTab(tmp_path / "samples")._size_combo.currentData() == "large"
    json_backend.setValue(AppSettings.SCO_LABEL_SIZE, "huge")
    assert AppSettings.get_sco_label_size() == "medium"


def test_text_size_and_hotkey_reach_settings_backups(json_backend):
    defaults = AppSettings.profile_default_values()
    assert defaults[AppSettings.SCO_LABEL_SIZE] == "medium"
    assert defaults[AppSettings.SCO_DRAWER_HOTKEY] == ""


CTRL, ALT, SHIFT = (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier,
                    Qt.KeyboardModifier.ShiftModifier)


def _press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier, virtual_key=0,
           release=True):
    """A key press as Windows delivers it: Qt's key (the character the layout
    makes), the modifiers held and the virtual key, then its release."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)[:2 if release else 1]:
        QApplication.sendEvent(widget, QKeyEvent(kind, key, modifiers, 0, virtual_key, 0, ""))


def test_hotkey_box_takes_combinations_and_refuses_others(qapp, json_backend, tmp_path):
    tab = OverlayTab(tmp_path / "samples")
    edit = tab._hotkey_edit
    assert edit.sequence() == "" and AppSettings.get_sco_drawer_hotkey() == ""
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    # #523: where Ctrl+Alt is AltGr, Ctrl+Alt+O makes "ó", which the old box
    # took for the key and refused. The virtual key says O.
    _press(edit, Qt.Key.Key_Oacute, CTRL | ALT, 0x4F)
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+Alt+O" and changed == [True]
    assert edit.text() == "Ctrl+Alt+O" and tab._hotkey_problem.isHidden()
    _press(edit, Qt.Key.Key_Exclam, CTRL | SHIFT, 0x31)        # Shift+1 makes "!"
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+Shift+1"
    # A key Windows has no hotkey code for is not saved; the box goes back.
    _press(edit, Qt.Key.Key_Escape, CTRL, 0x1B)
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+Shift+1" and len(changed) == 2
    assert edit.text() == "Ctrl+Shift+1" and not tab._hotkey_problem.isHidden()
    assert tab._hotkey_problem.text().startswith("This cannot be a hotkey.")
    tab._hotkey_clear.click()                                  # the Clear button
    assert AppSettings.get_sco_drawer_hotkey() == "" and len(changed) == 3
    assert edit.text() == "" and tab._hotkey_problem.isHidden()
    assert OverlayTab(tmp_path / "samples")._hotkey_edit.sequence() == ""
    _press(edit, Qt.Key.Key_F9, virtual_key=0x78)
    assert OverlayTab(tmp_path / "samples")._hotkey_edit.text() == "F9"


def test_the_clear_button_sits_beside_the_box_and_only_when_there_is_a_hotkey(
        qapp, json_backend, tmp_path):
    """#523: every key pressed in the box is taken as the hotkey, so a Clear
    button to its right is how a hotkey is removed. It is lit only with a
    hotkey saved and the drawer on."""
    tab = OverlayTab(tmp_path / "samples")
    edit, clear = tab._hotkey_edit, tab._hotkey_clear
    assert clear.text() == "Clear" and not edit.isClearButtonEnabled()
    assert not clear.isEnabled()                                # nothing to clear
    _press(edit, Qt.Key.Key_O, CTRL | ALT, 0x4F)
    assert clear.isEnabled()
    tab.resize(900, 900)
    tab.show()
    qapp.processEvents()
    box, button = edit.geometry(), clear.geometry()
    assert edit.parent() is clear.parent() and button.left() >= box.right()
    assert abs(button.center().y() - box.center().y()) <= 2     # on the same line
    tab.hide()
    tab._checks["drawer"].setChecked(False)
    assert not clear.isEnabled()                                # greyed with the drawer
    tab._checks["drawer"].setChecked(True)
    clear.click()
    assert AppSettings.get_sco_drawer_hotkey() == "" and not clear.isEnabled()
    assert OverlayTab(tmp_path / "samples")._hotkey_clear.isEnabled() is False
    AppSettings.set_sco_drawer_hotkey("F9")
    assert OverlayTab(tmp_path / "samples")._hotkey_clear.isEnabled()   # a saved one


def test_hotkey_box_shows_held_modifiers_and_takes_every_key(qapp, json_backend, tmp_path):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    edit = OverlayTab(tmp_path / "samples")._hotkey_edit
    _press(edit, Qt.Key.Key_Control, CTRL, 0x11, release=False)
    _press(edit, Qt.Key.Key_Alt, CTRL | ALT, 0x12, release=False)
    assert edit.text() == "Ctrl+Alt+" and edit.sequence() == ""   # more keys can follow
    for key in (Qt.Key.Key_Alt, Qt.Key.Key_Control):
        QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyRelease, key,
                                               Qt.KeyboardModifier.NoModifier, 0, 0, 0, ""))
    assert edit.text() == ""                                   # let go: nothing recorded
    # Tab is a key here, not a focus move: alone it is refused (it needs
    # Ctrl, Alt or Win), with Ctrl it is recorded, and the box keeps the
    # focus both times. No app shortcut takes a key first.
    tab = edit.window()
    tab.show()
    edit.setFocus()
    qapp.processEvents()
    _press(edit, Qt.Key.Key_Tab, virtual_key=0x09)
    assert edit.sequence() == "" and edit.hasFocus() and not tab._hotkey_problem.isHidden()
    _press(edit, Qt.Key.Key_Tab, CTRL, 0x09)
    assert edit.sequence() == "Ctrl+Tab" and edit.hasFocus()
    tab.hide()
    override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S, CTRL, 0, 0x53, 0, "")
    QApplication.sendEvent(edit, override)
    assert override.isAccepted()
    # Nothing can be typed: a plain letter is refused, not text, and the box
    # goes back to the saved combination. An F key can stand alone.
    _press(edit, Qt.Key.Key_P, virtual_key=0x50)
    assert edit.sequence() == "Ctrl+Tab" and edit.text() == "Ctrl+Tab"
    _press(edit, Qt.Key.Key_F9, virtual_key=0x78)
    assert edit.sequence() == "F9"


def test_hotkey_box_takes_a_symbol_key(qapp, json_backend, tmp_path, monkeypatch):
    """#523: Ctrl+/ is saved by the symbol its key types on the player's
    layout (looked up through Windows, stood in for here)."""
    from src.gui import global_hotkey

    monkeypatch.setattr(global_hotkey, "layout_symbol", {0xBF: "/"}.get)
    monkeypatch.setattr(global_hotkey, "layout_symbol_key", {"/": 0xBF}.get)
    tab = OverlayTab(tmp_path / "samples")
    _press(tab._hotkey_edit, Qt.Key.Key_Slash, CTRL, 0xBF)
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+/" and tab._hotkey_problem.isHidden()
    _press(tab._hotkey_edit, Qt.Key.Key_Slash, virtual_key=0xBF)   # alone: refused
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+/" and not tab._hotkey_problem.isHidden()


def test_hotkey_box_without_a_virtual_key_uses_qt_key(qapp, json_backend, tmp_path):
    """A press with no Windows key (another platform, or sent by code) still
    records the keys Qt names."""
    edit = OverlayTab(tmp_path / "samples")._hotkey_edit
    _press(edit, Qt.Key.Key_O, CTRL | ALT)
    assert edit.sequence() == "Ctrl+Alt+O"
    _press(edit, Qt.Key.Key_Oacute, CTRL | ALT)                # no key to fall back on
    assert edit.sequence() == "Ctrl+Alt+O"


def test_options_sit_in_titled_boxes_with_rows_of_switches(qapp, json_backend, tmp_path):
    """#523: one box per part, and the alerts and drawer sections side by
    side with their help as tooltips."""
    from PyQt6.QtWidgets import QGroupBox

    tab = OverlayTab(tmp_path / "samples")
    boxes = tab.findChildren(QGroupBox)
    assert [b.title() for b in boxes] == [
        "Scan decoder", "Drawer", "Blueprints from Game.log", "Scan samples"]
    home = {"scan_decoder": 0, "drawer": 1, "live_blueprint_watch": 2, "save_samples": 3}
    for name, check in tab._checks.items():
        index = home.get(name, 0 if name.startswith("alert_") else 1)
        assert boxes[index].isAncestorOf(check), name
    assert tab._size_combo.parent() is not None and boxes[0].isAncestorOf(tab._size_combo)
    for widget in (tab._position_combo, tab._hotkey_edit):
        assert boxes[1].isAncestorOf(widget)
    assert boxes[3].isAncestorOf(tab._open_samples_btn)
    for prefix in ("alert_", "drawer_"):
        row = [tab._checks[n] for n in tab._checks if n.startswith(prefix)]
        tab.resize(1000, 900)
        tab.show()
        qapp.processEvents()
        assert len({c.mapTo(tab, c.rect().topLeft()).y() for c in row}) == 1, prefix
        assert all(c.toolTip() for c in row) and not any(n in tab._hints for n in tab._checks
                                                         if n.startswith(prefix))
    tab.hide()


def test_a_refused_hotkey_shows_on_the_tab_and_the_status_bar(qapp, json_backend, tmp_path):
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    tab = OverlayTab(tmp_path / "samples")
    shown = []
    stub = SimpleNamespace(overlay_tab=tab,
                           statusBar=lambda: SimpleNamespace(showMessage=shown.append))
    MainWindow._on_sco_hotkey_problem(stub, "taken")
    assert not tab._hotkey_problem.isHidden()
    assert tab._hotkey_problem.text().startswith("Windows refused this hotkey.")
    assert shown == [tab._hotkey_problem.text()]
    MainWindow._on_sco_hotkey_problem(stub, "")
    assert tab._hotkey_problem.isHidden() and len(shown) == 1


def test_apply_options_hands_the_overlay_its_size_and_hotkey(json_backend):
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    AppSettings.set_sco_label_size("large")
    AppSettings.set_sco_drawer_hotkey("Ctrl+Shift+O")
    got = {}
    overlay = SimpleNamespace(
        set_options=lambda options: got.setdefault("options", options),
        drawer=SimpleNamespace(set_position=lambda p: got.setdefault("position", p)),
        set_label_size=lambda s: got.setdefault("size", s),
        set_drawer_hotkey=lambda h: got.setdefault("hotkey", h),
        is_running=lambda: False)
    MainWindow._apply_sco_options(SimpleNamespace(_sco_overlay=overlay))
    assert (got["size"], got["hotkey"]) == ("large", "Ctrl+Shift+O")
    assert set(got["options"]) == set(AppSettings.SCO_OPTION_SETTING)


def test_channel_switch_restarts_the_live_watch(monkeypatch):
    from unittest.mock import MagicMock

    from src.gui import main_window
    monkeypatch.setattr(main_window, "AppSettings", MagicMock())
    me = MagicMock()
    me._check_p4k_freshness.return_value = False
    main_window.MainWindow._on_channel_changed(me, "PTU")
    me._stop_sco_log_watcher.assert_called_once_with()
    me._apply_sco_options.assert_called_once_with()
