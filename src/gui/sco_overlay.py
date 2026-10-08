"""Smart Citizen Overlay (SCO): always-on-top windows drawn over the game.

Two windows, because they need opposite input behaviour:

- ``ScanLabelWindow`` shows the decoded mining signature ("2 x Bexalite")
  just under the scanner's signature readout. Clicks pass straight through
  it to the game.
- ``BlueprintDrawer`` is a handle on the right screen edge that expands into
  a searchable blueprint list with owned checkboxes. It has to take clicks,
  so using it takes focus from the game; the player needs a free cursor.

``ScoOverlay`` owns both, plus the capture timer. The reader that turns a
capture of the signature panel into text is pluggable (``SignatureReader``);
the default, ``hud_signature_reader``, matches the HUD's digits against
reference glyphs (``src/utils/sco_digit_reader.py``). With no reader set, no
screen capture runs at all.

Overlays only draw over Star Citizen in borderless windowed mode, not
exclusive fullscreen. SCO only captures the screen; it never reads game
memory or sends input.

Data comes from ``MainWindow``: ``{name: BlueprintItem}`` metadata and the
owned set. Owned changes made in the drawer go back out through
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
)
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)

from src.utils.i18n import tr
from src.utils.mining_signatures import (
    OTHER_SIGNATURES, SignatureMatch, decode_signature, parse_signature_text,
)
from src.utils.sco_digit_reader import DIGIT_HEIGHT_AT_1600, read_signature

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
    red, green = data[2::4], data[1::4]
    # The capture spans SCAN_REGION's height, so this is the screen height.
    screen_height = height / SCAN_REGION[3]
    reading = read_signature(width, height, red, DIGIT_HEIGHT_AT_1600 * screen_height / 1600,
                             green=green)
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


class ArrowTab(QWidget):
    """The drawer's handle: a tapered tab with a chevron. Points left (open
    me) while the drawer is closed and right (close me) while it's open."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(DRAWER_HANDLE_WIDTH, DRAWER_HANDLE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.colors = DEFAULT_OVERLAY_COLORS
        self.points_left = True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        tip, back = (cx - dx, cx + dx) if self.points_left else (cx + dx, cx - dx)
        p.drawPolyline([QPointF(back, cy - dy), QPointF(tip, cy), QPointF(back, cy + dy)])
        p.end()


class BlueprintDrawer(QWidget):
    """Right-edge arrow tab that expands into a see-through blueprint list."""

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

        self._panel = QFrame(self)
        self._panel.setObjectName("scoDrawerPanel")
        self._panel.setFixedWidth(DRAWER_PANEL_WIDTH)
        self._summary = QLabel(self._panel)
        self._banner = QLabel(self._panel)
        self._banner.setWordWrap(True)
        self._banner.hide()
        self._search = QLineEdit(self._panel)
        self._search.setPlaceholderText(tr("sco.drawer_search_placeholder"))
        self._search.textChanged.connect(self._render)
        self._owned_only = QCheckBox(tr("sco.drawer_owned_only"), self._panel)
        self._owned_only.toggled.connect(self._render)
        self._list = QListWidget(self._panel)
        self._list.itemChanged.connect(self._on_item_changed)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.addWidget(self._summary)
        panel_layout.addWidget(self._banner)
        panel_layout.addWidget(self._search)
        panel_layout.addWidget(self._owned_only)
        panel_layout.addWidget(self._list)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._handle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._panel)
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
            QListWidget {{ color: {colors.text}; background: transparent; border: none; }}
            QListWidget::item:selected {{ background: {_rgba(colors.accent, 60)}; }}
            QCheckBox::indicator, QListWidget::indicator {{
                width: 10px; height: 10px; border: 1px solid {colors.text};
                background: transparent;
            }}
            QCheckBox::indicator:checked, QListWidget::indicator:checked {{
                background: {colors.accent}; border-color: {colors.accent};
            }}
        """)

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
        self._handle.points_left = not self._expanded
        self._handle.update()
        self._dock_right()

    def show_docked(self) -> None:
        self._dock_right()
        self.show()

    def _dock_right(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        width = DRAWER_HANDLE_WIDTH + (DRAWER_PANEL_WIDTH if self._expanded else 0)
        height = int(screen.height() * 0.7) if self._expanded else DRAWER_HANDLE_HEIGHT
        self.setFixedSize(width, height)
        self.move(screen.right() - width + 1, screen.y() + (screen.height() - height) // 2)

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
        self._sampled: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(CAPTURE_INTERVAL_MS)
        self._timer.timeout.connect(self._capture_once)
        self._last_value: Optional[int] = None
        self._shown_value: Optional[int] = None
        self._candidate: Optional[int] = None
        self._candidate_count = 0

    def set_reader(self, reader: Optional[SignatureReader]) -> None:
        self._reader = reader
        if self.is_running():
            self._sync_timer()

    def is_running(self) -> bool:
        return self.drawer.isVisible()

    def start(self) -> None:
        # Pick up a theme change made since the overlay was last shown.
        self.drawer.apply_colors(OverlayColors.from_theme())
        self.drawer.show_docked()
        self._sync_timer()

    def stop(self) -> None:
        self._timer.stop()
        self.label.hide()
        self.drawer.hide()

    def _sync_timer(self) -> None:
        # No reader yet means nothing to do with a capture, so don't take one.
        if self._reader is None:
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
        if (self._sample_dir is None or text in self._sampled
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
