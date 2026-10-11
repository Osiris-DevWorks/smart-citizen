"""Smart Citizen Overlay (SCO): always-on-top windows drawn over the game.

Two windows, because they need opposite input behaviour:

- ``ScanLabelWindow`` shows the decoded mining signature ("2 x Bexalite")
  just under the scanner's signature readout. Clicks pass straight through
  it to the game.
- ``BlueprintDrawer`` is a handle on the right screen edge that expands into
  three searchable sections: blueprints with owned checkboxes, minerals by
  star system and location, and crafting (mineral to items and back). It
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPalette, QPen,
    QTransform,
)
from PyQt6.QtWidgets import (
    QBoxLayout, QCheckBox, QFrame, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from src.utils.i18n import tr
from src.utils.mining_catalog import (
    CraftingIndex, MineralInfo, locations_by_system, minerals_at, ore_signature,
    star_system,
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
# centre. Amr confirmed the area is the same across cockpits; the box is
# padded for head movement (~115 px between the two samples).
SCAN_REGION = (0.38, 0.28, 0.24, 0.12)
CAPTURE_INTERVAL_MS = 250
# Tester builds keep a crop of each distinct reading (and the text read) so
# misreads can be fixed by adding reference glyphs. Capped per session.
MAX_SAMPLES_PER_SESSION = 200
SAMPLE_PADDING = 12
# Hide a reading this long after the number was last seen.
LABEL_HOLD_MS = 1500
# Gap between the readout's baseline and the label, in screen px. Keeps the
# label clear of the digits while the readout bobs with head movement.
LABEL_GAP = 10
# A new reading must repeat on this many captures in a row before it replaces
# the label, so a one-frame misread can't flash "Unidentified".
READINGS_TO_CHANGE = 2
NEW_BLUEPRINT_BANNER_MS = 8000

DRAWER_HANDLE_WIDTH = 16
DRAWER_HANDLE_HEIGHT = 44
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
        c = ODW_OVERLAY_COLORS
        self._label.setStyleSheet(
            f"QLabel {{ color: {c.text}; background: {_rgba(c.background)};"
            f" border: 1px solid {c.accent}; border-radius: 4px;"
            " padding: 2px 8px; font-weight: bold; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, anchor: QPoint) -> None:
        """Show *text* centred under *anchor*: the middle of its top edge
        sits on that point (screen coordinates)."""
        self._label.setText(text)
        self.adjustSize()
        self.move(anchor.x() - self.width() // 2, anchor.y())
        self.show()
        self._hide_timer.start(LABEL_HOLD_MS)


def drawer_edge(position: str) -> str:
    """The screen edge a drawer position docks to: its side, or the top or
    bottom edge for the two centre positions."""
    vertical, _, horizontal = position.partition("_")
    if horizontal == "center":
        return BOTTOM if vertical == "bottom" else TOP
    return LEFT if horizontal == "left" else RIGHT


class ArrowTab(QWidget):
    """The drawer's handle: a tapered tab with a chevron, its tall side
    against the screen edge it docks to. Points inward (open me) while the
    drawer is closed and toward the edge (close me) while it's open."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.colors = DEFAULT_OVERLAY_COLORS
        self.points_inward = True
        self.set_edge(RIGHT)

    def set_edge(self, edge: str) -> None:
        self.edge = edge
        if edge in (LEFT, RIGHT):
            self.setFixedSize(DRAWER_HANDLE_WIDTH, DRAWER_HANDLE_HEIGHT)
        else:
            self.setFixedSize(DRAWER_HANDLE_HEIGHT, DRAWER_HANDLE_WIDTH)
        self.update()

    def _to_edge(self) -> QTransform:
        """Maps the right-edge drawing below onto this tab's edge."""
        w = DRAWER_HANDLE_WIDTH
        if self.edge == LEFT:
            return QTransform(-1, 0, 0, 1, w, 0)
        if self.edge == TOP:
            return QTransform(0, -1, 1, 0, 0, w)
        if self.edge == BOTTOM:
            return QTransform(0, 1, 1, 0, 0, 0)
        return QTransform()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event):
        # Drawn as a right-edge tab (tall side right), then turned to the edge.
        w, h = DRAWER_HANDLE_WIDTH, DRAWER_HANDLE_HEIGHT
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._to_edge())
        # Tall side against the panel / screen edge, tapering outward.
        tab = QPainterPath()
        tab.moveTo(w - 0.5, 0.5)
        tab.lineTo(0.5, h * 0.15)
        tab.lineTo(0.5, h * 0.85)
        tab.lineTo(w - 0.5, h - 0.5)
        tab.closeSubpath()
        bg = QColor(self.colors.background)
        bg.setAlpha(DRAWER_ALPHA)
        p.fillPath(tab, bg)
        p.setPen(QPen(QColor(self.colors.accent), 1.2))
        p.drawPath(tab)

        pen = QPen(QColor(self.colors.accent), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy, dx, dy = w * 0.55, h / 2, w * 0.18, h * 0.16
        tip, back = (cx - dx, cx + dx) if self.points_inward else (cx + dx, cx - dx)
        p.drawPolyline([QPointF(back, cy - dy), QPointF(tip, cy), QPointF(back, cy + dy)])
        p.end()


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
    """Right-edge arrow tab that expands into a see-through panel with
    blueprint, mineral and crafting searches."""

    owned_toggled = pyqtSignal(str, bool)

    def __init__(self, colors: OverlayColors = DEFAULT_OVERLAY_COLORS):
        super().__init__(None, _OVERLAY_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # The game keeps focus while the player hovers, so tooltips must
        # show on an inactive window too.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self._meta: dict = {}
        self._owned: set = set()
        self._expanded = False

        self._handle = ArrowTab(self)
        self._handle.setToolTip(tr("sco.drawer_handle_tooltip"))
        self._handle.clicked.connect(self.toggle)

        self._minerals: dict[str, MineralInfo] = {}
        self._crafting = CraftingIndex()

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
        self._search.setPlaceholderText(tr("sco.drawer_search_placeholder"))
        self._search.textChanged.connect(self._render)
        self._owned_only = QCheckBox(tr("sco.drawer_owned_only"), bp_page)
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
            "sco.minerals_search_placeholder", self._render_minerals)
        # Crafting: a mineral lists what it goes into, an item what it needs.
        self._crafting_search, self._crafting_tree, crafting_page = self._search_page(
            "sco.crafting_search_placeholder", self._render_crafting)

        self._sections = QTabWidget(self._panel)
        self._section_pages = {
            "blueprints": self._sections.addTab(bp_page, tr("sco.section_blueprints")),
            "minerals": self._sections.addTab(mineral_page, tr("sco.section_minerals")),
            "crafting": self._sections.addTab(crafting_page, tr("sco.section_crafting")),
        }

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
            QListWidget, QTreeWidget {{ color: {colors.text}; background: transparent; border: none; }}
            QListWidget::item:selected, QTreeWidget::item:selected {{
                background: {_rgba(colors.accent, 60)};
            }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                color: {colors.secondary}; background: transparent; padding: 3px 8px;
                border-bottom: 1px solid transparent;
            }}
            QTabBar::tab:selected {{ color: {colors.accent}; border-bottom-color: {colors.accent}; }}
            QCheckBox::indicator, QListWidget::indicator {{
                width: 10px; height: 10px; border: 1px solid {colors.text};
                background: transparent;
            }}
            QCheckBox::indicator:checked, QListWidget::indicator:checked {{
                background: {colors.accent}; border-color: {colors.accent};
            }}
        """)

    def _search_page(self, placeholder_key: str, render) -> tuple[QLineEdit, QTreeWidget, QWidget]:
        page = QWidget()
        search = QLineEdit(page)
        search.setPlaceholderText(tr(placeholder_key))
        search.textChanged.connect(render)
        tree = QTreeWidget(page)
        tree.setHeaderHidden(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(search)
        layout.addWidget(tree)
        return search, tree, page

    def set_sections(self, blueprints: bool, minerals: bool, crafting: bool) -> None:
        """Show or hide the drawer's sections (Overlay tab switches)."""
        for name, on in (("blueprints", blueprints), ("minerals", minerals),
                         ("crafting", crafting)):
            self._sections.setTabVisible(self._section_pages[name], on)

    def set_catalog(self, minerals: dict[str, MineralInfo], crafting: CraftingIndex) -> None:
        """Mining Compendium minerals and the crafting index for the searches."""
        self._minerals = dict(minerals)
        self._crafting = crafting
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

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._panel.setVisible(self._expanded)
        self._handle.points_inward = not self._expanded
        self._handle.update()
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
                lines.append(tr("sco.drawer_more_missions", count=len(missions) - TOOLTIP_MAX_MISSIONS))
        return "\n".join(lines)

    def _render_minerals(self) -> None:
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
            info = self._mineral_for(names)
            if info is not None:
                node.setToolTip(0, mineral_tooltip(info, self._crafting))
            for category, item in self._crafting.items_using(key):
                child = QTreeWidgetItem([f"{item} ({category})"])
                child.setToolTip(0, self._item_tooltip(item, category))
                node.addChild(child)
            tree.addTopLevelItem(node)
            node.setExpanded(True)
        # An item matched: what it needs.
        for item, category in sorted(self._crafting.items().items(), key=lambda kv: kv[0].lower()):
            if needle not in item.lower():
                continue
            node = QTreeWidgetItem([tr("sco.crafting_needs", item=item)])
            node.setToolTip(0, self._item_tooltip(item, category))
            for material in self._crafting.materials_for(item):
                child = QTreeWidgetItem([material])
                info = self._mineral_for([material])
                if info is not None:
                    child.setToolTip(0, mineral_tooltip(info, self._crafting))
                node.addChild(child)
            tree.addTopLevelItem(node)
            node.setExpanded(True)

    def _mineral_for(self, names) -> Optional[MineralInfo]:
        """The compendium mineral behind a material's display names, if any."""
        for n in names:
            word = n.split(" ")[0].lower()
            for mineral, info in self._minerals.items():
                if mineral.lower() == word:
                    return info
        return None

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


class ScoOverlay(QObject):
    """Owns the overlay windows and the signature capture loop."""

    owned_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None, sample_dir: Optional[Path] = None):
        super().__init__(parent)
        self.label = ScanLabelWindow()
        self.drawer = BlueprintDrawer(OverlayColors.from_theme())
        self.drawer.owned_toggled.connect(self.owned_toggled)
        self._reader: Optional[SignatureReader] = hud_signature_reader
        self._sample_dir = sample_dir
        self._save_samples = True
        self._sampled: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(CAPTURE_INTERVAL_MS)
        self._timer.timeout.connect(self._capture_once)
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
        self._show_label = on("scan_decoder")
        self._show_drawer = on("drawer")
        self._save_samples = on("save_samples")
        self.drawer.set_sections(on("drawer_blueprints"), on("drawer_minerals"),
                                 on("drawer_crafting"))
        if self._running:
            self._sync_windows()

    def set_reader(self, reader: Optional[SignatureReader]) -> None:
        self._reader = reader
        if self.is_running():
            self._sync_timer()

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True
        # Pick up a theme change made since the overlay was last shown.
        self.drawer.apply_colors(OverlayColors.from_theme())
        self._sync_windows()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self.label.hide()
        self.drawer.hide()

    def _sync_windows(self) -> None:
        if self._show_drawer:
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
        screen = QGuiApplication.primaryScreen()
        region = scan_region_rect(screen.geometry())
        image = screen.grabWindow(0, region.x(), region.y(), region.width(), region.height()).toImage()
        self._mask_own_label(image, region)
        try:
            found = self._reader(image) if self._reader else None
        except Exception:
            logger.exception("SCO signature reader failed; stopping capture")
            self._timer.stop()
            return
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
                return
        matches = decode_signature(value)
        if not matches and value != self._last_value:
            logger.debug("SCO: no deposit matches signature %s", value)
        self._last_value = self._shown_value = value
        self.label.show_text(format_matches(matches), anchor)

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
        if (self._sample_dir is None or not self._save_samples or text in self._sampled
                or len(self._sampled) >= MAX_SAMPLES_PER_SESSION):
            return
        self._sampled.add(text)
        crop = image.copy(where.adjusted(-SAMPLE_PADDING, -SAMPLE_PADDING,
                                         SAMPLE_PADDING, SAMPLE_PADDING))
        try:
            self._sample_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            crop.save(str(self._sample_dir / f"{stamp}_{text.replace(',', '')}.png"))
        except OSError:
            logger.warning("SCO: could not save a digit sample to %s", self._sample_dir)
