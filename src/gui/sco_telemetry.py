"""The game telemetry panel (a test): docked at a screen edge, or its own window.

For now it is a mock-up: it shows sample values (``SAMPLE``), because no game
build sends telemetry yet, and it reads nothing from the game.
``TelemetryPanel`` is what ``MainWindow`` drives. It shows one of two shells
around the same view:

* ``TelemetryDock``, a see-through panel with a tab at a screen edge, in the
  overlay drawer's look and on top of the game, and
* ``TelemetryWindow``, an ordinary window for another monitor, in the same
  colours, whose readouts grow with it and spread into columns
  (``TelemetryView.fit_to``).

The view's Dock and Undock buttons switch between the two, and its place row
says where the panel docks: a small map of the screen (``DockPad``) picks the
position and the button beside it the screen. The panel follows the Overlay
tab's button alone (``OverlayTab.telemetry_window_toggled``,
``MainWindow._sync_telemetry_window``), whether or not the overlay runs.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from PyQt6.QtCore import (
    QByteArray, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QGuiApplication, QPainter, QPainterPath, QPen, QPolygonF, QScreen,
)
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX, QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from src.gui.game_screen import game_screen
from src.gui.sco_overlay import (
    BOTTOM, DEFAULT_OVERLAY_COLORS, DRAWER_ALPHA, GAME_SCREEN_CHECK_MS, LEFT,
    PASS_THROUGH_IDLE_POLL_MS, PASS_THROUGH_POLL_MS, RIGHT, TOP, OverlayColors, SectionTabBar,
    drawer_edge, game_in_front, pointer_hidden, set_click_through, within_device_pixels,
)
from src.utils.i18n import tr
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)

# The frame both shells draw the drawer's look on, and the texts styled by name.
PANEL_NAME = "scoTelemetryPanel"
HEADING_NAME = "scoTelemetryHeading"
SHIP_NAME = "scoTelemetryShip"
SPEED_NAME = "scoTelemetrySpeed"
SHIELDS_NAME = "scoTelemetryShields"
# The frame's one-pixel outline, both sides.
OUTLINE = 2
# The readouts at their smallest: one column in a frame this wide. It is the
# separate window's narrowest width and the docked panel's width beside its
# tab (each a little wider where a language's texts need it).
MINIMUM_WIDTH = 300
DOCK_PANEL_WIDTH = MINIMUM_WIDTH
# The view's own margins (left, top, right, bottom), the gap between its rows
# and the gap between two columns of readouts, all at scale 1.
VIEW_MARGINS = (14, 10, 14, 12)
ROW_GAP = 7
COLUMN_GAP = 20
# How much wider each further column makes the design: a column and its gap.
COLUMN_STEP = MINIMUM_WIDTH - OUTLINE - VIEW_MARGINS[0] - VIEW_MARGINS[2] + COLUMN_GAP
# The separate window grows its readouts with it, in steps of SCALE_STEP so
# that a drag restyles them only now and then. A font comes in whole pixels,
# so a scale can need a little more room than its share of the design:
# FIT_TRIES corrections bring it back inside. The readouts take up to
# WIDEST times their design's width at that scale (their bars grow longer)
# and the height they need. What the window has beyond that lies round them
# as margin, never between them. The window opens at DEFAULT_SCALE the first
# time.
SCALE_STEP = 0.05
FIT_TRIES = 3
WIDEST = 1.3
DEFAULT_SCALE = 1.25
# The readouts' four groups, and which stand in which column by how many
# columns there are: balanced, so no column ends far above the others.
FLIGHT, SYSTEMS, PILOT, WHERE = "flight", "systems", "pilot", "where"
COLUMN_PLANS = {
    1: ((FLIGHT, SYSTEMS, PILOT, WHERE),),
    2: ((FLIGHT, PILOT), (SYSTEMS, WHERE)),
    3: ((FLIGHT,), (SYSTEMS,), (PILOT, WHERE)),
}
COLUMN_CHOICES = tuple(COLUMN_PLANS)
# The docked panel's one tab: its name is its tooltip's key (sco.section_...).
TELEMETRY_TAB = "telemetry"
# The docked panel: an overlay window like the drawer, which also never takes
# the focus. It has nothing to type in, so a click on its tab or its buttons
# leaves the keyboard with the game.
_DOCK_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)
# A dock pad cell's state, for the style sheet.
PLACE_PROPERTY, PLACE_FREE, PLACE_LIT = "place", "free", "lit"
# The saved screen choice that follows the game. Any other is a screen's name
# as Qt gives it: the monitor's own ("MSI MP275Q", with "(1)" and "(2)" after
# two of one model), or Windows' device name for a monitor that has none
# ("\\.\DISPLAY2"). The screen button shows at most SCREEN_LABEL_LENGTH
# characters of it.
GAME_SCREEN = ""
SCREEN_LABEL_LENGTH = 20
_DEVICE_PREFIX = "\\\\.\\"

# A readout's colour by how it stands: all well, take care, act now. A level
# is drawn in the theme's accent down to CAUTION_LEVEL, then in these.
NOMINAL_COLOR = "#5CFF8A"
CAUTION_COLOR = "#E8B84F"
WARNING_COLOR = "#E85F4F"
CAUTION_LEVEL = 0.5
WARNING_LEVEL = 0.25
# A warning light's state, as the game's VehicleAnnunciator gives it (its two
# flashing states shown as their steady ones).
LIGHT_OFF, LIGHT_NOMINAL, LIGHT_MINOR, LIGHT_MAJOR = "off", "nominal", "minor", "major"
LIGHTS_PER_ROW = 5


@dataclass(frozen=True)
class TelemetrySample:
    """What the view shows, shaped after the game's telemetry frames
    (sc.game.telemetry.v1: VehicleState with its flight instruments, shields
    and annunciators, ActorVitals, ActorLocation, GameDebugInfo). A level is a
    fraction from 0 to 1. The defaults are made-up values for the mock-up."""
    manufacturer: str = "Drake"
    vehicle_name: str = "Cutlass Black"
    master_mode: str = "SCM"
    speed: float = 212.0                    # metres a second
    g_force: float = 1.8
    shields: float = 0.86
    shield_faces: tuple = (0.95, 0.9, 0.42, 1.0)     # front, back, left, right
    hull: float = 0.97
    hydrogen_fuel: float = 0.64
    quantum_fuel: float = 0.41
    boost: float = 0.78
    annunciators: tuple = (
        ("PWR", LIGHT_NOMINAL), ("WPN", LIGHT_NOMINAL), ("THR", LIGHT_NOMINAL),
        ("SHLD", LIGHT_MINOR), ("COOL", LIGHT_NOMINAL), ("QDRV", LIGHT_OFF),
        ("RADR", LIGHT_NOMINAL), ("PROX", LIGHT_NOMINAL), ("HIT", LIGHT_MAJOR),
        ("MISL", LIGHT_NOMINAL))
    # Each vital by its name in the game's ActorVitals (its label: vital_label).
    vitals: tuple = (("health", 1.0), ("oxygen", 0.98), ("hunger", 0.72), ("thirst", 0.18))
    location: tuple = ("Stanton", "Crusader", "Orison")
    armistice_zone: bool = True
    fps: float = 74.0
    ping_ms: float = 38.0
    server_fps: float = 28.0


SAMPLE = TelemetrySample()
# The ship's level bars, by the sample's field. A bar's label is the text
# sco.telemetry_level_<field>.
LEVEL_BARS = ("hull", "hydrogen_fuel", "quantum_fuel", "boost")


def _telemetry_icon() -> QPainterPath:
    """A pulse line, on the drawer icons' 24-unit grid."""
    path = QPainterPath()
    path.moveTo(3, 13)
    for point in ((8, 13), (10.5, 6), (13.5, 19), (16, 13), (21, 13)):
        path.lineTo(*point)
    return path


def level_color(level: float, colors: OverlayColors) -> str:
    """A level's colour: the theme's accent while it is healthy, then the
    caution colour, then the warning colour."""
    if level >= CAUTION_LEVEL:
        return colors.accent
    return CAUTION_COLOR if level >= WARNING_LEVEL else WARNING_COLOR


def percent(level: float) -> str:
    return f"{round(level * 100)} %"


def vital_label(name: str) -> str:
    """A vital's label in the player's language (sco.telemetry_vital_<name>),
    or its name as the game gives it when the app has no word for it."""
    key = f"sco.telemetry_vital_{name}"
    text = tr(key)
    return name if text == key else text


def scaled(length: float, scale: float) -> int:
    """*length* (pixels at scale 1) at *scale*, in whole pixels. Nothing that
    has a size scales away to none."""
    return max(1, round(length * scale)) if length else 0


def whole_steps(scale: float) -> float:
    """*scale* taken down to a whole number of ``SCALE_STEP``."""
    return round(math.floor(scale / SCALE_STEP + 1e-6) * SCALE_STEP, 2)


def design_width(columns: int) -> int:
    """How wide the readouts' frame is drawn up in *columns* columns, at scale 1."""
    return MINIMUM_WIDTH + (columns - 1) * COLUMN_STEP


def _screens() -> list:
    """The connected screens (the tests' seam)."""
    return QGuiApplication.screens()


def screen_keys() -> list:
    """Every screen the docked panel can be told to use, as saved: the game's
    screen first (``GAME_SCREEN``), then each connected screen by its name
    (each name once, and no screen without one)."""
    keys = [GAME_SCREEN]
    for screen in _screens():
        if screen.name() not in keys:
            keys.append(screen.name())
    return keys


def resolved_screen_key(key: str) -> str:
    """*key* while that screen is connected, else ``GAME_SCREEN``: a screen
    that has gone leaves the panel following the game."""
    return key if key in screen_keys() else GAME_SCREEN


def next_screen_key(key: str) -> str:
    """The choice after *key*, round again from the last to the first."""
    keys = screen_keys()
    return keys[(keys.index(resolved_screen_key(key)) + 1) % len(keys)]


def screen_for_key(key: str) -> Optional[QScreen]:
    """The connected screen saved as *key*. None for ``GAME_SCREEN`` and for a
    screen that is not connected."""
    if key == GAME_SCREEN:
        return None
    return next((screen for screen in _screens() if screen.name() == key), None)


def screen_name(key: str) -> str:
    """A screen's name as the player knows it: Windows' own device prefix
    (``\\\\.\\``) is left off the name of a monitor that has no other."""
    return key.removeprefix(_DEVICE_PREFIX)


def screen_label(key: str) -> str:
    """What the screen button reads for *key*: the game's screen, or the
    screen's name, a long one cut in its middle so that two monitors of one
    model (which differ at the end, "(1)" and "(2)") still read apart."""
    if key == GAME_SCREEN:
        return tr("sco.telemetry_screen_game")
    name = screen_name(key)
    if len(name) <= SCREEN_LABEL_LENGTH:
        return name
    head = SCREEN_LABEL_LENGTH // 2
    return f"{name[:head]}…{name[head + 1 - SCREEN_LABEL_LENGTH:]}"


def _set_style(widget: QWidget, style: str) -> None:
    """Give *widget* the style sheet *style*, unless it has it already: a
    style sheet set again polishes every widget under it again."""
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)


def panel_style(colors: OverlayColors, alpha: int) -> str:
    """The drawer's look (``BlueprintDrawer.apply_colors``) for the frame that
    holds the view: the theme's window colour at *alpha* under an accent
    outline."""
    colour = QColor(colors.background)
    background = f"rgba({colour.red()}, {colour.green()}, {colour.blue()}, {alpha})"
    return f"""
        QFrame#{PANEL_NAME} {{
            background: {background};
            border: 1px solid {colors.accent};
        }}
    """


def readout_style(colors: OverlayColors, scale: float = 1.0) -> str:
    """The readouts' look at *scale*: the drawer's text colours and outlined
    buttons with the readouts' own sizes, the warning lights and the dock
    pad's cells. Every length grows with the scale, so the view looks the
    same at any size."""
    def px(length: float) -> str:
        return f"{scaled(length, scale)}px"

    line = px(1)
    pill = (f"border-radius: {px(3)}; font-size: {px(9)}; font-weight: bold;"
            f" padding: {px(1)} {px(4)};")
    cell = f"padding: 0px; border-radius: {px(2)};"
    return f"""
        QLabel {{ color: {colors.text}; background: transparent; font-size: {px(12)}; }}
        QLabel#{HEADING_NAME} {{
            color: {colors.accent}; font-size: {px(16)}; font-weight: bold;
        }}
        QLabel#{SHIP_NAME} {{ font-size: {px(14)}; font-weight: bold; }}
        QLabel#{SPEED_NAME} {{ font-size: {px(30)}; font-weight: bold; }}
        QLabel#{SHIELDS_NAME} {{ font-size: {px(18)}; font-weight: bold; }}
        QLabel[role="secondary"] {{ color: {colors.secondary}; font-size: {px(11)}; }}
        QLabel[light="{LIGHT_OFF}"] {{
            color: {colors.secondary}; border: {line} solid {colors.secondary}; {pill}
        }}
        QLabel[light="{LIGHT_NOMINAL}"] {{
            color: {NOMINAL_COLOR}; border: {line} solid {NOMINAL_COLOR}; {pill}
        }}
        QLabel[light="{LIGHT_MINOR}"] {{
            color: {colors.background}; background: {CAUTION_COLOR};
            border: {line} solid {CAUTION_COLOR}; {pill}
        }}
        QLabel[light="{LIGHT_MAJOR}"] {{
            color: {colors.background}; background: {WARNING_COLOR};
            border: {line} solid {WARNING_COLOR}; {pill}
        }}
        QLabel[tag="sample"] {{
            color: {CAUTION_COLOR}; border: {line} solid {CAUTION_COLOR}; {pill}
        }}
        QLabel[tag="mode"] {{
            color: {colors.accent}; border: {line} solid {colors.accent}; {pill}
        }}
        QPushButton {{
            color: {colors.text}; background: transparent; font-size: {px(12)};
            border: {line} solid {colors.secondary}; border-radius: {px(3)};
            padding: {px(1)} {px(8)};
        }}
        QPushButton:hover {{ border-color: {colors.accent}; color: {colors.accent}; }}
        QPushButton[{PLACE_PROPERTY}="{PLACE_FREE}"] {{ {cell} }}
        QPushButton[{PLACE_PROPERTY}="{PLACE_LIT}"] {{
            {cell} background: {colors.accent}; border-color: {colors.accent};
        }}
    """


class LevelBar(QWidget):
    """A thin bar for one level: a dim track with the level filled in, in the
    level's colour (``level_color``)."""

    HEIGHT = 6
    SHORTEST = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self._colors = DEFAULT_OVERLAY_COLORS
        self.set_scale(1.0)

    def set_level(self, level: float) -> None:
        self.level = min(max(float(level), 0.0), 1.0)
        self.update()

    def set_colors(self, colors: OverlayColors) -> None:
        self._colors = colors
        self.update()

    def set_scale(self, scale: float) -> None:
        self.setFixedHeight(scaled(self.HEIGHT, scale))
        self.setMinimumWidth(scaled(self.SHORTEST, scale))

    def fill_color(self) -> str:
        return level_color(self.level, self._colors)

    def paintEvent(self, _event):  # noqa: N802 (Qt's name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        whole = QRectF(self.rect())
        radius = whole.height() / 2
        track = QColor(self._colors.secondary)
        track.setAlpha(70)
        painter.setBrush(track)
        painter.drawRoundedRect(whole, radius, radius)
        if self.level > 0:
            filled = QRectF(whole)
            filled.setWidth(max(whole.height(), whole.width() * self.level))
            painter.setBrush(QColor(self.fill_color()))
            painter.drawRoundedRect(filled, radius, radius)
        painter.end()


class ShieldRose(QWidget):
    """The ship from above inside its four shield faces: front, back, left
    and right, each an arc that fades as the face drains and turns to the
    caution and warning colours when it is low."""

    SIZE = 68
    # Each face's arc: where it starts, counter-clockwise from three o'clock.
    # Front is up, as the ship's nose is.
    FACE_STARTS = (55, 235, 145, 325)       # front, back, left, right
    FACE_SPAN = 70

    def __init__(self, parent=None):
        super().__init__(parent)
        self.faces: tuple = (0.0, 0.0, 0.0, 0.0)
        self._colors = DEFAULT_OVERLAY_COLORS
        self.set_scale(1.0)

    def set_faces(self, faces) -> None:
        self.faces = tuple(min(max(float(face), 0.0), 1.0) for face in faces)
        self.update()

    def set_colors(self, colors: OverlayColors) -> None:
        self._colors = colors
        self.update()

    def set_scale(self, scale: float) -> None:
        side = scaled(self.SIZE, scale)
        self.setFixedSize(side, side)
        self.update()

    def paintEvent(self, _event):  # noqa: N802 (Qt's name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Drawn on a SIZE by SIZE grid, whatever size it has.
        painter.scale(self.width() / self.SIZE, self.height() / self.SIZE)
        ring = QRectF(5, 5, self.SIZE - 10, self.SIZE - 10)
        for start, face in zip(self.FACE_STARTS, self.faces):
            colour = QColor(level_color(face, self._colors))
            colour.setAlphaF(0.3 + 0.7 * face)
            pen = QPen(colour, 5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(ring, start * 16, self.FACE_SPAN * 16)
        centre = QPointF(self.SIZE / 2, self.SIZE / 2)
        hull = QPolygonF([centre + QPointF(0, -13), centre + QPointF(8, 10),
                          centre + QPointF(0, 5), centre + QPointF(-8, 10)])
        painter.setPen(QPen(QColor(self._colors.text), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(hull)
        painter.end()


class DockPad(QWidget):
    """A small map of the screen: a button at each place the panel docks at
    (``AppSettings.SCO_DRAWER_POSITIONS``, so none in the middle), with the
    place in use lit. A click on one asks to dock there (``picked``)."""

    picked = pyqtSignal(str)

    CELL_WIDTH, CELL_HEIGHT, GAP = 16, 10, 3
    ROWS = ("top", "middle", "bottom")
    COLUMNS = ("left", "center", "right")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self.position = ""
        self.cells: dict[str, QPushButton] = {}
        for row, vertical in enumerate(self.ROWS):
            for column, horizontal in enumerate(self.COLUMNS):
                position = f"{vertical}_{horizontal}"
                if position not in AppSettings.SCO_DRAWER_POSITIONS:
                    continue
                cell = QPushButton(self)
                cell.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                cell.setProperty(PLACE_PROPERTY, PLACE_FREE)
                cell.clicked.connect(
                    lambda _checked=False, place=position: self.picked.emit(place))
                self._grid.addWidget(cell, row, column)
                self.cells[position] = cell
        self.set_scale(1.0)
        self.retranslate_ui()

    def set_position(self, position: str) -> None:
        """Light the cell at *position* and put the others out."""
        self.position = position
        for place, cell in self.cells.items():
            state = PLACE_LIT if place == position else PLACE_FREE
            if cell.property(PLACE_PROPERTY) != state:
                cell.setProperty(PLACE_PROPERTY, state)
                # A property the style sheet reads shows after a fresh polish.
                cell.style().unpolish(cell)
                cell.style().polish(cell)

    def set_scale(self, scale: float) -> None:
        self._grid.setSpacing(scaled(self.GAP, scale))
        for cell in self.cells.values():
            cell.setFixedSize(scaled(self.CELL_WIDTH, scale), scaled(self.CELL_HEIGHT, scale))

    def retranslate_ui(self) -> None:
        """Each cell is named for its place, as the Overlay tab's pickers name it."""
        for place, cell in self.cells.items():
            name = tr(f"overlay.position_{place}")
            cell.setToolTip(name)
            cell.setAccessibleName(name)


class TelemetryView(QWidget):
    """What the telemetry panel shows, in either shell. A mock-up for now: a
    heading, the place row, a status line, and readouts filled with sample
    values (``show_sample``) under a "Sample data" tag: the ship with its
    speed, shield faces, levels and warning lights, the pilot's vitals, where
    they are and how the game runs.

    Its heading row holds the button that asks for the other shell
    (``switch_requested``): Undock on the docked panel, Dock in the window.
    Its place row shows where the panel docks (``set_place``): a pick on the
    pad is ``place_picked``, and the screen button asks for the next screen
    (``screen_cycle_requested``).

    The readouts stand in one column at scale 1 until ``fit_to`` gives them a
    frame to fill: then they take the number of columns (``COLUMN_PLANS``)
    that lets them grow largest and every length grows with them.
    """

    switch_requested = pyqtSignal()
    place_picked = pyqtSignal(str)
    screen_cycle_requested = pyqtSignal()

    def __init__(self, docked: bool, parent=None):
        super().__init__(parent)
        self._docked = docked
        self._colors = DEFAULT_OVERLAY_COLORS
        self._columns = COLUMN_CHOICES[0]
        self._scale = 1.0
        self._screen_key = GAME_SCREEN
        # What sets a length again at each change of scale, every layout
        # (see _settle), and how big the readouts are in each number of
        # columns at scale 1 (measured when asked for, and again after
        # anything that changes it).
        self._sizers: list[Callable[[Callable[[float], int]], None]] = []
        self._layouts: list = []
        self._designs: dict[int, QSize] = {}
        layout = self._box(QVBoxLayout(self), ROW_GAP, VIEW_MARGINS)

        heading_row = self._box(QHBoxLayout(), ROW_GAP)
        self._heading = QLabel()
        self._heading.setObjectName(HEADING_NAME)
        heading_row.addWidget(self._heading)
        heading_row.addStretch()
        self._switch_btn = self._button(self.switch_requested)
        heading_row.addWidget(self._switch_btn)
        layout.addLayout(heading_row)

        # Where it docks: the place on a small map of the screen, and the
        # screen on a button that steps through them.
        place_row = self._box(QHBoxLayout(), ROW_GAP)
        self._place_caption = self._caption()
        place_row.addWidget(self._place_caption)
        self._pad = DockPad()
        self._pad.picked.connect(self.place_picked)
        place_row.addWidget(self._pad)
        self._screen_btn = self._button(self.screen_cycle_requested)
        place_row.addWidget(self._screen_btn)
        place_row.addStretch()
        layout.addLayout(place_row)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # The readouts, in one to three columns side by side. They take any
        # room the frame has to spare.
        self._sections: dict[str, QWidget] = {}
        self._body = self._box(QHBoxLayout(), COLUMN_GAP)
        self._column_boxes = []
        for _ in range(max(COLUMN_CHOICES)):
            column = self._box(QVBoxLayout(), ROW_GAP)
            self._body.addLayout(column)
            self._column_boxes.append(column)
        layout.addLayout(self._body, 1)

        # The ship: who built it and what it is, and its master mode. Then
        # its speed on the left, the shield faces round the ship on the right.
        flight = self._section(FLIGHT)
        ship_row = self._box(QHBoxLayout(), ROW_GAP)
        self._sample_tag = self._pill("tag", "sample")
        ship_row.addWidget(self._sample_tag)
        self._ship = QLabel()
        self._ship.setObjectName(SHIP_NAME)
        ship_row.addWidget(self._ship)
        ship_row.addStretch()
        self._mode = self._pill("tag", "mode")
        ship_row.addWidget(self._mode)
        flight.addLayout(ship_row)
        flight_row = self._box(QHBoxLayout(), ROW_GAP)
        speed_box = self._box(QVBoxLayout(), 0)
        self._speed = QLabel()
        self._speed.setObjectName(SPEED_NAME)
        speed_box.addWidget(self._speed)
        self._speed_caption = self._caption()
        speed_box.addWidget(self._speed_caption)
        flight_row.addLayout(speed_box)
        flight_row.addStretch()
        shields_box = self._box(QVBoxLayout(), 0)
        shields_box.addStretch()
        self._shields = QLabel()
        self._shields.setObjectName(SHIELDS_NAME)
        self._shields.setAlignment(Qt.AlignmentFlag.AlignRight)
        shields_box.addWidget(self._shields)
        self._shields_caption = self._caption()
        self._shields_caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        shields_box.addWidget(self._shields_caption)
        shields_box.addStretch()
        flight_row.addLayout(shields_box)
        self._shield_rose = ShieldRose()
        flight_row.addWidget(self._shield_rose)
        flight.addLayout(flight_row)

        # The ship's systems. One bar a level: its label, the bar, its figure.
        # Then its warning lights, in the game's own order and wording.
        systems = self._section(SYSTEMS)
        levels = self._grid(8, 4)
        levels.setColumnStretch(1, 1)
        self._levels: dict[str, tuple[LevelBar, QLabel]] = {}
        self._level_captions: dict[str, QLabel] = {}
        for row, name in enumerate(LEVEL_BARS):
            bar, figure = LevelBar(), QLabel()
            figure.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._keep_sized(lambda px, figure=figure: figure.setMinimumWidth(px(40)))
            self._level_captions[name] = self._caption()
            levels.addWidget(self._level_captions[name], row, 0)
            levels.addWidget(bar, row, 1)
            levels.addWidget(figure, row, 2)
            self._levels[name] = (bar, figure)
        systems.addLayout(levels)
        self._lights_grid = self._grid(4, 4)
        self._lights: dict[str, QLabel] = {}
        systems.addLayout(self._lights_grid)

        # The pilot: one small bar a vital, two to a row.
        pilot = self._section(PILOT)
        self._pilot_caption = self._caption()
        pilot.addWidget(self._pilot_caption)
        self._vitals_grid = self._grid(8, 4)
        self._vitals: dict[str, LevelBar] = {}
        self._vital_captions: dict[str, QLabel] = {}
        pilot.addLayout(self._vitals_grid)

        # Where the pilot is, and how the game runs.
        where = self._section(WHERE)
        self._location = QLabel()
        self._location.setWordWrap(True)
        where.addWidget(self._location)
        self._game = self._caption()
        where.addWidget(self._game)

        self._note = self._caption()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        self._lay_out_columns()
        self.sample = SAMPLE
        self.show_sample(SAMPLE)
        self.retranslate_ui()
        self._restyle()

    @property
    def columns(self) -> int:
        """How many columns the readouts stand in."""
        return self._columns

    @property
    def scale(self) -> float:
        """How many times their smallest size the readouts are drawn at."""
        return self._scale

    @staticmethod
    def _caption(text: str = "") -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "secondary")
        return label

    @staticmethod
    def _pill(kind: str, value: str, text: str = "") -> QLabel:
        """A small outlined tag, styled by its *kind* property (``readout_style``)."""
        label = QLabel(text)
        label.setProperty(kind, value)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @staticmethod
    def _button(pressed) -> QPushButton:
        """A button that never takes the keyboard, which the game keeps."""
        button = QPushButton()
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(pressed)
        return button

    def _px(self, length: float) -> int:
        return scaled(length, self._scale)

    def _keep_sized(self, size: Callable[[Callable[[float], int]], None]) -> None:
        """Run *size* now and at every change of scale. It is handed what
        turns a length at scale 1 into pixels at the scale in use."""
        self._sizers.append(size)
        size(self._px)

    def _box(self, layout, gap: float, margins: tuple = (0, 0, 0, 0)):
        """*layout* with its gap and margins kept in step with the scale."""
        def size(px):
            layout.setContentsMargins(*(px(margin) for margin in margins))
            layout.setSpacing(px(gap))
        self._keep_sized(size)
        self._layouts.append(layout)
        return layout

    def _grid(self, across: float, down: float) -> QGridLayout:
        """A grid whose gaps across and down are kept in step with the scale."""
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        def size(px):
            layout.setHorizontalSpacing(px(across))
            layout.setVerticalSpacing(px(down))
        self._keep_sized(size)
        self._layouts.append(layout)
        return layout

    def _section(self, name: str) -> QVBoxLayout:
        """A group of readouts that moves between the columns as one."""
        group = QWidget()
        self._sections[name] = group
        return self._box(QVBoxLayout(group), ROW_GAP)

    def _lay_out_columns(self) -> None:
        """Stand each group in the column the plan gives it: a column's first
        group at its top and its last at its bottom, any room to spare shared
        out between them, and a group alone at the top."""
        plan = COLUMN_PLANS[self._columns]
        for index, column in enumerate(self._column_boxes):
            while column.count():
                column.takeAt(0)        # a group stays this view's, a stretch goes
            groups = plan[index] if index < len(plan) else ()
            for place, name in enumerate(groups):
                if place:
                    column.addStretch(1)
                column.addWidget(self._sections[name])
            if len(groups) == 1:
                column.addStretch(1)
            # A column with nothing in it takes no share of the width.
            self._body.setStretch(index, 1 if groups else 0)

    def show_sample(self, sample: TelemetrySample) -> None:
        """Fill every readout from *sample*."""
        self.sample = sample
        self._ship.setText(f"{sample.manufacturer.upper()} {sample.vehicle_name}")
        self._mode.setText(sample.master_mode)
        self._speed.setText(f"{round(sample.speed)}")
        self._shields.setText(percent(sample.shields))
        self._shield_rose.set_faces(sample.shield_faces)
        for name, (bar, figure) in self._levels.items():
            level = getattr(sample, name)
            bar.set_level(level)
            figure.setText(percent(level))
        self._fill_lights(sample.annunciators)
        self._fill_vitals(sample.vitals)
        self._word_sample()
        self._designs.clear()

    def _word_sample(self) -> None:
        """The readouts that are worded, in the language in use: set with
        each sample and again after a language switch."""
        sample = self.sample
        self._speed_caption.setText(tr("sco.telemetry_speed_line", g=f"{sample.g_force:.1f}"))
        place = " › ".join(sample.location)
        if sample.armistice_zone:
            place = f"{place}  ·  {tr('sco.telemetry_armistice')}"
        self._location.setText(place)
        self._game.setText(tr("sco.telemetry_game_line", fps=round(sample.fps),
                              ping=round(sample.ping_ms), server_fps=round(sample.server_fps)))
        for name, caption in self._vital_captions.items():
            caption.setText(vital_label(name))

    def _fill_lights(self, annunciators) -> None:
        while self._lights_grid.count():
            self._lights_grid.takeAt(0).widget().deleteLater()
        self._lights = {}
        for index, (name, state) in enumerate(annunciators):
            light = self._pill("light", state, name)
            self._lights_grid.addWidget(light, index // LIGHTS_PER_ROW, index % LIGHTS_PER_ROW)
            self._lights[name] = light

    def _fill_vitals(self, vitals) -> None:
        while self._vitals_grid.count():
            self._vitals_grid.takeAt(0).widget().deleteLater()
        self._vitals, self._vital_captions = {}, {}
        for index, (name, level) in enumerate(vitals):
            row, column = index // 2, (index % 2) * 2
            bar = LevelBar()
            bar.set_level(level)
            bar.set_colors(self._colors)
            bar.set_scale(self._scale)
            self._vital_captions[name] = self._caption()    # worded by _word_sample
            self._vitals_grid.addWidget(self._vital_captions[name], row, column)
            self._vitals_grid.addWidget(bar, row, column + 1)
            self._vitals_grid.setColumnStretch(column + 1, 1)
            self._vitals[name] = bar

    def _bars(self) -> Iterator[LevelBar]:
        """Every level bar: the ship's, then the pilot's."""
        for bar, _figure in self._levels.values():
            yield bar
        yield from self._vitals.values()

    def set_place(self, position: str, screen_key: str) -> None:
        """Show where the panel docks: *position* lit on the pad, and the
        screen saved as *screen_key* on the button beside it (the game's
        screen for one that is not connected). The button is hidden while
        there is only one screen to choose."""
        self._pad.set_position(position)
        self._screen_key = resolved_screen_key(screen_key)
        self._sync_screen_button()

    def _sync_screen_button(self) -> None:
        text = screen_label(self._screen_key)
        shown = len(screen_keys()) > 2
        if text != self._screen_btn.text() or shown == self._screen_btn.isHidden():
            self._screen_btn.setText(text)
            self._screen_btn.setVisible(shown)
            self._designs.clear()       # the place row can be the widest
        # What a click does, and under it the whole name of the screen picked.
        hint = tr("sco.telemetry_screen_hint")
        name = screen_name(self._screen_key)
        self._screen_btn.setToolTip(f"{hint}\n{name}" if name else hint)

    def apply_colors(self, colors: OverlayColors) -> None:
        """The theme's colours, for the texts and the readouts it paints itself."""
        self._colors = colors
        self._shield_rose.set_colors(colors)
        for bar in self._bars():
            bar.set_colors(colors)
        self._restyle()

    def _restyle(self) -> None:
        _set_style(self, readout_style(self._colors, self._scale))

    def retranslate_ui(self) -> None:
        """Set every text again (at construction and after a language switch)."""
        self._heading.setText(tr("sco.telemetry_title"))
        self._status.setText(tr("sco.telemetry_waiting"))
        self._sample_tag.setText(tr("sco.telemetry_sample").upper())
        self._note.setText(tr("sco.telemetry_placeholder"))
        action = "undock" if self._docked else "dock"
        self._switch_btn.setText(tr(f"sco.telemetry_{action}"))
        self._switch_btn.setToolTip(tr(f"sco.telemetry_{action}_hint"))
        self._place_caption.setText(tr("sco.telemetry_place"))
        self._pad.retranslate_ui()
        self._sync_screen_button()
        self._shields_caption.setText(tr("sco.telemetry_shields"))
        self._pilot_caption.setText(tr("sco.telemetry_pilot").upper())
        for name, caption in self._level_captions.items():
            caption.setText(tr(f"sco.telemetry_level_{name}"))
        self._word_sample()
        self._designs.clear()

    def _settle(self) -> None:
        """Bring every layout up to date for measuring. A changed text or
        size reaches the layouts above it only as posted events are handled.
        Until then a row inside another layout still answers with its old
        size, and so does a group for its place in its column."""
        for layout in (*self._layouts, self._pad.layout()):
            layout.invalidate()
        for group in (self._pad, *self._sections.values()):
            group.updateGeometry()

    def height_for(self, width: int) -> int:
        """How tall the view's frame is at *width*, its outline included, as
        the readouts are laid out now."""
        self._settle()
        return self.layout().totalHeightForWidth(width - OUTLINE) + OUTLINE

    def least_width(self) -> int:
        """The narrowest frame the readouts fit in as they are laid out now,
        its outline included."""
        self._settle()
        return self.layout().minimumSize().width() + OUTLINE

    def design_size(self, columns: int = COLUMN_CHOICES[0]) -> QSize:
        """How big the view's frame is in *columns* columns at scale 1: the
        width it is drawn up at (wider where a language's texts need it) and
        the height the readouts then take."""
        kept = (self._columns, self._scale)
        design = self._design(columns)
        self._arrange(*kept)
        return design

    def _design(self, columns: int) -> QSize:
        """As ``design_size``, but it leaves the readouts laid out for the
        measuring when it had to measure."""
        if columns not in self._designs:
            self._arrange(columns, 1.0)
            width = max(design_width(columns), self.least_width())
            self._designs[columns] = QSize(width, self.height_for(width))
        return self._designs[columns]

    def size_at(self, columns: int, scale: float) -> QSize:
        """The frame the readouts take in *columns* columns at *scale*:
        their design's width at that scale, and the height they need there
        (whole pixels cost a little more or less than the design's share)."""
        kept = (self._columns, self._scale)
        design = self._design(columns)
        self._arrange(columns, scale)
        width = max(self.least_width(), math.ceil(design.width() * scale))
        taken = QSize(width, self.height_for(width))
        self._arrange(*kept)
        return taken

    def fit_to(self, width: int, height: int) -> QSize:
        """Lay the readouts out for a frame of *width* by *height*: in the
        number of columns that lets them grow largest (the fewest, when it
        makes no difference), at the largest scale, never under 1, at which
        they still fit. Returns the frame they then take (``_taken``), for
        the shell to centre in the room it has."""
        columns, scale = COLUMN_CHOICES[0], 1.0
        for choice in COLUMN_CHOICES:
            design = self._design(choice)
            fits = whole_steps(min(width / design.width(), height / design.height()))
            if fits > scale:
                columns, scale = choice, fits
        self._arrange(columns, scale)
        taken = self._taken(width)
        for _ in range(FIT_TRIES):
            over = max(taken.width() / width, taken.height() / height)
            if over <= 1 or self._scale <= 1.0:
                break
            smaller = min(whole_steps(self._scale / over), round(self._scale - SCALE_STEP, 2))
            self._arrange(columns, max(1.0, smaller))
            taken = self._taken(width)
        return taken

    def _taken(self, width: int) -> QSize:
        """The frame the readouts take as they are laid out now, with
        *width* to be had: up to ``WIDEST`` times their design's width at
        the scale in use (never under their least width), and the height
        they need at that width."""
        drawn = self._design(self._columns).width() * self._scale
        wide = max(self.least_width(), min(width, round(drawn * WIDEST)))
        return QSize(wide, self.height_for(wide))

    def _arrange(self, columns: int, scale: float) -> None:
        if columns != self._columns:
            self._columns = columns
            self._lay_out_columns()
        if scale != self._scale:
            self._scale = scale
            for size in self._sizers:
                size(self._px)
            self._pad.set_scale(scale)
            self._shield_rose.set_scale(scale)
            for bar in self._bars():
                bar.set_scale(scale)
            self._restyle()


class TelemetryWindow(QWidget):
    """The telemetry panel as its own window, in the overlay's colours.

    A normal window with a title bar, so it can be dragged to another
    monitor, resized, maximised and snapped like any other. Its readouts
    fill it: they grow with it and spread into columns
    (``TelemetryView.fit_to``), so a large window shows large readouts, not
    wide gaps. Showing it never takes the focus (the game keeps the
    keyboard), and it does not keep the app alive when the main window
    closes. Its place and size are remembered
    (``AppSettings.get_/set_sco_telemetry_window_geometry``), and it is never
    smaller than its readouts need in one column at their smallest.

    ``closed_by_user`` says the player closed it with its own X (or Alt+F4),
    which puts the Overlay tab's button back to Open. Hiding it from code says
    nothing. ``dock_requested`` is its Dock button.
    """

    closed_by_user = pyqtSignal()
    dock_requested = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._placed = False

        self._frame = QFrame(self)
        self._frame.setObjectName(PANEL_NAME)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)
        # No layout holds the view: _fit places it in the frame's middle. In
        # a layout, the height the readouts have at the window's width is
        # the least height Windows then lets the window have, so it could
        # not be dragged smaller than its readouts happened to be (measured
        # on the Windows platform: the offscreen one does not do it).
        self.view = TelemetryView(docked=False, parent=self._frame)
        self.view.switch_requested.connect(self.dock_requested)

        self.apply_colors(DEFAULT_OVERLAY_COLORS)
        self.retranslate_ui()

    def apply_colors(self, colors: OverlayColors) -> None:
        """The overlay's colours, solid: a window has nothing to show through to."""
        _set_style(self._frame, panel_style(colors, 255))
        self.view.apply_colors(colors)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("sco.telemetry_title"))
        self.view.retranslate_ui()
        self._take_design()

    def set_place(self, position: str, screen_key: str) -> None:
        """Show where the panel docks on the view's place row."""
        self.view.set_place(position, screen_key)
        self._take_design()

    def _take_design(self) -> None:
        """The view's texts set how small the window can be, and how its
        readouts fill the size it has."""
        self.setMinimumSize(self.view.design_size())
        self._fit()

    def _fit(self) -> None:
        """Lay the readouts out for the size the window has, and put the
        view, at the size they take, in the middle of the window."""
        taken = self.view.fit_to(self.width(), self.height())
        size = QSize(taken.width() - OUTLINE, taken.height() - OUTLINE)
        corner = QPoint((self.width() - size.width()) // 2, (self.height() - size.height()) // 2)
        self.view.setGeometry(QRect(corner, size))

    def default_size(self) -> QSize:
        """The size it opens at before the player has placed it: what its
        readouts take in one column at ``DEFAULT_SCALE``, and never less
        than that share of their design, which is what the fit goes by."""
        taken = self.view.size_at(COLUMN_CHOICES[0], DEFAULT_SCALE)
        share = math.ceil(self.view.design_size().height() * DEFAULT_SCALE)
        return QSize(taken.width(), max(taken.height(), share))

    def show_window(self) -> None:
        """Show it where it was last left, or at its default size the first time."""
        if not self._placed:
            self._placed = True
            geometry = AppSettings.get_sco_telemetry_window_geometry()
            restored = bool(geometry) and self.restoreGeometry(QByteArray(geometry))
            if not restored:
                self.resize(self.default_size())
            logger.info("SCO: telemetry window opened %s",
                        "where it was left" if restored else "at its default size")
        self.show()

    def _remember_place(self) -> None:
        AppSettings.set_sco_telemetry_window_geometry(self.saveGeometry())

    def resizeEvent(self, event):  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self._fit()

    def hideEvent(self, event):  # noqa: N802 (Qt's name)
        # Every way it goes away (the tab's button, docking, the app closing,
        # its own X) ends in a hide, so this is the one place its place is saved.
        if self._placed:
            self._remember_place()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802 (Qt's name)
        super().closeEvent(event)
        # Only a close the window system sent (the X, Alt+F4) to the window
        # while it shows is the player's: close() from code is not, and nor is
        # a close that reaches it hidden (a tool closing the whole app).
        if event.isAccepted() and event.spontaneous() and self.isVisible():
            logger.info("SCO: telemetry window closed by the player")
            self.closed_by_user.emit()


class _TelemetryTab(SectionTabBar):
    """The drawer's tab bar with the telemetry panel's one tab, so the tab is
    drawn, turned to its edge and clicked exactly as the drawer's are."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons = {TELEMETRY_TAB: _telemetry_icon()}
        self.sections = [TELEMETRY_TAB]
        self._resize()


class TelemetryDock(QWidget):
    """The telemetry panel docked at a screen edge, in the overlay drawer's look.

    A see-through frameless window on top of the game, at one of the drawer's
    eight positions on the screen picked for it, or else the screen the game
    is on (``set_place``). Its tab lies on the screen edge and opens and
    closes the panel beside it (``set_expanded``, ``expanded_changed``). It
    never takes the focus, and while Star Citizen is in front with its
    pointer hidden (the player aiming) every click passes through it to the
    game, as with the drawer (``set_pass_through``). ``undock_requested`` is
    its Undock button.
    """

    undock_requested = pyqtSignal()
    expanded_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__(None, _DOCK_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._position = AppSettings.SCO_TELEMETRY_DOCK_POSITION_DEFAULT
        self._screen_choice = GAME_SCREEN
        self._screen: Optional[QScreen] = None
        self._expanded = True
        self.pass_through = False

        self._handle = _TelemetryTab(self)
        self._handle.set_current(TELEMETRY_TAB)     # lit: the panel starts opened out
        self._handle.clicked.connect(lambda _name: self.set_expanded(not self._expanded))
        self._panel = QFrame(self)
        self._panel.setObjectName(PANEL_NAME)
        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(0, 0, 0, 0)
        self.view = TelemetryView(docked=True)
        self.view.switch_requested.connect(self.undock_requested)
        inner.addWidget(self.view)

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._handle)
        self._layout.addWidget(self._panel)

        # Asked often only while the game is in front (see _sync_pass_through).
        self._pass_through_timer = QTimer(self)
        self._pass_through_timer.setInterval(PASS_THROUGH_IDLE_POLL_MS)
        self._pass_through_timer.timeout.connect(self._sync_pass_through)
        self._screen_timer = QTimer(self)
        self._screen_timer.setInterval(GAME_SCREEN_CHECK_MS)
        self._screen_timer.timeout.connect(self._follow_screen)
        QGuiApplication.instance().screenRemoved.connect(self._on_screen_removed)

        self.apply_colors(DEFAULT_OVERLAY_COLORS)
        self.retranslate_ui()
        self.set_position(self._position)

    def apply_colors(self, colors: OverlayColors) -> None:
        """The drawer's colours, see-through as the drawer is."""
        self._handle.colors = colors
        self._handle.update()
        _set_style(self._panel, panel_style(colors, DRAWER_ALPHA))
        self.view.apply_colors(colors)

    def retranslate_ui(self) -> None:
        # No title bar shows it, but tools and screen readers read the title.
        self.setWindowTitle(tr("sco.telemetry_title"))
        self.view.retranslate_ui()
        self._dock()    # the texts set the panel's size

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """Open the panel out from its tab, or fold it away to the tab alone."""
        was, self._expanded = self._expanded, bool(expanded)
        self._panel.setVisible(self._expanded)
        self._handle.set_current(TELEMETRY_TAB if self._expanded else None)
        self._dock()
        if self._expanded != was:
            self.expanded_changed.emit(self._expanded)

    def set_place(self, position: str, screen_key: str) -> None:
        """Dock at *position* on the screen saved as *screen_key* (the game's
        screen for ``GAME_SCREEN`` and while that screen is not connected),
        and show both on the view's place row."""
        self.view.set_place(position, screen_key)
        self._screen_choice = screen_key
        self._follow_screen()
        self.set_position(position)

    def set_position(self, position: str) -> None:
        """Dock to one of ``AppSettings.SCO_DRAWER_POSITIONS``."""
        if position not in AppSettings.SCO_DRAWER_POSITIONS:
            position = AppSettings.SCO_TELEMETRY_DOCK_POSITION_DEFAULT
        self._position = position
        edge = drawer_edge(position)
        self._handle.set_edge(edge)
        # As the drawer: the panel lies against the screen edge with the tab
        # on its inner side, and folded away only the tab shows, on the edge.
        self._layout.setDirection({
            RIGHT: QBoxLayout.Direction.LeftToRight,
            LEFT: QBoxLayout.Direction.RightToLeft,
            TOP: QBoxLayout.Direction.BottomToTop,
            BOTTOM: QBoxLayout.Direction.TopToBottom,
        }[edge])
        self._layout.setAlignment(
            self._handle,
            Qt.AlignmentFlag.AlignVCenter if edge in (LEFT, RIGHT)
            else Qt.AlignmentFlag.AlignHCenter)
        self._dock()

    def set_screen(self, screen: Optional[QScreen]) -> None:
        """Dock to *screen* (None: the primary screen), moving there at once."""
        self._screen = screen
        self._dock()

    def show_docked(self) -> None:
        self._follow_screen()
        self._dock()
        self.show()

    def _panel_size(self) -> QSize:
        """The open panel's size: its readouts in one column at their
        smallest, and never shorter than its tab."""
        design = self.view.design_size()
        return QSize(design.width(), max(design.height(), self._handle.height()))

    def _dock(self) -> None:
        """Place and size the window at its position, as the drawer docks."""
        display = self._screen or QGuiApplication.primaryScreen()
        screen = display.availableGeometry()
        edge = drawer_edge(self._position)
        vertical = self._position.partition("_")[0]
        handle = self._handle.size()
        panel = self._panel_size() if self._expanded else QSize(0, 0)
        self._panel.setFixedSize(self._panel_size())
        if edge in (LEFT, RIGHT):
            width = handle.width() + panel.width()
            height = max(handle.height(), panel.height())
        else:
            width = max(handle.width(), panel.width())
            height = handle.height() + panel.height()
        x = {LEFT: screen.x(), RIGHT: screen.right() - width + 1}.get(
            edge, screen.x() + (screen.width() - width) // 2)
        if vertical == "top":
            y = screen.y()
        elif vertical == "bottom":
            y = screen.bottom() - height + 1
        else:
            y = screen.y() + (screen.height() - height) // 2
        x, y = within_device_pixels(display, x, y, width, height)
        # In one step, the fixed size let go for it, as the drawer does: sized
        # first, a window can lie on the monitor beyond for a moment.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self.setGeometry(x, y, width, height)
        self.setFixedSize(width, height)

    def _follow_screen(self) -> None:
        """Dock on the screen picked for it while that one is connected, and
        otherwise on the screen Star Citizen is on (the primary one without
        the game)."""
        screen = screen_for_key(self._screen_choice) or game_screen()
        if screen is not self._screen:
            self.set_screen(screen)

    def _on_screen_removed(self, screen: QScreen) -> None:
        # Never keep a screen Qt is about to delete.
        if screen is self._screen:
            self.set_screen(None)

    def set_pass_through(self, on: bool) -> None:
        """Let every click through to the window below, the game (*on*), or
        take clicks again, on the window's own style as the drawer does."""
        self.pass_through = on
        # Only a real Windows window has the style. The offscreen platform the
        # tests run on gives made-up ids, which must never reach user32.
        if QGuiApplication.platformName() == "windows":
            set_click_through(int(self.winId()), on)

    def _sync_pass_through(self) -> None:
        """Clicks pass through to the game while Star Citizen is in front with
        its pointer hidden (the player aiming), so a shot fired as the hidden
        pointer crosses the panel never lands on its tab or its buttons. It
        takes clicks while the pointer shows or another window is in front.
        Asked often only while the game is in front: Qt runs a timer of 20 ms
        or less on a 1 ms Windows timer."""
        in_front = game_in_front()
        self.set_pass_through(in_front and pointer_hidden())
        interval = PASS_THROUGH_POLL_MS if in_front else PASS_THROUGH_IDLE_POLL_MS
        if self._pass_through_timer.interval() != interval:
            self._pass_through_timer.setInterval(interval)

    def showEvent(self, event):  # noqa: N802 (Qt's name)
        super().showEvent(event)
        self._sync_pass_through()
        self._pass_through_timer.start()
        self._screen_timer.start()

    def hideEvent(self, event):  # noqa: N802 (Qt's name)
        self._pass_through_timer.stop()
        self._screen_timer.stop()
        super().hideEvent(event)


class TelemetryPanel(QObject):
    """The telemetry panel as ``MainWindow`` drives it: open or closed
    (``set_open``), and while open one of its two shells, the docked panel or
    the separate window, as saved. The shells' Dock and Undock buttons switch
    and save which (``set_docked``), a pick on either shell's pad docks the
    panel at that place (``set_dock_position``, announced with
    ``dock_position_changed`` for the Overlay tab's picker) and either
    shell's screen button moves it to the next screen (``cycle_dock_screen``).
    ``closed_by_user`` is the window's own X."""

    closed_by_user = pyqtSignal()
    dock_position_changed = pyqtSignal(str)

    def __init__(self, icon=None, parent=None):
        super().__init__(parent)
        self.window = TelemetryWindow()
        self.dock = TelemetryDock()
        if icon is not None:
            self.window.setWindowIcon(icon)
        self.window.closed_by_user.connect(self.closed_by_user)
        self.window.dock_requested.connect(lambda: self.set_docked(True))
        self.dock.undock_requested.connect(lambda: self.set_docked(False))
        self.dock.expanded_changed.connect(AppSettings.set_sco_telemetry_dock_expanded)
        for shell in (self.window, self.dock):
            shell.view.place_picked.connect(self.set_dock_position)
            shell.view.screen_cycle_requested.connect(self.cycle_dock_screen)
        # A screen plugged in or taken away changes what the screen button offers.
        screens = QGuiApplication.instance()
        screens.screenAdded.connect(self._on_screens_changed)
        screens.screenRemoved.connect(self._on_screens_changed)
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def set_open(self, is_open: bool) -> None:
        """Show the shell in use, or hide both. Hiding saves the window's place."""
        self._open = bool(is_open)
        self.sync()

    def set_docked(self, docked: bool) -> None:
        """Dock at the screen edge (True) or be its own window, saved."""
        AppSettings.set_sco_telemetry_window_docked(docked)
        logger.info("SCO: telemetry panel %s", "docked" if docked else "undocked")
        self.sync()

    def set_dock_position(self, position: str) -> None:
        """Dock at *position*, saved: a pick on either shell's pad. Picked in
        the separate window, it docks the panel there."""
        AppSettings.set_sco_telemetry_dock_position(position)
        position = AppSettings.get_sco_telemetry_dock_position()
        logger.info("SCO: telemetry panel docks at %s", position)
        self.dock_position_changed.emit(position)
        self.set_docked(True)

    def cycle_dock_screen(self) -> None:
        """Dock on the next screen there is to choose, saved: either shell's
        screen button. A docked panel moves there at once."""
        key = next_screen_key(AppSettings.get_sco_telemetry_dock_screen())
        AppSettings.set_sco_telemetry_dock_screen(key)
        logger.info("SCO: telemetry panel docks on %s", key or "the game's screen")
        self.sync()

    def sync(self) -> None:
        """Show the saved shell at its saved place in the theme's colours.
        Run again when a setting changes: nothing already showing is shown
        again, so a window the player moved stays where it is."""
        if not self._open:
            self.dock.hide()
            self.window.hide()
            return
        colors = OverlayColors.from_theme()
        self._show_place()
        if AppSettings.get_sco_telemetry_window_docked():
            self.window.hide()
            self.dock.apply_colors(colors)
            if not self.dock.isVisible():
                self.dock.set_expanded(AppSettings.get_sco_telemetry_dock_expanded())
                self.dock.show_docked()
        else:
            self.dock.hide()
            self.window.apply_colors(colors)
            if not self.window.isVisible():
                self.window.show_window()

    def _show_place(self) -> None:
        """Hand both shells the saved place: the docked panel moves to it,
        and each shows it on its place row."""
        position = AppSettings.get_sco_telemetry_dock_position()
        screen_key = AppSettings.get_sco_telemetry_dock_screen()
        self.window.set_place(position, screen_key)
        self.dock.set_place(position, screen_key)

    def _on_screens_changed(self, _screen: QScreen) -> None:
        if self._open:
            self._show_place()

    def refresh_colors(self) -> None:
        """Take the theme's colours again after a live theme swap."""
        colors = OverlayColors.from_theme()
        self.dock.apply_colors(colors)
        self.window.apply_colors(colors)

    def retranslate_ui(self) -> None:
        self.window.retranslate_ui()
        self.dock.retranslate_ui()
