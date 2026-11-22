"""The SCO drawer's Order section (3.1.0): build a crafting order and see
everything it needs.

Modelled on the RK site's Crafting Central. From the top:

- the **order summary**: every material the whole order needs, with how
  much at each quality, a cSCU / SCU switch, Copy (plain text for
  Discord), **Watch minerals** (adds the order's minerals to the scan watch
  list, so the label alerts when one is read) and Clear (asks once more by
  its own text, since a box over the game is no place for a dialog);
- a search to add an item: adding one that is already on the order raises
  its count, so each item is one line;
- one card per line: its count with - and +, a mark when its blueprint is
  not owned yet, and a collapsible body with each crafting slot's material
  and amount, a quality slider, the stat bonuses that quality gives, and
  for a "2 of these 3" pick the slots it uses.

The maths is ``src/utils/crafting_order.py``; the data comes from
``crafting_index.json`` (``mining_catalog.CraftingIndex``). The order is
saved through ``AppSettings`` on every change. Like the rest of the drawer,
only the search box ever takes the keyboard (#523): everything here is
``NoFocus`` and works by mouse.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.utils import crafting_order as co
from src.utils.i18n import tr
from src.utils.mining_catalog import CraftingIndex, MineralInfo, is_unknown_material, ore_key
from src.utils.ore_qualities import QUALITY_TABLE_SOURCE, tier_of
from src.utils.owned_items import normalize_item_name
from src.utils.settings import AppSettings

# How many search results show at once, and how tall that list may get.
SEARCH_LIMIT = 30
SEARCH_LIST_HEIGHT = 140
# New order, Save over a name and Delete ask to be clicked again within this time.
CLEAR_CONFIRM_MS = 3000
# How tall a quality slider's tier ticks are.
TICK_HEIGHT = 4
logger = logging.getLogger(__name__)

# Bonus colours: better, worse (neutral takes the panel's secondary colour).
BONUS_UP = "#5CFF8A"
BONUS_DOWN = "#FF7A7A"


def _owned_key(name: str) -> str:
    """How an owned name and a blueprint's item name are matched: the
    Blueprint Tracker's own normalizer (tags, [Owned], aliases), any case."""
    return normalize_item_name(name).casefold()


def _no_focus(*widgets: QWidget) -> None:
    for widget in widgets:
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _button(text: str = "", tooltip: str = "", slot: Optional[Callable] = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    _no_focus(btn)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


def _wrapped(text: str = "", secondary: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if secondary:
        label.setProperty("role", "secondary")
    return label


class StepSlider(QSlider):
    """A quality slider that marks the qualities its material comes at with
    a tick under the groove (only those can be picked, see
    ``crafting_order.clamp_quality``)."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._steps: tuple[int, ...] = ()

    def set_steps(self, steps) -> None:
        self._steps = tuple(steps)
        self.setMinimumHeight(self.sizeHint().height() + (TICK_HEIGHT if self._steps else 0))
        self.update()

    def steps(self) -> tuple[int, ...]:
        return self._steps

    def paintEvent(self, event):  # noqa: N802 (Qt's name)
        super().paintEvent(event)
        if not self._steps:
            return
        try:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            style = self.style()
            groove = style.subControlRect(
                QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
            )
            handle = style.subControlRect(
                QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
            )
            span = max(1, groove.width() - handle.width())
            painter = QPainter(self)
            painter.setPen(self.palette().color(self.foregroundRole()))
            bottom = self.height() - 1
            for value in self._steps:
                if not self.minimum() <= value <= self.maximum():
                    continue
                x = (
                    groove.x()
                    + handle.width() // 2
                    + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), value, span)
                )
                painter.drawLine(x, bottom - TICK_HEIGHT + 1, x, bottom)
            painter.end()
        except Exception as exc:  # a Qt override: an exception here ends the app
            logger.warning(f"Could not draw the quality ticks: {exc}")


class OrderLineCard(QFrame):
    """One line of the order. Emits ``changed`` after a count, quality or
    pick change, and ``removed`` with its key."""

    changed = pyqtSignal()
    removed = pyqtSignal(str)
    expanded_changed = pyqtSignal(str, bool)

    def __init__(
        self, section: "OrderSection", line: co.OrderLine, bp: dict, expanded: bool, parent=None
    ):
        super().__init__(parent)
        self.setObjectName("scoOrderCard")
        self._section = section
        self.line = line
        self.bp = bp

        self._toggle = QToolButton()
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._toggle.setAutoRaise(True)
        self._toggle.clicked.connect(self._on_toggle)
        self._name = _wrapped()
        self._name.setToolTip(bp.get("c", ""))
        self._owned = _wrapped(secondary=True)
        self._count = QLabel()
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count.setMinimumWidth(26)
        minus = _button("−", tr("sco.order_less"), lambda: self._step(-1))
        plus = _button("+", tr("sco.order_more"), lambda: self._step(1))
        remove = _button("✕", tr("sco.order_remove"), lambda: self.removed.emit(self.line.key))
        for btn in (minus, plus, remove):
            btn.setFixedWidth(24)
        _no_focus(self._toggle)

        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self._name)
        names.addWidget(self._owned)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(names, 1)
        for widget in (minus, self._count, plus, remove):
            head.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)

        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(18, 2, 0, 2)
        body.setSpacing(2)
        self._slot_widgets: list[dict] = []
        shown_picks: set[int] = set()
        for i, slot in enumerate(bp["s"]):
            g = slot.get("g")
            if g is not None and g not in shown_picks:
                shown_picks.add(g)
                pick = (bp.get("p") or [{}])[g] if g < len(bp.get("p") or []) else {}
                body.addWidget(
                    _wrapped(
                        tr("sco.order_pick", need=pick.get("k", 1), of=pick.get("n", 1)),
                        secondary=True,
                    )
                )
            body.addWidget(self._slot_row(i, slot))
        self._total_bonus = _wrapped()
        body.addWidget(self._total_bonus)
        self._body.setVisible(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addLayout(head)
        layout.addWidget(self._body)
        self.refresh()

    def _slot_row(self, index: int, slot: dict) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        top = QHBoxLayout()
        pick = None
        if slot.get("g") is not None:
            pick = QCheckBox()
            pick.setToolTip(tr("sco.order_pick_tooltip"))
            _no_focus(pick)
            pick.clicked.connect(lambda _c, i=index: self._on_pick(i))
            top.addWidget(pick)
        what = _wrapped()
        top.addWidget(what, 1)
        layout.addLayout(top)
        slider = StepSlider()
        slider.setRange(max(co.QUALITY_MIN, int(slot.get("min", 0))), co.QUALITY_MAX)
        slider.set_steps(co.slot_steps(slot, self._section.stepped))
        slider.setSingleStep(10)
        slider.setPageStep(100)
        _no_focus(slider)
        quality = QLabel()
        quality.setMinimumWidth(48)
        slider.valueChanged.connect(lambda v, i=index: self._on_quality(i, v))
        slider.sliderReleased.connect(self.changed)
        q_row = QHBoxLayout()
        q_row.addWidget(slider, 1)
        q_row.addWidget(quality)
        layout.addLayout(q_row)
        bonus = _wrapped()
        layout.addWidget(bonus)
        if slot.get("min", 0) > co.QUALITY_MIN:
            layout.addWidget(
                _wrapped(tr("sco.order_min_quality", quality=slot["min"]), secondary=True)
            )
        self._slot_widgets.append(
            {
                "row": row,
                "pick": pick,
                "what": what,
                "slider": slider,
                "quality": quality,
                "bonus": bonus,
            }
        )
        return row

    def _quality_tooltip(self, slot: dict, material: str) -> str:
        tiers = slot.get("tiers")
        if not tiers:
            return tr("sco.order_quality_tooltip")
        return tr(
            (
                "sco.order_quality_tiers_tooltip"
                if self._section.stepped
                else "sco.order_quality_range_tooltip"
            ),
            material=material,
            source=QUALITY_TABLE_SOURCE,
            tiers=", ".join(f"{tier} {value}" for tier, value in tiers),
        )

    def _on_toggle(self) -> None:
        show = self._body.isHidden()
        self._body.setVisible(show)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if show else Qt.ArrowType.RightArrow)
        self.expanded_changed.emit(self.line.key, show)

    def _step(self, delta: int) -> None:
        count = max(1, min(co.COUNT_MAX, self.line.count + delta))
        if count == self.line.count:
            return
        self.line.count = count
        self.refresh()
        self.changed.emit()

    def _on_pick(self, index: int) -> None:
        self.line.on = co.toggle_pick_slot(self.bp, self.line.on, index)
        self.refresh()
        self.changed.emit()

    def _on_quality(self, index: int, value: int) -> None:
        slot = self.bp["s"][index]
        value = co.clamp_quality(
            value,
            slot.get("min", 0),
            co.slot_steps(slot, self._section.stepped),
            current=self.line.q[index],
        )
        if self.line.q[index] == value:
            slider = self._slot_widgets[index]["slider"]
            if slider.value() != value:  # snapped back to where it was
                slider.blockSignals(True)
                slider.setValue(value)
                slider.blockSignals(False)
            return
        self.line.q[index] = value
        self.refresh()
        # The summary follows while dragging; the order is saved on release
        # (sliderReleased) or at once for a click on the groove.
        if self._slot_widgets[index]["slider"].isSliderDown():
            self._section.refresh_summary()
        else:
            self.changed.emit()

    def refresh(self) -> None:
        """Set every text from the line as it is now."""
        section = self._section
        self._name.setText(self.bp["n"])
        self._owned.setText("" if section.is_owned(self.bp["n"]) else tr("sco.order_not_owned"))
        self._owned.setVisible(bool(self._owned.text()))
        self._count.setText(f"×{self.line.count}")
        for i, slot in enumerate(self.bp["s"]):
            widgets = self._slot_widgets[i]
            on = self.line.on[i] if i < len(self.line.on) else True
            material = section.material_name(slot["mat"])
            amount = co.format_amount(float(slot["q"]) * self.line.count, slot["u"], section.volume)
            widgets["what"].setText(
                tr("sco.order_slot", slot=slot["n"], material=material, amount=amount)
            )
            widgets["what"].setToolTip(section.material_tooltip(slot["mat"]))
            if widgets["pick"] is not None:
                widgets["pick"].setChecked(on)
            slider = widgets["slider"]
            if slider.value() != self.line.q[i]:
                slider.blockSignals(True)
                slider.setValue(self.line.q[i])
                slider.blockSignals(False)
            tier = tier_of(slot.get("tiers"), self.line.q[i])
            widgets["quality"].setText(
                tr("sco.order_quality_tier", quality=self.line.q[i], tier=tier)
                if tier
                else tr("sco.order_quality", quality=self.line.q[i])
            )
            slider.setToolTip(self._quality_tooltip(slot, material))
            mods = co.stat_modifiers(self.bp, section.index.curves, self.line.q, only=i)
            widgets["bonus"].setText(section.bonus_html(mods))
            widgets["bonus"].setVisible(bool(mods))
            for name in ("what", "slider", "quality", "bonus"):
                widgets[name].setEnabled(on)
        total = co.stat_modifiers(self.bp, section.index.curves, self.line.q, self.line.on)
        self._total_bonus.setText(
            tr("sco.order_item_bonus", bonuses=section.bonus_html(total))
            if total
            else tr("sco.order_no_bonus")
        )


class OrderSection(QWidget):
    """The drawer's Order page. ``watch_requested`` carries the ore keys
    (``ORE_SIGNATURES`` names) to add to the scan watch list."""

    watch_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.index = CraftingIndex()
        self._by_key: dict[str, dict] = {}
        self._lines: list[co.OrderLine] = []
        # Loaded once the catalog holds blueprints, so an older index (or
        # none yet) never empties the saved order.
        self._loaded = False
        # A saved-order message (a bad name, a failed save), shown in the status line.
        self._status_note = ""
        self._owned: set[str] = set()
        self._mineral_by_material: dict[str, MineralInfo] = {}
        self._tooltip_for: Callable[[MineralInfo], str] = lambda info: info.name
        self._expanded: set[str] = set()
        self._cards: list[OrderLineCard] = []
        self.volume = AppSettings.get_sco_order_volume()
        # Quality sliders stop at each ore's tier qualities, or take any
        # quality (off: ores mixed to a quality in between).
        self.stepped = AppSettings.get_sco_order_quality_steps()

        # Summary: title + toggle, buttons, the materials tree.
        self._summary_toggle = QToolButton()
        self._summary_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._summary_toggle.setAutoRaise(True)
        self._summary_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._summary_toggle.clicked.connect(self._on_summary_toggle)
        _no_focus(self._summary_toggle)
        self._volume_btn = _button(slot=self._toggle_volume)
        self._copy_btn = _button(slot=self._copy)
        self._watch_btn = _button(slot=self._watch)
        # New order empties this one; a first click arms it (a short "Sure?"
        # on the button, the why in the status line, so nothing runs off the
        # drawer) and a second within CLEAR_CONFIRM_MS clears it.
        self._new_btn = _button(slot=self._new_order)
        self._new_armed = False
        self._new_timer = QTimer(self)
        self._new_timer.setSingleShot(True)
        self._new_timer.timeout.connect(self._disarm_new)
        self._summary_tree = QTreeWidget()
        self._summary_tree.setHeaderHidden(True)
        self._summary_tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._summary_tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._summary_tree.itemExpanded.connect(lambda _i: self._fit_summary())
        self._summary_tree.itemCollapsed.connect(lambda _i: self._fit_summary())
        _no_focus(self._summary_tree)
        self._summary_body = QWidget()
        summary_layout = QVBoxLayout(self._summary_body)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        buttons = QHBoxLayout()
        for btn in (self._volume_btn, self._copy_btn, self._watch_btn):
            buttons.addWidget(btn)
        buttons.addStretch()
        summary_layout.addLayout(buttons)
        summary_layout.addWidget(self._summary_tree)
        self._status = _wrapped(secondary=True)

        from src.gui.sco_overlay import DrawerSearch  # the drawer's own search box

        # Saved orders: a name to save the order under (<name>.json), and a
        # list of the saved ones to load.
        self._save_name = DrawerSearch()
        self._save_name.setMaxLength(co.SAVED_ORDER_NAME_MAX)
        self._save_name.returnPressed.connect(self._save_named)
        self._save_name.textChanged.connect(lambda _t: self._disarm_save())
        self._save_btn = _button(slot=self._save_named)
        self._save_armed = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._disarm_save)
        self._saved_orders = QComboBox()
        self._saved_orders.currentIndexChanged.connect(self._on_saved_order_picked)
        _no_focus(self._saved_orders, self._saved_orders.view())
        self._load_btn = _button(slot=self._load_named)
        # Delete asks for a second click within CLEAR_CONFIRM_MS, as New order does.
        self._delete_btn = _button(slot=self._delete_named)
        self._delete_armed = False
        self._delete_timer = QTimer(self)
        self._delete_timer.setSingleShot(True)
        self._delete_timer.timeout.connect(self._disarm_delete)
        save_row = QHBoxLayout()
        save_row.addWidget(self._save_name, 1)
        save_row.addWidget(self._save_btn)
        load_row = QHBoxLayout()
        load_row.addWidget(self._saved_orders, 1)
        load_row.addWidget(self._load_btn)
        load_row.addWidget(self._delete_btn)
        new_row = QHBoxLayout()
        new_row.addWidget(self._new_btn)
        new_row.addStretch()
        summary_layout.addLayout(save_row)
        summary_layout.addLayout(load_row)
        summary_layout.addLayout(new_row)

        # Add an item.

        self.search = DrawerSearch()
        self.search.textChanged.connect(self._render_results)
        self._owned_only = QCheckBox()
        self._owned_only.setChecked(AppSettings.get_sco_order_owned_only())
        self._owned_only.toggled.connect(self._on_owned_only_toggled)
        _no_focus(self._owned_only)
        self._quality_steps = QCheckBox()
        self._quality_steps.setChecked(self.stepped)
        self._quality_steps.toggled.connect(self._on_quality_steps_toggled)
        _no_focus(self._quality_steps)
        self._results = QListWidget()
        self._results.setMaximumHeight(SEARCH_LIST_HEIGHT)
        self._results.itemClicked.connect(self._on_result_clicked)
        self._results.hide()
        _no_focus(self._results)

        self._lines_box = QVBoxLayout()
        self._lines_box.setContentsMargins(0, 0, 0, 0)
        self._lines_box.setSpacing(4)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.addWidget(self._summary_toggle)
        content_layout.addWidget(self._summary_body)
        content_layout.addWidget(self._status)
        content_layout.addWidget(self.search)
        content_layout.addWidget(self._owned_only)
        content_layout.addWidget(self._quality_steps)
        content_layout.addWidget(self._results)
        content_layout.addLayout(self._lines_box)
        content_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        _no_focus(scroll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(scroll)
        self.retranslate_ui()

    # -- data in ---------------------------------------------------------

    def set_catalog(
        self,
        index: CraftingIndex,
        mineral_by_material: dict[str, MineralInfo],
        tooltip_for: Callable[[MineralInfo], str],
    ) -> None:
        """The crafting index (its blueprints) and, for Where to mine and
        Watch minerals, each material's compendium mineral."""
        self.index = index
        self._mineral_by_material = dict(mineral_by_material)
        # Before the order loads, so its qualities snap to the real ones.
        co.attach_quality_tiers(index.blueprints, self._quality_names)
        self._by_key = co.blueprints_by_key(index.blueprints)
        self._tooltip_for = tooltip_for
        if self._by_key:
            self._lines = co.load_order(AppSettings.get_sco_order(), self._by_key, self.stepped)
            self._loaded = True
        self._rebuild_cards()
        self._render_results()
        self._refresh_saved_buttons()

    def set_owned(self, owned) -> None:
        """The owned blueprint names, for the not-owned mark and the Owned
        only filter. Called on every owned change (the Blueprint Tracker,
        the drawer's own list, a log scan), so both follow at once."""
        self._owned = {_owned_key(name) for name in owned}
        for card in self._cards:
            card.refresh()
        self._render_results()

    def lines(self) -> list[co.OrderLine]:
        return list(self._lines)

    # -- helpers the cards use -------------------------------------------

    def is_owned(self, name: str) -> bool:
        return _owned_key(name) in self._owned

    def material_name(self, key: str) -> str:
        if is_unknown_material(key):
            return tr("sco.order_unknown_material")
        return self.index.material_name(key)

    def _quality_names(self, key: str) -> list[str]:
        """Names to find a material in the ore quality table by: its key
        (English), its compendium mineral (English), then its own names."""
        names = [key]
        info = self._mineral_by_material.get(key)
        if info is not None:
            names.append(info.name)
        names.extend((self.index.materials.get(key) or {}).get("names", []))
        if key in self.index.item_materials:
            names.append(self.index.item_materials[key])
        return names

    def _material_names(self) -> dict[str, str]:
        """Every slot material's display name, commodities and items alike."""
        keys = set(self.index.materials) | set(self.index.item_materials)
        for bp in self.index.blueprints:
            keys.update(slot["mat"] for slot in bp["s"])
        return {key: self.material_name(key) for key in keys}

    def material_tooltip(self, key: str) -> str:
        info = self._mineral_by_material.get(key)
        return self._tooltip_for(info) if info is not None else self.material_name(key)

    def bonus_html(self, mods: dict[str, co.StatModifier]) -> str:
        parts = []
        for stat in sorted(mods, key=lambda s: self.index.stats.get(s, s).casefold()):
            mod = mods[stat]
            sign = co.modifier_sign(mod)
            colour = BONUS_UP if sign > 0 else BONUS_DOWN if sign < 0 else None
            value = co.format_modifier(mod)
            if colour:
                value = f'<span style="color:{colour}">{value}</span>'
            parts.append(f"{self.index.stats.get(stat, stat)} {value}")
        return " · ".join(parts)

    # -- order changes ---------------------------------------------------

    def add(self, bp: dict, count: int = 1) -> None:
        """Add *count* of *bp* (raising its line when it is on the order)."""
        if not self._loaded:
            return
        before = len(self._lines)
        co.add_to_order(self._lines, bp, count, self.stepped)
        if len(self._lines) == before:
            for card in self._cards:
                if card.line.key == bp["k"]:
                    card.refresh()
        else:
            self._rebuild_cards()
        self._save()

    def remove(self, key: str) -> None:
        self._lines = [line for line in self._lines if line.key != key]
        self._expanded.discard(key)
        self._rebuild_cards()
        self._save()

    def clear(self) -> None:
        self._lines = []
        self._expanded.clear()
        self._rebuild_cards()
        self._save()

    def _save(self) -> None:
        if self._loaded:
            AppSettings.set_sco_order([line.to_dict() for line in self._lines])
        self.refresh_summary()

    def _rebuild_cards(self) -> None:
        for card in self._cards:
            # Hidden at once: deleteLater waits for the event loop, and until
            # then the old card still paints over the new ones.
            self._lines_box.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = []
        for line in self._lines:
            bp = self._by_key.get(line.key)
            if bp is None:
                continue
            card = OrderLineCard(self, line, bp, line.key in self._expanded)
            card.changed.connect(self._save)
            card.removed.connect(self.remove)
            card.expanded_changed.connect(self._on_card_expanded)
            self._lines_box.addWidget(card)
            self._cards.append(card)
        self.refresh_summary()

    def _on_card_expanded(self, key: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(key)
        else:
            self._expanded.discard(key)

    # -- summary -----------------------------------------------------------

    def _totals(self) -> list[co.MaterialTotal]:
        return co.material_totals(self._lines, self._by_key)

    def refresh_summary(self) -> None:
        crafts = sum(line.count for line in self._lines)
        self._summary_toggle.setText(tr("sco.order_summary", items=len(self._lines), crafts=crafts))
        open_rows = {
            self._summary_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self._summary_tree.topLevelItemCount())
            if self._summary_tree.topLevelItem(i).isExpanded()
        }
        self._summary_tree.clear()
        totals = self._totals()
        for row in totals:
            name = self.material_name(row.material)
            node = QTreeWidgetItem(
                [
                    tr(
                        "sco.order_material_total",
                        material=name,
                        amount=co.format_amount(row.amount, row.unit, self.volume),
                    )
                ]
            )
            node.setData(0, Qt.ItemDataRole.UserRole, row.material)
            tip = [
                self.material_tooltip(row.material),
                tr("sco.order_used_by", items=", ".join(row.items)),
            ]
            node.setToolTip(0, "\n".join(tip))
            for quality, amount in row.by_quality:
                node.addChild(
                    QTreeWidgetItem(
                        [
                            tr(
                                "sco.order_band",
                                quality=quality,
                                amount=co.format_amount(amount, row.unit, self.volume),
                            )
                        ]
                    )
                )
            self._summary_tree.addTopLevelItem(node)
            node.setExpanded(row.material in open_rows)
        if not totals:
            self._summary_tree.addTopLevelItem(QTreeWidgetItem([tr("sco.order_empty")]))
        has_lines = bool(self._lines)
        for btn in (self._copy_btn, self._watch_btn, self._new_btn):
            btn.setEnabled(has_lines)
        self._refresh_saved_buttons()
        self._watch_btn.setEnabled(bool(self._watchable(totals)))
        self._fit_summary()
        self._status.setText(self._status_text())
        self._status.setVisible(bool(self._status.text()))

    def _status_text(self) -> str:
        if not self.index.blueprints:
            return tr("sco.order_no_data")
        return self._status_note

    def _fit_summary(self) -> None:
        """Size the tree to its rows, so the page scrolls as one."""
        tree = self._summary_tree
        rows = 0
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            rows += 1 + (item.childCount() if item.isExpanded() else 0)
        height = max(tree.sizeHintForRow(0), tree.fontMetrics().height() + 4, 16)
        tree.setFixedHeight(max(1, rows) * height + 2 * tree.frameWidth() + 6)

    def _on_summary_toggle(self) -> None:
        show = self._summary_body.isHidden()
        self._summary_body.setVisible(show)
        self._summary_toggle.setArrowType(
            Qt.ArrowType.DownArrow if show else Qt.ArrowType.RightArrow
        )

    def _toggle_volume(self) -> None:
        self.volume = co.VOLUME_SCU if self.volume == co.VOLUME_CSCU else co.VOLUME_CSCU
        AppSettings.set_sco_order_volume(self.volume)
        self._volume_btn.setText(self._volume_text())
        for card in self._cards:
            card.refresh()
        self.refresh_summary()

    def _volume_text(self) -> str:
        return (
            tr("sco.order_show_scu") if self.volume == co.VOLUME_CSCU else tr("sco.order_show_cscu")
        )

    def _copy(self) -> None:
        names = self._material_names()
        text = co.order_text(self._totals(), self._lines, self._by_key, names, self.volume)
        QApplication.clipboard().setText(text)
        self._copy_btn.setText(tr("sco.order_copied"))
        QTimer.singleShot(2000, lambda: self._copy_btn.setText(tr("sco.order_copy")))

    def _watchable(self, totals: list[co.MaterialTotal]) -> set[str]:
        ores = set()
        for row in totals:
            info = self._mineral_by_material.get(row.material)
            ore = (
                ore_key(info.name)
                if info is not None
                else ore_key(self.material_name(row.material))
            )
            if ore:
                ores.add(ore)
        return ores

    def _watch(self) -> None:
        ores = self._watchable(self._totals())
        if ores:
            self.watch_requested.emit(ores)

    def _new_order(self) -> None:
        """Start a new order: the second click empties this one and the
        save name. Saved orders are left as they are."""
        if not self._new_armed:
            self._new_armed = True
            self._new_btn.setText(tr("sco.order_new_confirm"))
            self._show_status(tr("sco.order_new_note"))
            self._new_timer.start(CLEAR_CONFIRM_MS)
            return
        self._disarm_new()
        self._save_name.clear()
        self._saved_orders.setCurrentIndex(-1)
        self.clear()

    # -- saved orders ------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt's name)
        """Read the orders folder when the section is shown, not when the
        drawer is built, so a file added by hand shows up too."""
        super().showEvent(event)
        try:
            self.refresh_saved_orders()
        except Exception as exc:  # a Qt override: an exception here ends the app
            logger.warning(f"Could not list the saved crafting orders: {exc}")

    def refresh_saved_orders(self, select: str = "") -> None:
        """Fill the saved-orders list from the orders folder, keeping the
        current choice (or choosing *select*)."""
        current = select or self._saved_orders.currentText()
        names = co.list_saved_orders(AppSettings.get_sco_orders_dir())
        self._saved_orders.blockSignals(True)
        self._saved_orders.clear()
        self._saved_orders.addItems(names)
        self._saved_orders.setCurrentIndex(names.index(current) if current in names else -1)
        self._saved_orders.blockSignals(False)
        self._refresh_saved_buttons()

    def _refresh_saved_buttons(self) -> None:
        self._save_btn.setEnabled(self._loaded and bool(self._lines))
        picked = self._saved_orders.currentIndex() >= 0
        self._load_btn.setEnabled(self._loaded and picked)
        self._delete_btn.setEnabled(picked)
        self._saved_orders.setEnabled(self._saved_orders.count() > 0)

    def _save_named(self) -> None:
        """Save the order as <name>.json. A name already saved asks for a
        second click within CLEAR_CONFIRM_MS, as New order does."""
        if not (self._loaded and self._lines):
            return
        folder = AppSettings.get_sco_orders_dir()
        path = co.saved_order_path(folder, self._save_name.text())
        if path is None:
            self._show_status(tr("sco.order_save_name_needed"))
            return
        if path.exists() and not self._save_armed:
            self._save_armed = True
            self._save_btn.setText(tr("sco.order_save_replace"))
            self._save_timer.start(CLEAR_CONFIRM_MS)
            return
        self._disarm_save()
        try:
            co.save_order(folder, path.stem, self._lines)
        except OSError as exc:
            logger.warning(f"Could not save the crafting order {path}: {exc}")
            self._show_status(tr("sco.order_save_failed", file=str(path)))
            return
        self._show_status("")
        self._save_name.clear()
        self.refresh_saved_orders(select=path.stem)
        self._save_btn.setText(tr("sco.order_saved"))
        QTimer.singleShot(2000, self._disarm_save)

    def _disarm_save(self) -> None:
        self._save_armed = False
        self._save_timer.stop()
        self._save_btn.setText(tr("sco.order_save"))

    def _load_named(self) -> None:
        """Replace the order with the saved one picked in the list."""
        name = self._saved_orders.currentText()
        if not (self._loaded and name):
            return
        raw = co.read_saved_order(AppSettings.get_sco_orders_dir(), name)
        lines = co.load_order(raw, self._by_key, self.stepped)
        if not lines:
            self._show_status(tr("sco.order_load_empty", name=name))
            return
        self._show_status("")
        self._lines = lines
        self._expanded.clear()
        self._rebuild_cards()
        self._save()

    def _on_saved_order_picked(self, _index: int) -> None:
        self._disarm_delete()
        self._refresh_saved_buttons()

    def _delete_named(self) -> None:
        """Delete the saved order picked in the list, on a second click. The
        order being built is left alone."""
        name = self._saved_orders.currentText()
        if not name:
            return
        if not self._delete_armed:
            self._delete_armed = True
            self._delete_btn.setText(tr("sco.order_delete_confirm"))
            self._show_status(tr("sco.order_delete_note", name=name))
            self._delete_timer.start(CLEAR_CONFIRM_MS)
            return
        self._disarm_delete()
        try:
            co.delete_saved_order(AppSettings.get_sco_orders_dir(), name)
        except OSError as exc:
            logger.warning(f"Could not delete the saved crafting order {name}: {exc}")
            self._show_status(tr("sco.order_delete_failed", name=name))
            return
        self._saved_orders.setCurrentIndex(-1)
        self.refresh_saved_orders()

    def _disarm_delete(self) -> None:
        if self._delete_armed:
            self._show_status("")  # the "click again" note
        self._delete_armed = False
        self._delete_timer.stop()
        self._delete_btn.setText(tr("sco.order_delete"))

    def _show_status(self, text: str) -> None:
        self._status_note = text
        self._status.setText(self._status_text())
        self._status.setVisible(bool(self._status.text()))

    def _disarm_new(self) -> None:
        if self._new_armed:
            self._show_status("")  # the "click again" note
        self._new_armed = False
        self._new_timer.stop()
        self._new_btn.setText(tr("sco.order_new"))

    # -- search ------------------------------------------------------------

    def _render_results(self) -> None:
        self._results.clear()
        names = self._material_names()
        keep = (lambda bp: self.is_owned(bp["n"])) if self._owned_only.isChecked() else None
        found = co.search_blueprints(
            self.index.blueprints, self.search.text(), names, SEARCH_LIMIT, keep
        )
        for bp in found:
            item = QListWidgetItem(bp["n"])
            item.setData(Qt.ItemDataRole.UserRole, bp["k"])
            needs = ", ".join(dict.fromkeys(names.get(s["mat"], s["mat"]) for s in bp["s"]))
            tip = [bp.get("c", ""), tr("sco.tooltip_needs", materials=needs)]
            if not self.is_owned(bp["n"]):
                tip.append(tr("sco.order_not_owned"))
            item.setToolTip("\n".join(t for t in tip if t))
            self._results.addItem(item)
        self._results.setVisible(bool(found))

    def _on_owned_only_toggled(self, checked: bool) -> None:
        AppSettings.set_sco_order_owned_only(checked)
        self._render_results()

    def _on_quality_steps_toggled(self, checked: bool) -> None:
        """Switch the sliders between tier steps and the full range. Back on
        steps, every quality snaps to its slot's nearest step; off, the
        qualities stay where they are."""
        AppSettings.set_sco_order_quality_steps(checked)
        self.stepped = checked
        if checked and self._loaded:
            self._lines = co.load_order(
                [line.to_dict() for line in self._lines], self._by_key, stepped=True
            )
        self._rebuild_cards()
        self._save()

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        bp = self._by_key.get(item.data(Qt.ItemDataRole.UserRole))
        if bp is not None:
            self.add(bp)
            self.search.clear()

    def retranslate_ui(self) -> None:
        self.search.setPlaceholderText(tr("sco.order_search_placeholder"))
        self._owned_only.setText(tr("sco.order_owned_only"))
        self._owned_only.setToolTip(tr("sco.order_owned_only_tooltip"))
        self._quality_steps.setText(tr("sco.order_quality_steps"))
        self._quality_steps.setToolTip(tr("sco.order_quality_steps_tooltip"))
        self._volume_btn.setText(self._volume_text())
        self._volume_btn.setToolTip(tr("sco.order_volume_tooltip"))
        self._copy_btn.setText(tr("sco.order_copy"))
        self._copy_btn.setToolTip(tr("sco.order_copy_tooltip"))
        self._watch_btn.setText(tr("sco.order_watch"))
        self._watch_btn.setToolTip(tr("sco.order_watch_tooltip"))
        self._disarm_new()
        self._new_btn.setToolTip(tr("sco.order_new_tooltip"))
        self._save_name.setPlaceholderText(tr("sco.order_save_placeholder"))
        self._disarm_save()
        self._save_btn.setToolTip(tr("sco.order_save_tooltip"))
        self._saved_orders.setPlaceholderText(tr("sco.order_saved_orders"))
        self._load_btn.setText(tr("sco.order_load"))
        self._load_btn.setToolTip(tr("sco.order_load_tooltip"))
        self._disarm_delete()
        self._delete_btn.setToolTip(tr("sco.order_delete_tooltip"))
        self._rebuild_cards()
        self._render_results()
