"""Smart Citizen Overlay (SCO): always-on-top windows drawn over the game.

Two windows, because they need opposite input behaviour:

- ``ScanLabelWindow`` shows the decoded mining signature ("2 x Bexalite")
  just under the scanner's signature readout. Clicks pass straight through
  it to the game.
- ``BlueprintDrawer`` is a handle on the right screen edge that expands into
  a searchable blueprint list with owned checkboxes. It has to take clicks,
  so using it takes focus from the game; the player needs a free cursor.

``ScoOverlay`` owns both, plus the capture timer. The digit reader that turns
a capture of the signature panel into text is pluggable (``SignatureReader``)
and not built yet: until one is set, no screen capture runs at all.

Overlays only draw over Star Citizen in borderless windowed mode, not
exclusive fullscreen. SCO only captures the screen; it never reads game
memory or sends input.

Data comes from ``MainWindow``: ``{name: BlueprintItem}`` metadata and the
owned set. Owned changes made in the drawer go back out through
``owned_toggled`` so ``MainWindow`` stays the one writer of the owned set.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from src.utils.i18n import tr
from src.utils.mining_signatures import (
    OTHER_SIGNATURES, SignatureMatch, decode_signature, parse_signature_text,
)

logger = logging.getLogger(__name__)

# Where the scanner's signature readout sits, as fractions of the primary
# screen (x, y, w, h). Measured from 2560x1600 Drake Golem screenshots: the
# pin + number sit in a small panel under the cockpit radar screen, top
# centre. Amr confirmed the area is the same across cockpits; the box is
# padded for head movement (~115 px between the two samples).
SCAN_REGION = (0.38, 0.28, 0.24, 0.12)
CAPTURE_INTERVAL_MS = 250
# Hide a reading this long after the number was last seen.
LABEL_HOLD_MS = 1500
NEW_BLUEPRINT_BANNER_MS = 8000

DRAWER_HANDLE_WIDTH = 28
DRAWER_PANEL_WIDTH = 340

# A reader takes a capture of SCAN_REGION and returns the HUD text it found
# ("10,200") and where, in capture coordinates, or None when nothing is shown.
SignatureReader = Callable[[QImage], Optional[tuple[str, QRect]]]

_OVERLAY_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
)


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
    """One line per reading: "2 x Bexalite", "3 x ROC Mineable", ..."""
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
        self._label.setStyleSheet(
            "QLabel { color: #FFE9A8; background: rgba(0, 0, 0, 170);"
            " border-radius: 4px; padding: 2px 6px; font-weight: bold; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, anchor: QPoint) -> None:
        """Show *text* with its top-left at *anchor* (screen coordinates)."""
        self._label.setText(text)
        self.adjustSize()
        self.move(anchor)
        self.show()
        self._hide_timer.start(LABEL_HOLD_MS)


class BlueprintDrawer(QWidget):
    """Right-edge handle that expands into a blueprint list."""

    owned_toggled = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__(None, _OVERLAY_FLAGS)
        self._meta: dict = {}
        self._owned: set = set()
        self._expanded = False

        self._handle = QPushButton(tr("sco.drawer_handle"), self)
        self._handle.setFixedWidth(DRAWER_HANDLE_WIDTH)
        self._handle.setToolTip(tr("sco.drawer_handle_tooltip"))
        self._handle.clicked.connect(self.toggle)

        self._panel = QFrame(self)
        self._panel.setFrameShape(QFrame.Shape.StyledPanel)
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
        layout.addWidget(self._handle)
        layout.addWidget(self._panel)
        self._panel.hide()

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._banner.hide)

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
        self._dock_right()

    def show_docked(self) -> None:
        self._dock_right()
        self.show()

    def _dock_right(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        width = DRAWER_HANDLE_WIDTH + (DRAWER_PANEL_WIDTH if self._expanded else 0)
        height = int(screen.height() * (0.7 if self._expanded else 0.12))
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
            lines.extend(sorted(item_meta.missions)[:8])
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = ScanLabelWindow()
        self.drawer = BlueprintDrawer()
        self.drawer.owned_toggled.connect(self.owned_toggled)
        self._reader: Optional[SignatureReader] = None
        self._timer = QTimer(self)
        self._timer.setInterval(CAPTURE_INTERVAL_MS)
        self._timer.timeout.connect(self._capture_once)
        self._last_value: Optional[int] = None

    def set_reader(self, reader: Optional[SignatureReader]) -> None:
        self._reader = reader
        if self.is_running():
            self._sync_timer()

    def is_running(self) -> bool:
        return self.drawer.isVisible()

    def start(self) -> None:
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
        try:
            found = self._reader(image) if self._reader else None
        except Exception:
            logger.exception("SCO signature reader failed; stopping capture")
            self._timer.stop()
            return
        if not found:
            return
        text, where = found
        value = parse_signature_text(text)
        if value is None:
            return
        matches = decode_signature(value)
        if not matches:
            if value != self._last_value:
                logger.debug("SCO: no deposit matches signature %s", value)
            self._last_value = value
            return
        self._last_value = value
        # Just under the readout, aligned to its left edge.
        anchor = QPoint(region.x() + where.left(), region.y() + where.bottom() + 4)
        self.label.show_text(format_matches(matches), anchor)
