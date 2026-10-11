"""Per-column filter header for the strings table."""

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QHeaderView, QLineEdit

from src.utils.i18n import tr


# Resting-border alpha used to approximate a 1.5px-feeling stroke without
# leaving the 2px integer grid that QSS borders require. ~60% opacity reads
# as a softened 2px line rather than a hard one. Focus state stays fully
# opaque so the active editor still pops.
_REST_BORDER_ALPHA = 150


def _filter_input_qss(palette: QPalette) -> str:
    """Build the per-editor stylesheet from the current palette.

    Rebuilt on every PaletteChange (see :meth:`FilterHeaderView.changeEvent`)
    because QSS doesn't accept ``palette(link)`` inside an ``rgba()``
    expression — we have to bake the colour in at the call site.
    """
    link = palette.color(QPalette.ColorRole.Link)
    rest = (
        f"rgba({link.red()}, {link.green()}, {link.blue()}, {_REST_BORDER_ALPHA})"
    )
    return f"""
        QLineEdit#columnFilter {{
            background-color: palette(base);
            border: 2px solid {rest};
            border-radius: 4px;
            padding: 1px 3px;
        }}
        QLineEdit#columnFilter:focus {{
            border: 3px solid palette(highlight);
            padding: 0px 2px;
        }}
    """


def _make_search_icon(color: QColor, size: int = 14) -> QIcon:
    """Render a magnifier glyph to a QIcon at the given palette colour.

    A drawn pixmap (rather than an asset file) keeps the icon palette-aware
    on theme swap and avoids depending on a font that ships a search emoji.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.GlobalColor.transparent)
    p.drawEllipse(2, 2, 7, 7)
    p.drawLine(8, 8, 12, 12)
    p.end()
    return QIcon(pix)


class FilterHeaderView(QHeaderView):
    """QHeaderView subclass that adds a row of QLineEdit filters below the header labels."""

    filter_changed = pyqtSignal()

    FILTER_ROW_HEIGHT = 26

    def __init__(self, column_names: list[str], parent=None, skip_columns: set[int] | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self._column_names = column_names
        self._skip_columns = skip_columns or set()
        self._filters: list[QLineEdit | None] = []
        # True while a press that landed in the header-label strip is still
        # held. The mouse overrides below consult it so an in-progress drag
        # (column resize, or a sort press) keeps receiving move/release
        # events after the pointer leaves that strip. See mouseMoveEvent.
        self._forwarding_mouse = False
        # Last non-zero height of the header's label strip. QHeaderView's own
        # sizeHint collapses to 0 during transient layout passes (a model
        # reset is one), and everything here that splits the header into
        # "labels on top, filter row below" needs a sane value at those
        # moments -- see _label_row_height.
        self._label_height_cache = 0
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.filter_changed.emit)

        icon_color = self.palette().color(QPalette.ColorRole.Mid)
        self._search_icon = _make_search_icon(icon_color)

        for i, name in enumerate(column_names):
            if i in self._skip_columns:
                self._filters.append(None)
                continue
            editor = QLineEdit(self)
            editor.setObjectName("columnFilter")
            editor.setPlaceholderText(tr("strings_tab.column_filter_placeholder", column=name.lower()))
            editor.setToolTip(tr("strings_tab.column_filter_tooltip", column=name))
            editor.setClearButtonEnabled(True)
            editor.addAction(self._search_icon, QLineEdit.ActionPosition.LeadingPosition)
            editor.textChanged.connect(self._on_text_changed)
            self._filters.append(editor)

        self._refresh_editor_styles()

        # Keep the editors glued to their columns during a horizontal scroll.
        # _position_editors() already subtracts offset(), but it only ran from
        # updateGeometries(), and QHeaderView.setOffset is a non-virtual slot
        # so scrolling never reached it: measured at full scroll, column 1 sat
        # at x=-1115 while its editor stayed at x=118. Unreachable while every
        # text column was Stretch (the table never overflowed); making columns
        # user-resizable is exactly what makes it reachable.
        self._view = parent
        self._scroll_bar = None
        self._sync_scroll_connection()

        # Same problem one step closer to home: dragging a column divider
        # resizes the section but updateGeometries() doesn't necessarily run,
        # so the editor kept its old width and left-edge while the column
        # moved out from under it (measured: section w=420 against editor
        # w=79). Repositioning on every section resize is what makes each
        # filter box stay exactly as wide as the column it filters.
        self.sectionResized.connect(lambda *_a: self._position_editors())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_filter_texts(self) -> list[str]:
        """Return lowered text for each column filter (empty string for skipped columns)."""
        return [f.text().lower() if f else "" for f in self._filters]

    def update_column_names(self, names: list[str]) -> None:
        """Refresh column names and editor placeholder texts after a language change."""
        self._column_names = names
        for i, editor in enumerate(self._filters):
            if editor is None:
                continue
            name = names[i] if i < len(names) else ""
            editor.setPlaceholderText(tr("strings_tab.column_filter_placeholder", column=name.lower()))
            editor.setToolTip(tr("strings_tab.column_filter_tooltip", column=name))

    def clear_all(self):
        """Clear every filter input without triggering per-keystroke signals."""
        for f in self._filters:
            if f is None:
                continue
            f.blockSignals(True)
            f.clear()
            f.blockSignals(False)
        self.filter_changed.emit()

    # ------------------------------------------------------------------
    # Size / paint
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.width(), s.height() + self.FILTER_ROW_HEIGHT)

    def paintSection(self, painter, rect, logicalIndex):
        """Paint the header label in the top portion only, not centered over the full height."""
        # During transient layout passes (theme swap, dock toggle, splitter drag,
        # font load), rect.height() can momentarily collapse below base_h. The
        # previous min(rect.height(), base_h) clamp then painted the label into
        # a near-zero rect, and that paint stuck until a full re-layout — which
        # for users meant restarting the app to get header text back. Force the
        # full base_h here; Qt clips on its own if rect is genuinely smaller.
        # _label_row_height, not a raw sizeHint read: that value itself
        # collapses to 0 during the same transient passes, which would put
        # the label back in a zero-height rect — the exact failure this
        # clamp exists to prevent.
        base_h = self._label_row_height()
        top_rect = QRect(rect.x(), rect.y(), rect.width(), base_h)
        super().paintSection(painter, top_rect, logicalIndex)

    def paintEvent(self, event):
        # Children (the QLineEdit filters) paint after their parent, so the tint
        # we draw here lands UNDER the editors. The result: the band reads as a
        # contiguous search strip with input boxes embedded in it, and the
        # skipped-column gaps (Category / ★ / Status) still get the tint so the
        # row is unmistakably a filter area.
        super().paintEvent(event)
        label_h = self._label_row_height()
        band = QRect(0, label_h, self.width(), self.FILTER_ROW_HEIGHT)
        painter = QPainter(self)
        tint = self.palette().color(QPalette.ColorRole.Highlight)
        tint.setAlpha(36)
        painter.fillRect(band, tint)
        painter.end()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def updateGeometries(self):
        super().updateGeometries()
        # Reserve space below the header labels for the filter row
        self.setViewportMargins(0, 0, 0, self.FILTER_ROW_HEIGHT)
        self._sync_scroll_connection()
        self._position_editors()

    def _position_editors(self):
        """Align each QLineEdit to its column's current geometry."""
        # Editors sit just below the painted header labels. _label_row_height
        # rather than a raw sizeHint read: that collapses to 0 mid-reset and
        # would stack the editors on top of the labels.
        y = self._label_row_height()
        if y <= 0:
            return          # header hasn't reported a real height yet
        for i, editor in enumerate(self._filters):
            if editor is None:
                continue
            x = self.sectionPosition(i) - self.offset()
            w = self.sectionSize(i)
            editor.setGeometry(x, y, w, self.FILTER_ROW_HEIGHT)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sync_scroll_connection(self) -> None:
        """(Re)bind the horizontal-scroll hook to the view's current scrollbar.

        Binding the QScrollBar once at construction would be silently wrong
        if the view ever swapped it: setHorizontalScrollBar destroys the old
        bar, so the connection would go dead and the filter boxes would stop
        tracking the scroll, looking exactly like a regression of the bug the
        hook exists to fix. Re-checked from updateGeometries, which Qt runs
        often enough that a swap can't go unnoticed.
        """
        view = getattr(self, "_view", None)
        if view is None or not hasattr(view, "horizontalScrollBar"):
            return
        bar = view.horizontalScrollBar()
        if bar is self._scroll_bar:
            return
        if self._scroll_bar is not None:
            try:
                self._scroll_bar.valueChanged.disconnect(self._on_horizontal_scroll)
            except (RuntimeError, TypeError):
                # RuntimeError is the one that matters, and the case this
                # whole method exists for: setHorizontalScrollBar *destroys*
                # the bar it replaces, so by the time we get here the old one
                # is a dangling wrapper and touching it raises "wrapped C/C++
                # object ... has been deleted". A destroyed bar needs no
                # disconnect. TypeError covers the milder case of the signal
                # not being connected in the first place.
                pass
        self._scroll_bar = bar
        if bar is not None:
            bar.valueChanged.connect(self._on_horizontal_scroll)

    def _on_horizontal_scroll(self, _value: int) -> None:
        self._position_editors()

    def _label_row_height(self) -> int:
        """Height of the header's label strip, never zero once known.

        ``QHeaderView.sizeHint()`` momentarily reports 0 during transient
        layout passes — a model reset (any reload: Apply Enhancements, a
        merge, a language change) is one. Reading it right then placed every
        filter editor at y=0, directly on top of the column labels, and
        nothing moved them back: the recovery only happened if some section
        also changed width in the same pass, so a reload that produced
        identical widths left the filter row covering the header until the
        user resized something.

        Falling back to the last good value keeps the split stable through
        those passes. Returns 0 only before the header has ever reported a
        real height, and callers skip laying out at all in that case.
        """
        height = QHeaderView.sizeHint(self).height()
        if height > 0:
            self._label_height_cache = height
        return self._label_height_cache

    def mousePressEvent(self, event):
        """Route clicks in the label area to sorting, let filter row clicks pass through."""
        self._forwarding_mouse = event.position().y() < self._label_row_height()
        if self._forwarding_mouse:
            # Check if a QLineEdit is stealing this click (shouldn't, but just in case)
            super().mousePressEvent(event)
        # Clicks in the filter row are handled by the QLineEdit widgets

    def mouseReleaseEvent(self, event):
        if self._forwarding_mouse or event.position().y() < self._label_row_height():
            super().mouseReleaseEvent(event)
        self._forwarding_mouse = False

    def mouseMoveEvent(self, event):
        # Once a press has been forwarded, keep forwarding until release even
        # if the pointer drops below the label strip. That strip is only ~16px
        # tall, so a column-resize drag leaves it almost immediately; gating
        # purely on the current y silently froze the drag mid-resize
        # (measured: a divider drag that drifted into the filter row left the
        # column at its original width). Hover moves with no button held still
        # obey the plain y test, so the filter row keeps its own cursor.
        # Self-heal the flag: it is set on press and cleared on release, but a
        # release can go missing (a broken mouse grab, a modal opening
        # mid-drag, a synthetic press with no matching release). A move with
        # no button held cannot be part of a drag, so it is a safe point to
        # clear it -- otherwise a lost release would leave every later hover
        # forwarding, showing the resize cursor over the filter boxes.
        if not event.buttons():
            self._forwarding_mouse = False
        if self._forwarding_mouse or event.position().y() < self._label_row_height():
            super().mouseMoveEvent(event)

    def _on_text_changed(self, text: str = "") -> None:
        self._debounce.stop()
        self._debounce.start()

    def _refresh_editor_styles(self) -> None:
        """Rebuild every filter editor's stylesheet from the current palette.

        Called from ``__init__`` and again on PaletteChange so the
        rgba-baked resting border tracks the active theme's Link colour.
        """
        qss = _filter_input_qss(self.palette())
        for editor in self._filters:
            if editor is not None:
                editor.setStyleSheet(qss)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._refresh_editor_styles()
