"""The game telemetry panel (a test: a mock-up with sample values for now).

Headless (``QT_QPA_PLATFORM=offscreen``). Covers its sample readouts, its two
shells, the separate window and the panel docked at a screen edge in the
drawer's look, the Dock and Undock buttons that switch between them, the place
row that picks where it docks (the pad for the place, the button for the
screen), the window's readouts growing with it and spreading into columns,
the Overlay tab's button opening and closing it with no running overlay, a
panel left open opening again at the next start as it was left, the window's
own X, and its state staying on this PC. The tab's button and picker are in
test_overlay_tab.py.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QObject, QPoint, QRect, QSettings, QSize, Qt
from PyQt6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.gui import main_window as main_window_module
from src.gui import sco_telemetry
from src.gui.main_window import MainWindow
from src.gui.overlay_tab import OverlayTab
from src.gui.sco_overlay import (
    BOTTOM, DEFAULT_OVERLAY_COLORS, DRAWER_ALPHA, LEFT, ODW_OVERLAY_COLORS,
    PASS_THROUGH_IDLE_POLL_MS, PASS_THROUGH_POLL_MS, RIGHT, TOP, OverlayColors, drawer_edge,
)
from src.gui.sco_telemetry import (
    CAUTION_COLOR, COLUMN_CHOICES, COLUMN_GAP, COLUMN_PLANS, DEFAULT_SCALE, DOCK_PANEL_WIDTH,
    FLIGHT, GAME_SCREEN, LEVEL_BARS, LIGHT_MAJOR, LIGHT_MINOR, LIGHT_NOMINAL, LIGHT_OFF,
    MINIMUM_WIDTH,
    OUTLINE, PILOT, PLACE_FREE, PLACE_LIT, PLACE_PROPERTY, SAMPLE, SCALE_STEP,
    SCREEN_LABEL_LENGTH, SYSTEMS, TELEMETRY_TAB, WARNING_COLOR, WHERE, WIDEST, DockPad, LevelBar,
    ShieldRose, TelemetryDock, TelemetryPanel, TelemetrySample, TelemetryView, TelemetryWindow,
    design_width, level_color, next_screen_key, panel_style, percent, readout_style,
    resolved_screen_key, scaled, screen_for_key, screen_keys, screen_label, screen_name,
    vital_label, whole_steps,
)
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings
from tests.gui_window import build_main_window, retire_main_window

pytestmark = pytest.mark.unit

OPEN_TEXT, CLOSE_TEXT = "Open Telemetry", "Close Telemetry"
# Two monitors of one model, named as Qt names them, and one Windows has only
# a device name for.
SCREEN_1, SCREEN_2, UNNAMED_SCREEN = "Vision 27Q (1)", "Vision 27Q (2)", "\\\\.\\DISPLAY3"
SCREEN_HINT = "The screen it docks on. Click for the next one."


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path, english_ui):
    """Settings in a file under tmp_path, never the registry: the panel's
    state and place are saved. No real theme is read, Windows is not asked
    where the game is, whether it is in front or whether its pointer shows,
    and no screen has a name to be picked by (tests that need an answer or a
    screen patch their own)."""
    monkeypatch.setattr(AppSettings, "_backend", JsonSettings(tmp_path / "config.json"))
    monkeypatch.setattr(OverlayColors, "from_theme",
                        classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    monkeypatch.setattr(sco_telemetry, "game_screen", lambda: None)
    monkeypatch.setattr(sco_telemetry, "game_in_front", lambda: False)
    monkeypatch.setattr(sco_telemetry, "pointer_hidden", lambda: False)
    monkeypatch.setattr(sco_telemetry, "_screens", lambda: [])


class _Owner(QObject):
    """A stand-in for MainWindow with what its telemetry methods use."""

    _sync_telemetry_window = MainWindow._sync_telemetry_window
    _set_telemetry_window_open = MainWindow._set_telemetry_window_open
    _on_telemetry_window_closed = MainWindow._on_telemetry_window_closed

    def __init__(self, tab=None):
        super().__init__()
        self._telemetry = None
        self._close_committed = False
        self.overlay_tab = tab or OverlayTab()

    def windowIcon(self):  # noqa: N802 (Qt's name)
        return QIcon()


def _closing_window():
    """A stand-in MainWindow.closeEvent runs through to the end, built as
    test_minimize_to_tray.py builds its own."""
    me = MagicMock()
    me._session_has_unapplied_edit = False
    me._suppress_user_ini_autosave = False
    me._loader_worker = None
    me._user_resized_columns = False
    me.entries = []
    me._close_committed = False
    return me


def _click_the_x(window) -> None:
    """What the title bar's X (or Alt+F4) does: a close event sent to the
    widget's own QWindow, which Qt hands to the widget as a spontaneous close.
    On the Windows platform a real WM_CLOSE reaches closeEvent the same way
    (measured). ``close()`` on the widget or its QWindow is not spontaneous."""
    QApplication.sendEvent(window.windowHandle(), QCloseEvent())


def _click_the_tab(dock) -> None:
    """A real press on the docked panel's tab."""
    QTest.mouseClick(dock._handle, Qt.MouseButton.LeftButton,
                     pos=dock._handle.rect().center())


def _screen_area() -> QRect:
    return QGuiApplication.primaryScreen().availableGeometry()


def _place(window, x: int = 120, y: int = 40, width: int = 500) -> QRect:
    """Somewhere the player could leave the window: it is never shorter than
    its readouts need, which depends on the platform's fonts."""
    return QRect(x, y, width, window.minimumHeight() + 12)


def _screen(name: str, x: int = 1000, y: int = 100) -> SimpleNamespace:
    """A stand-in for a connected screen: its name and what docking asks of it."""
    return SimpleNamespace(name=lambda: name,
                           availableGeometry=lambda: QRect(x, y, 640, 480),
                           devicePixelRatio=lambda: 1)


def _connect(monkeypatch, *screens) -> None:
    """The screens that are connected, the same ones each time they are asked for."""
    monkeypatch.setattr(sco_telemetry, "_screens", lambda: list(screens))


def _lit(pad) -> list:
    return [place for place, cell in pad.cells.items()
            if cell.property(PLACE_PROPERTY) == PLACE_LIT]


# -- the view both shells show ------------------------------------------------

def test_the_view_says_its_values_are_samples_and_offers_the_other_shell(qapp):
    from src.utils import i18n

    docked, windowed = TelemetryView(docked=True), TelemetryView(docked=False)
    for view in (docked, windowed):
        assert view._heading.text() == "Game Telemetry"
        assert view._status.text() == "Waiting for telemetry from the game."
        assert view._sample_tag.text() == "SAMPLE DATA"
        assert "sample values, not from the game" in view._note.text()
        assert view._switch_btn.toolTip()
    assert docked._switch_btn.text() == "Undock" and windowed._switch_btn.text() == "Dock"
    asked = []
    docked.switch_requested.connect(lambda: asked.append("undock"))
    windowed.switch_requested.connect(lambda: asked.append("dock"))
    docked._switch_btn.click()
    windowed._switch_btn.click()
    assert asked == ["undock", "dock"]
    assert docked._switch_btn.focusPolicy() == Qt.FocusPolicy.NoFocus

    i18n.set_language("german")                 # english_ui puts English back
    for view in (docked, windowed):
        view.retranslate_ui()
        assert view._heading.text() == "Spieltelemetrie"
        assert view._status.text() == "Warte auf Telemetrie vom Spiel."
        assert view._sample_tag.text() == "BEISPIELDATEN"
        assert "Beispielwerte" in view._note.text()
        # The readouts' own labels and worded lines too, the sample's values kept.
        assert view._shields_caption.text() == "Schilde" and view._pilot_caption.text() == "PILOT"
        assert [caption.text() for caption in view._level_captions.values()] == [
            "H\u00fclle", "Wasserstoff", "Quantum", "Boost"]
        assert [caption.text() for caption in view._vital_captions.values()] == [
            "Gesundheit", "Sauerstoff", "Hunger", "Durst"]
        assert view._location.text() == (
            "Stanton \u203a Crusader \u203a Orison  \u00b7  Waffenstillstandszone")
        assert view._game.text() == "74 FPS  \u00b7  38 ms Ping  \u00b7  Server 28 FPS"
        assert view._speed_caption.text() == "m/s   1.8 G" and view._speed.text() == "212"
    assert docked._switch_btn.text() == "Abdocken" and windowed._switch_btn.text() == "Andocken"


def test_the_view_is_filled_with_sample_readouts(qapp):
    """A mock-up of what the game's telemetry carries: the ship, its speed,
    shield faces, levels and warning lights, the pilot's vitals, where they
    are and how the game runs."""
    view = TelemetryView(docked=True)
    assert view.sample is SAMPLE
    assert view._ship.text() == "DRAKE Cutlass Black" and view._mode.text() == "SCM"
    assert view._speed.text() == "212" and view._speed_caption.text() == "m/s   1.8 G"
    assert view._shields.text() == "86 %"
    assert view._shield_rose.faces == SAMPLE.shield_faces == (0.95, 0.9, 0.42, 1.0)
    figures = {name: (bar.level, figure.text()) for name, (bar, figure) in view._levels.items()}
    assert figures == {"hull": (0.97, "97 %"), "hydrogen_fuel": (0.64, "64 %"),
                       "quantum_fuel": (0.41, "41 %"), "boost": (0.78, "78 %")}
    # The game's ten warning lights, in its order, each in its state.
    assert list(view._lights) == ["PWR", "WPN", "THR", "SHLD", "COOL", "QDRV", "RADR", "PROX",
                                  "HIT", "MISL"]
    states = {name: light.property("light") for name, light in view._lights.items()}
    assert (states["SHLD"], states["HIT"], states["QDRV"], states["PWR"]) == (
        LIGHT_MINOR, LIGHT_MAJOR, LIGHT_OFF, LIGHT_NOMINAL)
    assert {name: bar.level for name, bar in view._vitals.items()} == {
        "health": 1.0, "oxygen": 0.98, "hunger": 0.72, "thirst": 0.18}
    # Their labels are worded by the app, in the language in use.
    assert {name: caption.text() for name, caption in view._vital_captions.items()} == {
        "health": "Health", "oxygen": "Oxygen", "hunger": "Hunger", "thirst": "Thirst"}
    assert {name: caption.text() for name, caption in view._level_captions.items()} == {
        "hull": "Hull", "hydrogen_fuel": "Hydrogen", "quantum_fuel": "Quantum", "boost": "Boost"}
    assert list(view._level_captions) == list(LEVEL_BARS) == list(view._levels)
    assert view._shields_caption.text() == "Shields" and view._pilot_caption.text() == "PILOT"
    assert view._location.text() == "Stanton › Crusader › Orison  ·  Armistice zone"
    assert view._game.text() == "74 FPS  ·  38 ms ping  ·  Server 28 FPS"
    # A low level is drawn in the caution colour, a very low one in the warning colour.
    assert view._levels["hull"][0].fill_color() == DEFAULT_OVERLAY_COLORS.accent
    assert view._levels["quantum_fuel"][0].fill_color() == CAUTION_COLOR
    assert view._vitals["thirst"].fill_color() == WARNING_COLOR
    assert not view.grab().isNull()             # every readout paints


def test_other_values_replace_the_sample(qapp):
    view = TelemetryView(docked=False)
    view.apply_colors(ODW_OVERLAY_COLORS)
    other = TelemetrySample(
        manufacturer="RSI", vehicle_name="Aurora MR", master_mode="NAV", speed=0.4,
        shields=0.2, shield_faces=(0, 0.1, 2, -1), hull=0.09,
        annunciators=(("PWR", LIGHT_OFF),), vitals=(("health", 0.5), ("stun", 0.3)),
        location=("Pyro",), armistice_zone=False, fps=30.4, ping_ms=120, server_fps=9.6)
    view.show_sample(other)
    assert view.sample is other
    assert view._vitals["health"].fill_color() == ODW_OVERLAY_COLORS.accent   # the colours in use
    assert view._vitals["health"].level == 0.5
    # A vital the app has no word for is shown as the game names it.
    assert [caption.text() for caption in view._vital_captions.values()] == ["Health", "stun"]
    assert view._ship.text() == "RSI Aurora MR" and view._mode.text() == "NAV"
    assert view._speed.text() == "0" and view._shields.text() == "20 %"
    assert view._shield_rose.faces == (0.0, 0.1, 1.0, 0.0)          # kept within 0 to 1
    assert view._levels["hull"][1].text() == "9 %"
    assert view._levels["hull"][0].fill_color() == WARNING_COLOR
    assert list(view._lights) == ["PWR"] and list(view._vitals) == ["health", "stun"]
    assert view._lights_grid.count() == 1 and view._vitals_grid.count() == 4    # the old ones gone
    assert view._location.text() == "Pyro"                          # no armistice zone
    assert view._game.text() == "30 FPS  ·  120 ms ping  ·  Server 10 FPS"
    assert not view.grab().isNull()


def test_a_levels_colour_and_figure(qapp):
    colors = ODW_OVERLAY_COLORS
    assert [level_color(level, colors) for level in (1.0, 0.5, 0.49, 0.25, 0.24, 0.0)] == [
        colors.accent, colors.accent, CAUTION_COLOR, CAUTION_COLOR, WARNING_COLOR, WARNING_COLOR]
    assert [percent(level) for level in (1.0, 0.666, 0.004, 0.0)] == ["100 %", "67 %", "0 %", "0 %"]
    bar = LevelBar()
    bar.set_colors(colors)
    for given, kept in ((0.3, 0.3), (7, 1.0), (-2, 0.0)):
        bar.set_level(given)
        assert bar.level == kept
    bar.set_level(0.3)
    assert bar.fill_color() == CAUTION_COLOR and not bar.grab().isNull()
    bar.set_level(0.9)
    assert bar.fill_color() == colors.accent        # the colours it was given
    rose = ShieldRose()
    rose.set_colors(colors)
    rose.set_faces((1, 0.5, 0.2, 0))
    assert rose.faces == (1.0, 0.5, 0.2, 0.0) and not rose.grab().isNull()
    assert [vital_label(name) for name in ("health", "thirst", "stun")] == [
        "Health", "Thirst", "stun"]
    assert SAMPLE.vitals == (("health", 1.0), ("oxygen", 0.98), ("hunger", 0.72), ("thirst", 0.18))


# -- where it docks: the pad and the screen button ------------------------------

def test_the_pad_is_a_map_of_the_eight_places_with_the_one_in_use_lit(qapp):
    from src.utils import i18n

    pad = DockPad()
    assert list(pad.cells) == list(AppSettings.SCO_DRAWER_POSITIONS)
    # Laid out as the screen is, with nothing in the middle, where nothing docks.
    where = {place: pad._grid.getItemPosition(pad._grid.indexOf(cell))[:2]
             for place, cell in pad.cells.items()}
    assert where == {
        "top_left": (0, 0), "top_center": (0, 1), "top_right": (0, 2),
        "middle_left": (1, 0), "middle_right": (1, 2),
        "bottom_left": (2, 0), "bottom_center": (2, 1), "bottom_right": (2, 2)}
    assert pad._grid.itemAtPosition(1, 1) is None

    assert _lit(pad) == []                              # none until it is told one
    pad.set_position("top_right")
    assert _lit(pad) == ["top_right"] and pad.position == "top_right"
    pad.set_position("bottom_center")                   # the one before is put out
    assert _lit(pad) == ["bottom_center"]
    assert pad.cells["top_right"].property(PLACE_PROPERTY) == PLACE_FREE
    picked = []
    pad.picked.connect(picked.append)
    pad.cells["middle_right"].click()
    pad.cells["top_left"].click()
    assert picked == ["middle_right", "top_left"]
    assert _lit(pad) == ["bottom_center"]               # a click only asks
    pad.set_position("nowhere")
    assert _lit(pad) == []

    cell = pad.cells["top_left"]
    assert cell.toolTip() == cell.accessibleName() == "Top left"
    assert cell.focusPolicy() == Qt.FocusPolicy.NoFocus and not cell.text()
    i18n.set_language("german")                         # english_ui puts English back
    pad.retranslate_ui()
    assert pad.cells["bottom_center"].toolTip() == "Unten Mitte"
    assert pad.cells["bottom_center"].accessibleName() == "Unten Mitte"


def test_the_pads_cells_grow_with_the_scale(qapp):
    pad = DockPad()
    assert pad.cells["top_left"].size() == QSize(DockPad.CELL_WIDTH, DockPad.CELL_HEIGHT)
    assert pad._grid.spacing() == DockPad.GAP
    pad.set_scale(2.5)
    for cell in pad.cells.values():
        assert cell.size() == QSize(40, 25)
    assert pad._grid.spacing() == 8


def test_the_place_row_shows_where_it_docks_and_asks_for_another_place(qapp, monkeypatch):
    from src.utils import i18n

    view = TelemetryView(docked=True)
    assert view._place_caption.text() == "Dock at:"
    view.set_place("bottom_center", GAME_SCREEN)
    assert _lit(view._pad) == ["bottom_center"]
    asked = []
    view.place_picked.connect(asked.append)
    view.screen_cycle_requested.connect(lambda: asked.append("the next screen"))
    view._pad.cells["top_left"].click()
    assert asked == ["top_left"] and _lit(view._pad) == ["bottom_center"]   # it only asks

    # With one screen there is nothing to choose, so no button.
    assert view._screen_btn.isHidden()
    _connect(monkeypatch, _screen(SCREEN_1))
    view.set_place("bottom_center", GAME_SCREEN)
    assert view._screen_btn.isHidden()
    _connect(monkeypatch, _screen(SCREEN_1), _screen(SCREEN_2))
    view.set_place("bottom_center", GAME_SCREEN)
    button = view._screen_btn
    assert not button.isHidden() and button.text() == "Game's screen"
    assert button.toolTip() == SCREEN_HINT and button.focusPolicy() == Qt.FocusPolicy.NoFocus
    button.click()
    assert asked == ["top_left", "the next screen"]
    assert button.text() == "Game's screen"             # it only asks
    view.set_place("top_right", SCREEN_2)
    assert button.text() == SCREEN_2 and button.toolTip() == f"{SCREEN_HINT}\n{SCREEN_2}"
    assert _lit(view._pad) == ["top_right"]
    view.set_place("top_right", "A Screen Taken Away")  # not connected: it follows the game
    assert button.text() == "Game's screen" and button.toolTip() == SCREEN_HINT

    i18n.set_language("german")                         # english_ui puts English back
    view.retranslate_ui()
    assert view._place_caption.text() == "Andocken an:"
    assert button.text() == "Bildschirm des Spiels"
    assert button.toolTip() == "Der Bildschirm, an dem sie andockt. Klicken für den nächsten."
    assert view._pad.cells["top_left"].toolTip() == "Oben links"


def test_the_screens_to_choose_are_the_games_and_each_connected_one(qapp, monkeypatch):
    assert screen_keys() == [GAME_SCREEN]               # no named screen: only the game's
    assert next_screen_key(GAME_SCREEN) == GAME_SCREEN
    first, second = _screen(SCREEN_1), _screen(SCREEN_2)
    _connect(monkeypatch, first, second, _screen(SCREEN_2), _screen(""))
    assert screen_keys() == [GAME_SCREEN, SCREEN_1, SCREEN_2]   # each name once, none unnamed
    assert [next_screen_key(key) for key in (GAME_SCREEN, SCREEN_1, SCREEN_2)] == [
        SCREEN_1, SCREEN_2, GAME_SCREEN]                # and round again
    assert next_screen_key("gone") == SCREEN_1          # from one that went: as from the game's
    assert resolved_screen_key(SCREEN_2) == SCREEN_2
    assert resolved_screen_key("gone") == GAME_SCREEN == resolved_screen_key(GAME_SCREEN)
    assert screen_for_key(SCREEN_1) is first and screen_for_key(SCREEN_2) is second
    assert screen_for_key(GAME_SCREEN) is None and screen_for_key("gone") is None


def test_a_screen_reads_as_its_own_name_cut_in_the_middle_when_long(qapp):
    assert screen_label(GAME_SCREEN) == "Game's screen"
    assert screen_label(SCREEN_1) == SCREEN_1
    # Windows' device prefix is left off the name of a monitor with no other.
    assert screen_name(UNNAMED_SCREEN) == screen_label(UNNAMED_SCREEN) == "DISPLAY3"
    assert screen_name(GAME_SCREEN) == ""
    exact = "x" * SCREEN_LABEL_LENGTH
    assert screen_label(exact) == exact
    # Two of one model differ at the end, so a long name keeps both its ends.
    one, two = "Long Vision Ultra Wide 3440 (1)", "Long Vision Ultra Wide 3440 (2)"
    assert screen_label(one) == "Long Visio… 3440 (1)" != screen_label(two)
    assert screen_label(two) == "Long Visio… 3440 (2)"
    assert len(screen_label(one)) == SCREEN_LABEL_LENGTH == 20


# -- the readouts grow with the window and spread into columns -----------------

def test_lengths_scale_to_whole_pixels_and_scales_to_whole_steps(qapp):
    assert [scaled(length, 1.0) for length in (0, 1, 7, 68)] == [0, 1, 7, 68]
    assert scaled(12, 1.25) == 15 and scaled(7, 1.4) == 10 and scaled(30, 4.3) == 129
    assert scaled(0, 9.0) == 0                          # no gap stays no gap
    assert scaled(1, 0.2) == 1                          # and nothing scales away
    assert SCALE_STEP == 0.05
    assert [whole_steps(scale) for scale in (0.99, 1.0, 1.049, 1.05, 1.249, 1.25, 3.0, 4.34)] == [
        0.95, 1.0, 1.0, 1.05, 1.2, 1.25, 3.0, 4.3]
    assert design_width(1) == MINIMUM_WIDTH == DOCK_PANEL_WIDTH == 300
    # Each further column adds a column's width and the gap before it.
    assert design_width(2) - design_width(1) == design_width(3) - design_width(2) == 290
    assert 290 == MINIMUM_WIDTH - OUTLINE - 28 + COLUMN_GAP


def test_the_readouts_style_grows_with_the_scale(qapp):
    colors = ODW_OVERLAY_COLORS
    plain, large = readout_style(colors), readout_style(colors, 2.5)
    assert plain == readout_style(colors, 1.0)
    for size in (12, 16, 14, 30, 18, 11, 9):            # text, heading, ship, speed, shields ...
        assert f"font-size: {size}px" in plain
        assert f"font-size: {scaled(size, 2.5)}px" in large
    assert "font-size: 12px" not in large and "border: 1px solid" in plain
    assert "border: 2px solid" in large and "border: 1px solid" not in large
    for style in (plain, large):
        assert colors.text in style and colors.accent in style and colors.secondary in style
        assert CAUTION_COLOR in style and WARNING_COLOR in style
        assert f'QPushButton[{PLACE_PROPERTY}="{PLACE_LIT}"]' in style
        assert f'QPushButton[{PLACE_PROPERTY}="{PLACE_FREE}"]' in style
    # The frame round them has the window colour, an accent outline and no sizes.
    frame = panel_style(colors, 200)
    assert "rgba(26, 31, 46, 200)" in frame and colors.accent in frame
    assert "font-size" not in frame


def test_every_group_of_readouts_stands_in_one_column_whatever_the_plan(qapp):
    view = TelemetryView(docked=False)
    groups = [FLIGHT, SYSTEMS, PILOT, WHERE]
    assert list(view._sections) == groups and COLUMN_CHOICES == (1, 2, 3)
    assert COLUMN_PLANS[1] == (tuple(groups),)          # one column: in their reading order
    for columns, plan in COLUMN_PLANS.items():
        assert len(plan) == columns
        assert sorted(name for column in plan for name in column) == sorted(groups)
        view._arrange(columns, 1.0)
        assert view.columns == columns
        for index, box in enumerate(view._column_boxes):
            wanted = plan[index] if index < columns else ()
            held = {name for name, group in view._sections.items() if box.indexOf(group) >= 0}
            assert held == set(wanted)
            places = [box.indexOf(view._sections[name]) for name in wanted]
            assert places == sorted(places)             # in the plan's order, top to bottom
            # A column with nothing in it takes no share of the width.
            assert view._body.stretch(index) == (1 if wanted else 0)
        assert not view.grab().isNull()
    # More columns are wider and less tall.
    one, two, three = (view.design_size(columns) for columns in COLUMN_CHOICES)
    assert one.width() < two.width() < three.width()
    assert one.height() > two.height() > three.height()
    assert one.width() >= design_width(1) and three.width() >= design_width(3)


def test_every_length_grows_with_the_scale(qapp):
    view = TelemetryView(docked=False)
    view.apply_colors(ODW_OVERLAY_COLORS)
    design = view.design_size()
    assert (view.columns, view.scale) == (1, 1.0)
    margins = view.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (14, 10, 14, 12)
    assert view.styleSheet() == readout_style(ODW_OVERLAY_COLORS, 1.0)

    view._arrange(1, 2.0)
    assert view.scale == 2.0
    margins = view.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (28, 20, 28, 24)
    assert view.layout().spacing() == 14 and view._body.spacing() == 2 * COLUMN_GAP
    assert view._lights_grid.horizontalSpacing() == 8 == view._lights_grid.verticalSpacing()
    assert view._vitals_grid.horizontalSpacing() == 16
    assert view._shield_rose.size() == QSize(2 * ShieldRose.SIZE, 2 * ShieldRose.SIZE)
    assert view._levels["hull"][0].height() == 2 * LevelBar.HEIGHT == 12
    assert view._levels["hull"][0].minimumWidth() == 2 * LevelBar.SHORTEST
    assert view._vitals["thirst"].height() == 12
    assert view._levels["hull"][1].minimumWidth() == 80
    assert view._pad.cells["top_left"].size() == QSize(32, 20)
    assert view.styleSheet() == readout_style(ODW_OVERLAY_COLORS, 2.0)
    # Twice the size, give or take what whole pixels cost.
    assert 1.85 * design.height() <= view.height_for(2 * design.width()) <= 2.15 * design.height()
    assert not view.grab().isNull()

    # Readouts made at that scale are that size too.
    view.show_sample(TelemetrySample(vitals=(("health", 0.4),)))
    assert view._vitals["health"].height() == 12
    assert view._vitals["health"].fill_color() == CAUTION_COLOR
    view._arrange(1, 1.0)
    assert view._vitals["health"].height() == LevelBar.HEIGHT
    assert view._shield_rose.size() == QSize(ShieldRose.SIZE, ShieldRose.SIZE)


@pytest.mark.parametrize("columns", COLUMN_CHOICES)
def test_a_frame_shaped_like_a_plan_gets_its_columns_at_the_scale_that_fits(qapp, columns):
    view = TelemetryView(docked=False)
    design = view.design_size(columns)
    assert (view.columns, view.scale) == (1, 1.0)       # measuring leaves it as it was
    # At a scale they take that share of their design's width, and are taller.
    larger = view.size_at(columns, 1.5)
    assert (view.columns, view.scale) == (1, 1.0)
    assert larger.width() >= math.ceil(design.width() * 1.5)
    assert 1.3 * design.height() < larger.height() < 1.7 * design.height()
    width, height = 2 * design.width(), 2 * design.height() + 30
    taken = view.fit_to(width, height)
    assert view.columns == columns
    assert 1.8 <= view.scale <= 2.0 and whole_steps(view.scale) == view.scale
    # What they take fits the frame: all its width, and the height they need.
    assert taken.width() == width and view.least_width() <= width
    assert taken.height() == view.height_for(width) <= height
    assert taken.height() >= 1.7 * design.height()      # and they fill most of it
    assert not view.grab().isNull()


def test_the_fewest_columns_win_when_more_would_be_no_larger(qapp):
    view = TelemetryView(docked=False)
    one, two = view.design_size(1), view.design_size(2)
    # Wide enough for two columns, but only as tall as one column at its smallest.
    taken = view.fit_to(two.width(), one.height())
    assert (view.columns, view.scale) == (1, 1.0)
    # One column takes its design's width and up to WIDEST times it, no more:
    # the rest of the frame is left round the readouts, not put between them.
    assert taken.width() == round(one.width() * WIDEST) < two.width()
    assert taken.height() == view.height_for(taken.width()) <= one.height()


def test_a_frame_too_small_keeps_one_column_at_the_smallest_scale(qapp):
    view = TelemetryView(docked=False)
    design = view.design_size()
    view.fit_to(2 * design.width(), 2 * design.height() + 30)
    assert view.scale > 1.5
    taken = view.fit_to(10, 10)
    assert (view.columns, view.scale) == (1, 1.0)
    assert taken == QSize(view.least_width(), view.height_for(view.least_width()))
    assert view.fit_to(design.width(), design.height()) == design       # and its design fits itself


def test_a_changed_text_is_measured_at_once(qapp):
    """Qt tells the layouts above a changed text as posted events are handled.
    The panel sizes itself right after a change, with no event handled yet, so
    the view brings its layouts up to date itself before it measures."""
    view = TelemetryView(docked=True)
    before = view.design_size()
    assert view.height_for(before.width()) == before.height()
    view.show_sample(TelemetrySample(location=("Stanton",) * 14))       # wraps onto more lines
    # Asked first, at the very width measured before, with nothing else measured since.
    assert view.height_for(before.width()) > before.height()
    assert view.design_size().height() > before.height()
    view.show_sample(TelemetrySample(vehicle_name="Cutlass Black of a Very Long Name Indeed"))
    assert view.least_width() > before.width()          # asked first here too
    assert view.design_size().width() > before.width()
    view.show_sample(SAMPLE)
    assert view.design_size() == before


def test_a_design_is_never_narrower_than_it_is_drawn_up(qapp, monkeypatch):
    """Each number of columns is drawn up at a width, so that every language
    starts from the same shape. Texts that need more make it wider, and texts
    that need less leave it as drawn up."""
    view = TelemetryView(docked=False)
    monkeypatch.setattr(view, "least_width", lambda: 10)
    assert [view.design_size(columns).width() for columns in COLUMN_CHOICES] == [300, 590, 880]
    assert [design_width(columns) for columns in COLUMN_CHOICES] == [300, 590, 880]
    view._designs.clear()
    monkeypatch.setattr(view, "least_width", lambda: 2000)
    assert [view.design_size(columns).width() for columns in COLUMN_CHOICES] == [2000] * 3


def test_what_does_not_fit_after_all_is_made_smaller(qapp):
    """The fit goes by the design's share of the frame, and whole pixels can
    cost more than that. Here the design is made out to be half its size, so
    the first guess is twice too large and has to be brought back."""
    view = TelemetryView(docked=False)
    design = view.design_size()
    half = QSize(design.width() // 2, design.height() // 2)
    never = QSize(10 ** 6, 10 ** 6)                     # two and three columns: out of it
    view._designs = {1: half, 2: never, 3: never}
    view.fit_to(design.width(), design.height())
    assert (view.columns, view.scale) == (1, 1.0)       # in one go, not a step at a time
    # In a frame too small even for that they are never drawn under their smallest.
    view._designs = {1: half, 2: never, 3: never}
    view.fit_to(round(design.width() * 0.8), round(design.height() * 0.8))
    assert (view.columns, view.scale) == (1, 1.0)
    # And a guess that fits is left alone.
    view._designs = {}
    view.fit_to(2 * design.width(), 2 * design.height() + 30)
    assert view.scale >= 1.8


# -- the separate window --------------------------------------------------------

def test_the_window_is_an_ordinary_one_that_takes_no_focus_and_keeps_nothing_open(qapp):
    window = TelemetryWindow()
    assert window.isWindow() and window.parent() is None
    assert window.windowType() == Qt.WindowType.Window
    # A title bar to drag it to another monitor by, and never forced on top.
    for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowStaysOnTopHint):
        assert not window.windowFlags() & flag, flag
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    # Never smaller than its readouts are in one column at their smallest.
    assert window.minimumSize() == window.view.design_size(1)
    assert window.minimumWidth() >= MINIMUM_WIDTH and window.minimumHeight() > 200
    assert window.windowTitle() == "Game Telemetry"
    asked = []
    window.dock_requested.connect(lambda: asked.append(True))
    window.view._switch_btn.click()
    assert asked == [True] and window.view._switch_btn.text() == "Dock"


def test_the_window_wears_the_overlays_colours_solid(qapp):
    window = TelemetryWindow()
    window.apply_colors(ODW_OVERLAY_COLORS)
    style = window._frame.styleSheet()
    assert style == panel_style(ODW_OVERLAY_COLORS, 255)
    assert "rgba(26, 31, 46, 255)" in style         # the ODW navy, nothing showing through
    assert ODW_OVERLAY_COLORS.accent in style
    assert window.view.styleSheet() == readout_style(ODW_OVERLAY_COLORS, window.view.scale)
    assert ODW_OVERLAY_COLORS.text in window.view.styleSheet()
    assert window.view._levels["hull"][0].fill_color() == ODW_OVERLAY_COLORS.accent
    assert window.view._vitals["health"].fill_color() == ODW_OVERLAY_COLORS.accent
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_the_window_title_follows_a_language_switch(qapp):
    from src.utils import i18n

    window = TelemetryWindow()
    i18n.set_language("german")                 # english_ui puts English back
    window.retranslate_ui()
    assert window.windowTitle() == "Spieltelemetrie"
    assert window.view._switch_btn.text() == "Andocken"


def test_a_language_switch_sizes_both_shells_as_if_they_were_built_in_it(qapp, monkeypatch):
    """The texts set how small the window can be, how its readouts fill it
    and how big the docked panel is, and a switch measures them again at once."""
    from src.utils import i18n

    # A screen picked by name, so its button reads the same in every language.
    _connect(monkeypatch, _screen(SCREEN_1), _screen(SCREEN_2))

    def built():
        window, dock = TelemetryWindow(), TelemetryDock()
        window.set_place("top_left", SCREEN_2)
        dock.set_place("top_left", SCREEN_2)
        window.show_window()
        window.resize(1100, 800)
        return window, dock

    def sizes(window, dock):
        return (window.minimumSize(), dock._panel.size(), window.view.columns,
                window.view.scale, window.view.size())

    window, dock = built()
    english = sizes(window, dock)
    i18n.set_language("french")                 # english_ui puts English back
    window.retranslate_ui()
    dock.retranslate_ui()
    fresh_window, fresh_dock = built()
    assert sizes(window, dock) == sizes(fresh_window, fresh_dock)
    assert sizes(window, dock) != english       # other words, another size
    assert dock._panel.size() == dock.view.design_size()
    window.hide()
    fresh_window.hide()


def test_a_long_screen_name_widens_both_shells(qapp, monkeypatch):
    """The place row can be the widest row, so both shells are measured again
    when the screen button's text changes."""
    monkeypatch.setattr(sco_telemetry, "SCREEN_LABEL_LENGTH", 80)
    long = "A Monitor With A Name That Goes On And On And On And On And On (1)"
    _connect(monkeypatch, _screen(long), _screen(SCREEN_2))
    window, dock = TelemetryWindow(), TelemetryDock()
    narrow = (window.minimumWidth(), dock._panel.width())
    window.set_place("top_left", long)
    dock.set_place("top_left", long)
    assert window.view._screen_btn.text() == dock.view._screen_btn.text() == long
    assert window.minimumWidth() > narrow[0] and dock._panel.width() > narrow[1]
    assert window.minimumSize() == window.view.design_size()
    assert dock._panel.size() == dock.view.design_size()
    window.set_place("top_left", GAME_SCREEN)           # and as narrow as before again
    dock.set_place("top_left", GAME_SCREEN)
    assert (window.minimumWidth(), dock._panel.width()) == narrow


def test_the_default_size_is_never_under_its_scales_share_of_the_design(qapp, monkeypatch):
    """The fit goes by the design's share of the window, so a window opened
    any smaller would show its readouts a step under DEFAULT_SCALE."""
    window = TelemetryWindow()
    share = math.ceil(window.view.design_size().height() * DEFAULT_SCALE)
    monkeypatch.setattr(window.view, "size_at", lambda columns, scale: QSize(400, 10))
    assert window.default_size() == QSize(400, share)
    monkeypatch.setattr(window.view, "size_at", lambda columns, scale: QSize(400, 10 ** 4))
    assert window.default_size() == QSize(400, 10 ** 4)     # nor under what they take


def test_only_the_players_own_close_is_reported(qapp):
    window = TelemetryWindow()
    closed = []
    window.closed_by_user.connect(lambda: closed.append(True))
    window.show_window()
    window.hide()                               # the tab's button closed it
    window.show_window()
    window.close()                              # closed from code
    assert closed == [] and not window.isVisible()
    window.show_window()
    window.windowHandle().close()               # so is a close of its QWindow
    assert closed == [] and not window.isVisible()
    _click_the_x(window)                        # a close that reaches it hidden
    assert closed == []
    window.show_window()
    _click_the_x(window)
    assert closed == [True] and not window.isVisible()


def test_the_window_opens_at_its_default_size_and_then_where_it_was_left(qapp):
    window = TelemetryWindow()
    window.show_window()
    view, design = window.view, window.view.design_size()
    assert window.size() == window.default_size()
    # Its readouts in one column, a little larger than their smallest, and
    # the window just the size they take.
    assert (view.columns, view.scale) == (1, DEFAULT_SCALE) and DEFAULT_SCALE > 1
    assert window.size() == view.size_at(1, DEFAULT_SCALE).expandedTo(
        QSize(0, math.ceil(design.height() * DEFAULT_SCALE)))
    assert window.width() >= math.ceil(design.width() * DEFAULT_SCALE) > window.minimumWidth()
    assert window.height() >= math.ceil(design.height() * DEFAULT_SCALE) > window.minimumHeight()
    assert view.width() == window.width() - OUTLINE
    assert 0 <= window.height() - OUTLINE - view.height() <= 0.05 * window.height()
    place = _place(window, 140, 30, 520)
    window.setGeometry(place)
    window.hide()                               # as when the button closes it
    window.show_window()
    assert window.geometry() == place           # the same window keeps its place
    window.hide()

    again = TelemetryWindow()                   # the next session
    again.show_window()
    assert again.geometry() == place
    again.hide()


def test_the_windows_readouts_grow_with_it_and_stay_in_its_middle(qapp):
    window = TelemetryWindow()
    window.show_window()
    view = window.view
    two = view.design_size(2)
    # Three times two columns' design, with room to spare below: wider than tall.
    window.resize(3 * two.width() + 40, 3 * two.height() + 200)
    qapp.processEvents()
    assert view.columns == 2 and 2.8 <= view.scale <= 3.05
    assert view.styleSheet() == readout_style(DEFAULT_OVERLAY_COLORS, view.scale)
    # The readouts take the window's width and the height they need.
    assert view.width() == window.width() - OUTLINE
    assert view.height() + OUTLINE == view.height_for(window.width()) < window.height() - 100
    # What is left over lies above and below them, half and half.
    frame, shape = window._frame.rect(), view.geometry()
    assert abs(shape.center().y() - frame.center().y()) <= 1
    assert shape.top() > 50 and frame.bottom() - shape.bottom() > 50

    # Nothing of the size the readouts have now holds the window to it: on
    # Windows a layout's height for the window's width is the least height
    # the window can then be given (measured), so no layout holds the view.
    assert not window.hasHeightForWidth()
    assert window.layout().totalMinimumSize().height() < 10
    assert window.minimumSize() == view.design_size(1)

    large = view.scale
    window.resize(window.width() // 2, window.height() // 2)        # smaller again
    assert 1.0 < view.scale < large
    window.resize(1, 1)                         # as small as it goes
    qapp.processEvents()
    assert window.size() == window.minimumSize()
    assert (view.columns, view.scale) == (1, 1.0)
    assert view.size() == window.size() - QSize(OUTLINE, OUTLINE)   # all of it, no margin
    window.hide()


def test_a_wide_low_window_gets_three_columns_and_a_tall_one_a_single_column(qapp):
    window = TelemetryWindow()
    window.show_window()
    view = window.view
    one, three = view.design_size(1), view.design_size(3)
    window.resize(2 * three.width(), max(2 * three.height() + 30, window.minimumHeight()))
    assert view.columns == 3 and view.scale > 1.0
    window.resize(2 * one.width(), 2 * one.height() + 30)
    assert view.columns == 1 and view.scale >= 1.8
    window.hide()


def test_a_saved_place_that_cannot_be_read_gives_the_default_size(qapp):
    AppSettings.set_sco_telemetry_window_geometry(b"not a saved geometry")
    window = TelemetryWindow()
    window.show_window()
    assert window.isVisible() and window.size() == window.default_size()
    window.hide()


def test_a_window_that_was_never_shown_saves_no_place(qapp):
    TelemetryWindow().hide()
    assert AppSettings.get_sco_telemetry_window_geometry() == b""


# -- the docked panel -----------------------------------------------------------

def test_the_docked_panel_is_an_overlay_window_that_never_takes_the_focus(qapp):
    dock = TelemetryDock()
    flags = dock.windowFlags()
    for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowStaysOnTopHint,
                 Qt.WindowType.WindowDoesNotAcceptFocus):
        assert flags & flag, flag
    assert dock.windowType() == Qt.WindowType.Tool
    for attribute in (Qt.WidgetAttribute.WA_TranslucentBackground,
                      Qt.WidgetAttribute.WA_ShowWithoutActivating,
                      Qt.WidgetAttribute.WA_AlwaysShowToolTips):
        assert dock.testAttribute(attribute), attribute
    assert not dock.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    assert dock.windowTitle() == "Game Telemetry"     # for tools and screen readers
    assert dock.view._switch_btn.text() == "Undock"
    asked = []
    dock.undock_requested.connect(lambda: asked.append(True))
    dock.view._switch_btn.click()
    assert asked == [True]


def test_the_docked_panel_wears_the_drawers_look(qapp):
    dock = TelemetryDock()
    dock.apply_colors(ODW_OVERLAY_COLORS)
    style = dock._panel.styleSheet()
    assert style == panel_style(ODW_OVERLAY_COLORS, DRAWER_ALPHA)
    assert f"rgba(26, 31, 46, {DRAWER_ALPHA})" in style       # see-through, as the drawer
    assert ODW_OVERLAY_COLORS.accent in style
    assert dock.view.styleSheet() == readout_style(ODW_OVERLAY_COLORS, 1.0)
    assert dock._handle.colors == ODW_OVERLAY_COLORS
    assert dock.view._levels["hull"][0].fill_color() == ODW_OVERLAY_COLORS.accent
    # The drawer's own tab bar, with the panel's one tab.
    assert dock._handle.sections == [TELEMETRY_TAB]
    assert dock._handle.tab_at(dock._handle.rect().center().toPointF()) == TELEMETRY_TAB
    assert dock._handle.current == TELEMETRY_TAB              # lit while the panel is open


@pytest.mark.parametrize("position", AppSettings.SCO_DRAWER_POSITIONS)
def test_it_docks_flush_at_each_of_the_drawers_positions(qapp, position):
    dock = TelemetryDock()
    dock.set_position(position)
    dock.show_docked()
    qapp.processEvents()
    area, shape = _screen_area(), dock.geometry()
    edge = drawer_edge(position)
    vertical, _, horizontal = position.partition("_")
    handle = dock._handle.geometry()
    panel = dock._panel.geometry()
    # Its readouts in one column at their smallest, however big the screen.
    assert (dock.view.columns, dock.view.scale) == (1, 1.0)
    assert panel.size() == dock.view.design_size() and dock._panel.isVisible()
    assert panel.width() >= DOCK_PANEL_WIDTH
    assert panel.height() == dock.view.height_for(panel.width())    # as tall as its readouts
    # The tab is turned to its edge: upright at a side, lying down at the top or bottom.
    assert dock._handle.edge == edge
    assert (handle.height() > handle.width()) is (edge in (LEFT, RIGHT))
    # The panel lies against the screen edge with the tab on its inner side.
    if edge == LEFT:
        assert shape.left() == area.left() and handle.left() == panel.right() + 1
    elif edge == RIGHT:
        assert shape.right() == area.right() and handle.right() + 1 == panel.left()
    elif edge == TOP:
        assert shape.top() == area.top() and handle.top() == panel.bottom() + 1
    else:
        assert edge == BOTTOM
        assert shape.bottom() == area.bottom() and handle.bottom() + 1 == panel.top()
    if vertical == "top":
        assert shape.top() == area.top()
    elif vertical == "bottom":
        assert shape.bottom() == area.bottom()
    else:
        assert abs(shape.center().y() - area.center().y()) <= 1
    if horizontal == "center":
        assert abs(shape.center().x() - area.center().x()) <= 1
    dock.hide()


def test_an_unknown_position_docks_at_the_default(qapp):
    dock = TelemetryDock()
    dock.set_position("somewhere else")
    assert dock._position == AppSettings.SCO_TELEMETRY_DOCK_POSITION_DEFAULT == "middle_left"
    assert dock.geometry().left() == _screen_area().left()


def test_its_tab_folds_the_panel_away_and_opens_it_out_again(qapp):
    dock = TelemetryDock()
    dock.set_position("middle_right")
    dock.show_docked()
    qapp.processEvents()
    changes = []
    dock.expanded_changed.connect(changes.append)
    open_size = dock.size()
    assert dock.is_expanded() and open_size.width() > DOCK_PANEL_WIDTH

    _click_the_tab(dock)
    assert changes == [False] and not dock.is_expanded() and not dock._panel.isVisible()
    assert dock.size() == dock._handle.size()                 # only the tab is left
    assert dock.geometry().right() == _screen_area().right()  # still on the edge
    assert dock._handle.current is None

    _click_the_tab(dock)
    assert changes == [False, True] and dock._panel.isVisible() and dock.size() == open_size
    assert dock.geometry().right() == _screen_area().right()
    dock.set_expanded(True)                                   # no change, nothing said
    assert changes == [False, True]
    dock.hide()


def test_clicks_pass_through_the_docked_panel_while_the_player_aims(qapp, monkeypatch):
    dock = TelemetryDock()
    answers = {"front": False, "hidden": False}
    monkeypatch.setattr(sco_telemetry, "game_in_front", lambda: answers["front"])
    monkeypatch.setattr(sco_telemetry, "pointer_hidden", lambda: answers["hidden"])
    assert not dock._pass_through_timer.isActive()            # asked only while it shows
    dock.show_docked()
    assert dock._pass_through_timer.isActive() and dock._screen_timer.isActive()
    assert not dock.pass_through
    assert dock._pass_through_timer.interval() == PASS_THROUGH_IDLE_POLL_MS

    answers.update(front=True, hidden=True)                   # the player aims
    dock._sync_pass_through()
    assert dock.pass_through and dock._pass_through_timer.interval() == PASS_THROUGH_POLL_MS
    answers.update(hidden=False)                              # F held: the pointer shows
    dock._sync_pass_through()
    assert not dock.pass_through and dock._pass_through_timer.interval() == PASS_THROUGH_POLL_MS
    answers.update(front=False, hidden=True)                  # another window is in front
    dock._sync_pass_through()
    assert not dock.pass_through
    assert dock._pass_through_timer.interval() == PASS_THROUGH_IDLE_POLL_MS

    dock.hide()
    assert not dock._pass_through_timer.isActive() and not dock._screen_timer.isActive()


def test_the_docked_panel_follows_the_game_to_its_screen(qapp, monkeypatch):
    other = _screen("", 1000, 100)
    where = {"screen": other}
    monkeypatch.setattr(sco_telemetry, "game_screen", lambda: where["screen"])
    dock = TelemetryDock()
    dock.set_position("top_left")
    dock.show_docked()                                        # asks where the game is
    assert dock.geometry().topLeft() == QPoint(1000, 100)
    where["screen"] = None                                    # the game moved back
    dock._follow_screen()
    assert dock.geometry().topLeft() == _screen_area().topLeft()
    dock.set_screen(other)
    dock._on_screen_removed(other)                            # a screen Qt is deleting
    assert dock.geometry().topLeft() == _screen_area().topLeft()
    dock.hide()


def test_the_docked_panel_sits_on_the_screen_picked_for_it(qapp, monkeypatch):
    """A picked screen wins over the game's while it is connected. Without it
    the panel is back with the game, and it returns when the screen does."""
    picked, games = _screen(SCREEN_2, 3000, 200), _screen(SCREEN_1, 1000, 100)
    connected = {"screens": [games, picked]}
    monkeypatch.setattr(sco_telemetry, "_screens", lambda: connected["screens"])
    monkeypatch.setattr(sco_telemetry, "game_screen", lambda: games)
    dock = TelemetryDock()
    dock.set_place("top_left", SCREEN_2)
    assert dock.geometry().topLeft() == QPoint(3000, 200)
    assert _lit(dock.view._pad) == ["top_left"] and dock.view._screen_btn.text() == SCREEN_2
    dock.show_docked()
    assert dock.geometry().topLeft() == QPoint(3000, 200)     # not where the game is
    dock.set_place("bottom_left", SCREEN_2)                   # another place on it
    assert dock.geometry().bottomLeft() == QRect(3000, 200, 640, 480).bottomLeft()

    connected["screens"] = [games]                            # taken away
    dock._follow_screen()                                     # its timer's tick
    assert dock.geometry().bottomLeft() == QRect(1000, 100, 640, 480).bottomLeft()
    connected["screens"] = [games, picked]                    # and back
    dock._follow_screen()
    assert dock.geometry().bottomLeft() == QRect(3000, 200, 640, 480).bottomLeft()

    dock.set_place("bottom_left", GAME_SCREEN)                # told to follow the game again
    assert dock.geometry().bottomLeft() == QRect(1000, 100, 640, 480).bottomLeft()
    assert dock.view._screen_btn.text() == "Game's screen"
    dock.hide()


# -- the panel: one shell or the other, as saved ---------------------------------

def test_the_dock_and_undock_buttons_switch_shells_and_are_remembered(qapp):
    panel = TelemetryPanel()
    assert not panel.is_open()
    panel.set_open(True)
    assert panel.window.isVisible() and not panel.dock.isVisible()      # a window, as it starts
    place = _place(panel.window)
    panel.window.setGeometry(place)

    panel.window.view._switch_btn.click()                               # Dock
    assert panel.dock.isVisible() and not panel.window.isVisible()
    assert AppSettings.get_sco_telemetry_window_docked() is True
    assert panel.dock.geometry().left() == _screen_area().left()        # middle left, the default

    panel.dock.view._switch_btn.click()                                 # Undock
    assert panel.window.isVisible() and not panel.dock.isVisible()
    assert AppSettings.get_sco_telemetry_window_docked() is False
    assert panel.window.geometry() == place                             # where it was left

    panel.set_open(False)
    assert not panel.window.isVisible() and not panel.dock.isVisible() and not panel.is_open()


def test_a_panel_left_docked_and_folded_opens_that_way(qapp):
    AppSettings.set_sco_telemetry_window_docked(True)
    AppSettings.set_sco_telemetry_dock_position("bottom_right")
    AppSettings.set_sco_telemetry_dock_expanded(False)
    panel = TelemetryPanel()
    panel.set_open(True)
    area = _screen_area()
    assert panel.dock.isVisible() and not panel.window.isVisible()
    assert not panel.dock.is_expanded() and panel.dock.size() == panel.dock._handle.size()
    assert panel.dock.geometry().bottomRight() == area.bottomRight()

    _click_the_tab(panel.dock)                                          # opened out: remembered
    assert AppSettings.get_sco_telemetry_dock_expanded() is True
    _click_the_tab(panel.dock)
    assert AppSettings.get_sco_telemetry_dock_expanded() is False
    panel.set_open(False)
    assert not panel.dock.isVisible()


def test_a_setting_change_moves_the_docked_panel_and_leaves_the_window_alone(qapp):
    panel = TelemetryPanel()
    panel.set_open(True)
    place = _place(panel.window, 90, 50, 480)
    panel.window.setGeometry(place)
    AppSettings.set_sco_telemetry_dock_position("top_right")
    panel.sync()                                                        # a picker changed
    assert panel.window.isVisible() and panel.window.geometry() == place
    assert _lit(panel.window.view._pad) == ["top_right"]                # shown on its pad

    panel.set_docked(True)
    area = _screen_area()
    assert panel.dock.geometry().topRight() == area.topRight()
    _click_the_tab(panel.dock)                                          # folded away
    AppSettings.set_sco_telemetry_dock_position("bottom_left")
    panel.sync()
    assert panel.dock.geometry().bottomLeft() == area.bottomLeft()
    assert not panel.dock.is_expanded()                                 # still folded
    assert _lit(panel.dock.view._pad) == ["bottom_left"] == _lit(panel.window.view._pad)
    panel.set_open(False)


def test_a_pick_on_either_pad_docks_the_panel_there_and_says_so(qapp):
    panel = TelemetryPanel()
    told = []
    panel.dock_position_changed.connect(told.append)
    panel.set_open(True)
    area = _screen_area()
    assert panel.window.isVisible()
    for view in (panel.window.view, panel.dock.view):
        assert _lit(view._pad) == ["middle_left"]                       # the default, on both

    panel.window.view._pad.cells["top_right"].click()                   # in the window: it docks
    assert told == ["top_right"]
    assert AppSettings.get_sco_telemetry_dock_position() == "top_right"
    assert AppSettings.get_sco_telemetry_window_docked() is True
    assert panel.dock.isVisible() and not panel.window.isVisible()
    assert panel.dock.geometry().topRight() == area.topRight()

    panel.dock.view._pad.cells["bottom_left"].click()                   # on the panel: it moves
    assert told == ["top_right", "bottom_left"]
    assert panel.dock.isVisible() and panel.dock.geometry().bottomLeft() == area.bottomLeft()
    for view in (panel.window.view, panel.dock.view):
        assert _lit(view._pad) == ["bottom_left"]

    panel.dock.view._switch_btn.click()                                 # Undock, then Dock:
    panel.window.view._switch_btn.click()                               # the place it had
    assert told == ["top_right", "bottom_left"]
    assert panel.dock.geometry().bottomLeft() == area.bottomLeft()
    panel.set_dock_position("no such place")                            # never saved as given
    assert told[-1] == "middle_left" == AppSettings.get_sco_telemetry_dock_position()
    panel.set_open(False)


def test_the_screen_button_takes_the_panel_to_the_next_screen(qapp, monkeypatch):
    _connect(monkeypatch, _screen(SCREEN_1, 1000, 100), _screen(SCREEN_2, 3000, 200))
    AppSettings.set_sco_telemetry_window_docked(True)
    AppSettings.set_sco_telemetry_dock_position("top_left")
    panel = TelemetryPanel()
    panel.set_open(True)
    button = panel.dock.view._screen_btn
    assert button.text() == "Game's screen" and not button.isHidden()
    assert panel.dock.geometry().topLeft() == _screen_area().topLeft()   # no game: the main screen

    button.click()
    assert AppSettings.get_sco_telemetry_dock_screen() == SCREEN_1
    assert panel.dock.geometry().topLeft() == QPoint(1000, 100) and button.text() == SCREEN_1
    button.click()
    assert panel.dock.geometry().topLeft() == QPoint(3000, 200)
    assert panel.window.view._screen_btn.text() == SCREEN_2             # the other shell shows it
    button.click()                                                      # round to the game's again
    assert AppSettings.get_sco_telemetry_dock_screen() == GAME_SCREEN
    assert panel.dock.geometry().topLeft() == _screen_area().topLeft()

    # In the window the button only picks: the window stays where it is.
    panel.dock.view._switch_btn.click()
    place = panel.window.geometry()
    panel.window.view._screen_btn.click()
    assert AppSettings.get_sco_telemetry_dock_screen() == SCREEN_1
    assert panel.window.isVisible() and panel.window.geometry() == place
    assert not panel.dock.isVisible()
    panel.window.view._switch_btn.click()                               # Dock: on the one picked
    assert panel.dock.geometry().topLeft() == QPoint(1000, 100)
    panel.set_open(False)


def test_a_screen_taken_away_or_plugged_in_changes_what_the_button_offers(qapp, monkeypatch):
    first = _screen(SCREEN_1, 1000, 100)
    connected = {"screens": [first, _screen(SCREEN_2, 3000, 200)]}
    monkeypatch.setattr(sco_telemetry, "_screens", lambda: connected["screens"])
    AppSettings.set_sco_telemetry_dock_screen(SCREEN_2)
    AppSettings.set_sco_telemetry_window_docked(True)
    AppSettings.set_sco_telemetry_dock_position("top_left")
    panel = TelemetryPanel()
    panel.set_open(True)
    button = panel.dock.view._screen_btn
    assert panel.dock.geometry().topLeft() == QPoint(3000, 200) and button.text() == SCREEN_2

    connected["screens"] = [first]                                      # taken away
    qapp.screenRemoved.emit(QGuiApplication.primaryScreen())            # as Qt says so
    assert panel.dock.geometry().topLeft() == _screen_area().topLeft()  # with the game again
    assert button.text() == "Game's screen" and button.isHidden()       # nothing to choose
    assert AppSettings.get_sco_telemetry_dock_screen() == SCREEN_2      # still asked for

    connected["screens"] = [first, _screen(SCREEN_2, 3000, 200)]        # plugged back in
    qapp.screenAdded.emit(QGuiApplication.primaryScreen())
    assert panel.dock.geometry().topLeft() == QPoint(3000, 200)
    assert button.text() == SCREEN_2 and not button.isHidden()

    panel.set_open(False)
    connected["screens"] = [first]
    panel._on_screens_changed(None)                                     # closed: left as it is
    assert button.text() == SCREEN_2
    assert not panel.dock.isVisible() and not panel.window.isVisible()


def test_the_panel_passes_on_the_windows_own_x_and_takes_the_apps_icon(qapp):
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.red)
    icon = QIcon(pixmap)
    panel = TelemetryPanel(icon)
    assert panel.window.windowIcon().cacheKey() == icon.cacheKey()
    closed = []
    panel.closed_by_user.connect(lambda: closed.append(True))
    panel.set_open(True)
    _click_the_x(panel.window)
    assert closed == [True] and not panel.window.isVisible()


def test_a_theme_swap_and_a_language_switch_reach_both_shells(qapp, monkeypatch):
    from src.utils import i18n

    panel = TelemetryPanel()
    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: ODW_OVERLAY_COLORS))
    panel.refresh_colors()
    assert ODW_OVERLAY_COLORS.accent in panel.window._frame.styleSheet()
    assert ODW_OVERLAY_COLORS.accent in panel.dock._panel.styleSheet()
    assert ODW_OVERLAY_COLORS.text in panel.window.view.styleSheet()
    assert ODW_OVERLAY_COLORS.text in panel.dock.view.styleSheet()
    assert panel.dock._handle.colors == ODW_OVERLAY_COLORS
    monkeypatch.setattr(OverlayColors, "from_theme",
                        classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    panel.set_open(True)                        # opening takes the theme's colours too
    assert DEFAULT_OVERLAY_COLORS.accent in panel.window._frame.styleSheet()
    assert DEFAULT_OVERLAY_COLORS.text in panel.window.view.styleSheet()
    panel.set_open(False)

    i18n.set_language("german")                 # english_ui puts English back
    panel.retranslate_ui()
    assert panel.window.windowTitle() == panel.dock.windowTitle() == "Spieltelemetrie"
    assert panel.window.view._switch_btn.text() == "Andocken"
    assert panel.dock.view._switch_btn.text() == "Abdocken"


# -- what is saved, and where it travels -----------------------------------------

def test_its_state_stays_on_this_pc_and_its_docked_position_travels(qapp):
    """Open or closed, docked or not, folded or not, the window's place and
    the screen it docks on are this PC's own, like the main window's place: a
    backup or Smart Sync would otherwise open, dock or move it on another PC,
    where a monitor's name means nothing. Where it docks is a preference, as
    the drawer's position is."""
    assert AppSettings.get_sco_telemetry_window_open() is False     # closed until asked for
    assert AppSettings.get_sco_telemetry_window_docked() is False   # a window until docked
    assert AppSettings.get_sco_telemetry_dock_expanded() is True
    assert AppSettings.get_sco_telemetry_dock_position() == "middle_left"
    assert AppSettings.get_sco_telemetry_dock_screen() == GAME_SCREEN == ""
    window = TelemetryWindow()
    window.show_window()
    window.hide()
    AppSettings.set_sco_telemetry_window_open(True)
    AppSettings.set_sco_telemetry_window_docked(True)
    AppSettings.set_sco_telemetry_dock_expanded(False)
    AppSettings.set_sco_telemetry_dock_position("top_right")
    AppSettings.set_sco_telemetry_dock_screen(SCREEN_2)
    assert AppSettings.get_sco_telemetry_window_open() is True
    assert AppSettings.get_sco_telemetry_window_docked() is True
    assert AppSettings.get_sco_telemetry_dock_expanded() is False
    assert AppSettings.get_sco_telemetry_window_geometry()
    assert AppSettings.get_sco_telemetry_dock_screen() == SCREEN_2

    exported = AppSettings.export_all_values()
    synced = AppSettings.smart_sync_settings_values()
    local = (AppSettings.SCO_TELEMETRY_WINDOW_OPEN, AppSettings.SCO_TELEMETRY_WINDOW_DOCKED,
             AppSettings.SCO_TELEMETRY_DOCK_EXPANDED, AppSettings.SCO_TELEMETRY_WINDOW_GEOMETRY,
             AppSettings.SCO_TELEMETRY_DOCK_SCREEN)
    for key in local:
        assert key not in AppSettings.profile_default_values(), key
        assert key not in exported and key not in synced, key
    # Nor does a backup that names them change anything here.
    assert AppSettings.import_values({key: False for key in local}) == 0
    assert AppSettings.get_sco_telemetry_window_open() is True
    assert AppSettings.get_sco_telemetry_dock_screen() == SCREEN_2
    AppSettings.set_sco_telemetry_dock_screen(None)                 # none: the game's screen
    assert AppSettings.get_sco_telemetry_dock_screen() == ""

    position = AppSettings.SCO_TELEMETRY_DOCK_POSITION
    assert AppSettings.profile_default_values()[position] == "middle_left"
    assert exported[position] == synced[position] == "top_right"
    AppSettings.set_sco_telemetry_dock_position("nowhere")          # not one of the eight
    assert AppSettings.get_sco_telemetry_dock_position() == "middle_left"


# -- MainWindow opens and closes it for the Overlay tab's button -----------------

def test_the_button_alone_opens_and_closes_the_panel(qapp):
    me = _Owner()
    me._sync_telemetry_window()
    assert me._telemetry is None                        # closed: nothing is even built
    me._set_telemetry_window_open(True)
    panel = me._telemetry
    assert panel.window.isVisible() and AppSettings.get_sco_telemetry_window_open() is True
    place = _place(panel.window, 100)
    panel.window.setGeometry(place)                     # the player moves it
    me._sync_telemetry_window()
    assert me._telemetry is panel
    assert panel.window.isVisible() and panel.window.geometry() == place
    me._set_telemetry_window_open(False)
    assert not panel.window.isVisible() and AppSettings.get_sco_telemetry_window_open() is False
    me._set_telemetry_window_open(True)                 # the same panel, where it was
    assert me._telemetry is panel
    assert panel.window.isVisible() and panel.window.geometry() == place
    panel.set_open(False)


def test_nothing_opens_once_the_app_is_closing(qapp):
    AppSettings.set_sco_telemetry_window_open(True)
    me = _Owner()
    me._close_committed = True
    me._sync_telemetry_window()
    assert me._telemetry is None
    me._close_committed = False
    me._sync_telemetry_window()
    assert me._telemetry.window.isVisible()
    me._close_committed = True
    me._sync_telemetry_window()
    assert not me._telemetry.window.isVisible() and not me._telemetry.dock.isVisible()


def test_the_tabs_button_opens_it_and_its_own_x_puts_the_button_back_to_open(qapp):
    tab = OverlayTab()
    me = _Owner(tab)
    tab.telemetry_window_toggled.connect(me._set_telemetry_window_open)
    asked = []
    tab.telemetry_window_toggled.connect(asked.append)
    tab._telemetry_btn.click()                          # the player's click
    window = me._telemetry.window
    assert window.isVisible() and tab._telemetry_btn.text() == CLOSE_TEXT
    place = _place(window, 110, 60, 480)
    window.setGeometry(place)

    _click_the_x(window)
    assert not window.isVisible()
    assert AppSettings.get_sco_telemetry_window_open() is False
    assert tab._telemetry_btn.text() == OPEN_TEXT
    assert asked == [True]                              # mirrored, not asked again
    me._sync_telemetry_window()
    assert not window.isVisible()                       # and it stays closed

    tab._telemetry_btn.click()                          # opened again, where it was
    assert asked == [True, True] and window.isVisible() and window.geometry() == place
    tab._telemetry_btn.click()                          # and closed by the button
    assert asked == [True, True, False] and not window.isVisible()
    assert AppSettings.get_sco_telemetry_window_open() is False


def test_a_place_picked_on_the_panel_shows_on_the_tabs_picker(qapp):
    tab = OverlayTab()
    me = _Owner(tab)
    changed = []
    tab.options_changed.connect(lambda: changed.append(True))
    me._set_telemetry_window_open(True)
    panel = me._telemetry
    combo = tab._telemetry_position_combo
    assert combo.currentData() == "middle_left"
    panel.window.view._pad.cells["bottom_right"].click()
    assert combo.currentData() == "bottom_right"
    assert AppSettings.get_sco_telemetry_dock_position() == "bottom_right"
    assert changed == []                                # shown, not announced as the tab's pick
    assert panel.dock.isVisible()
    panel.set_open(False)


def test_closing_the_app_hides_the_panel_saves_its_place_and_keeps_it_saved_as_open(
        qapp, monkeypatch):
    for setter in ("set_window_state", "set_window_geometry", "set_string_column_widths"):
        monkeypatch.setattr(AppSettings, setter, staticmethod(lambda *a, **k: None))
    AppSettings.set_sco_telemetry_window_open(True)
    panel = TelemetryPanel()
    closed = []
    panel.closed_by_user.connect(lambda: closed.append(True))
    panel.set_open(True)
    place = _place(panel.window, 120, 70, 480)
    panel.window.setGeometry(place)
    me = _closing_window()
    me._telemetry = panel

    MainWindow.closeEvent(me, MagicMock())

    assert not panel.window.isVisible() and not panel.is_open()
    # Not the player's X: it is still saved as open, so the next start opens it.
    assert closed == [] and AppSettings.get_sco_telemetry_window_open() is True
    again = TelemetryWindow()
    again.show_window()
    assert again.geometry() == place
    again.hide()


def test_a_cancelled_close_leaves_the_panel_open(qapp, monkeypatch):
    buttons = [MagicMock(name="apply"), MagicMock(name="exit"), MagicMock(name="cancel")]
    box = MagicMock()
    box.addButton.side_effect = list(buttons)
    box.clickedButton.return_value = buttons[2]
    monkeypatch.setattr(main_window_module, "QMessageBox", MagicMock(return_value=box))
    panel = TelemetryPanel()
    panel.set_open(True)
    me = _closing_window()
    me._session_has_unapplied_edit = True
    me._telemetry = panel

    MainWindow.closeEvent(me, MagicMock())

    assert panel.window.isVisible() and panel.is_open()
    panel.set_open(False)


# -- the assembled MainWindow, for what a stand-in cannot show ----------------

def test_on_the_real_window_the_button_docking_a_picker_and_the_x_all_reach_it(
        qapp, tmp_path, monkeypatch):
    """The tab's button opens the window with no overlay started, it carries
    the app's icon, its Dock button docks it, the tab's picker moves it and so
    does a pick on its own pad (which the tab's picker then shows), Undock
    brings the window back, a language switch rewords everything, a theme swap
    recolours it, and the window's own X puts the button back to Open."""
    from src.utils import i18n

    window = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
    try:
        tab = window.overlay_tab
        button = tab._telemetry_btn
        assert window._telemetry is None and button.text() == OPEN_TEXT
        button.click()                                  # the player's click
        panel = window._telemetry
        assert panel.window.isVisible() and panel.window.windowTitle() == "Game Telemetry"
        assert button.text() == CLOSE_TEXT
        assert AppSettings.get_sco_telemetry_window_open() is True
        assert window._sco_overlay is None              # no overlay was started for it
        assert not window.windowIcon().isNull()
        assert panel.window.windowIcon().cacheKey() == window.windowIcon().cacheKey()

        panel.window.view._switch_btn.click()           # Dock
        area = _screen_area()
        assert panel.dock.isVisible() and not panel.window.isVisible()
        assert panel.dock.geometry().left() == area.left()
        combo = tab._telemetry_position_combo           # the tab's picker moves it
        combo.setCurrentIndex(combo.findData("bottom_right"))
        assert panel.dock.geometry().bottomRight() == area.bottomRight()
        assert _lit(panel.dock.view._pad) == ["bottom_right"]
        panel.dock.view._pad.cells["top_right"].click()     # and so does its own pad
        assert panel.dock.geometry().topRight() == area.topRight()
        assert combo.currentData() == "top_right"       # which the tab's picker shows
        assert AppSettings.get_sco_telemetry_dock_position() == "top_right"

        monkeypatch.setattr(OverlayColors, "from_theme",
                            classmethod(lambda cls: ODW_OVERLAY_COLORS))
        window.refresh_action_buttons()                 # a live theme swap
        assert panel.dock._handle.colors == ODW_OVERLAY_COLORS

        panel.dock.view._switch_btn.click()             # Undock
        assert panel.window.isVisible() and not panel.dock.isVisible()

        i18n.set_language("german")                     # english_ui puts English back
        window.retranslate_ui()
        assert panel.window.windowTitle() == "Spieltelemetrie"
        assert panel.dock.view._switch_btn.text() == "Abdocken"
        assert button.text() == "Telemetrie schließen"

        _click_the_x(panel.window)
        assert not panel.window.isVisible()
        assert button.text() == "Telemetrie öffnen"
        assert AppSettings.get_sco_telemetry_window_open() is False
    finally:
        if window._telemetry is not None:
            window._telemetry.set_open(False)
        retire_main_window(window)


@pytest.mark.parametrize("docked", [False, True])
def test_a_panel_left_open_opens_again_as_it_was_when_the_app_next_starts(
        qapp, tmp_path, monkeypatch, docked):
    # What the last session left in the settings build_main_window uses.
    saved = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    saved.setValue(AppSettings.SCO_TELEMETRY_WINDOW_OPEN, True)
    saved.setValue(AppSettings.SCO_TELEMETRY_WINDOW_DOCKED, docked)
    saved.sync()
    window = build_main_window(tmp_path, monkeypatch, AppSettings.UI_MODE_ADVANCED)
    try:
        assert window.overlay_tab._telemetry_btn.text() == CLOSE_TEXT
        assert window._telemetry is None                # not before the main window shows
        window.show()
        # One pass of the event loop after the main window, so it opens above
        # it: opened inside showEvent it ended up behind (measured on Windows).
        assert window._telemetry is None
        qapp.processEvents()
        panel = window._telemetry
        assert panel.dock.isVisible() is docked and panel.window.isVisible() is not docked
    finally:
        if window._telemetry is not None:
            window._telemetry.set_open(False)
        retire_main_window(window)
