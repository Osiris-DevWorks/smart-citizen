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
    # The player ID test starts off, and so do its "show information for all
    # players" switch and the locations to highlight.
    off = {"alert_color", "alert_bigger", "alert_sound", AppSettings.SCO_PLAYER_ID,
           AppSettings.SCO_PLAYER_ID_ALL, AppSettings.SCO_HIGHLIGHT_LOCATIONS}
    for name in AppSettings.SCO_OPTION_SETTING:
        assert AppSettings.get_sco_option(name) is (name not in off), name


def test_a_checkbox_saves_its_option(qapp, json_backend, tmp_path):
    tab = OverlayTab()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    assert set(tab._checks) == set(AppSettings.SCO_OPTION_SETTING)
    tab._checks["scan_decoder"].setChecked(False)
    assert AppSettings.get_sco_option("scan_decoder") is False
    assert AppSettings.get_sco_option("drawer") is True
    assert changed == [True]
    # A new tab reads the saved state back.
    assert not OverlayTab()._checks["scan_decoder"].isChecked()


def test_start_button_asks_and_set_running_only_mirrors(qapp, json_backend, tmp_path):
    tab = OverlayTab()
    asked = []
    tab.overlay_toggled.connect(asked.append)
    tab._start_btn.click()
    assert asked == [True]
    tab.set_running(False)   # e.g. the overlay refused to start
    assert asked == [True] and not tab._start_btn.isChecked()


def test_refresh_styles_follows_a_theme_swap(qapp, json_backend, tmp_path, monkeypatch):
    tab = OverlayTab()
    monkeypatch.setattr("src.gui.overlay_tab.get_button_color", lambda role: "#123456")
    assert "#123456" not in tab._start_btn.styleSheet()
    tab.refresh_styles()
    assert "background-color: #123456" in tab._start_btn.styleSheet()


def test_position_picker_is_a_no_scroll_combo(qapp, json_backend, tmp_path):
    from src.gui.combo_box import NoScrollComboBox
    assert isinstance(OverlayTab()._position_combo, NoScrollComboBox)


def test_option_defaults_reach_settings_backups(json_backend):
    defaults = AppSettings.profile_default_values()
    for key, default in AppSettings.SCO_OPTION_SETTING.values():
        assert defaults[key] == default


def test_drawer_off_greys_out_its_sections(qapp, json_backend, tmp_path):
    tab = OverlayTab()
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
    tab = OverlayTab()
    combo = tab._position_combo
    assert combo.count() == len(AppSettings.SCO_DRAWER_POSITIONS) == 8
    assert combo.currentData() == "middle_right"
    assert combo.currentText() == "Middle right"
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    combo.setCurrentIndex(AppSettings.SCO_DRAWER_POSITIONS.index("bottom_center"))
    assert AppSettings.get_sco_drawer_position() == "bottom_center" and changed == [True]
    assert OverlayTab()._position_combo.currentData() == "bottom_center"
    tab._checks["drawer"].setChecked(False)
    assert not combo.isEnabled()


def test_bad_stored_position_reads_as_default(json_backend):
    json_backend.setValue(AppSettings.SCO_DRAWER_POSITION, "middle_center")
    assert AppSettings.get_sco_drawer_position() == "middle_right"


def test_set_option_mirrors_without_saving_or_emitting(qapp, json_backend, tmp_path):
    tab = OverlayTab()
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

    tab = OverlayTab()
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
    tab = OverlayTab()
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
    tab = OverlayTab()
    combo = tab._size_combo
    assert isinstance(combo, NoScrollComboBox)
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Small", "Medium", "Large", "Extra large"]
    assert combo.currentData() == "medium"
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    combo.setCurrentIndex(AppSettings.SCO_LABEL_SIZES.index("large"))
    assert AppSettings.get_sco_label_size() == "large" and changed == [True]
    assert OverlayTab()._size_combo.currentData() == "large"
    json_backend.setValue(AppSettings.SCO_LABEL_SIZE, "huge")
    assert AppSettings.get_sco_label_size() == "medium"


def test_alert_sound_picker_and_preview(qapp, json_backend, tmp_path, monkeypatch):
    """The "Play a sound" alert's sound: Smart Citizen's chime by default or a
    Windows sound, saved when picked, and a Preview button that plays it."""
    from src.gui import sco_overlay
    from src.gui.combo_box import NoScrollComboBox

    assert AppSettings.get_sco_alert_sound() == "default"
    AppSettings.set_sco_option("alert_sound", True)
    tab = OverlayTab()
    combo = tab._sound_combo
    assert isinstance(combo, NoScrollComboBox)
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Smart Citizen Default",
        "Voice: US, female", "Voice: US, male", "Voice: UK, female", "Voice: UK, male",
        "Voice: Australia, female", "Voice: Australia, male",
        "Voice: Ireland, female", "Voice: Ireland, male",
        "Voice: Nigeria, female", "Voice: Nigeria, male",
        "Windows Asterisk", "Windows Exclamation",
        "Windows Critical Stop", "Windows Default Beep", "Windows Notification"]
    assert tab._sound_label.text() == "Alert sound:"
    assert tab._sound_preview.text() == "Preview"
    played = []
    monkeypatch.setattr(sco_overlay, "play_alert_sound", played.append)
    tab._sound_preview.click()
    assert played == ["default"]
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    combo.setCurrentIndex(AppSettings.SCO_ALERT_SOUNDS.index("notification"))
    assert AppSettings.get_sco_alert_sound() == "notification" and changed == [True]
    tab._sound_preview.click()
    assert played == ["default", "notification"]
    assert OverlayTab()._sound_combo.currentData() == "notification"
    json_backend.setValue(AppSettings.SCO_ALERT_SOUND, "kazoo")
    assert AppSettings.get_sco_alert_sound() == "default"


def test_the_sound_picker_hangs_under_play_a_sound(qapp, json_backend, tmp_path):
    tab = OverlayTab()
    parts = (tab._sound_label, tab._sound_combo, tab._sound_preview)
    assert AppSettings.get_sco_option("alert_sound") is False
    assert not any(w.isEnabled() for w in parts)            # sound alert off by default
    tab._checks["alert_sound"].setChecked(True)
    assert all(w.isEnabled() for w in parts)
    tab._checks["scan_decoder"].setChecked(False)
    assert not any(w.isEnabled() for w in parts)


def test_text_size_and_hotkey_reach_settings_backups(json_backend):
    defaults = AppSettings.profile_default_values()
    assert defaults[AppSettings.SCO_ALERT_SOUND] == "default"
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
    tab = OverlayTab()
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
    assert OverlayTab()._hotkey_edit.sequence() == ""
    _press(edit, Qt.Key.Key_F9, virtual_key=0x78)
    assert OverlayTab()._hotkey_edit.text() == "F9"


def test_the_clear_button_sits_beside_the_box_and_only_when_there_is_a_hotkey(
        qapp, json_backend, tmp_path):
    """#523: every key pressed in the box is taken as the hotkey, so a Clear
    button to its right is how a hotkey is removed. It is lit only with a
    hotkey saved and the drawer on."""
    tab = OverlayTab()
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
    assert OverlayTab()._hotkey_clear.isEnabled() is False
    AppSettings.set_sco_drawer_hotkey("F9")
    assert OverlayTab()._hotkey_clear.isEnabled()   # a saved one


def test_hotkey_box_shows_held_modifiers_and_takes_every_key(qapp, json_backend, tmp_path):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    edit = OverlayTab()._hotkey_edit
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
    tab = OverlayTab()
    _press(tab._hotkey_edit, Qt.Key.Key_Slash, CTRL, 0xBF)
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+/" and tab._hotkey_problem.isHidden()
    _press(tab._hotkey_edit, Qt.Key.Key_Slash, virtual_key=0xBF)   # alone: refused
    assert AppSettings.get_sco_drawer_hotkey() == "Ctrl+/" and not tab._hotkey_problem.isHidden()


def test_hotkey_box_without_a_virtual_key_uses_qt_key(qapp, json_backend, tmp_path):
    """A press with no Windows key (another platform, or sent by code) still
    records the keys Qt names."""
    edit = OverlayTab()._hotkey_edit
    _press(edit, Qt.Key.Key_O, CTRL | ALT)
    assert edit.sequence() == "Ctrl+Alt+O"
    _press(edit, Qt.Key.Key_Oacute, CTRL | ALT)                # no key to fall back on
    assert edit.sequence() == "Ctrl+Alt+O"


def test_options_sit_in_titled_boxes_with_rows_of_switches(qapp, json_backend, tmp_path):
    """#523: one box per part, and the alerts and drawer sections side by
    side with their help as tooltips."""
    from PyQt6.QtWidgets import QGroupBox

    tab = OverlayTab()
    boxes = tab.findChildren(QGroupBox)
    assert [b.title() for b in boxes] == [
        "Scan decoder", "Drawer", "Blueprints from Game.log", "Player ID and locations (test)"]
    home = {"scan_decoder": 0, "drawer": 1, "live_blueprint_watch": 2, "highlight_locations": 3}
    for name, check in tab._checks.items():
        index = home.get(name, 3 if name.startswith("player_id") else
                         0 if name.startswith("alert_") else 1)
        assert boxes[index].isAncestorOf(check), name
    for widget in (tab._player_lists_btn, tab._locations_btn, tab._player_status_label):
        assert boxes[3].isAncestorOf(widget)
    assert tab._size_combo.parent() is not None and boxes[0].isAncestorOf(tab._size_combo)
    for widget in (tab._position_combo, tab._hotkey_edit):
        assert boxes[1].isAncestorOf(widget)
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

    tab = OverlayTab()
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
        set_alert_sound=lambda s: got.setdefault("sound", s),
        set_drawer_hotkey=lambda h: got.setdefault("hotkey", h),
        is_running=lambda: False)
    MainWindow._apply_sco_options(SimpleNamespace(_sco_overlay=overlay))
    assert (got["size"], got["hotkey"], got["sound"]) == ("large", "Ctrl+Shift+O", "default")
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


# -- The player ID test -------------------------------------------------------

LISTS = {"orgs": [["WOLVES", "#40C057"]], "players": [["FRIEND_ONE", "WOLVES", "#FA5252"]],
         "unlisted": "#ADB5BD"}
LOCATIONS = [["NEW BABBAGE", "#40C057"], ["OM-3", "#FA5252"]]
HISTORY = {"session": "2026-11-15 14:02:10",
           "names": [["STRANGER", "2026-11-15 14:02:10"], ["OLD_HAND", "2026-11-01 09:00:00"]]}


def test_player_id_switches_hang_under_its_switch(qapp, json_backend, tmp_path):
    """The player ID test starts off. The two switches under it grey out
    with it, its status line with it and the locations switch together, and
    the lists can be edited either way."""
    tab = OverlayTab()
    main = tab._checks[AppSettings.SCO_PLAYER_ID]
    unlisted = tab._checks[AppSettings.SCO_PLAYER_ID_UNLISTED]
    everything = tab._checks[AppSettings.SCO_PLAYER_ID_ALL]
    under = (unlisted, everything, tab._player_status_label)
    assert (main.isChecked(), unlisted.isChecked(), everything.isChecked()) == (False, True, False)
    assert not any(w.isEnabled() for w in under) and tab._player_lists_btn.isEnabled()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    main.setChecked(True)
    assert all(w.isEnabled() for w in under) and changed == [True]
    everything.setChecked(True)
    unlisted.setChecked(False)
    assert AppSettings.get_sco_option(AppSettings.SCO_PLAYER_ID_ALL) is True
    assert AppSettings.get_sco_option(AppSettings.SCO_PLAYER_ID_UNLISTED) is False
    assert len(changed) == 3
    assert main.text() == "Mark the names of other players"
    assert everything.text() == "Test: Show information for all players"
    assert everything.toolTip().startswith("For checking that the reading works at all.")
    assert unlisted.text() == "Mark names on no list too" and unlisted.toolTip()
    assert tab._player_lists_btn.text() == "Edit player lists..."
    fresh = OverlayTab()                                    # a new tab reads them back
    assert fresh._checks[AppSettings.SCO_PLAYER_ID_ALL].isChecked()
    assert not fresh._checks[AppSettings.SCO_PLAYER_ID_UNLISTED].isChecked()
    main.setChecked(False)
    assert not any(w.isEnabled() for w in under)
    assert AppSettings.get_sco_option(AppSettings.SCO_PLAYER_ID_ALL) is True   # kept


def test_highlight_locations_sits_beside_the_names(qapp, json_backend, tmp_path):
    """Players' names are the left half of the box and the locations to
    highlight the right half, each with its switch and its editor. The
    status line runs under both and is live with either switch, since the
    same looks read names and locations."""
    tab = OverlayTab()
    names = tab._checks[AppSettings.SCO_PLAYER_ID]
    places = tab._checks[AppSettings.SCO_HIGHLIGHT_LOCATIONS]
    assert places.text() == "Highlight locations" and not places.isChecked()
    assert tab._hints[AppSettings.SCO_HIGHLIGHT_LOCATIONS].text().startswith("A test.")
    assert tab._locations_btn.text() == "Edit locations..." and tab._locations_btn.isEnabled()
    tab.resize(1100, 900)
    tab.show()
    qapp.processEvents()
    try:
        def left_top(widget):
            point = widget.mapTo(tab, widget.rect().topLeft())
            return point.x(), point.y()

        assert left_top(names)[1] == left_top(places)[1]             # side by side
        middle = tab.width() // 2
        assert left_top(names)[0] < middle <= left_top(places)[0]
        assert left_top(tab._player_lists_btn)[0] < middle <= left_top(tab._locations_btn)[0]
        for name in (AppSettings.SCO_PLAYER_ID_UNLISTED, AppSettings.SCO_PLAYER_ID_ALL):
            assert left_top(tab._checks[name])[0] < middle
        # The status line is under both halves.
        status_y = left_top(tab._player_status_label)[1]
        assert status_y > max(left_top(tab._player_lists_btn)[1], left_top(tab._locations_btn)[1])
    finally:
        tab.hide()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    places.setChecked(True)
    assert AppSettings.get_sco_option(AppSettings.SCO_HIGHLIGHT_LOCATIONS) is True
    assert changed == [True] and tab._player_status_label.isEnabled()
    # The switches under the names one still follow the names switch alone.
    assert not tab._checks[AppSettings.SCO_PLAYER_ID_UNLISTED].isEnabled()
    places.setChecked(False)
    assert not tab._player_status_label.isEnabled()


def test_the_distance_switch_sits_under_both_halves(qapp, json_backend, tmp_path):
    """Reading only text with a distance line under it is about what the
    looks read at all, names and locations alike. So its switch runs under
    both halves, with its hint under it, is on from the start, and is live
    with either half's switch."""
    tab = OverlayTab()
    distance = tab._checks[AppSettings.SCO_PLAYER_ID_DISTANCE]
    hint = tab._hints[AppSettings.SCO_PLAYER_ID_DISTANCE]
    assert distance.text() == "Only read text with a distance line under it"
    assert distance.isChecked() and AppSettings.get_sco_option(AppSettings.SCO_PLAYER_ID_DISTANCE)
    assert hint.text().startswith("Every marker in the game shows its distance under its name")
    assert "player on foot" in hint.text()
    tab.resize(1100, 950)
    tab.show()
    qapp.processEvents()
    try:
        def top(widget):
            return widget.mapTo(tab, widget.rect().topLeft()).y()

        def left(widget):
            return widget.mapTo(tab, widget.rect().topLeft()).x()

        # Under both editors' buttons, above the status line, starting where
        # the names' own switch starts.
        assert top(distance) > max(top(tab._player_lists_btn), top(tab._locations_btn))
        assert top(distance) < top(hint) < top(tab._player_status_label)
        assert left(distance) == left(tab._checks[AppSettings.SCO_PLAYER_ID])
        # Its hint runs the box's whole width, past the middle where the
        # locations' half begins: it belongs to neither half.
        assert left(hint) + hint.width() > left(tab._locations_btn) + tab._locations_btn.width()
    finally:
        tab.hide()
    # Greyed with both halves off, live with either on.
    assert not distance.isEnabled() and not hint.isEnabled()
    tab._checks[AppSettings.SCO_HIGHLIGHT_LOCATIONS].setChecked(True)
    assert distance.isEnabled() and hint.isEnabled()
    tab._checks[AppSettings.SCO_HIGHLIGHT_LOCATIONS].setChecked(False)
    tab._checks[AppSettings.SCO_PLAYER_ID].setChecked(True)
    assert distance.isEnabled()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    distance.setChecked(False)
    assert AppSettings.get_sco_option(AppSettings.SCO_PLAYER_ID_DISTANCE) is False
    assert changed == [True]
    assert not OverlayTab()._checks[AppSettings.SCO_PLAYER_ID_DISTANCE].isChecked()


def test_the_lists_editor_saves_what_it_leaves(qapp, json_backend, tmp_path, monkeypatch):
    """The button opens the editor with the saved lists and the names read
    in play as the settings hold them. What an OK leaves is saved and
    announced, so a running overlay takes the new lists. A Cancel saves
    nothing. The record of past players is emptied only on an OK that asks
    for it."""
    from PyQt6.QtWidgets import QDialog

    from src.gui import overlay_tab

    opened = []
    script = {"answer": QDialog.DialogCode.Accepted, "leaves": LISTS, "cleared": False}

    class FakeDialog:
        def __init__(self, data, past, parent=None):
            opened.append((data, past, parent))

        def exec(self):
            return script["answer"]

        def lists(self):
            return script["leaves"]

        def past_cleared(self):
            return script["cleared"]

    monkeypatch.setattr(overlay_tab, "PlayerListsDialog", FakeDialog)
    tab = OverlayTab()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    tab._player_lists_btn.click()
    assert opened == [({}, {}, tab)]              # nothing saved yet, nothing read yet
    assert AppSettings.get_player_lists() == LISTS and changed == [True]
    # The names read in play come from the settings, read each time.
    AppSettings.set_player_history(HISTORY)
    script.update(answer=QDialog.DialogCode.Rejected, cleared=True,
                  leaves={"orgs": [], "players": [], "unlisted": "#000000"})
    tab._player_lists_btn.click()
    assert opened[1] == (LISTS, HISTORY, tab)
    assert AppSettings.get_player_lists() == LISTS and changed == [True]
    assert AppSettings.get_player_history() == HISTORY          # a Cancel clears nothing
    script.update(answer=QDialog.DialogCode.Accepted, cleared=False, leaves=LISTS)
    tab._player_lists_btn.click()
    assert AppSettings.get_player_history() == HISTORY          # nor an OK that did not ask
    script.update(cleared=True)
    tab._player_lists_btn.click()
    assert AppSettings.get_player_history() == {} and len(changed) == 3


def test_the_real_editors_ok_reaches_the_settings(qapp, json_backend, tmp_path, monkeypatch):
    from src.gui.player_lists_dialog import PlayerListsDialog

    seen = {}

    def edit_and_press_ok(dialog):                # what exec() gives back: a plain number
        seen["offered"] = [dialog.past.item(row).text() for row in range(dialog.past.count())]
        dialog.add_player("friend_one", "", "green")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlayerListsDialog, "exec", edit_and_press_ok)
    AppSettings.set_player_lists({"orgs": [["Wolves", "red"]], "players": [], "unlisted": "blue"})
    AppSettings.set_player_history(HISTORY)
    tab = OverlayTab()
    tab._player_lists_btn.click()
    assert AppSettings.get_player_lists() == {
        "orgs": [["WOLVES", "#FA5252"]], "players": [["FRIEND_ONE", "", "#40C057"]],
        "unlisted": "#4DABF7"}
    # The real editor was handed the names read in play, and an OK keeps them.
    assert seen["offered"] == ["STRANGER    2026-11-15", "OLD_HAND    2026-11-01"]
    assert AppSettings.get_player_history() == HISTORY


def test_the_locations_editor_saves_what_it_leaves(qapp, json_backend, tmp_path, monkeypatch):
    """The locations button opens their editor with the saved list. What an
    OK leaves is saved and announced. A Cancel saves nothing."""
    from PyQt6.QtWidgets import QDialog

    from src.gui import overlay_tab

    opened = []
    script = {"answer": QDialog.DialogCode.Accepted, "leaves": LOCATIONS}

    class FakeDialog:
        def __init__(self, data, parent=None):
            opened.append((data, parent))

        def exec(self):
            return script["answer"]

        def locations(self):
            return script["leaves"]

    monkeypatch.setattr(overlay_tab, "LocationListDialog", FakeDialog)
    tab = OverlayTab()
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    tab._locations_btn.click()
    assert opened == [([], tab)]
    assert AppSettings.get_location_list() == LOCATIONS and changed == [True]
    script.update(answer=QDialog.DialogCode.Rejected, leaves=[])
    tab._locations_btn.click()
    assert opened[1] == (LOCATIONS, tab)
    assert AppSettings.get_location_list() == LOCATIONS and changed == [True]


def test_the_real_locations_editors_ok_reaches_the_settings(qapp, json_backend, tmp_path,
                                                            monkeypatch):
    from src.gui.player_lists_dialog import LocationListDialog

    def edit_and_press_ok(dialog):
        dialog.add_location("new  babbage", "green")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(LocationListDialog, "exec", edit_and_press_ok)
    AppSettings.set_location_list([["om-3", "red"]])
    tab = OverlayTab()
    tab._locations_btn.click()
    assert AppSettings.get_location_list() == [["OM-3", "#FA5252"], ["NEW BABBAGE", "#40C057"]]


def test_the_player_id_status_line(qapp, json_backend, tmp_path):
    from src.gui import player_id_overlay
    from src.utils.i18n import tr

    tab = OverlayTab()
    label = tab._player_status_label
    assert label.text() == "Start the overlay with names or locations switched on to see it work."
    tab.set_player_id_status("no_game", {})
    assert label.text() == "Running. Waiting for Star Citizen to be the window in front."
    tab.set_player_id_status("looking", {"width": 3840, "height": 2160, "seconds": 0.42,
                                         "lines": 31, "skipped": 19, "read": 12, "marked": 3})
    assert label.text() == ("Looking at the game (3840x2160). The last look took 0.42 s: "
                            "31 lines of text found, 19 left out for having no distance line, "
                            "12 tags read, 3 marked.")
    tab.retranslate_ui()                          # a language switch keeps what it says
    assert label.text().startswith("Looking at the game (3840x2160).")
    # Every state the overlay can report has its text.
    states = [value for name, value in vars(player_id_overlay).items()
              if name.startswith("STATUS_") and isinstance(value, str)]
    assert sorted(states) == ["failed", "looking", "no_game", "off", "starting"]
    for state in states:
        key = f"overlay.player_id_status_{state}"
        assert tr(key) != key, state


def test_player_lists_round_trip_and_reach_a_backup_only_once_saved(json_backend):
    import json

    assert AppSettings.get_player_lists() == {}
    # The user's own data, like the owned blueprints: an older backup that
    # has no lists must not empty them, so no default is put into a backup.
    assert AppSettings.SCO_PLAYER_LISTS not in AppSettings.profile_default_values()
    assert AppSettings.SCO_PLAYER_LISTS not in AppSettings.export_all_values()
    AppSettings.set_player_lists(LISTS)
    assert AppSettings.get_player_lists() == LISTS
    assert json.loads(AppSettings.export_all_values()[AppSettings.SCO_PLAYER_LISTS]) == LISTS
    for damaged in ("not json", "[1, 2]", '"text"', ""):
        json_backend.setValue(AppSettings.SCO_PLAYER_LISTS, damaged)
        assert AppSettings.get_player_lists() == {}, damaged


def test_the_locations_round_trip_and_reach_a_backup_only_once_saved(json_backend):
    import json

    assert AppSettings.get_location_list() == []
    # The user's own data too: no default goes into a backup.
    assert AppSettings.SCO_LOCATION_LIST not in AppSettings.profile_default_values()
    assert AppSettings.SCO_LOCATION_LIST not in AppSettings.export_all_values()
    AppSettings.set_location_list(LOCATIONS)
    assert AppSettings.get_location_list() == LOCATIONS
    assert json.loads(AppSettings.export_all_values()[AppSettings.SCO_LOCATION_LIST]) == LOCATIONS
    for damaged in ("not json", '{"a": 1}', '"text"', ""):
        json_backend.setValue(AppSettings.SCO_LOCATION_LIST, damaged)
        assert AppSettings.get_location_list() == [], damaged


def test_the_names_read_in_play_never_reach_a_backup(json_backend):
    """They are other players' names, read off the screen: kept on this PC,
    and left out of an Export Settings backup and of an import."""
    assert AppSettings.get_player_history() == {}
    AppSettings.set_player_history(HISTORY)
    assert AppSettings.get_player_history() == HISTORY
    assert AppSettings.is_profile_excluded_key(AppSettings.SCO_PLAYER_HISTORY)
    assert AppSettings.SCO_PLAYER_HISTORY not in AppSettings.profile_default_values()
    exported = AppSettings.export_all_values()
    assert AppSettings.SCO_PLAYER_HISTORY not in exported
    assert not any("STRANGER" in str(value) for value in exported.values())
    for damaged in ("not json", "[1, 2]", '"text"', ""):
        json_backend.setValue(AppSettings.SCO_PLAYER_HISTORY, damaged)
        assert AppSettings.get_player_history() == {}, damaged


def test_starting_the_overlay_wires_the_player_id_status(json_backend, monkeypatch):
    """MainWindow hands the Overlay tab the player ID test's status when it
    makes the overlay."""
    from unittest.mock import MagicMock

    from src.gui import main_window, sco_overlay

    made = MagicMock()
    monkeypatch.setattr(sco_overlay, "ScoOverlay", MagicMock(return_value=made))
    me = MagicMock()
    me._sco_overlay = None
    me._blueprint_meta = {"Agni": object()}
    main_window.MainWindow._toggle_sco_overlay(me, True)
    assert me._sco_overlay is made
    made.player_id.status.connect.assert_called_once_with(me.overlay_tab.set_player_id_status)
    made.start.assert_called_once_with()


def test_apply_options_hands_the_overlay_the_player_id_switches(json_backend):
    from types import SimpleNamespace

    from src.gui.main_window import MainWindow

    AppSettings.set_sco_option(AppSettings.SCO_PLAYER_ID, True)
    AppSettings.set_sco_option(AppSettings.SCO_PLAYER_ID_ALL, True)
    AppSettings.set_sco_option(AppSettings.SCO_HIGHLIGHT_LOCATIONS, True)
    got = {}
    overlay = SimpleNamespace(
        set_options=lambda options: got.update(options),
        drawer=SimpleNamespace(set_position=lambda p: None),
        set_label_size=lambda s: None, set_alert_sound=lambda s: None,
        set_drawer_hotkey=lambda h: None, is_running=lambda: False)
    MainWindow._apply_sco_options(SimpleNamespace(_sco_overlay=overlay))
    assert (got["player_id"], got["player_id_unlisted"], got["player_id_all"]) == (
        True, True, True)
    assert got["highlight_locations"] is True
    assert got["player_id_distance"] is True              # its default, never switched
