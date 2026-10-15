"""Smart Citizen Overlay (SCO): always-on-top windows drawn over the game.

Two windows, because they need opposite input behaviour:

- ``ScanLabelWindow`` shows the decoded mining signature ("2 x Bexalite")
  just under the scanner's signature readout. Clicks pass straight through
  it to the game.
- ``BlueprintDrawer`` is a stack of three icon tabs on a screen edge, one per
  searchable section: blueprints with owned checkboxes, minerals by star
  system and location, and crafting (mineral to items and back). A tab opens
  the drawer straight to its section. It
  has to take clicks, so using it takes focus from the game; the player
  needs a free cursor.

``ScoOverlay`` owns both, plus the capture timer. The reader that turns a
capture of the signature panel into text is pluggable (``SignatureReader``);
the default, ``hud_signature_reader``, matches the HUD's digits against
reference glyphs (``src/utils/sco_digit_reader.py``). With no reader set, no
screen capture runs at all.

Overlays only draw over Star Citizen in borderless windowed mode, not
exclusive fullscreen. SCO only captures the screen; it never reads game
memory or sends input.

Data comes from ``MainWindow``: ``{name: BlueprintItem}`` metadata and the
owned set, plus the Mining Compendium minerals and the crafting index
(``src/utils/mining_catalog.py``). Owned changes made in the drawer go back out through
``owned_toggled`` so ``MainWindow`` stays the one writer of the owned set.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QObject, QPoint, QPointF, QRect, QRunnable, Qt, QThreadPool, QTimer,
    QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPalette, QPen,
    QTransform,
)
from PyQt6.QtWidgets import (
    QBoxLayout, QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.utils.i18n import tr
from src.utils.mining_catalog import (
    CraftingIndex, MineralInfo, locations_by_system, minerals_at, ore_key,
    ore_signature, star_system,
)
from src.utils.mining_signatures import (
    OTHER_SIGNATURES, SignatureMatch, decode_signature, parse_signature_text,
)
from src.utils.sco_digit_reader import DIGIT_HEIGHT_AT_1600, read_signature
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)

# Where the scanner's signature readout sits, as fractions of the primary
# screen (x, y, w, h). Measured from 2560x1600 Drake Golem screenshots: the
# pin + number sit in a small panel under the cockpit radar screen, top
# centre. In-game checks found the area is the same across cockpits; the box is
# padded for head movement (~115 px between the two samples).
SCAN_REGION = (0.38, 0.28, 0.24, 0.12)
CAPTURE_INTERVAL_MS = 250
# A crop of each distinct reading (named after the text read) is kept so
# misreads can be fixed by adding reference glyphs (scripts/add_sco_sample.py).
# On by default in every build ("Save scan samples" on the Overlay tab).
# Capped per session, and the folder keeps only the newest MAX_SAMPLES_KEPT.
MAX_SAMPLES_PER_SESSION = 200
MAX_SAMPLES_KEPT = 1000
SAMPLE_PADDING = 12
# Hide a reading this long after the number was last seen.
LABEL_HOLD_MS = 1500
# Gap between the readout's baseline and the label, in screen px. Keeps the
# label clear of the digits while the readout bobs with head movement.
LABEL_GAP = 10
# Room around the label for its glow when it decodes a watched mineral. The
# top stays under LABEL_GAP so the label window (masked out of each capture)
# never covers the readout's own digits.
GLOW_MARGIN = 12
GLOW_TOP_MARGIN = LABEL_GAP - 2
# One glow pulse (bright and back), in ms, and its blur radius range in px.
GLOW_PULSE_MS = 1400
GLOW_BLUR = (6, 22)
# A new reading must repeat on this many captures in a row before it replaces
# the label, so a one-frame misread can't flash "Unidentified".
READINGS_TO_CHANGE = 2
NEW_BLUEPRINT_BANNER_MS = 8000

# One section tab: thickness off the edge, length along it, and the share
# of its length each tapered end takes. Neighbouring tabs overlap by the
# taper, so their slanted ends meet.
DRAWER_HANDLE_WIDTH = 22
DRAWER_HANDLE_HEIGHT = 48
DRAWER_HANDLE_TAPER = 0.15
DRAWER_HANDLE_OVERLAP = round(DRAWER_HANDLE_HEIGHT * DRAWER_HANDLE_TAPER)
DRAWER_ICON_SIZE = 14
DRAWER_PANEL_WIDTH = 340
# Share of the screen an open drawer takes along its edge: the full side
# for a left/right drawer, less for a top/bottom one, which sits over the
# middle of the view.
DRAWER_SIDE_LENGTH = 0.7
DRAWER_TOP_BOTTOM_LENGTH = 0.5
# Screen edge each drawer position docks to (see AppSettings.SCO_DRAWER_POSITIONS).
LEFT, RIGHT, TOP, BOTTOM = "left", "right", "top", "bottom"
# Missions listed in a blueprint's tooltip before "...and N more".
TOOLTIP_MAX_MISSIONS = 12
# How much of the game shows through the drawer: 0 = invisible, 255 = solid.
DRAWER_ALPHA = 184
# The open section's tab is nearly solid, so it reads as in front.
DRAWER_HANDLE_SELECTED_ALPHA = 240

# A reader takes a capture of SCAN_REGION and returns the HUD text it found
# ("10,200") and where, in capture coordinates, or None when nothing is shown.
SignatureReader = Callable[[QImage], Optional[tuple[str, QRect]]]


def hud_signature_reader(image: QImage) -> Optional[tuple[str, QRect]]:
    """The default ``SignatureReader``: digit matching on the red channel."""
    if image.isNull():
        return None
    rgb = image.convertToFormat(QImage.Format.Format_RGB32)
    width, height = rgb.width(), rgb.height()
    data = rgb.constBits().asstring(rgb.sizeInBytes())
    # Format_RGB32 is 0xffRRGGBB per pixel: B, G, R, A in memory on x86.
    red, green, blue = data[2::4], data[1::4], data[0::4]
    # The capture spans SCAN_REGION's height, so this is the screen height.
    screen_height = height / SCAN_REGION[3]
    reading = read_signature(width, height, red, DIGIT_HEIGHT_AT_1600 * screen_height / 1600,
                             green=green, blue=blue)
    if reading is None:
        return None
    return reading.text, QRect(*reading.box)


_OVERLAY_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
)


@dataclass(frozen=True)
class OverlayColors:
    """Drawer colours, taken from the Smart Citizen theme in use."""
    background: str   # the theme's window colour (drawn at DRAWER_ALPHA)
    text: str
    accent: str       # outline, arrow, header, checked boxes
    secondary: str    # counts, placeholder text

    @classmethod
    def from_theme(cls) -> "OverlayColors":
        from src.gui.theme import get_tagline_color, get_title_color
        palette = QGuiApplication.palette()
        return cls(
            background=palette.color(QPalette.ColorRole.Window).name(),
            text=palette.color(QPalette.ColorRole.WindowText).name(),
            accent=get_title_color(),
            secondary=get_tagline_color(),
        )


# The default SCLE theme, used until a theme is applied (and in tests).
DEFAULT_OVERLAY_COLORS = OverlayColors(
    background="#0d1826", text="#d8e8f0", accent="#4FD7E8", secondary="#6FB5D0",
)

# The signature label always uses the ODW theme (navy, cream, Osiris gold),
# whatever theme the app runs in. Same values as theme.py's ODW palette.
ODW_OVERLAY_COLORS = OverlayColors(
    background="#1A1F2E", text="#F0E6CF", accent="#C9A961", secondary="#A08C5A",
)


def _rgba(hex_color: str, alpha: int = DRAWER_ALPHA) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def scan_region_rect(screen_rect: QRect) -> QRect:
    """SCAN_REGION resolved against a screen's geometry."""
    fx, fy, fw, fh = SCAN_REGION
    return QRect(
        screen_rect.x() + int(screen_rect.width() * fx),
        screen_rect.y() + int(screen_rect.height() * fy),
        int(screen_rect.width() * fw),
        int(screen_rect.height() * fh),
    )


def format_matches(matches: list[SignatureMatch]) -> str:
    """One line per reading: "2 x Bexalite", "3 x ROC Mineable", ...

    No readings (a deposit missing from the table, or a misread) shows
    "Unidentified".
    """
    if not matches:
        return tr("sco.unidentified")
    lines = []
    for m in matches:
        if m.kind in OTHER_SIGNATURES:
            name = tr(f"sco.kind_{m.kind}")
        else:
            name = m.kind.title()
        lines.append(f"{m.count} × {name}")
    return "\n".join(lines)


class ScanLabelWindow(QWidget):
    """Click-through label that shows the decoded signature."""

    def __init__(self):
        super().__init__(None, _OVERLAY_FLAGS
                         | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glow_color = DEFAULT_OVERLAY_COLORS.accent
        self.glowing = False
        self._glow = QGraphicsDropShadowEffect(self._label)
        self._glow.setOffset(0, 0)
        self._glow.setEnabled(False)
        self._label.setGraphicsEffect(self._glow)
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(GLOW_PULSE_MS)
        self._pulse.setStartValue(0.0)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setEndValue(0.0)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)
        self._restyle()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(GLOW_MARGIN, GLOW_TOP_MARGIN, GLOW_MARGIN, GLOW_MARGIN)
        layout.addWidget(self._label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, anchor: QPoint, glowing: bool = False) -> None:
        """Show *text* centred under *anchor*: the middle of the box's top
        edge sits on that point (screen coordinates). *glowing* pulses the
        border in the theme colour (a watched mineral)."""
        self._label.setText(text)
        self.set_glowing(glowing)
        self.adjustSize()
        self.move(anchor.x() - self.width() // 2, anchor.y() - GLOW_TOP_MARGIN)
        self.show()
        self._hide_timer.start(LABEL_HOLD_MS)

    def set_glow_color(self, color: str) -> None:
        """The theme colour the glow pulses in (the label keeps ODW colours)."""
        self._glow_color = color
        self._restyle()

    def set_glowing(self, glowing: bool) -> None:
        if glowing == self.glowing:
            return
        self.glowing = glowing
        self._glow.setEnabled(glowing)
        if glowing:
            self._pulse.start()
        else:
            self._pulse.stop()
        self._restyle()

    def _restyle(self) -> None:
        c = ODW_OVERLAY_COLORS
        border = self._glow_color if self.glowing else c.accent
        self._label.setStyleSheet(
            f"QLabel {{ color: {c.text}; background: {_rgba(c.background)};"
            f" border: {2 if self.glowing else 1}px solid {border}; border-radius: 4px;"
            " padding: 2px 8px; font-weight: bold; }"
        )

    def _on_pulse(self, value: float) -> None:
        low, high = GLOW_BLUR
        self._glow.setBlurRadius(low + (high - low) * value)
        color = QColor(self._glow_color)
        color.setAlpha(int(90 + 165 * value))
        self._glow.setColor(color)

    def hideEvent(self, event):
        self._pulse.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self.glowing:
            self._pulse.start()
        super().showEvent(event)


def drawer_edge(position: str) -> str:
    """The screen edge a drawer position docks to: its side, or the top or
    bottom edge for the two centre positions."""
    vertical, _, horizontal = position.partition("_")
    if horizontal == "center":
        return BOTTOM if vertical == "bottom" else TOP
    return LEFT if horizontal == "left" else RIGHT


def _arc(path: QPainterPath, center: tuple[float, float], radius: float,
         end: tuple[float, float]) -> None:
    """Counter-clockwise arc from the path's current point to ``end``."""
    cx, cy = center
    start = path.currentPosition()
    a0 = math.degrees(math.atan2(cy - start.y(), start.x() - cx))
    a1 = math.degrees(math.atan2(cy - end[1], end[0] - cx))
    path.arcTo(cx - radius, cy - radius, 2 * radius, 2 * radius, a0, (a1 - a0) % 360)


def _polyline(path: QPainterPath, *points: tuple[float, float], close: bool = False) -> None:
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    if close:
        path.closeSubpath()


def _blueprints_icon() -> QPainterPath:
    """A page with a folded corner and two lines of text."""
    path = QPainterPath()
    _polyline(path, (6, 3), (14, 3), (18, 7), (18, 21), (6, 21), close=True)
    _polyline(path, (14, 3), (14, 7), (18, 7))
    _polyline(path, (9, 12), (15, 12))
    _polyline(path, (9, 16), (15, 16))
    return path


def _minerals_icon() -> QPainterPath:
    """A cut gem seen from the side."""
    path = QPainterPath()
    _polyline(path, (7, 4), (17, 4), (21, 9), (12, 20), (3, 9), close=True)
    _polyline(path, (3, 9), (21, 9))
    _polyline(path, (12, 20), (9, 9), (12, 4), (15, 9), close=True)
    return path


def _crafting_icon() -> QPainterPath:
    """An open-ended wrench, head top right."""
    path = QPainterPath()
    path.moveTo(14.7, 6.3)
    _arc(path, (12.84, 9.84), 4, (9.3, 11.7))
    _polyline(path, (9.3, 11.7), (4, 17), (7, 20), (12.3, 14.7))
    _arc(path, (14.16, 11.16), 4, (17.7, 9.3))
    for point in ((15.2, 11.8), (12.8, 11.2), (12.2, 8.8), (14.7, 6.3)):
        path.lineTo(*point)
    return path


# Drawer sections in handle order, each with its icon on a 24-unit grid.
SECTION_ICONS = {
    "blueprints": _blueprints_icon,
    "minerals": _minerals_icon,
    "crafting": _crafting_icon,
}


class SectionTabBar(QWidget):
    """The drawer's handles: one tapered tab per section, stacked along the
    screen edge with the tall side against it. Neighbouring tabs overlap at
    their tapered ends, and the open section's tab is drawn last so it sits
    in front. A click on a tab emits ``clicked`` with its section name."""

    clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.colors = DEFAULT_OVERLAY_COLORS
        self.sections: list[str] = list(SECTION_ICONS)
        self.current: Optional[str] = None
        self.edge = RIGHT
        self._icons = {name: make() for name, make in SECTION_ICONS.items()}
        self._resize()

    def set_edge(self, edge: str) -> None:
        self.edge = edge
        self._resize()

    def set_sections(self, sections: list[str]) -> None:
        self.sections = [name for name in SECTION_ICONS if name in sections]
        self._resize()

    def set_current(self, name: Optional[str]) -> None:
        self.current = name
        self.update()

    def _resize(self) -> None:
        n = len(self.sections)
        length = n * DRAWER_HANDLE_HEIGHT - max(n - 1, 0) * DRAWER_HANDLE_OVERLAP
        if self.edge in (LEFT, RIGHT):
            self.setFixedSize(DRAWER_HANDLE_WIDTH, length)
        else:
            self.setFixedSize(length, DRAWER_HANDLE_WIDTH)
        self.update()

    def _to_edge(self) -> QTransform:
        """Maps the right-edge drawing below onto this bar's edge."""
        w = DRAWER_HANDLE_WIDTH
        if self.edge == LEFT:
            return QTransform(-1, 0, 0, 1, w, 0)
        if self.edge == TOP:
            return QTransform(0, -1, 1, 0, 0, w)
        if self.edge == BOTTOM:
            return QTransform(0, 1, 1, 0, 0, 0)
        return QTransform()

    @staticmethod
    def _tab_top(index: int) -> float:
        return index * (DRAWER_HANDLE_HEIGHT - DRAWER_HANDLE_OVERLAP)

    def _tab_shape(self, index: int) -> QPainterPath:
        """Tab ``index`` as drawn on the right edge: tall side right."""
        w, h, top = DRAWER_HANDLE_WIDTH, DRAWER_HANDLE_HEIGHT, self._tab_top(index)
        tab = QPainterPath()
        _polyline(tab, (w - 0.5, top + 0.5), (0.5, top + h * DRAWER_HANDLE_TAPER),
                  (0.5, top + h * (1 - DRAWER_HANDLE_TAPER)), (w - 0.5, top + h - 0.5),
                  close=True)
        return tab

    def _paint_order(self) -> list[int]:
        """Back to front: the open section's tab last."""
        indices = range(len(self.sections))
        return sorted(indices, key=lambda i: self.sections[i] == self.current)

    def tab_at(self, pos: QPointF) -> Optional[str]:
        """The section whose tab is in front at ``pos`` (widget coordinates)."""
        to_local, _ = self._to_edge().inverted()
        point = to_local.map(QPointF(pos))
        for i in reversed(self._paint_order()):
            if self._tab_shape(i).contains(point):
                return self.sections[i]
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            name = self.tab_at(event.position())
            if name:
                self.clicked.emit(name)

    def mouseMoveEvent(self, event):
        name = self.tab_at(event.position())
        self.setToolTip(tr(f"sco.section_{name}") if name else "")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        to_edge = self._to_edge()
        p.setTransform(to_edge)
        for i in self._paint_order():
            name = self.sections[i]
            selected = name == self.current
            tab = self._tab_shape(i)
            bg = QColor(self.colors.background)
            bg.setAlpha(DRAWER_HANDLE_SELECTED_ALPHA if selected else DRAWER_ALPHA)
            # Source mode replaces the tab underneath, so an overlap shows
            # only the tab in front instead of both outlines.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillPath(tab, bg)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            # Closed, every tab is lit; open, only the open section's.
            lit = selected or self.current is None
            colour = QColor(self.colors.accent if lit else self.colors.secondary)
            p.setPen(QPen(colour, 1.8 if selected else 1.2))
            p.drawPath(tab)
            self._paint_icon(p, to_edge, name, i, colour)
        p.end()

    def _paint_icon(self, p: QPainter, to_edge: QTransform, name: str, index: int,
                    colour: QColor) -> None:
        # The icon's centre follows the tab, but the icon itself stays upright
        # whatever edge the bar is turned to.
        w, h, size = DRAWER_HANDLE_WIDTH, DRAWER_HANDLE_HEIGHT, DRAWER_ICON_SIZE
        centre = to_edge.map(QPointF(w * 0.56, self._tab_top(index) + h / 2))
        scale = size / 24
        p.save()
        p.setTransform(QTransform(scale, 0, 0, scale,
                                  centre.x() - size / 2, centre.y() - size / 2))
        pen = QPen(colour, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(self._icons[name])
        p.restore()


def mineral_tooltip(info: MineralInfo, crafting: CraftingIndex) -> str:
    """Everything known about a mineral: tier, scan signature, locations by
    star system, and how many crafted items use it."""
    lines = [info.name]
    if info.tier:
        lines.append(tr("sco.tooltip_tier", tier=info.tier))
    rs = ore_signature(info.name)
    if rs:
        lines.append(tr("sco.tooltip_signature", base=f"{rs[0]:,}", count=rs[1]))
    for system, locations in locations_by_system(info.locations).items():
        lines.append(f"{system or tr('sco.system_other')}: {', '.join(locations)}")
    key = crafting.material_key_for(info.name)
    if key:
        lines.append(tr("sco.tooltip_used_in", count=len(crafting.items_using(key))))
    return "\n".join(lines)


def location_tooltip(location: str, minerals: dict[str, MineralInfo]) -> str:
    """A location's star system and the minerals found there."""
    lines = [location]
    system = star_system(location)
    if system:
        lines.append(tr("sco.tooltip_system", system=system))
    here = minerals_at(location, minerals)
    if here:
        lines.append(tr("sco.tooltip_minerals_here", minerals=", ".join(here)))
    return "\n".join(lines)


class BlueprintDrawer(QWidget):
    """A stack of section tabs on a screen edge (blueprints, minerals,
    crafting). A tab opens the see-through panel straight to its section;
    the open section's tab closes it again."""

    owned_toggled = pyqtSignal(str, bool)
    # The Minerals section's scan decoder switch (the Overlay tab's too).
    scan_decoder_toggled = pyqtSignal(bool)
    # The ores ticked in the Minerals section, after every change.
    watched_changed = pyqtSignal(object)

    def __init__(self, colors: OverlayColors = DEFAULT_OVERLAY_COLORS):
        super().__init__(None, _OVERLAY_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # The game keeps focus while the player hovers, so tooltips must
        # show on an inactive window too.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self._meta: dict = {}
        self._owned: set = set()
        self._expanded = False

        self._handle = SectionTabBar(self)
        self._handle.clicked.connect(self.open_section)

        self._minerals: dict[str, MineralInfo] = {}
        self._crafting = CraftingIndex()
        self._mineral_by_material: dict[str, MineralInfo] = {}

        self._panel = QFrame(self)
        self._panel.setObjectName("scoDrawerPanel")
        self._panel.setFixedWidth(DRAWER_PANEL_WIDTH)
        self._banner = QLabel(self._panel)
        self._banner.setWordWrap(True)
        self._banner.hide()

        # Blueprints: owned checkboxes, same set the Blueprint Tracker edits.
        bp_page = QWidget()
        self._summary = QLabel(bp_page)
        self._search = QLineEdit(bp_page)
        self._search.textChanged.connect(self._render)
        self._owned_only = QCheckBox(bp_page)
        self._owned_only.toggled.connect(self._render)
        self._list = QListWidget(bp_page)
        self._list.itemChanged.connect(self._on_item_changed)
        bp_layout = QVBoxLayout(bp_page)
        bp_layout.setContentsMargins(0, 4, 0, 0)
        bp_layout.addWidget(self._summary)
        bp_layout.addWidget(self._search)
        bp_layout.addWidget(self._owned_only)
        bp_layout.addWidget(self._list)

        # Minerals: mineral -> star system -> location.
        self._mineral_search, self._mineral_tree, mineral_page = self._search_page(
            self._render_minerals)
        self._watched: set[str] = set()
        self._decoder_check = QCheckBox(mineral_page)
        self._decoder_check.setChecked(True)
        self._decoder_check.toggled.connect(self.scan_decoder_toggled)
        self._clear_watched_btn = QPushButton(mineral_page)
        self._clear_watched_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_watched_btn.clicked.connect(self._clear_watched)
        top_row = QHBoxLayout()
        top_row.addWidget(self._decoder_check)
        top_row.addStretch()
        top_row.addWidget(self._clear_watched_btn)
        mineral_page.layout().insertLayout(0, top_row)
        # Column 1 holds each ore's watch checkbox, against the right edge.
        self._mineral_tree.setColumnCount(2)
        header = self._mineral_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._mineral_tree.itemChanged.connect(self._on_mineral_watch_changed)
        # Crafting: a mineral lists what it goes into, an item what it needs.
        self._crafting_search, self._crafting_tree, crafting_page = self._search_page(
            self._render_crafting)

        # The tabs pick the page, so the panel only needs a stack of them.
        self._sections = QStackedWidget(self._panel)
        self._section_pages = dict(zip(SECTION_ICONS, (bp_page, mineral_page, crafting_page)))
        for page in self._section_pages.values():
            self._sections.addWidget(page)
        self._current: Optional[str] = None

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.addWidget(self._banner)
        panel_layout.addWidget(self._sections)

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._handle)
        self._layout.addWidget(self._panel)
        self._position = AppSettings.SCO_DRAWER_POSITION_DEFAULT
        self.set_position(self._position)
        self._panel.hide()

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._banner.hide)
        self.apply_colors(colors)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Apply tr() to the fixed texts, then redraw the list and trees,
        whose rows and tooltips are translated too. Called at construction
        and by MainWindow after a language switch."""
        self._search.setPlaceholderText(tr("sco.drawer_search_placeholder"))
        self._owned_only.setText(tr("sco.drawer_owned_only"))
        self._mineral_search.setPlaceholderText(tr("sco.minerals_search_placeholder"))
        self._crafting_search.setPlaceholderText(tr("sco.crafting_search_placeholder"))
        self._decoder_check.setText(tr("overlay.scan_decoder"))
        self._decoder_check.setToolTip(tr("overlay.scan_decoder_hint"))
        self._clear_watched_btn.setText(tr("sco.clear_watched"))
        self._render()
        self._render_minerals()
        self._render_crafting()

    def apply_colors(self, colors: OverlayColors) -> None:
        """Restyle the tab and panel, e.g. after the app theme changes."""
        self._handle.colors = colors
        self._handle.update()
        self._summary.setStyleSheet(f"color: {colors.accent}; font-weight: bold;")
        self._panel.setStyleSheet(f"""
            QFrame#scoDrawerPanel {{
                background: {_rgba(colors.background)};
                border: 1px solid {colors.accent};
            }}
            QLabel, QCheckBox {{ color: {colors.text}; background: transparent; }}
            QLineEdit {{
                color: {colors.text}; background: {_rgba(colors.background, 120)};
                border: 1px solid {colors.secondary}; border-radius: 3px; padding: 2px 4px;
            }}
            QListWidget, QTreeWidget {{
                color: {colors.text}; background: transparent; border: none;
            }}
            QListWidget::item:selected, QTreeWidget::item:selected {{
                background: {_rgba(colors.accent, 60)};
            }}
            QPushButton {{
                color: {colors.text}; background: transparent;
                border: 1px solid {colors.secondary}; border-radius: 3px; padding: 1px 8px;
            }}
            QPushButton:hover {{ border-color: {colors.accent}; color: {colors.accent}; }}
            QPushButton:disabled {{ color: {colors.secondary}; }}
            QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator {{
                width: 10px; height: 10px; border: 1px solid {colors.text};
                background: transparent;
            }}
            QCheckBox::indicator:checked, QListWidget::indicator:checked,
            QTreeWidget::indicator:checked {{
                background: {colors.accent}; border-color: {colors.accent};
            }}
        """)

    def _search_page(self, render) -> tuple[QLineEdit, QTreeWidget, QWidget]:
        page = QWidget()
        search = QLineEdit(page)
        search.textChanged.connect(render)
        tree = QTreeWidget(page)
        tree.setHeaderHidden(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(search)
        layout.addWidget(tree)
        return search, tree, page

    def set_sections(self, shown) -> None:
        """Show only the sections (``SECTION_ICONS`` names) in *shown*."""
        shown = [name for name in SECTION_ICONS if name in shown]
        self._handle.set_sections(shown)
        if self._current not in shown:
            self.close_drawer()
        self._dock()

    def has_sections(self) -> bool:
        """False when every section is switched off, leaving no tab to show."""
        return bool(self._handle.sections)

    def set_scan_decoder(self, on: bool) -> None:
        """Mirror the scan decoder switch without asking for a change."""
        self._decoder_check.blockSignals(True)
        self._decoder_check.setChecked(on)
        self._decoder_check.blockSignals(False)

    def set_watched(self, ores) -> None:
        """Tick these ores (``ORE_SIGNATURES`` keys) without asking for a change."""
        self._watched = set(ores)
        self._render_minerals()

    def _clear_watched(self) -> None:
        if not self._watched:
            return
        self._watched.clear()
        self._render_minerals()
        self.watched_changed.emit(set())

    def _on_mineral_watch_changed(self, item: QTreeWidgetItem, column: int) -> None:
        ore = item.data(1, Qt.ItemDataRole.UserRole)
        if column != 1 or not ore:
            return
        if item.checkState(1) == Qt.CheckState.Checked:
            self._watched.add(ore)
        else:
            self._watched.discard(ore)
        self._clear_watched_btn.setEnabled(bool(self._watched))
        self.watched_changed.emit(set(self._watched))

    def set_catalog(self, minerals: dict[str, MineralInfo], crafting: CraftingIndex) -> None:
        """Mining Compendium minerals and the crafting index for the searches."""
        self._minerals = dict(minerals)
        self._crafting = crafting
        # Material key -> compendium mineral, linked the same way the mineral
        # tooltips link the other way (CIG spells some differently).
        self._mineral_by_material = {}
        for name, info in self._minerals.items():
            key = crafting.material_key_for(name)
            if key:
                self._mineral_by_material.setdefault(key, info)
        self._render_minerals()
        self._render_crafting()

    def set_items(self, meta: dict, owned: set) -> None:
        """Replace the list contents: ``{name: BlueprintItem}`` + owned names."""
        self._meta = dict(meta)
        self._owned = set(owned)
        self._render()

    def notify_new(self, names: list[str]) -> None:
        """Flash the names of blueprints the live log watcher just found."""
        if not names:
            return
        self._banner.setText(tr("sco.drawer_new_blueprints", names=", ".join(names)))
        self._banner.show()
        self._banner_timer.start(NEW_BLUEPRINT_BANNER_MS)

    def open_section(self, name: str) -> None:
        """A tab click: open the drawer on ``name``, or close it when ``name``
        is already the open section."""
        if self._expanded and self._current == name:
            self.close_drawer()
            return
        self._current = name
        self._sections.setCurrentWidget(self._section_pages[name])
        self._set_expanded(True)

    def close_drawer(self) -> None:
        self._current = None
        self._set_expanded(False)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._panel.setVisible(expanded)
        self._handle.set_current(self._current)
        self._dock()

    def show_docked(self) -> None:
        self._dock()
        self.show()

    def set_position(self, position: str) -> None:
        """Dock to one of ``AppSettings.SCO_DRAWER_POSITIONS``."""
        if position not in AppSettings.SCO_DRAWER_POSITIONS:
            position = AppSettings.SCO_DRAWER_POSITION_DEFAULT
        self._position = position
        edge = drawer_edge(position)
        self._handle.set_edge(edge)
        # Open, the panel lies against the screen edge with the handle on
        # its inner side; closed, only the handle shows, on the edge.
        direction = {
            RIGHT: QBoxLayout.Direction.LeftToRight,
            LEFT: QBoxLayout.Direction.RightToLeft,
            TOP: QBoxLayout.Direction.BottomToTop,
            BOTTOM: QBoxLayout.Direction.TopToBottom,
        }[edge]
        self._layout.setDirection(direction)
        sideways = edge in (LEFT, RIGHT)
        self._layout.setAlignment(
            self._handle,
            Qt.AlignmentFlag.AlignVCenter if sideways else Qt.AlignmentFlag.AlignHCenter)
        self._dock()

    def _dock(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        edge = drawer_edge(self._position)
        vertical, _, horizontal = self._position.partition("_")
        handle = self._handle.size()
        if edge in (LEFT, RIGHT):
            width = handle.width() + (DRAWER_PANEL_WIDTH if self._expanded else 0)
            height = (int(screen.height() * DRAWER_SIDE_LENGTH) if self._expanded
                      else handle.height())
        else:
            width = DRAWER_PANEL_WIDTH if self._expanded else handle.width()
            height = handle.height() + (
                int(screen.height() * DRAWER_TOP_BOTTOM_LENGTH) if self._expanded else 0)
        self.setFixedSize(width, height)
        x = {LEFT: screen.x(), RIGHT: screen.right() - width + 1}.get(
            edge, screen.x() + (screen.width() - width) // 2)
        if vertical == "top":
            y = screen.y()
        elif vertical == "bottom":
            y = screen.bottom() - height + 1
        else:
            y = screen.y() + (screen.height() - height) // 2
        self.move(x, y)

    def _render(self) -> None:
        needle = self._search.text().strip().lower()
        owned_only = self._owned_only.isChecked()
        self._list.blockSignals(True)
        self._list.clear()
        for name in sorted(self._meta, key=str.lower):
            item_meta = self._meta[name]
            is_owned = name in self._owned
            if owned_only and not is_owned:
                continue
            if needle and needle not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if is_owned else Qt.CheckState.Unchecked)
            item.setToolTip(self._tooltip(item_meta))
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._summary.setText(tr(
            "sco.drawer_summary",
            owned=len(self._owned & set(self._meta)), total=len(self._meta),
        ))

    @staticmethod
    def _tooltip(item_meta) -> str:
        details = [v for v in (item_meta.type, item_meta.cls, item_meta.size, item_meta.grade) if v]
        lines = [" · ".join(details)] if details else []
        if item_meta.missions:
            lines.append(tr("sco.drawer_missions", count=len(item_meta.missions)))
            missions = sorted(item_meta.missions)
            lines.extend(missions[:TOOLTIP_MAX_MISSIONS])
            if len(missions) > TOOLTIP_MAX_MISSIONS:
                lines.append(tr("sco.drawer_more_missions",
                                count=len(missions) - TOOLTIP_MAX_MISSIONS))
        return "\n".join(lines)

    def _render_minerals(self) -> None:
        self._clear_watched_btn.setEnabled(bool(self._watched))
        self._mineral_tree.blockSignals(True)
        try:
            self._fill_mineral_tree()
        finally:
            self._mineral_tree.blockSignals(False)

    def _fill_mineral_tree(self) -> None:
        needle = self._mineral_search.text().strip().lower()
        self._mineral_tree.clear()
        if not self._minerals:
            self._mineral_tree.addTopLevelItem(QTreeWidgetItem([tr("sco.minerals_none")]))
            return
        for name in sorted(self._minerals, key=str.lower):
            info = self._minerals[name]
            if needle and needle not in name.lower() and not any(
                    needle in loc.lower() for loc in info.locations):
                continue
            node = QTreeWidgetItem([name])
            node.setToolTip(0, mineral_tooltip(info, self._crafting))
            # Only an ore the scanner has a signature for can glow.
            ore = ore_key(name)
            if ore:
                node.setData(1, Qt.ItemDataRole.UserRole, ore)
                node.setCheckState(1, Qt.CheckState.Checked if ore in self._watched
                                   else Qt.CheckState.Unchecked)
                node.setToolTip(1, tr("sco.watch_mineral_tooltip"))
            for system, locations in locations_by_system(info.locations).items():
                sys_node = QTreeWidgetItem([system or tr("sco.system_other")])
                for loc in locations:
                    loc_node = QTreeWidgetItem([loc])
                    loc_node.setToolTip(0, location_tooltip(loc, self._minerals))
                    sys_node.addChild(loc_node)
                node.addChild(sys_node)
            self._mineral_tree.addTopLevelItem(node)
            if needle:
                node.setExpanded(True)
                for i in range(node.childCount()):
                    node.child(i).setExpanded(True)

    def _render_crafting(self) -> None:
        needle = self._crafting_search.text().strip().lower()
        tree = self._crafting_tree
        tree.clear()
        if not self._crafting.materials:
            tree.addTopLevelItem(QTreeWidgetItem([tr("sco.crafting_none")]))
            return
        if not needle:
            return
        # A mineral (or other material) matched: what it goes into.
        for key, names in sorted(self._crafting.material_names().items(),
                                 key=lambda kv: kv[1][0].lower()):
            if not any(needle in n.lower() for n in names + [key]):
                continue
            node = QTreeWidgetItem([tr("sco.crafting_used_in", material=names[0])])
            info = self._mineral_by_material.get(key)
            if info is not None:
                node.setToolTip(0, mineral_tooltip(info, self._crafting))
            for category, item in self._crafting.items_using(key):
                child = QTreeWidgetItem([f"{item} ({category})"])
                child.setToolTip(0, self._item_tooltip(item, category))
                node.addChild(child)
            tree.addTopLevelItem(node)
            node.setExpanded(True)
        # An item matched: what it needs. materials_for gives each material's
        # first display name, which leads back to its key.
        key_by_name = {names[0]: key for key, names in self._crafting.material_names().items()}
        for item, category in sorted(self._crafting.items().items(), key=lambda kv: kv[0].lower()):
            if needle not in item.lower():
                continue
            node = QTreeWidgetItem([tr("sco.crafting_needs", item=item)])
            node.setToolTip(0, self._item_tooltip(item, category))
            for material in self._crafting.materials_for(item):
                child = QTreeWidgetItem([material])
                info = self._mineral_by_material.get(key_by_name.get(material))
                if info is not None:
                    child.setToolTip(0, mineral_tooltip(info, self._crafting))
                node.addChild(child)
            tree.addTopLevelItem(node)
            node.setExpanded(True)

    def _item_tooltip(self, item: str, category: str) -> str:
        lines = [item, category]
        materials = self._crafting.materials_for(item)
        if materials:
            lines.append(tr("sco.tooltip_needs", materials=", ".join(materials)))
        return "\n".join(lines)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        name = item.text()
        checked = item.checkState() == Qt.CheckState.Checked
        if checked:
            self._owned.add(name)
        else:
            self._owned.discard(name)
        self.owned_toggled.emit(name, checked)


def prune_samples(folder: Path, keep: int = MAX_SAMPLES_KEPT) -> int:
    """Delete all but the newest *keep* crops (``*.png``) in *folder*.

    Returns how many were deleted. A missing folder or a file that can't be
    removed is skipped.
    """
    try:
        crops = sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    removed = 0
    for old in crops[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


class _SaveSampleTask(QRunnable):
    """Writes one sample crop off the GUI thread, pruning the folder first
    when asked (once per overlay session)."""

    def __init__(self, crop: QImage, target: Path, prune: bool):
        super().__init__()
        self._crop, self._target, self._prune = crop, target, prune

    def run(self) -> None:
        folder = self._target.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("SCO: could not create the samples folder %s", folder)
            return
        if self._prune:
            prune_samples(folder, MAX_SAMPLES_KEPT - 1)
        # QImage.save reports failure by returning False, not by raising.
        if not self._crop.save(str(self._target)):
            logger.warning("SCO: could not save a digit sample to %s", self._target)


class _ReadTask(QRunnable):
    """Runs a ``SignatureReader`` on one capture off the GUI thread.

    The reader is pure Python and can take 100+ ms on a busy capture (text
    or noise under the scan region), which would stall the windows if it ran
    in the capture timer's slot. ``QImage`` is safe to use from any thread.
    """

    def __init__(self, reader: SignatureReader, image: QImage, region: QRect,
                 done: pyqtSignal, token: int):
        super().__init__()
        self._reader, self._image, self._region = reader, image, region
        self._done, self._token = done, token

    def run(self) -> None:
        try:
            found, failed = self._reader(self._image), False
        except Exception:
            logger.exception("SCO signature reader failed; stopping capture")
            found, failed = None, True
        self._done.emit(self._token, found, failed, self._image, self._region)


class ScoOverlay(QObject):
    """Owns the overlay windows and the signature capture loop."""

    # (token, reader result, reader raised, capture, capture region); emitted
    # from the reader's pool thread, delivered on the GUI thread.
    _read_done = pyqtSignal(int, object, bool, object, object)

    owned_toggled = pyqtSignal(str, bool)
    scan_decoder_toggled = pyqtSignal(bool)
    watched_changed = pyqtSignal(object)
    # The reader raised and the capture stopped; a restart (stop + start)
    # tries again. MainWindow tells the player, who would see nothing else.
    decoder_failed = pyqtSignal()

    def __init__(self, parent=None, sample_dir: Optional[Path] = None):
        super().__init__(parent)
        self.label = ScanLabelWindow()
        self.drawer = BlueprintDrawer(OverlayColors.from_theme())
        self.drawer.owned_toggled.connect(self.owned_toggled)
        self.drawer.scan_decoder_toggled.connect(self.scan_decoder_toggled)
        self.drawer.watched_changed.connect(self._on_watched_changed)
        self._watched: set[str] = set()
        self._shown_matches: list[SignatureMatch] = []
        self._reader: Optional[SignatureReader] = hud_signature_reader
        self._sample_dir = sample_dir
        self._save_samples = True
        self._sampled: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(CAPTURE_INTERVAL_MS)
        self._timer.timeout.connect(self._capture_once)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._reading = False       # a capture is with the reader
        self._read_token = 0        # bumped on stop, so a late result is dropped
        self._read_done.connect(self._on_read_done)
        self._last_value: Optional[int] = None
        self._shown_value: Optional[int] = None
        self._candidate: Optional[int] = None
        self._candidate_count = 0
        self._running = False
        self._show_label = True
        self._show_drawer = True

    def set_options(self, options: dict[str, bool]) -> None:
        """Apply the Overlay tab's switches (``AppSettings.SCO_OPTION_SETTING``
        names; missing ones count as on). Takes effect at once if running."""
        on = lambda name: options.get(name, True)  # noqa: E731
        self._show_label = on(AppSettings.SCO_SCAN_DECODER)
        self.drawer.set_scan_decoder(self._show_label)
        self._show_drawer = on(AppSettings.SCO_DRAWER)
        self._save_samples = on(AppSettings.SCO_SAVE_SAMPLES)
        self.drawer.set_sections(
            [name for name in SECTION_ICONS if on(AppSettings.SCO_DRAWER_SECTION_PREFIX + name)])
        if self._running:
            self._sync_windows()

    def set_watched_minerals(self, ores) -> None:
        """Ores (``ORE_SIGNATURES`` keys) whose decode makes the label glow."""
        self._watched = set(ores)
        self.drawer.set_watched(self._watched)
        self.label.set_glowing(self._glows(self._shown_matches))

    def _on_watched_changed(self, ores: set) -> None:
        self._watched = set(ores)
        self.label.set_glowing(self._glows(self._shown_matches))
        self.watched_changed.emit(set(ores))

    def _glows(self, matches: list[SignatureMatch]) -> bool:
        return any(m.kind in self._watched for m in matches)

    def set_reader(self, reader: Optional[SignatureReader]) -> None:
        self._reader = reader
        if self.is_running():
            self._sync_timer()

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True
        # Pick up a theme change made since the overlay was last shown.
        colors = OverlayColors.from_theme()
        self.drawer.apply_colors(colors)
        self.label.set_glow_color(colors.accent)
        self._sync_windows()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self._read_token += 1
        self.label.hide()
        self.drawer.hide()

    def _sync_windows(self) -> None:
        if self._show_drawer and self.drawer.has_sections():
            if not self.drawer.isVisible():
                self.drawer.show_docked()
        else:
            self.drawer.hide()
        if not self._show_label:
            self.label.hide()
        self._sync_timer()

    def _sync_timer(self) -> None:
        # No reader, or no label to show, means nothing to do with a capture.
        if self._reader is None or not self._show_label:
            self._timer.stop()
        else:
            self._timer.start()

    def _capture_once(self) -> None:
        # One read at a time: a tick that lands while the last capture is
        # still being read is skipped, so a slow read can't queue up work.
        # A confirming capture queued just before a stop must not run either.
        if self._reading or self._reader is None or not self._timer.isActive():
            return
        screen = QGuiApplication.primaryScreen()
        region = scan_region_rect(screen.geometry())
        image = screen.grabWindow(
            0, region.x(), region.y(), region.width(), region.height()).toImage()
        self._mask_own_label(image, region)
        self._reading = True
        self._pool.start(_ReadTask(self._reader, image, region, self._read_done, self._read_token))

    def wait_for_reader(self, msecs: int = -1) -> bool:
        """Block until no capture is being read and no sample is being saved
        (used on close and in tests)."""
        return self._pool.waitForDone(msecs)

    def _on_read_done(self, token: int, found, failed: bool, image: QImage, region: QRect) -> None:
        self._reading = False
        if token != self._read_token or not self._running:
            return
        if failed:
            self._timer.stop()
            self.label.hide()
            self.decoder_failed.emit()
            return
        self._handle_found(found, image, region)

    def _handle_found(self, found, image: QImage, region: QRect) -> None:
        if not found:
            return
        text, where = found
        self._save_sample(image, text, where)
        value = parse_signature_text(text)
        if value is None:
            return
        # The reader works in capture pixels; the screen may be DPI-scaled.
        scale = region.width() / image.width() if image.width() else 1.0
        where = QRect(int(where.x() * scale), int(where.y() * scale),
                      int(where.width() * scale), int(where.height() * scale))
        # Just under the readout, centred on it.
        anchor = QPoint(region.x() + where.center().x(), region.y() + where.bottom() + LABEL_GAP)
        self._on_reading(value, anchor)

    def _on_reading(self, value: int, anchor: QPoint) -> None:
        """Show *value*'s decode, once it has held for READINGS_TO_CHANGE captures."""
        if value != self._shown_value or not self.label.isVisible():
            if value == self._candidate:
                self._candidate_count += 1
            else:
                self._candidate, self._candidate_count = value, 1
            if self._candidate_count < READINGS_TO_CHANGE:
                # Confirm with the next frame now, not on the next tick, so a
                # new signal shows up to a tick sooner while the player sweeps
                # from one rock to the next.
                if self._timer.isActive():
                    QTimer.singleShot(0, self._capture_once)
                return
        # Accepted (or still the shown value): a pending candidate is void,
        # so a misread has to repeat back to back, not just come back later.
        self._candidate, self._candidate_count = None, 0
        matches = decode_signature(value)
        if not matches and value != self._last_value:
            logger.debug("SCO: no deposit matches signature %s", value)
        self._last_value = self._shown_value = value
        self._shown_matches = matches
        self.label.show_text(format_matches(matches), anchor, self._glows(matches))

    def _mask_own_label(self, image: QImage, region: QRect) -> None:
        """Black out our own label in the capture so its text is never read
        (it can sit over the readout for a moment while the head moves)."""
        if not self.label.isVisible() or not region.width():
            return
        overlap = self.label.geometry().intersected(region)
        if overlap.isEmpty():
            return
        scale = image.width() / region.width()
        local = overlap.translated(-region.x(), -region.y())
        painter = QPainter(image)
        painter.fillRect(QRect(int(local.x() * scale), int(local.y() * scale),
                               int(local.width() * scale) + 1, int(local.height() * scale) + 1),
                         QColor(0, 0, 0))
        painter.end()

    def _save_sample(self, image: QImage, text: str, where: QRect) -> None:
        """Keep one crop per distinct reading, named after the text read."""
        if (not self._save_samples or text in self._sampled
                or len(self._sampled) >= MAX_SAMPLES_PER_SESSION):
            return
        # Marked tried either way, so a held reading that can't be saved
        # doesn't warn four times a second.
        self._sampled.add(text)
        # Resolved now, not at start, so a data-folder move is followed.
        sample_dir = self._sample_dir or AppSettings.get_sco_samples_dir()
        crop = image.copy(where.adjusted(-SAMPLE_PADDING, -SAMPLE_PADDING,
                                         SAMPLE_PADDING, SAMPLE_PADDING))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = sample_dir / f"{stamp}_{text.replace(',', '')}.png"
        # Written on the reader's pool thread: the GUI thread never touches
        # the disk. The first save of a session prunes the folder.
        self._pool.start(_SaveSampleTask(crop, target, prune=len(self._sampled) == 1))
