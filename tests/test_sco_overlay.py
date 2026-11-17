"""Smart Citizen Overlay (SCO) windows, driven headlessly.

``QT_QPA_PLATFORM=offscreen``, same pattern as test_restore_backup.py — no
pytest-qt. Covers the drawer's list/filter/owned-toggle behaviour, the
signature label text, the capture loop only running with a reader set, and
the default reader working on a real QImage.
"""
from __future__ import annotations

import ctypes
import sys

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor

from src.gui import sco_overlay as so
from src.gui.sco_overlay import (
    DEFAULT_OVERLAY_COLORS, DRAWER_HANDLE_HEIGHT, DRAWER_HANDLE_OVERLAP,
    DRAWER_HANDLE_WIDTH, LABEL_GAP, PASS_THROUGH_IDLE_POLL_MS, PASS_THROUGH_POLL_MS,
    SAVE_SAMPLES_ENV, SCAN_REGION, SECTION_ICONS, WS_EX_TRANSPARENT, BlueprintDrawer,
    OverlayColors, SectionTabBar, drawer_edge, ScoOverlay, device_end, format_matches,
    game_in_front, hud_signature_reader, monitor_at, native_work_area, pointer_hidden,
    qt_round, scan_region_rect, set_click_through, within_device_pixels,
)
from src.utils.blueprint_meta import BlueprintItem
from src.utils.mining_catalog import CraftingIndex, MineralInfo
from src.utils.mining_signatures import decode_signature
from src.utils.settings import AppSettings


@pytest.fixture(autouse=True)
def _hermetic_overlay(monkeypatch, tmp_path):
    """No real theme or samples-folder reads: the overlay takes its colours
    from settings on every start and resolves the samples folder per save.
    Nor is Windows asked which window is in front, which a running overlay
    does every tick (tests that need it patch their own answer)."""
    monkeypatch.setattr(OverlayColors, "from_theme",
                        classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    monkeypatch.setattr("src.gui.sco_overlay.AppSettings.get_sco_samples_dir",
                        staticmethod(lambda: tmp_path / "default_samples"))
    monkeypatch.setattr(so, "game_in_front", lambda: False)


@pytest.fixture
def samples_on(monkeypatch):
    """The sample capture is on only with SAVE_SAMPLES_ENV set at startup."""
    monkeypatch.setenv(SAVE_SAMPLES_ENV, "1")


def _meta():
    return {
        "Agni": BlueprintItem("Agni", frozenset({"Haul cargo"}), "Quantum Drive", "Industrial",
                              "S3", "B"),
        "Norfield": BlueprintItem("Norfield", frozenset(), "Cooler", "Military", "S1", "A"),
        "Bracer": BlueprintItem("Bracer"),
    }


def _names(drawer):
    return [drawer._list.item(i).text() for i in range(drawer._list.count())]


def test_drawer_lists_and_filters(qapp):
    drawer = BlueprintDrawer()
    drawer.set_items(_meta(), {"Agni"})
    assert _names(drawer) == ["Agni", "Bracer", "Norfield"]
    assert drawer._summary.text() == "Owned 1 of 3"
    drawer._owned_only.setChecked(True)
    assert _names(drawer) == ["Agni"]
    drawer._owned_only.setChecked(False)
    drawer._search.setText("nor")
    assert _names(drawer) == ["Norfield"]


def _long_list_drawer(qapp):
    drawer = BlueprintDrawer()
    drawer.open_section("blueprints")
    drawer.show_docked()
    meta = {f"Item {i:03}": BlueprintItem(f"Item {i:03}") for i in range(300)}
    owned = {name for i, name in enumerate(meta) if i % 2 == 0}
    drawer.set_items(meta, owned)
    qapp.processEvents()
    bar = drawer._list.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    return drawer, meta, owned, bar


def test_a_tick_keeps_the_list_where_it_was(qapp):
    # Every tick comes back through set_items (MainWindow recomputes the
    # owned set); the list must not jump to the top each time.
    drawer, meta, owned, bar = _long_list_drawer(qapp)
    position = bar.value()
    assert position > 0
    drawer.set_items(meta, owned | {"Item 151"})
    qapp.processEvents()
    assert bar.value() == position
    item = drawer._list.findItems("Item 151", Qt.MatchFlag.MatchExactly)[0]
    assert item.checkState() == Qt.CheckState.Checked
    assert drawer._summary.text() == "Owned 151 of 300"
    drawer.hide()


def test_an_untick_under_owned_only_keeps_the_list_where_it_was(qapp):
    drawer, meta, owned, bar = _long_list_drawer(qapp)
    drawer._owned_only.setChecked(True)
    qapp.processEvents()
    bar.setValue(bar.maximum() // 2)
    position = bar.value()
    drawer.set_items(meta, owned - {"Item 100"})
    qapp.processEvents()
    assert "Item 100" not in _names(drawer) and bar.value() == position
    drawer.hide()


def test_drawer_checkbox_emits_owned_toggle(qapp):
    drawer = BlueprintDrawer()
    drawer.set_items(_meta(), set())
    seen = []
    drawer.owned_toggled.connect(lambda n, c: seen.append((n, c)))
    drawer._list.item(0).setCheckState(Qt.CheckState.Checked)
    assert seen == [("Agni", True)]


def test_drawer_tooltip_shows_details_and_missions(qapp):
    tip = BlueprintDrawer._tooltip(_meta()["Agni"])
    assert "Quantum Drive" in tip and "S3" in tip and "Haul cargo" in tip


def test_tooltip_caps_long_mission_lists(qapp):
    from src.gui.sco_overlay import TOOLTIP_MAX_MISSIONS
    missions = frozenset(f"Mission {i:02d}" for i in range(TOOLTIP_MAX_MISSIONS + 3))
    tip = BlueprintDrawer._tooltip(BlueprintItem("Agni", missions)).splitlines()
    assert tip[0] == f"Rewarded by {len(missions)} missions:"
    assert tip[-1] == "...and 3 more"
    assert len(tip) == TOOLTIP_MAX_MISSIONS + 2


def test_format_matches(qapp):
    assert format_matches(decode_signature(10200)) == "3 × Lindinium"
    assert format_matches(decode_signature(15697)) == "Unidentified"
    # #523: a round number that fits salvage too lists salvage first and
    # marks ROC and FPS surface only, since in space salvage is the answer.
    assert format_matches(decode_signature(12000)).splitlines() == [
        "6 × Salvage", "3 × ROC Mineable (surface only)", "4 × FPS Mineable (surface only)",
    ]
    assert format_matches(decode_signature(6000)).splitlines() == [
        "3 × Salvage", "2 × FPS Mineable (surface only)",
    ]
    # Without salvage in the reading nothing is moved or marked.
    assert format_matches(decode_signature(3000)) == "1 × FPS Mineable"
    assert format_matches(decode_signature(2000)) == "1 × Salvage"


def test_scan_region_scales_with_screen(qapp):
    r = scan_region_rect(QRect(0, 0, 2560, 1600))
    assert (r.x(), r.y()) == (int(2560 * SCAN_REGION[0]), int(1600 * SCAN_REGION[1]))
    # The two sample readouts (7,200 and 10,200) sit inside the box.
    assert r.contains(1150, 550) and r.contains(1290, 572)


def test_a_tab_opens_its_own_section(qapp):
    drawer = BlueprintDrawer()
    assert drawer._handle.current is None and not drawer._panel.isVisibleTo(drawer)
    drawer.open_section("minerals")
    assert drawer._panel.isVisibleTo(drawer)
    assert drawer._sections.currentWidget() is drawer._section_pages["minerals"]
    assert drawer._handle.current == "minerals"
    # Another tab switches the section and keeps the drawer open.
    drawer.open_section("crafting")
    assert drawer._panel.isVisibleTo(drawer)
    assert drawer._sections.currentWidget() is drawer._section_pages["crafting"]
    # The open section's own tab closes it.
    drawer.open_section("crafting")
    assert not drawer._panel.isVisibleTo(drawer) and drawer._handle.current is None


def _tab_centre(bar, index):
    from PyQt6.QtCore import QPointF

    step = DRAWER_HANDLE_HEIGHT - DRAWER_HANDLE_OVERLAP
    return QPointF(DRAWER_HANDLE_WIDTH * 0.75, index * step + DRAWER_HANDLE_HEIGHT / 2)


def test_tabs_overlap_and_the_open_one_is_in_front(qapp):
    from PyQt6.QtCore import QPointF

    bar = SectionTabBar()
    assert bar.height() == 3 * DRAWER_HANDLE_HEIGHT - 2 * DRAWER_HANDLE_OVERLAP
    for i, name in enumerate(SECTION_ICONS):
        assert bar.tab_at(_tab_centre(bar, i)) == name
    # Along the edge, where Blueprints' and Minerals' tall sides overlap, the
    # later tab is in front until Blueprints opens.
    overlap = QPointF(DRAWER_HANDLE_WIDTH - 1, DRAWER_HANDLE_HEIGHT - DRAWER_HANDLE_OVERLAP / 2)
    assert bar.tab_at(overlap) == "minerals"
    bar.set_current("blueprints")
    assert bar.tab_at(overlap) == "blueprints"
    # The slanted gap beside the overlap belongs to no tab.
    assert bar.tab_at(QPointF(1, DRAWER_HANDLE_HEIGHT - DRAWER_HANDLE_OVERLAP / 2)) is None


def test_a_click_on_a_tab_opens_its_section(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QMouseEvent

    drawer = BlueprintDrawer()
    bar = drawer._handle
    centre = _tab_centre(bar, 2)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, centre, centre, Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    bar.mousePressEvent(press)
    assert drawer._handle.current == "crafting" and drawer._panel.isVisibleTo(drawer)


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_tabs_run_along_each_edge(qapp, edge):
    bar = SectionTabBar()
    bar.set_edge(edge)
    length = 3 * DRAWER_HANDLE_HEIGHT - 2 * DRAWER_HANDLE_OVERLAP
    sideways = edge in ("left", "right")
    assert (bar.width(), bar.height()) == (
        (DRAWER_HANDLE_WIDTH, length) if sideways else (length, DRAWER_HANDLE_WIDTH))
    # The first tab sits at the start of the bar, the last at its end.
    from PyQt6.QtCore import QPointF

    mid, near = DRAWER_HANDLE_WIDTH / 2, DRAWER_HANDLE_HEIGHT / 2
    far = length - DRAWER_HANDLE_HEIGHT / 2
    at = (lambda along: QPointF(mid, along)) if sideways else (lambda along: QPointF(along, mid))
    assert bar.tab_at(at(near)) == "blueprints" and bar.tab_at(at(far)) == "crafting"


def test_tab_bar_paints(qapp):
    from PyQt6.QtGui import QImage

    bar = SectionTabBar()
    bar.set_current("minerals")
    image = QImage(bar.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    bar.render(image)
    assert any(image.pixelColor(x, y).alpha() for x in range(image.width())
               for y in range(image.height()))


def _painted_pixels(bar, scale):
    """The device pixels *bar* paints (any alpha) at *scale* device pixels
    per logical one, as Windows hit-tests the drawer's see-through window.
    Rendered without the window background, which render() draws by default
    and the see-through drawer never does."""
    from PyQt6.QtGui import QImage, QRegion
    from PyQt6.QtWidgets import QWidget

    image = QImage(bar.size() * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(0)
    bar.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image, [(x, y) for x in range(image.width()) for y in range(image.height())
                   if image.pixelColor(x, y).alpha()]


@pytest.mark.parametrize("edge", ["right", "left", "top", "bottom"])
@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("current", [None, "minerals"])
def test_every_pixel_the_tabs_paint_opens_a_tab(qapp, edge, scale, current):
    """Windows sends a click on any pixel the tabs paint to the drawer, which
    then takes focus from the game, so every such pixel must open a tab. The
    anti-aliased outline outside a tab's shape opened nothing: a game's hidden
    pointer parked in the screen corner sat on such a pixel, and a click
    there lost the game's focus with nothing to show for it."""
    from PyQt6.QtCore import QPointF

    bar = SectionTabBar()
    bar.set_edge(edge)
    bar.set_current(current)
    image, painted = _painted_pixels(bar, scale)
    # The render covers the bar at this scale, edge to edge.
    assert max(x for x, _ in painted) == image.width() - 1
    assert max(y for _, y in painted) == image.height() - 1
    # A click on a device pixel reaches Qt at that pixel's top-left corner.
    missed = [(x, y) for x, y in painted if bar.tab_at(QPointF(x / scale, y / scale)) is None]
    assert not missed, missed[:10]


def test_the_outline_pixel_in_the_corner_opens_the_first_tab(qapp):
    """The top-right drawer's outermost pixel, the screen corner: painted by
    the first tab's outline, outside its shape (player report, 2026-11-16)."""
    from PyQt6.QtCore import QPointF

    bar = SectionTabBar()
    _, painted = _painted_pixels(bar, 1.0)
    corner = (bar.width() - 1, 0)
    assert corner in painted
    assert not bar._tab_shape(0).contains(QPointF(*corner))
    assert bar.tab_at(QPointF(*corner)) == "blueprints"


@pytest.mark.parametrize("current, point, section", [
    # Closed at 125%: device pixel (10, 55), painted by Blueprints' outline
    # alone, 0.77 px from it and 1.72 px from Minerals, which is in front.
    (None, (8.0, 44.0), "blueprints"),
    # Closed at 200%: the last column beside Blueprints' lower corner.
    (None, (21.5, 39.5), "blueprints"),
    (None, (21.5, 41.0), "blueprints"),
    # Minerals open at 100%: (8, 86) is painted by Crafting's outline alone.
    # The open tab, tested first, used to take it and close the drawer.
    ("minerals", (8.0, 86.0), "crafting"),
    ("minerals", (21.6, 39.2), "blueprints"),
])
def test_an_outline_pixel_opens_the_nearest_tab(qapp, current, point, section):
    """A press on no tab but on an outline opens the tab whose outline is
    nearest, not the first one front to back (found in review)."""
    from PyQt6.QtCore import QPointF

    bar = SectionTabBar()
    bar.set_current(current)
    assert bar.tab_at(QPointF(*point)) == section


def _click_through_qt(drawer, x, y):
    """A left click at (x, y) in the drawer, handed to its window as Windows
    hands it over, so Qt picks the widget that gets it (QWidget.childAt)."""
    from PyQt6.QtCore import QCoreApplication, QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    local = QPointF(x, y)
    screen_pos = QPointF(drawer.mapToGlobal(QPoint(0, 0))) + local
    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QCoreApplication.sendEvent(drawer.windowHandle(), QMouseEvent(
            kind, local, screen_pos, Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def docked_drawer(qapp):
    """A drawer shown at its default place (middle right), hidden after."""
    drawer = BlueprintDrawer()
    drawer.show_docked()
    yield drawer
    drawer.hide()


@pytest.mark.parametrize("position, point", [
    ("top_right", (21.5, 0.0)),        # the screen's corner pixel at 200%
    ("middle_right", (21.5, 10.0)),     # the bar's last device column at 200%
    ("middle_right", (21.5, 65.0)),
    ("middle_right", (21.5, 110.0)),
    ("middle_right", (21.0, 10.0)),     # control: inside the bar's rectangle
    ("top_center", (10.0, 21.5)),       # the bar's last device row at 200%
])
def test_a_click_on_the_bars_outermost_pixels_opens_its_tab(docked_drawer, slot_errors,
                                                            position, point):
    """Qt hands a click to the child under it by a rectangle a pixel short of
    the child's right and bottom edges, so above 100% the tab bar's outermost
    painted line reached the drawer, which opened nothing, though Windows had
    given the drawer focus for it (found in review)."""
    from PyQt6.QtCore import QPointF

    drawer = docked_drawer
    drawer.set_position(position)
    expected = drawer._handle.tab_at(QPointF(*point))
    assert expected
    _click_through_qt(drawer, *point)
    assert drawer.is_open() and drawer._current == expected
    assert not slot_errors


def test_a_click_on_the_open_drawers_bar_edge_switches_section(docked_drawer, slot_errors):
    """Open, the bar sits inside the drawer beside the panel: its last column
    still reaches the drawer, which finds the tab from the bar's own place."""
    from PyQt6.QtCore import QPointF

    drawer = docked_drawer
    drawer.open_section("blueprints")
    bar = drawer._handle.geometry()
    assert bar.top() > 0                                       # the bar is set in the drawer
    assert drawer._handle.tab_at(QPointF(21.5, 65.0)) == "minerals"
    _click_through_qt(drawer, bar.left() + 21.5, bar.top() + 65.0)
    assert drawer.is_open() and drawer._current == "minerals"
    assert not slot_errors


def test_a_click_between_the_tabs_opens_nothing(docked_drawer, slot_errors):
    _click_through_qt(docked_drawer, 1.0, 44.5)        # the slanted gap between two tabs
    assert not docked_drawer.is_open()
    assert not slot_errors


def test_drawer_takes_theme_colours(qapp):
    gold = OverlayColors(background="#12100c", text="#e8e0cc", accent="#C9A961",
                         secondary="#A08C5A")
    drawer = BlueprintDrawer(gold)
    assert drawer._handle.colors == gold
    assert "#C9A961" in drawer._panel.styleSheet()
    assert "rgba(18, 16, 12," in drawer._panel.styleSheet()   # see-through window colour
    drawer.apply_colors(DEFAULT_OVERLAY_COLORS)
    assert drawer._handle.colors == DEFAULT_OVERLAY_COLORS


def test_no_reader_means_no_capture(qapp):
    # Keep the test off the registry-backed theme setting.
    overlay = ScoOverlay()
    overlay.set_reader(None)
    overlay.start()
    assert not overlay._timer.isActive()
    overlay.set_reader(lambda image: None)
    assert overlay._timer.isActive()
    overlay.stop()
    assert not overlay._timer.isActive()


def test_default_reader_is_the_hud_reader(qapp):
    assert ScoOverlay()._reader is hud_signature_reader


def test_hud_reader_reads_a_qimage(qapp):
    # The fixtures are 1600 px-tall screen crops; pad to a full SCAN_REGION
    # height so the reader's digit-size estimate matches the real capture.
    from pathlib import Path

    from PyQt6.QtGui import QColor, QImage, QPainter

    crop = QImage(str(Path(__file__).parent / "fixtures" / "sco" / "p6_3400.png"))
    capture = QImage(crop.width(), int(1600 * SCAN_REGION[3]), QImage.Format.Format_RGB32)
    capture.fill(QColor(10, 30, 50))
    painter = QPainter(capture)
    painter.drawImage(0, 40, crop)
    painter.end()
    text, where = hud_signature_reader(capture)
    assert text == "3,400"
    assert 40 <= where.top() <= 40 + crop.height()


def test_sample_saved_once_per_reading(qapp, tmp_path, samples_on):
    from PyQt6.QtGui import QImage

    overlay = ScoOverlay(sample_dir=tmp_path / "samples")
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    overlay._save_sample(image, "7,200", QRect(50, 40, 30, 11))
    overlay._save_sample(image, "7,200", QRect(50, 40, 30, 11))
    assert overlay.wait_for_reader(5000)
    saved = list((tmp_path / "samples").iterdir())
    assert len(saved) == 1 and saved[0].name.endswith("_7200.png")


def test_one_frame_misread_does_not_replace_the_label(qapp):
    from PyQt6.QtCore import QPoint

    overlay = ScoOverlay()
    at = QPoint(10, 10)
    overlay._on_reading(7200, at)
    assert not overlay.label.isVisible()            # first sighting: wait
    overlay._on_reading(7200, at)
    assert overlay.label._label.text() == "2 × Bexalite"
    overlay._on_reading(7208, at)                   # one misread frame
    assert overlay.label._label.text() == "2 × Bexalite"
    overlay._on_reading(7200, at)
    overlay._on_reading(7208, at)                   # the misread again, but not back to back
    assert overlay.label._label.text() == "2 × Bexalite"
    overlay._on_reading(10200, at)
    overlay._on_reading(10200, at)                  # a real change sticks
    assert overlay.label._label.text() == "3 × Lindinium"
    overlay.stop()


def test_label_is_centred_under_the_readout_in_odw_colours(qapp):
    from PyQt6.QtCore import QPoint

    from src.gui.sco_overlay import ODW_OVERLAY_COLORS, ScanLabelWindow

    label = ScanLabelWindow()
    label.show_text("3 × Lindinium", QPoint(500, 300))
    assert abs(label.x() + label.width() // 2 - 500) <= 1
    # The box sits on the anchor; the window around it leaves room for a glow,
    # less above, so it never reaches back over the readout.
    label.layout().activate()
    assert label.y() + label._label.y() == 300
    assert 0 < 300 - label.y() < LABEL_GAP
    assert label._label.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert ODW_OVERLAY_COLORS.accent in label._label.styleSheet()
    label.hide()


def test_a_watched_mineral_makes_the_label_glow(qapp):
    from PyQt6.QtCore import QPoint

    overlay = ScoOverlay()
    overlay.set_reader(None)
    overlay.start()
    at = QPoint(500, 300)
    try:
        overlay.set_watched_minerals({"lindinium"})
        for _ in range(2):
            overlay._on_reading(10200, at)                  # 3 × Lindinium
        assert overlay.label.glowing and overlay.label._glow.isEnabled()
        assert DEFAULT_OVERLAY_COLORS.accent in overlay.label._label.styleSheet()
        for _ in range(2):
            overlay._on_reading(7200, at)                   # 2 × Bexalite
        assert not overlay.label.glowing
        # Ticking the mineral while its reading shows lights it up at once.
        overlay.drawer.set_catalog(*_catalog())
        overlay.set_watched_minerals({"bexalite"})
        assert overlay.label.glowing
    finally:
        overlay.stop()


def test_drawer_mineral_checkboxes_and_clear_all(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog(*_catalog())
    seen = []
    drawer.watched_changed.connect(seen.append)
    tree = drawer._mineral_tree
    rows = {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}
    beryl = rows["Beryl"]
    assert beryl.checkState(1) == Qt.CheckState.Unchecked
    assert not drawer._clear_watched_btn.isEnabled()
    beryl.setCheckState(1, Qt.CheckState.Checked)
    assert seen[-1] == {"beryl"} and drawer._clear_watched_btn.isEnabled()
    # The tick survives a new search.
    drawer._mineral_search.setText("ber")
    assert tree.topLevelItem(0).checkState(1) == Qt.CheckState.Checked
    drawer._clear_watched_btn.click()
    assert seen[-1] == set() and tree.topLevelItem(0).checkState(1) == Qt.CheckState.Unchecked
    assert not drawer._clear_watched_btn.isEnabled()
    # set_watched mirrors the saved list without echoing it back.
    count = len(seen)
    drawer.set_watched({"beryl"})
    assert tree.topLevelItem(0).checkState(1) == Qt.CheckState.Checked and len(seen) == count


def test_only_ores_with_a_signature_get_a_checkbox(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog({"Hadanite": MineralInfo("Hadanite", "Gems", ("Aberdeen",))},
                       CraftingIndex())
    rows = _top_rows(drawer._mineral_tree)
    assert rows["Hadanite"].data(1, Qt.ItemDataRole.CheckStateRole) is None


def _top_rows(tree):
    return {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}


def test_salvage_can_be_watched(qapp):
    """#523: salvage ends the Minerals list with its own watch box, and a
    decode that includes it sets off the label's alerts."""
    from PyQt6.QtCore import QPoint

    overlay = ScoOverlay()
    overlay.set_reader(None)
    overlay.start()
    try:
        drawer = overlay.drawer
        drawer.set_catalog(*_catalog())
        tree = drawer._mineral_tree
        assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == [
            "Beryl", "Hadanite", "Salvage"]                     # after the minerals
        salvage = tree.topLevelItem(2)
        assert salvage.checkState(1) == Qt.CheckState.Unchecked
        assert "2,000 each, up to 30" in salvage.toolTip(0)
        assert salvage.toolTip(1) == "Alert when salvage is scanned"
        seen = []
        overlay.watched_changed.connect(seen.append)
        salvage.setCheckState(1, Qt.CheckState.Checked)
        assert seen == [{"salvage"}]
        for _ in range(2):
            overlay._on_reading(6000, QPoint(500, 300))     # 3 × Salvage or 2 × FPS
        assert overlay.label.watched and overlay.label.glowing
        # Clear all takes it off too, and a search for a mineral hides the row.
        drawer._clear_watched_btn.click()
        assert seen[-1] == set() and not overlay.label.watched
        drawer._mineral_search.setText("ber")
        assert "Salvage" not in _top_rows(tree)
        drawer._mineral_search.setText("salv")
        assert list(_top_rows(tree)) == ["Salvage"]
    finally:
        overlay.stop()


def test_drawer_scan_decoder_switch(qapp):
    overlay = ScoOverlay()
    seen = []
    overlay.scan_decoder_toggled.connect(seen.append)
    check = overlay.drawer._decoder_check
    assert check.isChecked()
    check.setChecked(False)
    assert seen == [False]
    # The Overlay tab's switch reaches the drawer without an echo.
    overlay.set_options({"scan_decoder": True})
    assert check.isChecked() and seen == [False]


def test_own_label_is_blacked_out_of_the_capture(qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QColor, QImage

    overlay = ScoOverlay()
    region = QRect(1000, 500, 400, 200)
    overlay.label.show_text("2 × Bexalite", QPoint(1200, 550))
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    overlay._mask_own_label(image, region)
    inside = overlay.label.geometry().center() - region.topLeft()
    assert image.pixelColor(inside) == QColor(0, 0, 0)
    assert image.pixelColor(5, 5) == QColor(255, 255, 255)
    overlay.stop()


def test_options_switch_parts_off_while_running(qapp):
    overlay = ScoOverlay()
    overlay.set_reader(lambda image: None)
    overlay.start()
    assert overlay.is_running() and overlay.drawer.isVisible() and overlay._timer.isActive()
    overlay.set_options({"scan_decoder": False, "drawer": False})
    assert overlay.is_running()   # still on, just with nothing showing
    assert not overlay.drawer.isVisible() and not overlay._timer.isActive()
    overlay.set_options({})
    assert overlay.drawer.isVisible() and overlay._timer.isActive()
    overlay.stop()
    assert not overlay.is_running()


def test_samples_are_off_without_the_env_var(qapp, tmp_path, monkeypatch):
    """Players never get the capture: it is for tuning the reader only."""
    from PyQt6.QtGui import QImage

    monkeypatch.delenv(SAVE_SAMPLES_ENV, raising=False)
    overlay = ScoOverlay(sample_dir=tmp_path / "samples")
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    overlay._save_sample(image, "7,200", QRect(10, 10, 30, 11))
    assert overlay.wait_for_reader(5000)
    assert not (tmp_path / "samples").exists()


def _catalog():
    minerals = {
        "Beryl": MineralInfo("Beryl", "Rare", ("Aaron Halo", "ARC-L3", "Monox")),
        "Hadanite": MineralInfo("Hadanite", "Uncommon", ("Aberdeen", "All Moons/Planets/Caves")),
    }
    crafting = CraftingIndex({
        "beryl": {"names": ["Beryl (Raw)", "Beryl"],
                  "items": [["Armor", "Antium Helmet"], ["Weapons", "Arclight Pistol"]]},
        "hadanite": {"names": ["Hadanite"], "items": [["Weapons", "Arclight Pistol"]]},
    })
    return minerals, crafting


def _tree(tree):
    def walk(item):
        return [item.text(0), [walk(item.child(i)) for i in range(item.childCount())]]
    return [walk(tree.topLevelItem(i)) for i in range(tree.topLevelItemCount())]


def test_mineral_search_groups_locations_by_system(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog(*_catalog())
    drawer._mineral_search.setText("beryl")
    assert _tree(drawer._mineral_tree) == [
        ["Beryl", [["Stanton", [["Aaron Halo", []], ["ARC-L3", []]]], ["Pyro", [["Monox", []]]]]],
    ]
    # A location finds the minerals there.
    drawer._mineral_search.setText("aberdeen")
    assert [row[0] for row in _tree(drawer._mineral_tree)] == ["Hadanite"]


def test_mineral_and_location_tooltips(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog(*_catalog())
    drawer._mineral_search.setText("beryl")
    beryl = drawer._mineral_tree.topLevelItem(0)
    tip = beryl.toolTip(0)
    assert "Tier: Rare" in tip and "Pyro: Monox" in tip and "Used in 2 crafted items" in tip
    assert "Scan signature: 3,540 per rock" in tip
    monox = beryl.child(1).child(0)
    assert monox.toolTip(0) == "Monox\nSystem: Pyro\nMinerals here: Beryl"


def test_crafting_search_both_ways(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog(*_catalog())
    drawer._crafting_search.setText("beryl")
    assert _tree(drawer._crafting_tree) == [
        ["Used in (by Beryl (Raw)):",
         [["Antium Helmet (Armor)", []], ["Arclight Pistol (Weapons)", []]]],
    ]
    drawer._crafting_search.setText("arclight")
    rows = _tree(drawer._crafting_tree)
    assert rows == [["Arclight Pistol needs:", [["Beryl (Raw)", []], ["Hadanite", []]]]]
    item = drawer._crafting_tree.topLevelItem(0)
    assert "Needs: Beryl (Raw), Hadanite" in item.toolTip(0)
    assert "Tier: Rare" in item.child(0).toolTip(0)   # the mineral's own tooltip


def test_crafting_links_materials_to_minerals_cig_spells_differently(qapp):
    # "Pressurized Ice" is the compendium's "Ice"; matching on the first
    # word missed it, so its rows had no mineral tooltip.
    minerals = {"Ice": MineralInfo("Ice", "", ("Yela",))}
    crafting = CraftingIndex({
        "pressurized_ice": {"names": ["Pressurized Ice"], "items": [["Armor", "Frost Suit"]]},
    })
    drawer = BlueprintDrawer()
    drawer.set_catalog(minerals, crafting)
    drawer._crafting_search.setText("pressurized")
    used_in = drawer._crafting_tree.topLevelItem(0)
    assert used_in.text(0) == "Used in (by Pressurized Ice):"
    assert used_in.toolTip(0).startswith("Ice\n")
    drawer._crafting_search.setText("frost")
    assert drawer._crafting_tree.topLevelItem(0).child(0).toolTip(0).startswith("Ice\n")


def test_drawer_follows_a_language_switch(qapp):
    from src.utils import i18n

    drawer = BlueprintDrawer()
    drawer.set_items(_meta(), {"Agni"})
    english = drawer._search.placeholderText(), drawer._summary.text()
    try:
        i18n.set_language("german")
        drawer.retranslate_ui()
        assert drawer._search.placeholderText() not in ("", english[0])
        assert drawer._summary.text() != english[1]
        assert drawer._clear_watched_btn.text() == i18n.tr("sco.clear_watched")
    finally:
        i18n.set_language("english")
    drawer.retranslate_ui()
    assert (drawer._search.placeholderText(), drawer._summary.text()) == english


def test_empty_catalog_says_how_to_fill_it(qapp):
    drawer = BlueprintDrawer()
    drawer.set_catalog({}, CraftingIndex())
    tree = drawer._mineral_tree
    # Salvage needs no catalog, so it stays, under the message.
    assert tree.topLevelItemCount() == 2 and tree.topLevelItem(1).text(0) == "Salvage"
    assert tree.topLevelItem(0).text(0).startswith("No minerals match")
    assert drawer._crafting_tree.topLevelItem(0).text(0).startswith("No matches")


def test_sections_follow_the_options(qapp):
    overlay = ScoOverlay()
    overlay.drawer.open_section("minerals")
    overlay.set_options({"drawer_minerals": False})
    assert overlay.drawer._handle.sections == ["blueprints", "crafting"]
    # Switching off the open section closes the drawer.
    assert not overlay.drawer._panel.isVisibleTo(overlay.drawer)
    assert overlay.drawer.has_sections()


def test_no_sections_hides_the_drawer(qapp):
    overlay = ScoOverlay()
    overlay.start()
    try:
        overlay.set_options({"drawer_blueprints": False, "drawer_minerals": False,
                             "drawer_crafting": False})
        assert not overlay.drawer.has_sections() and not overlay.drawer.isVisible()
    finally:
        overlay.stop()


@pytest.mark.parametrize("position, edge, corner", [
    ("top_left", "left", "top_left"),
    ("top_center", "top", "top"),
    ("top_right", "right", "top_right"),
    ("middle_left", "left", "left"),
    ("middle_right", "right", "right"),
    ("bottom_left", "left", "bottom_left"),
    ("bottom_center", "bottom", "bottom"),
    ("bottom_right", "right", "bottom_right"),
])
def test_drawer_docks_at_each_position(qapp, position, edge, corner):
    from PyQt6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen().availableGeometry()
    drawer = BlueprintDrawer()
    drawer.set_position(position)
    assert drawer_edge(position) == edge and drawer._handle.edge == edge
    for expanded in (False, True):
        if expanded:
            drawer.open_section("blueprints")
        g = drawer.geometry()
        assert screen.contains(g), (position, expanded, g)
        if "left" in corner:
            assert g.left() == screen.left()
        if "right" in corner:
            assert g.right() == screen.right()
        if "top" in corner:
            assert g.top() == screen.top()
        if "bottom" in corner:
            assert g.bottom() == screen.bottom()
        if corner in ("left", "right"):
            assert abs(g.center().y() - screen.center().y()) <= 1
        if corner in ("top", "bottom"):
            assert abs(g.center().x() - screen.center().x()) <= 1
    # Open, the panel lies against the screen edge with the handle inside it.
    drawer.layout().activate()
    handle, panel = drawer._handle.geometry(), drawer._panel.geometry()
    if edge == "right":
        assert handle.right() < panel.left()
    elif edge == "left":
        assert handle.left() > panel.right()
    elif edge == "top":
        assert handle.top() > panel.bottom()
    else:
        assert handle.bottom() < panel.top()


def test_unknown_position_falls_back_to_middle_right(qapp):
    drawer = BlueprintDrawer()
    drawer.set_position("nowhere")
    assert drawer._handle.edge == "right"


# --- the drawer inside its screen in device pixels -------------------------------

class FakeScreen:
    """A QScreen as Qt on Windows shows a 2560 x 1440 monitor with a 60 px
    taskbar at *ratio*: the top-left in device pixels, the sizes divided by
    the ratio and rounded."""

    def __init__(self, ratio):
        self._ratio = ratio
        self._geometry = QRect(0, 0, qt_round(2560 / ratio), qt_round(1440 / ratio))
        self._available = QRect(0, 0, qt_round(2560 / ratio), qt_round(1380 / ratio))
        self.native_work_area = (0, 0, 2560, 1380)

    def geometry(self):
        return QRect(self._geometry)

    def availableGeometry(self):
        return QRect(self._available)

    def devicePixelRatio(self):
        return self._ratio


def _fake_primary_screen(monkeypatch, ratio, monitor_beyond=True):
    """A FakeScreen at *ratio* as the primary screen, its work area as
    Windows names it, and a monitor (or none) just past every edge."""
    screen = FakeScreen(ratio)
    monkeypatch.setattr(so.QGuiApplication, "primaryScreen", staticmethod(lambda: screen))
    monkeypatch.setattr(so, "native_work_area", lambda s: s.native_work_area)
    monkeypatch.setattr(so, "monitor_at", lambda *rect: monitor_beyond)
    return screen


def test_qt_round_takes_a_half_away_from_zero():
    # Python's round() takes a half to even; Qt 6 places windows with qRound,
    # which takes it away from zero (measured: QPoint(-5, 0) * 0.5 is -3).
    assert [qt_round(v) for v in (0.5, 1.5, 2.5, 27.5, 2532.5, 2.4, 2.6)] == \
        [1, 2, 3, 28, 2533, 2, 3]
    assert [qt_round(v) for v in (-0.5, -1.5, -2.5, -2.4, -2.6, 0.0, -0.0)] == \
        [-1, -2, -3, -2, -3, 0, 0]


def test_flush_in_logical_pixels_ended_past_the_edge():
    """Why the fit is needed: at 125% and 150% the closed drawer flush with
    the right edge in logical pixels ended one device pixel past it, as
    measured on real windows (2533 to 2561 and 2528 to 2561)."""
    for ratio in (1.25, 1.5):
        screen = FakeScreen(ratio)
        x = screen.availableGeometry().right() - DRAWER_HANDLE_WIDTH + 1
        assert device_end(x, DRAWER_HANDLE_WIDTH, 0, ratio) == 2561


@pytest.mark.parametrize("ratio", [1.25, 1.5, 1.75, 2.0, 2.25])
@pytest.mark.parametrize("position", AppSettings.SCO_DRAWER_POSITIONS)
def test_the_drawer_stays_on_its_screen_in_device_pixels(qapp, monkeypatch, ratio, position):
    """In device pixels as Qt places the window, with a monitor (or the
    taskbar) beyond every edge: inside the work area, flush with the edge it
    docks to, or a logical pixel short of a right or bottom edge where Qt's
    rounding would end it past the edge."""
    screen = _fake_primary_screen(monkeypatch, ratio)
    right, bottom = screen.native_work_area[2:]
    area = screen.availableGeometry()
    drawer = BlueprintDrawer()
    drawer.set_position(position)
    edge = drawer_edge(position)
    for expanded in (False, True):
        if expanded:
            drawer.open_section("blueprints")
        g = drawer.geometry()
        assert qt_round(g.x() * ratio) >= 0 and qt_round(g.y() * ratio) >= 0, (expanded, g)
        assert device_end(g.x(), g.width(), 0, ratio) <= right, (expanded, g)
        assert device_end(g.y(), g.height(), 0, ratio) <= bottom, (expanded, g)
        if edge == "left":
            assert g.left() == area.left(), (expanded, g)
        if edge == "top":
            assert g.top() == area.top(), (expanded, g)
        if edge == "right":
            assert area.right() - 1 <= g.right() <= area.right(), (expanded, g)
        if edge == "bottom":
            assert area.bottom() - 1 <= g.bottom() <= area.bottom(), (expanded, g)


@pytest.mark.parametrize("ratio", [1.25, 1.5, 1.75, 2.25])
@pytest.mark.parametrize("position", ["middle_right", "top_right", "bottom_center"])
def test_with_no_monitor_beyond_the_drawer_stays_flush(qapp, monkeypatch, ratio, position):
    """A device pixel past an edge with no monitor beyond shows nowhere, and
    moving back for it took the screen's last pixel, where a pointer pushed
    to the edge clicks, from the drawer (found in review)."""
    area = _fake_primary_screen(monkeypatch, ratio, monitor_beyond=False).availableGeometry()
    drawer = BlueprintDrawer()
    drawer.set_position(position)
    for expanded in (False, True):
        if expanded:
            drawer.open_section("blueprints")
        g = drawer.geometry()
        if drawer_edge(position) == "right":
            assert g.right() == area.right(), (expanded, g)
        else:
            assert g.bottom() == area.bottom(), (expanded, g)


def test_at_100_percent_nothing_is_asked_and_the_drawer_is_flush(qapp, monkeypatch):
    screen = _fake_primary_screen(monkeypatch, 1.0)

    def no_lookup(_screen):
        raise AssertionError("no monitor lookup at 100%")
    monkeypatch.setattr(so, "native_work_area", no_lookup)
    drawer = BlueprintDrawer()
    drawer.set_position("middle_right")
    assert drawer.geometry().right() == screen.availableGeometry().right()
    drawer.set_position("middle_left")
    assert drawer.geometry().left() == screen.availableGeometry().left()


def test_without_a_work_area_from_windows_the_position_stands(monkeypatch):
    screen = FakeScreen(1.25)
    monkeypatch.setattr(so, "native_work_area", lambda s: None)
    assert within_device_pixels(screen, 2026, 10, 22, 130) == (2026, 10)


def test_the_fit_moves_the_drawer_only_where_it_reaches_the_edge(monkeypatch):
    screen = FakeScreen(1.25)
    monkeypatch.setattr(so, "native_work_area", lambda s: s.native_work_area)
    monkeypatch.setattr(so, "monitor_at", lambda *rect: True)
    # Flush right at 125% overran by one device pixel: one logical pixel back.
    assert within_device_pixels(screen, 2026, 10, 22, 130) == (2025, 10)
    # A window 23 px wide from 2025 ends exactly at the edge (2531 + 29 =
    # 2560), on the screen: it stays.
    assert device_end(2025, 23, 0, 1.25) == 2560
    assert within_device_pixels(screen, 2025, 10, 23, 130) == (2025, 10)
    # A left-docked drawer and one well inside the screen stay where they are.
    assert within_device_pixels(screen, 0, 10, 22, 130) == (0, 10)
    assert within_device_pixels(screen, 1000, 500, 22, 130) == (1000, 500)
    # The bottom the same: flush with the work area's bottom (1104 logical,
    # 1380 device) a 130 px window from 974 ends at 1218 + 163 = 1381.
    assert device_end(974, 130, 0, 1.25) == 1381
    assert within_device_pixels(screen, 500, 974, 22, 130) == (500, 973)


def test_the_fit_asks_about_the_pixels_just_past_the_edge(monkeypatch):
    """Windows is asked whether a monitor shows the column just past the right
    edge, along the drawer's rows, and the row just past the bottom, along its
    columns. With none there the drawer stays where it is."""
    screen = FakeScreen(1.25)
    asked = []
    monkeypatch.setattr(so, "native_work_area", lambda s: s.native_work_area)
    monkeypatch.setattr(so, "monitor_at", lambda *rect: asked.append(rect) or False)
    # x 2026 starts at device 2533 (2532.5 rounded up), y 10 at 13 (12.5).
    assert within_device_pixels(screen, 2026, 10, 22, 130) == (2026, 10)
    assert asked == [(2560, 13, 2561, 176)]
    asked.clear()
    assert within_device_pixels(screen, 500, 974, 22, 130) == (500, 974)
    assert asked == [(625, 1380, 653, 1381)]
    asked.clear()
    assert within_device_pixels(screen, 1000, 500, 22, 130) == (1000, 500)
    assert asked == []                                  # nothing reaches an edge


class FakeMonitorUser32:
    """MonitorFromRect over one monitor's rectangle, and nothing else: any
    other call raises, so only monitors are asked about, never a window or a
    process (EAC)."""

    def __init__(self, monitor=(0, 0, 2560, 1440)):
        self.monitor, self.calls = monitor, []

    def MonitorFromRect(self, pointer, flags):  # noqa: N802 (Windows' name)
        rect = pointer._obj
        self.calls.append(("MonitorFromRect", (rect.left, rect.top, rect.right, rect.bottom),
                           flags))
        left, top, right, bottom = self.monitor
        overlaps = (rect.left < right and left < rect.right
                    and rect.top < bottom and top < rect.bottom)
        return 9 if overlaps else 0


def test_a_monitor_is_found_only_where_one_shows_the_pixels():
    user32 = FakeMonitorUser32()
    assert monitor_at(2559, 10, 2560, 20, user32) is True
    assert monitor_at(2560, 10, 2561, 20, user32) is False
    assert user32.calls[0] == ("MonitorFromRect", (2559, 10, 2560, 20), so.MONITOR_DEFAULTTONULL)


def test_off_windows_a_monitor_is_assumed(monkeypatch):
    monkeypatch.setattr(so, "_user32", lambda: None)
    assert monitor_at(0, 0, 1, 1) is True


# --- the work area Windows gives a screen ------------------------------------------

class FakeUser32:
    """MonitorFromPoint / GetMonitorInfoW over a set table, and nothing else:
    any other call raises, so only monitors are asked about, never a window
    or a process (EAC)."""

    def __init__(self, monitor=7, work=(2560, -491, 3640, 1381), info_ok=True):
        self.monitor, self.work, self.info_ok = monitor, work, info_ok
        self.calls = []

    def MonitorFromPoint(self, point, flags):  # noqa: N802 (Windows' name)
        self.calls.append(("MonitorFromPoint", (point.x, point.y), flags))
        return self.monitor

    def GetMonitorInfoW(self, monitor, pointer):  # noqa: N802 (Windows' name)
        self.calls.append(("GetMonitorInfoW", monitor))
        if not self.info_ok:
            return 0
        info = pointer._obj
        assert info.cbSize == ctypes.sizeof(type(info))
        info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = self.work
        return 1


class _ScreenAt:
    def __init__(self, x, y):
        self._geometry = QRect(x, y, 864, 1536)

    def geometry(self):
        return QRect(self._geometry)


def test_the_work_area_is_the_monitors_at_the_screens_top_left():
    """Qt keeps a screen's top-left in device pixels (here a portrait monitor
    right of a 2560 px one, at 125%), so its monitor is the one at that point."""
    user32 = FakeUser32()
    assert native_work_area(_ScreenAt(2560, -491), user32) == (2560, -491, 3640, 1381)
    assert user32.calls[0] == ("MonitorFromPoint", (2560, -491), so.MONITOR_DEFAULTTONULL)


@pytest.mark.parametrize("user32", [
    FakeUser32(monitor=0),          # no monitor at that point
    FakeUser32(info_ok=False),      # monitor info refused
])
def test_no_work_area_is_none(user32):
    assert native_work_area(_ScreenAt(0, 0), user32) is None


def test_off_windows_there_is_no_work_area(monkeypatch):
    monkeypatch.setattr(so, "_user32", lambda: None)
    assert native_work_area(_ScreenAt(0, 0)) is None


# --- clicks pass through the drawer while the game hides its pointer -------------

class FakePointerUser32:
    """The window in front, its class and title, and whether the pointer shows."""

    def __init__(self, front=0x51C, cls="CryENGINE", title="Star Citizen", showing=False,
                 cursor_ok=True):
        self.front, self.cls, self.title = front, cls, title
        self.showing, self.cursor_ok = showing, cursor_ok
        self.calls = []

    def GetForegroundWindow(self):  # noqa: N802 (Windows' name)
        self.calls.append("GetForegroundWindow")
        return self.front

    def GetClassNameW(self, hwnd, buf, size):  # noqa: N802 (Windows' name)
        self.calls.append("GetClassNameW")
        assert hwnd == self.front and size == len(buf)      # never past the buffer
        buf.value = self.cls
        return len(self.cls)

    def GetWindowTextW(self, hwnd, buf, size):  # noqa: N802 (Windows' name)
        self.calls.append("GetWindowTextW")
        assert hwnd == self.front and size == len(buf)
        buf.value = self.title
        return len(self.title)

    def GetCursorInfo(self, pointer):  # noqa: N802 (Windows' name)
        self.calls.append("GetCursorInfo")
        if not self.cursor_ok:
            return 0
        info = pointer._obj
        assert info.cbSize == ctypes.sizeof(type(info))
        info.flags = so.CURSOR_SHOWING if self.showing else 0
        return 1


def test_the_game_is_known_by_its_window_class():
    user32 = FakePointerUser32()
    assert game_in_front(user32) is True
    # Only Windows is asked, about the window in front, never the game's
    # process (EAC).
    assert user32.calls == ["GetForegroundWindow", "GetClassNameW"]


def test_the_game_is_known_by_its_title_too():
    user32 = FakePointerUser32(cls="SomethingElse")
    assert game_in_front(user32) is True
    assert user32.calls == ["GetForegroundWindow", "GetClassNameW", "GetWindowTextW"]


@pytest.mark.parametrize("user32", [
    FakePointerUser32(cls="Chrome_WidgetWin_1", title="A video"),   # another program
    FakePointerUser32(front=0),                                      # nothing in front
])
def test_anything_else_in_front_is_not_the_game(user32):
    assert game_in_front(user32) is False


def test_a_hidden_pointer_is_aiming():
    """While aiming the game hides its pointer but lets it run over the whole
    screen, so a shot fired as it crossed the drawer took the game's focus
    (player report, 2026-11-16, measured in game)."""
    user32 = FakePointerUser32()
    assert pointer_hidden(user32) is True
    assert user32.calls == ["GetCursorInfo"]


@pytest.mark.parametrize("user32", [
    FakePointerUser32(showing=True),    # F held or the mobiGlas open: meant to be clicked
    FakePointerUser32(cursor_ok=False),  # Windows does not say
])
def test_a_showing_or_unknown_pointer_is_not_aiming(user32):
    assert pointer_hidden(user32) is False


def test_off_windows_nothing_is_in_front_or_hidden(monkeypatch):
    monkeypatch.setattr(so, "_user32", lambda: None)
    assert game_in_front() is False and pointer_hidden() is False


class FakeStyleUser32:
    """One window's extended style through GetWindowLongPtrW and
    SetWindowLongPtrW, every write recorded."""

    HWND = 0x7A0
    STYLE = 0x80088                     # the drawer's: LAYERED, TOOLWINDOW, TOPMOST

    def __init__(self, style=STYLE):
        self.style, self.writes = style, []

    def GetWindowLongPtrW(self, hwnd, index):  # noqa: N802 (Windows' name)
        assert (hwnd, index) == (self.HWND, so.GWL_EXSTYLE)
        return self.style

    def SetWindowLongPtrW(self, hwnd, index, value):  # noqa: N802 (Windows' name)
        assert (hwnd, index) == (self.HWND, so.GWL_EXSTYLE)
        old, self.style = self.style, value
        self.writes.append(value)
        return old


def test_click_through_sets_and_clears_its_own_bit_only_when_it_changes():
    user32 = FakeStyleUser32()
    hwnd, style = FakeStyleUser32.HWND, FakeStyleUser32.STYLE
    assert set_click_through(hwnd, True, user32) is True
    set_click_through(hwnd, True, user32)                       # asked again: nothing written
    set_click_through(hwnd, False, user32)
    set_click_through(hwnd, False, user32)                      # nor here
    assert user32.writes == [style | WS_EX_TRANSPARENT, style]


def test_click_through_puts_the_style_back_when_something_cleared_it():
    user32 = FakeStyleUser32()
    set_click_through(FakeStyleUser32.HWND, True, user32)
    user32.style = FakeStyleUser32.STYLE                        # cleared behind its back
    set_click_through(FakeStyleUser32.HWND, True, user32)
    assert user32.style == FakeStyleUser32.STYLE | WS_EX_TRANSPARENT


def test_click_through_needs_a_window_and_windows(monkeypatch):
    user32 = FakeStyleUser32()
    assert set_click_through(0, True, user32) is False and user32.writes == []
    monkeypatch.setattr(so, "_user32", lambda: None)
    assert set_click_through(FakeStyleUser32.HWND, True) is False


def test_a_window_that_is_not_layered_is_warned_about_once(monkeypatch, caplog):
    """Windows lets clicks through a WS_EX_TRANSPARENT window only when it is
    layered too (measured). The drawer is, as a see-through frameless window,
    and a change that took that away would bring the focus steal back with
    every other test passing, so it is logged (found in review)."""
    monkeypatch.setattr(so, "_warned_not_layered", False)
    user32 = FakeStyleUser32(style=FakeStyleUser32.STYLE & ~so.WS_EX_LAYERED)
    with caplog.at_level("WARNING", logger="src.gui.sco_overlay"):
        set_click_through(FakeStyleUser32.HWND, True, user32)
        set_click_through(FakeStyleUser32.HWND, False, user32)
        set_click_through(FakeStyleUser32.HWND, True, user32)
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert user32.style & WS_EX_TRANSPARENT                     # still set: never worse
    caplog.clear()
    monkeypatch.setattr(so, "_warned_not_layered", False)
    with caplog.at_level("WARNING", logger="src.gui.sco_overlay"):
        set_click_through(FakeStyleUser32.HWND, True, FakeStyleUser32())
    assert not caplog.records                                   # layered: nothing to say


def test_the_drawer_stays_a_layered_window(qapp):
    """What makes Qt layer the drawer's window on Windows: no frame and a
    see-through background. Without them clicks could not pass through it."""
    drawer = BlueprintDrawer()
    assert drawer.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert drawer.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_the_structs_have_windows_layout():
    """Windows refuses a struct of the wrong size (error 87), and the fakes
    only compare a struct with itself, so the 64-bit layouts are pinned."""
    assert ctypes.sizeof(so._CursorInfo) == 24
    assert (so._CursorInfo.flags.offset, so._CursorInfo.hCursor.offset,
            so._CursorInfo.ptScreenPos.offset) == (4, 8, 16)
    assert ctypes.sizeof(so._MonitorInfo) == 40
    assert (so._MonitorInfo.rcMonitor.offset, so._MonitorInfo.rcWork.offset,
            so._MonitorInfo.dwFlags.offset) == (4, 20, 36)
    assert ctypes.sizeof(so._Rect) == 16 and ctypes.sizeof(so._Point) == 8


@pytest.mark.skipif(sys.platform != "win32", reason="user32 is Windows only")
def test_the_real_calls_take_the_structs(monkeypatch):
    """Once for real: Windows takes each struct (a wrong size fails with 87,
    which the fakes cannot see), names the work area of the monitor at (0, 0),
    finds a monitor there and none far away, and sets and clears the style on
    a message-only window this test makes (never shown)."""
    from ctypes import wintypes

    user32 = so._user32()
    for _ in range(2):          # Windows clears cbSize after a call: a fresh struct each time
        info = so._CursorInfo()
        info.cbSize = ctypes.sizeof(info)
        ctypes.set_last_error(0)
        assert user32.GetCursorInfo(ctypes.byref(info)) or ctypes.get_last_error() != 87
    pointer_hidden()            # through the typed copy, which a wrong type makes raise
    work = native_work_area(_ScreenAt(0, 0))
    assert work is not None and work[0] <= 0 < work[2] and work[1] <= 0 < work[3]
    assert monitor_at(0, 0, 1, 1) is True
    assert monitor_at(-1000000, -1000000, -999999, -999999) is False

    # A message-only window (its parent HWND_MESSAGE, (HWND)-3), typed on a
    # copy of user32 of the test's own.
    windows = ctypes.WinDLL("user32", use_last_error=True)
    windows.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, wintypes.LPVOID]
    windows.CreateWindowExW.restype = wintypes.HWND
    windows.DestroyWindow.argtypes = [wintypes.HWND]
    windows.DestroyWindow.restype = wintypes.BOOL
    hwnd = windows.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, -3, None, None, None)
    assert hwnd
    monkeypatch.setattr(so, "_warned_not_layered", True)    # this window is not layered
    try:
        assert set_click_through(hwnd, True)
        assert user32.GetWindowLongPtrW(hwnd, so.GWL_EXSTYLE) & WS_EX_TRANSPARENT
        assert set_click_through(hwnd, False)
        assert not user32.GetWindowLongPtrW(hwnd, so.GWL_EXSTYLE) & WS_EX_TRANSPARENT
    finally:
        windows.DestroyWindow(hwnd)


def test_the_drawer_sets_its_window_style_only_on_windows(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(so, "set_click_through", lambda hwnd, on: calls.append((hwnd, on)))
    drawer = BlueprintDrawer()
    drawer.set_pass_through(True)
    # The tests' offscreen platform gives made-up window ids: none reaches user32.
    assert drawer.pass_through is True and calls == []
    monkeypatch.setattr(so.QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    drawer.set_pass_through(False)
    assert drawer.pass_through is False and calls == [(int(drawer.winId()), False)]


def test_clicks_pass_through_the_drawer_while_the_game_hides_its_pointer(qapp, monkeypatch,
                                                                         slot_errors):
    from tests.event_loop import pump_until

    game = {"in_front": True, "hidden": True}
    monkeypatch.setattr(so, "game_in_front", lambda: game["in_front"])
    monkeypatch.setattr(so, "pointer_hidden", lambda: game["hidden"])
    overlay = ScoOverlay()
    overlay.set_reader(None)
    drawer = overlay.drawer
    timer = overlay._pass_through_timer
    try:
        assert not timer.isActive()                             # not running
        overlay.start()
        # Asked at once as the drawer shows, then every PASS_THROUGH_POLL_MS
        # while the game is in front.
        assert drawer.pass_through is True
        assert timer.isActive() and timer.interval() == PASS_THROUGH_POLL_MS
        game["hidden"] = False                                  # F held: the pointer shows
        assert pump_until(lambda: drawer.pass_through is False, seconds=2)
        game["hidden"] = True                                   # F let go
        assert pump_until(lambda: drawer.pass_through is True, seconds=2)
        # Another window in front: clicks are taken, and Windows is asked less
        # often, since Qt runs a timer of 20 ms or less on a 1 ms Windows timer.
        game["in_front"] = False
        assert pump_until(lambda: timer.interval() == PASS_THROUGH_IDLE_POLL_MS, seconds=2)
        assert drawer.pass_through is False and PASS_THROUGH_IDLE_POLL_MS > 20
        game["in_front"] = True
        assert pump_until(lambda: drawer.pass_through is True
                          and timer.interval() == PASS_THROUGH_POLL_MS, seconds=2)
        overlay.set_options({"drawer": False})                  # no drawer, nothing to ask
        assert not timer.isActive()
        game["hidden"] = False                                  # the pointer shows meanwhile
        overlay.set_options({})
        # Asked again at once on showing, not left as it was before the hide.
        assert timer.isActive() and drawer.pass_through is False
    finally:
        overlay.stop()
    assert not timer.isActive()
    assert not slot_errors


def test_clicks_starting_to_pass_through_close_a_tooltip(qapp):
    """A tooltip is a window of its own that takes clicks, and Qt hides it
    only 0.3 s after the pointer leaves, so one left up as the player lets go
    of F and starts shooting could take a shot (found in review)."""
    from PyQt6.QtWidgets import QApplication, QToolTip

    def showing():
        return [w for w in QApplication.topLevelWidgets()
                if w.objectName() == so.TOOLTIP_OBJECT_NAME and w.isVisible()]

    drawer = BlueprintDrawer()
    drawer.show_docked()
    try:
        QToolTip.showText(QPoint(100, 100), "a tip", drawer)
        assert showing()
        drawer.set_pass_through(True)
        assert not showing()
        drawer.set_pass_through(False)
        QToolTip.showText(QPoint(120, 120), "a later tip", drawer)
        assert showing()                                        # tooltips still work after
        drawer.set_pass_through(False)                          # taking clicks closes nothing
        assert showing()
    finally:
        QToolTip.hideText()
        drawer.hide()


def test_the_drawer_takes_its_new_place_and_size_in_one_step(qapp, monkeypatch):
    """Resized at its old place first, an opening right drawer lay mostly on
    the monitor beyond, and with that monitor at another scale Qt moved the
    window there mid-resize and rescaled it, so the move kept a wrong size
    (found in review, from Qt 6.11's source)."""
    drawer = BlueprintDrawer()
    drawer.set_position("middle_right")
    calls = []
    for name in ("move", "resize", "setGeometry", "setFixedSize"):
        original = getattr(drawer, name)

        def record(*args, _name=name, _original=original):
            calls.append((_name, args, drawer.geometry()))     # the geometry before the call
            return _original(*args)
        monkeypatch.setattr(drawer, name, record)
    for change in (lambda: drawer.open_section("blueprints"), drawer.close_drawer):
        calls.clear()
        change()
        g = drawer.geometry()
        assert [call[:2] for call in calls] == [
            ("setGeometry", (g.x(), g.y(), g.width(), g.height())),
            ("setFixedSize", (g.width(), g.height()))]
        # The one step gave the whole new geometry. Qt clamps a geometry to
        # the fixed size, so without letting that go first the new size came
        # only with setFixedSize, a second step at the new place.
        assert calls[1][2] == g
        assert drawer.minimumSize() == drawer.maximumSize() == g.size()


def _deliver(overlay):
    """Wait for the reader's pool thread, then deliver its queued result."""
    from PyQt6.QtCore import QCoreApplication

    assert overlay.wait_for_reader(5000)
    QCoreApplication.processEvents()


def _read(overlay, reader, region=QRect(0, 0, 200, 100)):
    from PyQt6.QtGui import QImage

    from src.gui.sco_overlay import _ReadTask
    image = QImage(region.width(), region.height(), QImage.Format.Format_RGB32)
    overlay._reading = True
    overlay._pool.start(_ReadTask(reader, image, region, overlay._read_done, overlay._read_token))
    _deliver(overlay)


def test_the_reader_runs_off_the_gui_thread(qapp):
    import threading

    overlay = ScoOverlay()
    overlay.start()
    threads = []

    def reader(image):
        threads.append(threading.current_thread())
        return "7,200", QRect(50, 40, 30, 11)

    for _ in range(2):   # two matching reads in a row change the label
        _read(overlay, reader)
    assert threads and all(t is not threading.main_thread() for t in threads)
    assert overlay.label._label.text() == "2 × Bexalite"
    assert not overlay._reading
    overlay.stop()


def test_a_tick_during_a_read_is_skipped(qapp, monkeypatch):
    overlay = ScoOverlay()
    overlay._reading = True

    def no_grab():
        raise AssertionError("captured while a read was in flight")

    monkeypatch.setattr("src.gui.sco_overlay.QGuiApplication.primaryScreen", staticmethod(no_grab))
    overlay._capture_once()


def test_a_failing_reader_stops_the_capture_and_says_so(qapp):
    overlay = ScoOverlay()
    overlay.start()
    assert overlay._timer.isActive()
    failed = []
    overlay.decoder_failed.connect(lambda: failed.append(True))

    def broken(image):
        raise ValueError("bad capture")

    _read(overlay, broken)
    assert not overlay._timer.isActive() and not overlay._reading
    assert failed == [True] and not overlay.label.isVisible()
    overlay.stop()
    overlay.start()                      # a restart tries again
    assert overlay._timer.isActive()
    overlay.stop()


def test_a_new_reading_is_confirmed_without_waiting_for_a_tick(qapp, monkeypatch):
    from PyQt6.QtCore import QCoreApplication, QPoint

    overlay = ScoOverlay()
    captures = []
    monkeypatch.setattr(overlay, "_capture_once", lambda: captures.append(True))
    overlay._on_reading(7200, QPoint(10, 10))      # stopped: nothing to confirm
    QCoreApplication.processEvents()
    assert captures == []
    overlay.start()
    overlay._on_reading(10200, QPoint(10, 10))     # first sighting of a new value
    QCoreApplication.processEvents()
    assert captures == [True]                      # the confirming capture ran at once
    overlay._on_reading(10200, QPoint(10, 10))     # confirmed: no extra capture
    QCoreApplication.processEvents()
    assert captures == [True] and overlay.label._label.text() == "3 × Lindinium"
    overlay.stop()


def test_a_read_finishing_after_stop_is_dropped(qapp):
    overlay = ScoOverlay()
    overlay.start()
    overlay._on_reading(7200, overlay.label.pos())   # one sighting pending
    from PyQt6.QtGui import QImage

    from src.gui.sco_overlay import _ReadTask
    overlay._reading = True
    task = _ReadTask(lambda image: ("7,200", QRect(50, 40, 30, 11)),
                     QImage(200, 100, QImage.Format.Format_RGB32), QRect(0, 0, 200, 100),
                     overlay._read_done, overlay._read_token)
    overlay.stop()
    overlay._pool.start(task)
    _deliver(overlay)
    assert not overlay.label.isVisible() and not overlay._reading


def test_a_failed_sample_save_is_logged(qapp, tmp_path, caplog, monkeypatch, samples_on):
    from PyQt6.QtGui import QImage

    overlay = ScoOverlay(sample_dir=tmp_path / "samples")
    monkeypatch.setattr(QImage, "save", lambda self, *a, **k: False)
    with caplog.at_level("WARNING", logger="src.gui.sco_overlay"):
        overlay._save_sample(QImage(80, 40, QImage.Format.Format_RGB32), "7,200",
                             QRect(10, 10, 30, 11))
        overlay._save_sample(QImage(80, 40, QImage.Format.Format_RGB32), "7,200",
                             QRect(10, 10, 30, 11))
        assert overlay.wait_for_reader(5000)
    assert len([r for r in caplog.records if "could not save" in r.getMessage()]) == 1


def test_samples_folder_is_resolved_at_save_time(qapp, tmp_path, monkeypatch, samples_on):
    from PyQt6.QtGui import QImage

    overlay = ScoOverlay()
    monkeypatch.setattr("src.gui.sco_overlay.AppSettings.get_sco_samples_dir",
                        staticmethod(lambda: tmp_path / "moved"))
    overlay._save_sample(QImage(80, 40, QImage.Format.Format_RGB32), "7,200", QRect(10, 10, 30, 11))
    assert overlay.wait_for_reader(5000)
    assert len(list((tmp_path / "moved").iterdir())) == 1


def test_prune_samples_keeps_the_newest(tmp_path):
    import os

    from src.gui.sco_overlay import prune_samples
    for i in range(5):
        crop = tmp_path / f"crop{i}.png"
        crop.write_bytes(b"x")
        os.utime(crop, (1000 + i, 1000 + i))
    (tmp_path / "notes.txt").write_text("kept")
    assert prune_samples(tmp_path, keep=2) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["crop3.png", "crop4.png", "notes.txt"]
    assert prune_samples(tmp_path / "missing") == 0


def test_the_first_save_of_a_session_prunes_the_folder(qapp, tmp_path, monkeypatch, samples_on):
    from PyQt6.QtGui import QImage

    monkeypatch.setattr("src.gui.sco_overlay.MAX_SAMPLES_KEPT", 3)
    samples = tmp_path / "samples"
    samples.mkdir()
    for i in range(5):
        (samples / f"old{i}.png").write_bytes(b"x")
    overlay = ScoOverlay(sample_dir=samples)
    overlay._save_sample(QImage(80, 40, QImage.Format.Format_RGB32), "7,200", QRect(10, 10, 30, 11))
    assert overlay.wait_for_reader(5000)
    names = [p.name for p in samples.iterdir()]
    assert len(names) == 3 and any(n.endswith("_7200.png") for n in names)


def test_every_drawer_section_has_its_own_switch():
    from src.utils.settings import AppSettings

    prefix = AppSettings.SCO_DRAWER_SECTION_PREFIX
    switches = {n[len(prefix):] for n in AppSettings.SCO_OPTION_SETTING if n.startswith(prefix)}
    assert switches == set(SECTION_ICONS)


# -- #523: centring, the selected row, alerts, text size and the hotkey --------

def test_every_alert_has_its_own_switch():
    from src.gui.sco_overlay import ALERTS
    from src.utils.settings import AppSettings

    prefix = AppSettings.SCO_ALERT_PREFIX
    switches = [n[len(prefix):] for n in AppSettings.SCO_OPTION_SETTING if n.startswith(prefix)]
    assert switches == list(ALERTS)


def test_the_label_centres_under_the_pin_and_the_number(qapp, tmp_path):
    """The label sat under the digits alone, right of the readout's middle,
    since the scanner's pin icon is left of them."""
    from PyQt6.QtGui import QImage

    from src.gui.sco_overlay import READOUT_PIN_WIDTH

    overlay = ScoOverlay(sample_dir=tmp_path)
    region = QRect(1000, 500, 400, 200)
    digits = QRect(100, 40, 34, 12)          # capture pixels, which are screen pixels here
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    for _ in range(2):
        overlay._handle_found(("7,200", digits), image, region)
    label = overlay.label
    centre = label.x() + label.width() / 2
    pin_left = digits.left() - READOUT_PIN_WIDTH * digits.height()
    assert abs(centre - (region.x() + (pin_left + digits.right()) / 2)) <= 1.5
    assert abs(centre - (region.x() + digits.center().x())) > 10      # where it used to sit
    label.layout().activate()
    assert label.y() + label._label.y() == region.y() + digits.bottom() + LABEL_GAP
    overlay.stop()


def test_the_label_holds_still_while_the_readout_only_jitters(qapp, tmp_path):
    """#523: the label moved on every capture, since captures of a still
    readout put its box a few pixels apart. It follows the readout once it
    has wandered more than ANCHOR_DEAD_ZONE digit heights, and down at once:
    held over a readout that sank, it would cover the digits' bottom row."""
    from PyQt6.QtGui import QImage

    from src.gui.sco_overlay import ANCHOR_DEAD_ZONE

    overlay = ScoOverlay(sample_dir=tmp_path)
    region = QRect(1000, 500, 400, 200)
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    label = overlay.label
    digits = QRect(100, 40, 34, 11)
    for _ in range(2):
        overlay._handle_found(("7,200", digits), image, region)
    held, where, first_text = label.anchor(), label.geometry(), label._label.text()
    # Sideways and upward wobble: held.
    for jitter in (QRect(102, 40, 35, 11), QRect(98, 39, 33, 11), QRect(101, 38, 36, 11)):
        overlay._handle_found(("7,200", jitter), image, region)
        assert label.anchor() == held and label.geometry() == where
    # A new number in the same place takes the same spot (centred, so only
    # its width changes).
    for _ in range(2):
        overlay._handle_found(("3,400", QRect(101, 40, 34, 11)), image, region)
    assert label.anchor() == held and label._label.text() != first_text
    # Sunk by a pixel, sideways by a pixel too: followed down, held across.
    overlay._handle_found(("3,400", digits.translated(1, 1)), image, region)
    assert label.anchor() == held + QPoint(0, 1)
    held = label.anchor()
    step = int(ANCHOR_DEAD_ZONE * digits.height()) + 2
    overlay._handle_found(("3,400", digits.translated(step, 1)), image, region)
    assert label.anchor() == held + QPoint(step, 0)                   # the readout moved
    # Hidden, the label is placed afresh, even 2 px from where it last was.
    label.hide()
    for _ in range(2):                                         # shown again once confirmed
        overlay._handle_found(("3,400", digits.translated(step + 2, 1)), image, region)
    assert label.isVisible() and label.anchor() == held + QPoint(step + 2, 0)
    overlay.stop()


def _fixture_capture(name, screen_h, dpi, drop=0):
    """A capture of the scan region, in device pixels, holding fixture *name*
    scaled to a *screen_h* px screen (*drop* px lower than usual), and that
    region in logical pixels at Windows scale *dpi*."""
    from pathlib import Path

    from PyQt6.QtGui import QImage, QPainter

    logical = QRect(0, 0, round(screen_h * 16 / 9 / dpi), round(screen_h / dpi))
    region = scan_region_rect(logical)
    capture = QImage(round(region.width() * dpi), round(region.height() * dpi),
                     QImage.Format.Format_RGB32)
    capture.fill(QColor(0, 0, 0))
    crop = QImage(str(Path(__file__).parent / "fixtures" / "sco" / f"{name}.png"))
    factor = screen_h / 1600
    crop = crop.scaled(round(crop.width() * factor), round(crop.height() * factor),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(capture)
    painter.drawImage(capture.width() // 3, capture.height() // 3 + drop, crop)
    painter.end()
    return capture, region


@pytest.mark.parametrize("name, screen_h, dpi", [
    ("live00_15600", 1080, 1.25), ("live01_8540", 1080, 1.25),
    ("g1_7200", 1440, 1.5), ("p2_2000", 1600, 1.25), ("live16_3400", 2160, 1.5),
])
def test_the_label_never_covers_the_readout_on_a_scaled_screen(
        qapp, tmp_path, name, screen_h, dpi):
    """#523: with Windows display scaling, the box came out of the device to
    logical conversion short of the digits, the label sat over their bottom
    row, and its blackout in the next capture made the reads fail (13 or 14
    of 16 at 1080 px and 125%). Captures of a still readout, as the overlay
    takes them, must keep reading, with the label still."""
    base, region = _fixture_capture(name, screen_h, dpi)
    overlay = ScoOverlay(sample_dir=tmp_path)
    overlay._running = True
    places = set()
    for _ in range(8):
        capture = base.copy()
        overlay._mask_own_label(capture, region)
        found = hud_signature_reader(capture)
        assert found is not None
        overlay._handle_found(found, capture, region)
        if overlay.label.isVisible():
            places.add(overlay.label.geometry().getRect())
    assert len(places) == 1
    overlay.stop()


@pytest.mark.parametrize("name, screen_h, dpi", [
    ("live00_15600", 1600, 1.0), ("g1_7200", 1600, 1.0), ("live00_15600", 2160, 1.5),
    ("g1_7200", 2160, 1.0),
])
def test_a_sinking_readout_keeps_reading(qapp, tmp_path, name, screen_h, dpi):
    """A readout that sinks a pixel per capture (the head bobbing) is
    followed down at once. Held still, the label covered its bottom rows
    and blacked them out, and the reads failed on every crop."""
    overlay = ScoOverlay(sample_dir=tmp_path)
    overlay._running = True
    columns = set()
    for drop in range(7):
        capture, region = _fixture_capture(name, screen_h, dpi, drop)
        overlay._mask_own_label(capture, region)
        found = hud_signature_reader(capture)
        assert found is not None, drop
        overlay._handle_found(found, capture, region)
        if overlay.label.isVisible():
            columns.add(overlay.label.geometry().x())
    assert len(columns) == 1                                   # held across all the while
    overlay.stop()


@pytest.mark.parametrize("name", ["live25_3600", "live29_7200"])
def test_a_still_readout_keeps_the_label_still(qapp, tmp_path, name):
    """Captures of one readout differ in brightness and noise, which moved
    its box by up to 3 px on these crops. The label keeps its column and at
    most settles down a pixel or two (it follows a box that ends lower)."""
    import random

    from PyQt6.QtGui import QImage

    capture, region = _fixture_capture(name, 1600, 1.0)
    rgb = capture.convertToFormat(QImage.Format.Format_RGB32)
    pixels = rgb.constBits().asstring(rgb.sizeInBytes())
    rng = random.Random(name)
    overlay = ScoOverlay(sample_dir=tmp_path)
    places = []
    for gain in (1.0, 1.0, 0.85, 1.15, 0.92, 1.08):
        varied = bytes(max(0, min(255, int(v * gain + rng.uniform(-8, 8)))) if i % 4 != 3 else v
                       for i, v in enumerate(pixels))
        frame = QImage(varied, rgb.width(), rgb.height(), rgb.bytesPerLine(),
                       QImage.Format.Format_RGB32).copy()
        found = hud_signature_reader(frame)
        assert found is not None
        overlay._handle_found(found, frame, region)
        if overlay.label.isVisible():
            places.append(overlay.label.geometry().topLeft())
    assert len({point.x() for point in places}) == 1
    tops = [point.y() for point in places]
    assert tops == sorted(tops) and tops[-1] - tops[0] <= 2
    overlay.stop()


def test_only_a_clicked_search_box_takes_the_keyboard(qapp):
    """#523: in game F is held to move the mouse, and a tab click gave the
    Blueprints or Crafting search box focus, so it filled with "ffff". Only
    a search box takes focus, and only when clicked; lists, trees, ticks and
    buttons work by mouse without it."""
    from PyQt6.QtWidgets import QWidget

    from src.gui.sco_overlay import DrawerSearch

    drawer = BlueprintDrawer()
    searches = [drawer._search, drawer._mineral_search, drawer._crafting_search]
    assert all(isinstance(s, DrawerSearch) for s in searches)
    for widget in drawer._panel.findChildren(QWidget):
        wanted = (Qt.FocusPolicy.ClickFocus if isinstance(widget, DrawerSearch)
                  else Qt.FocusPolicy.NoFocus)
        assert widget.focusPolicy() == wanted, type(widget).__name__
    drawer.show_docked()
    for name in SECTION_ICONS:
        drawer.open_section(name)
        drawer.activateWindow()
        qapp.processEvents()
        assert drawer.focusWidget() not in searches, name
    drawer.hide()


def test_a_held_key_types_nothing_in_a_drawer_search(qapp):
    """A key held since before the box had focus (F, in game) only sends
    repeats: they type nothing, while a press types and a held Backspace
    still deletes."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    drawer = BlueprintDrawer()
    search = drawer._search

    def key(qt_key, text, repeat):
        QApplication.sendEvent(search, QKeyEvent(QEvent.Type.KeyPress, qt_key,
                                                 Qt.KeyboardModifier.NoModifier, text, repeat))

    for _ in range(5):
        key(Qt.Key.Key_F, "f", True)
    assert search.text() == ""
    key(Qt.Key.Key_A, "a", False)
    key(Qt.Key.Key_G, "g", False)
    assert search.text() == "ag"
    key(Qt.Key.Key_Backspace, "\b", True)
    assert search.text() == "a"


def test_a_selected_row_keeps_light_text(qapp):
    """The selected row took the theme's highlighted text colour, near black
    in the default SCLE theme, on the dark see-through panel."""
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QApplication

    # The theme is set on the whole app, as theme.apply_theme does: a palette
    # on the drawer alone is dropped when its style sheet polishes it.
    saved = QApplication.palette()
    palette = QApplication.palette()
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(10, 18, 32))   # SCLE's
    QApplication.setPalette(palette)
    drawer = BlueprintDrawer()
    drawer.set_catalog(*_catalog())
    drawer.open_section("minerals")
    drawer.show_docked()
    try:
        tree = drawer._mineral_tree
        row = _top_rows(tree)["Beryl"]
        tree.setCurrentItem(row)
        qapp.processEvents()
        image = tree.viewport().grab().toImage()
        rect = tree.visualRect(tree.indexFromItem(row, 0))
        dark = light = 0
        for y in range(rect.top(), rect.bottom() + 1):
            for x in range(rect.left(), rect.right() + 1):
                c = image.pixelColor(x, y)
                if c.alpha() < 200:
                    continue
                luma = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                dark += luma < 60
                light += luma > 150
        assert light > 20 and dark == 0
    finally:
        drawer.hide()
        QApplication.setPalette(saved)


def _shown(overlay, value):
    """Two readings in a row put a new value on the label."""
    from PyQt6.QtCore import QPoint

    for _ in range(2):
        overlay._on_reading(value, QPoint(500, 300))


def _running_overlay():
    overlay = ScoOverlay()
    overlay.set_reader(None)
    overlay.start()
    overlay.set_watched_minerals({"lindinium"})
    return overlay


def test_default_alerts_are_the_glow_and_the_flash(qapp):
    from src.gui.sco_overlay import ScanLabelWindow
    assert ScanLabelWindow()._alerts == {"glow", "flash"}


def test_the_alerts_follow_the_options(qapp, monkeypatch):
    from PyQt6.QtCore import QPoint

    from src.gui.sco_overlay import ALERT_COLOR, ALERT_TEXT_SCALE
    chimes = []
    monkeypatch.setattr("src.gui.sco_overlay.play_alert_sound", lambda sound: chimes.append(sound))
    overlay = _running_overlay()
    label = overlay.label
    try:
        overlay.set_options({"alert_glow": False, "alert_flash": False})
        _shown(overlay, 10200)                                  # 3 × Lindinium, watched
        assert label.watched and not label.glowing and not label._flash_timer.isActive()
        assert f"color: {ALERT_COLOR}" not in label._label.styleSheet() and chimes == []
        points, width = label._font_points(), label.width()
        overlay.set_options({"alert_color": True, "alert_bigger": True, "alert_sound": True,
                             "alert_flash": False})
        assert label.glowing and f"color: {ALERT_COLOR}" in label._label.styleSheet()
        assert label._font_points() == pytest.approx(points * ALERT_TEXT_SCALE)
        assert label.width() > width and abs(label.x() + label.width() // 2 - 500) <= 1
        assert chimes == []            # switching an alert on is no new reading
        _shown(overlay, 7200)                                   # 2 × Bexalite, not watched
        assert not (label.watched or label.glowing)
        assert f"color: {ALERT_COLOR}" not in label._label.styleSheet()
        assert label._font_points() == pytest.approx(points)
        _shown(overlay, 10200)                                  # watched and new: one chime
        assert chimes == ["default"]
        overlay._on_reading(10200, QPoint(500, 300))            # still showing: no more
        assert chimes == ["default"]
        overlay.set_alert_sound("exclamation")                 # the picked sound plays
        _shown(overlay, 7200)
        _shown(overlay, 10200)
        assert chimes == ["default", "exclamation"]
    finally:
        overlay.stop()


def test_a_watched_target_flashes_three_times_when_first_read(qapp):
    from PyQt6.QtCore import QPoint

    from src.gui.sco_overlay import ALERT_COLOR
    overlay = _running_overlay()
    label = overlay.label
    try:
        _shown(overlay, 10200)
        assert label._flash_timer.isActive() and label._flash_on
        green = QColor(ALERT_COLOR)
        assert f"rgba({green.red()}, {green.green()}, {green.blue()}," in label._label.styleSheet()
        size = label._label.sizeHint()
        states = [label._flash_on]
        while label._flash_timer.isActive():
            label._flash_tick()
            states.append(label._flash_on)
            assert label._label.sizeHint() == size              # a flash moves nothing
        assert states.count(True) == 3 and not label._flash_on
        overlay._on_reading(10200, QPoint(500, 300))            # a steady repeat: no flash
        assert not label._flash_timer.isActive()
        label.hide()
        _shown(overlay, 10200)                                  # back after it was gone
        assert label._flash_timer.isActive()
        overlay.set_options({"alert_flash": False})             # switched off: stops at once
        assert not label._flash_timer.isActive() and not label._flash_on
    finally:
        overlay.stop()


def test_the_scan_text_size(qapp):
    from PyQt6.QtCore import QPoint

    from src.gui.sco_overlay import LABEL_SIZE_SCALE, ScanLabelWindow
    assert set(LABEL_SIZE_SCALE) == set(AppSettings.SCO_LABEL_SIZES)
    label = ScanLabelWindow()
    label.show_text("3 × Lindinium", QPoint(500, 300))
    points, width = label._font_points(), label.width()
    label.set_text_size("extra_large")
    assert label._font_points() == pytest.approx(points * LABEL_SIZE_SCALE["extra_large"])
    assert f"font-size: {label._font_points():.1f}pt" in label._label.styleSheet()
    assert label.width() > width and abs(label.x() + label.width() // 2 - 500) <= 1
    label.set_text_size("enormous")                             # unknown: medium
    assert label._font_points() == pytest.approx(points)
    label.hide()
    overlay = ScoOverlay()
    overlay.set_label_size("small")
    assert overlay.label._size == "small"


def test_the_chime_is_a_short_wav():
    import io
    import wave

    from src.gui.sco_overlay import alert_chime_wav
    with wave.open(io.BytesIO(alert_chime_wav())) as wav:
        assert (wav.getnchannels(), wav.getsampwidth()) == (1, 2)
        assert 0.1 < wav.getnframes() / wav.getframerate() < 0.5


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="PlaySound is Windows only")
def test_the_chime_plays_from_memory_without_waiting(monkeypatch):
    from src.gui import sco_overlay
    calls = []
    monkeypatch.setattr(sco_overlay, "_play_sound",
                        lambda data, module, flags: calls.append((data, module, flags)) or True)
    assert sco_overlay.play_alert_sound()
    (data, module, flags), = calls
    assert data and module is None
    assert flags == sco_overlay.SND_MEMORY | sco_overlay.SND_ASYNC | sco_overlay.SND_NODEFAULT
    assert sco_overlay._chime is not None          # kept alive while Windows reads it


def test_every_alert_sound_but_the_chime_is_a_windows_sound():
    """The picker's choices and the sounds play_alert_sound knows stay in step."""
    from src.gui.sco_overlay import VOICE_ALERT_SOUNDS, WINDOWS_ALERT_SOUNDS
    assert AppSettings.SCO_ALERT_SOUNDS[0] == AppSettings.SCO_ALERT_SOUND_DEFAULT
    assert not set(VOICE_ALERT_SOUNDS) & set(WINDOWS_ALERT_SOUNDS)
    assert set(VOICE_ALERT_SOUNDS) | set(WINDOWS_ALERT_SOUNDS) == set(
        AppSettings.SCO_ALERT_SOUNDS[1:])
    assert len(VOICE_ALERT_SOUNDS) == 10


@pytest.mark.parametrize("sound", [s for s in AppSettings.SCO_ALERT_SOUNDS
                                   if s.startswith("voice_")])
def test_every_voice_ships_as_a_short_wav(sound):
    """Each voice is a WAV PlaySound can read, in assets/sounds (bundled with
    the rest of assets/), short enough for an alert."""
    import wave

    from src.gui.sco_overlay import voice_sound_path
    with wave.open(voice_sound_path(sound)) as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() in (1, 2)
        assert 0.5 < wav.getnframes() / wav.getframerate() < 4


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="PlaySound is Windows only")
def test_a_windows_sound_plays_by_alias_without_waiting(monkeypatch):
    import ctypes

    from src.gui import sco_overlay
    calls = []
    monkeypatch.setattr(sco_overlay, "_play_sound",
                        lambda data, module, flags: calls.append((data, module, flags)) or True)
    assert sco_overlay.play_alert_sound("critical_stop")
    (data, module, flags), = calls
    assert ctypes.wstring_at(data) == "SystemHand" and module is None
    assert flags == sco_overlay.SND_ALIAS | sco_overlay.SND_ASYNC | sco_overlay.SND_NODEFAULT


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="PlaySound is Windows only")
def test_a_voice_plays_from_its_file_without_waiting(monkeypatch):
    import ctypes

    from src.gui import sco_overlay
    calls = []
    monkeypatch.setattr(sco_overlay, "_play_sound",
                        lambda data, module, flags: calls.append((data, module, flags)) or True)
    assert sco_overlay.play_alert_sound("voice_uk_female")
    (data, module, flags), = calls
    assert ctypes.wstring_at(data) == sco_overlay.voice_sound_path("voice_uk_female")
    assert flags == sco_overlay.SND_FILENAME | sco_overlay.SND_ASYNC | sco_overlay.SND_NODEFAULT


def test_play_alert_sound_is_quiet_off_windows(monkeypatch):
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay.sys, "platform", "linux")
    assert sco_overlay.play_alert_sound("asterisk") is False


class _FakeUser32:
    """RegisterHotKey and UnregisterHotKey, recorded instead of called, and a
    keyboard whose keys in ``down`` read as down, every key asked about
    recorded in ``asked``."""

    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse
        self.down, self.asked = set(), []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802
        self.calls.append(("register", modifiers, key))
        return not self.refuse

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.calls.append(("unregister",))
        return True

    def GetAsyncKeyState(self, virtual_key):  # noqa: N802
        self.asked.append(virtual_key)
        return -0x8000 if virtual_key in self.down else 0      # the high bit: down now


def _overlay_with_fake_hotkey(refuse=False):
    from src.gui.global_hotkey import GlobalHotkey

    overlay = ScoOverlay()
    overlay.set_reader(None)
    fake = _FakeUser32(refuse)
    overlay._hotkey = GlobalHotkey(overlay, user32=fake)
    overlay._hotkey.activated.connect(overlay.toggle_drawer)
    return overlay, fake


# Windows' virtual-key codes, as the stand-in keyboard is asked for them.
CTRL, SHIFT, ALT, LWIN, RWIN, O_KEY = 0x11, 0x10, 0x12, 0x5B, 0x5C, 0x4F
CTRL_SHIFT_O = ("register", 0x2 | 0x4 | 0x4000, O_KEY)


def _recording(handed):
    """A give_focus_back stand-in: notes each window, and Windows agrees."""
    def give_focus_back(window):
        handed.append(window)
        return True
    return give_focus_back


def test_the_hotkey_is_held_only_while_the_drawer_shows(qapp):
    overlay, fake = _overlay_with_fake_hotkey()
    problems = []
    overlay.hotkey_problem.connect(problems.append)
    overlay.set_drawer_hotkey("Ctrl+Shift+O")
    assert fake.calls == []                                     # not running
    overlay.start()
    assert fake.calls == [CTRL_SHIFT_O] and problems == [""]
    overlay.set_options({"drawer": False})
    assert fake.calls[-1] == ("unregister",)
    overlay.set_options({})
    assert fake.calls[-1] == CTRL_SHIFT_O
    overlay.set_drawer_hotkey("F9")
    assert fake.calls[-2:] == [("unregister",), ("register", 0x4000, 0x78)]
    overlay.set_drawer_hotkey("")
    assert fake.calls[-1] == ("unregister",)
    overlay.set_drawer_hotkey("F9")
    overlay.stop()
    assert fake.calls[-1] == ("unregister",) and overlay._hotkey.registered is None


def test_a_refused_hotkey_is_reported_once_per_start(qapp, caplog):
    overlay, fake = _overlay_with_fake_hotkey(refuse=True)
    problems = []
    overlay.hotkey_problem.connect(problems.append)
    overlay.set_drawer_hotkey("Ctrl+Shift+O")
    with caplog.at_level("WARNING", logger="src.gui.global_hotkey"):
        overlay.start()
        overlay.set_options({})                                 # MainWindow applies options next
    assert fake.calls == [CTRL_SHIFT_O] and problems == ["taken"]
    assert overlay._hotkey.registered is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    overlay.stop()                                              # the refusal is cleared
    assert problems == ["taken", ""]
    overlay.start()                                             # and tried again
    assert fake.calls == [CTRL_SHIFT_O, CTRL_SHIFT_O]
    overlay.stop()


def test_the_hotkey_opens_the_drawer_on_its_last_section_and_hands_focus_back(qapp, monkeypatch):
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: 4242)   # the game
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    activated = []
    monkeypatch.setattr(drawer, "activateWindow", lambda: activated.append(True))
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)
    try:
        overlay._hotkey.activated.emit()                        # as Windows delivers it
        assert drawer.is_open() and drawer._current == "blueprints" and activated == [True]
        overlay._hotkey.activated.emit()
        assert not drawer.is_open() and handed == [4242]
        drawer.open_section("crafting")                         # no hotkey, no activating click
        drawer.close_drawer()
        assert handed == [4242]                                 # nothing took focus
        overlay.toggle_drawer()
        assert drawer._current == "crafting"                    # the section used last
        drawer.open_section("crafting")                         # its own tab closes it
        assert not drawer.is_open() and handed == [4242, 4242]
    finally:
        overlay.stop()


def test_a_drawer_hidden_by_its_switch_forgets_the_window(qapp, monkeypatch):
    """Switched off while the hotkey had it open, the drawer closes nothing
    the hotkey opened, so a later close by its own tab hands focus nowhere."""
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: 4242)
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)
    try:
        overlay.toggle_drawer()                                 # the hotkey opens it
        overlay.set_options({"drawer": False})                  # switched off on the tab
        overlay.set_options({})                                 # and back on, still open
        assert drawer.isVisible() and drawer.is_open()
        drawer.open_section(drawer._current)                    # its own tab closes it
        assert not drawer.is_open() and handed == []
    finally:
        overlay.stop()


def test_the_hotkey_leaves_focus_alone_once_the_player_moved_on(qapp, monkeypatch):
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: 4242)
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: False)   # the player clicked away
    try:
        overlay.toggle_drawer()
        overlay.toggle_drawer()
        assert not drawer.is_open() and handed == []
        overlay.set_options({"drawer": False})                  # no drawer, nothing to open
        overlay.toggle_drawer()
        assert not drawer.is_open()
    finally:
        overlay.stop()


def _native(drawer, message, event_type=b"windows_generic_MSG"):
    """Hand the drawer a Windows message the way Qt does (offscreen, Qt sends
    none): the event type and a pointer to a built ``MSG``."""
    from ctypes import addressof, wintypes

    from PyQt6 import sip

    msg = wintypes.MSG()
    msg.message = message
    return drawer.nativeEvent(event_type, sip.voidptr(addressof(msg)))


def test_only_a_click_about_to_activate_the_drawer_names_a_window(qapp, monkeypatch):
    """Every native message is left to Qt (not handled), and only Windows'
    WM_MOUSEACTIVATE, sent before a click activates the drawer, names the
    window that has focus then."""
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: 4242)
    assert sco_overlay.WM_MOUSEACTIVATE == 0x0021                # Windows' own value
    drawer = BlueprintDrawer()
    named = []
    drawer.taking_focus.connect(named.append)
    for message in (0x0200, 0x0201, 0x0006):                    # mouse move, button down, activate
        assert _native(drawer, message) == (False, 0)
    assert _native(drawer, 0x0021, b"windows_dispatcher_MSG") == (False, 0)
    assert drawer.nativeEvent(b"windows_generic_MSG", None) == (False, 0)
    assert named == []
    assert _native(drawer, 0x0021) == (False, 0)                # Qt still activates it
    assert named == [4242]


def test_a_click_names_the_window_in_front_while_the_pointer_was_over_it(qapp, monkeypatch):
    """In game nothing is in front by the time Windows sends WM_MOUSEACTIVATE
    (GetForegroundWindow gave none, logged in testing), so a click names the
    window in front at the pointer's last move over the drawer, never the
    drawer itself; a window in front at the click itself still comes first."""
    from src.gui import sco_overlay
    assert sco_overlay.WM_MOUSEMOVE == 0x0200                    # Windows' own values
    assert sco_overlay.WM_MOUSELEAVE == 0x02A3
    focus = {"window": 4242}                                    # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    drawer = BlueprintDrawer()
    named = []
    drawer.taking_focus.connect(named.append)
    _native(drawer, sco_overlay.WM_MOUSEMOVE)                   # the pointer comes over it
    focus["window"] = int(drawer.winId())                       # the drawer in front: not noted
    _native(drawer, sco_overlay.WM_MOUSEMOVE)
    focus["window"] = 0                                         # nothing in front: not noted
    _native(drawer, sco_overlay.WM_MOUSEMOVE)
    assert named == []                                          # a move names nothing
    _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
    assert named == [4242]
    focus["window"] = 777
    _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
    assert named == [4242, 777]
    _native(drawer, sco_overlay.WM_MOUSELEAVE)                  # the pointer left: note dropped
    focus["window"] = 0
    _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
    assert named == [4242, 777, 0]


def test_closing_after_a_click_in_game_hands_focus_back(qapp, monkeypatch, slot_errors):
    """The tab path as logged in game: the pointer moves over the drawer
    while the game is in front, nothing is in front at the click, the tab
    closes the drawer with its button down, and focus goes back to the game
    once the button comes up."""
    from src.gui import sco_overlay
    from tests.event_loop import pump_until

    focus = {"window": 0x15057C}                                # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    held = {"button": False}
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: held["button"])
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)
    try:
        _native(drawer, sco_overlay.WM_MOUSEMOVE)               # over a tab, the game in front
        focus["window"] = 0                                     # Windows took focus for the click
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("minerals")
        focus["window"] = int(drawer.winId())                   # the drawer has focus now
        _native(drawer, sco_overlay.WM_MOUSEMOVE)               # on to an item and back
        held["button"] = True
        drawer.open_section("minerals")                         # its tab closes it, button down
        assert handed == []
        held["button"] = False
        assert pump_until(lambda: handed == [0x15057C], seconds=2)
    finally:
        overlay.stop()
    assert not slot_errors


def test_the_hotkey_takes_the_noted_window_when_the_drawer_is_in_front(qapp, monkeypatch,
                                                                       slot_errors):
    """A hand-back Windows refused leaves the closed drawer in front, so the
    hotkey would remember the drawer itself: it takes the window noted under
    the pointer instead, and closing hands focus back to that one. Once the
    pointer has left the drawer that note is gone, so an old one is never
    brought back."""
    from src.gui import sco_overlay

    focus = {"window": 4242}                                    # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: False)
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)
    try:
        _native(drawer, sco_overlay.WM_MOUSEMOVE)               # the pointer over it, game in front
        focus["window"] = int(drawer.winId())                   # the closed drawer kept focus
        overlay.toggle_drawer()                                 # the hotkey opens it
        overlay.toggle_drawer()                                 # and closes it
        assert handed == [4242]
        _native(drawer, sco_overlay.WM_MOUSELEAVE)              # the pointer left: note dropped
        overlay.toggle_drawer()
        overlay.toggle_drawer()
        assert handed == [4242]                                 # no old window brought back
    finally:
        overlay.stop()
    assert not slot_errors


def test_closing_after_a_click_gave_the_drawer_focus_hands_it_back(qapp, monkeypatch, slot_errors):
    """A click gives the drawer focus as the hotkey can: Windows asks first,
    while the game still has focus, so closing the drawer by its own tab or
    the hotkey hands focus back to the game, unless the player clicked away."""
    from src.gui import sco_overlay
    focus = {"window": 4242}                                    # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    active = {"drawer": True}
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: active["drawer"])
    try:
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)           # a click on a closed tab
        drawer.open_section("minerals")
        drawer.open_section("minerals")                         # its own tab closes it
        assert not drawer.is_open() and handed == [4242]
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("crafting")
        overlay.toggle_drawer()                                 # the hotkey closes it
        assert not drawer.is_open() and handed == [4242, 4242]
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("crafting")
        active["drawer"] = False                                # the player clicked the game
        drawer.open_section("crafting")
        assert handed == [4242, 4242]
        active["drawer"] = True
        focus["window"] = int(drawer.winId())                   # never the drawer itself
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("blueprints")
        drawer.open_section("blueprints")
        assert handed == [4242, 4242]
    finally:
        overlay.stop()
    assert not slot_errors


def _clicked_overlay(monkeypatch, held, handed):
    """A running overlay whose drawer a click gave focus (the game is window
    4242), with the mouse button state and the hand-back recorded."""
    from src.gui import sco_overlay
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: 4242)
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: held["button"])
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    monkeypatch.setattr(overlay.drawer, "isActiveWindow", lambda: True)
    return overlay


def test_a_tab_click_hands_focus_back_once_its_button_is_up(qapp, monkeypatch, slot_errors):
    """A tab click closes the drawer with its mouse button still down, and
    focus handed back then left the game needing a click before it took a
    key, while the hotkey's did not (found in testing): the hand-back waits
    for the button to come up, then goes at once, and once."""
    from PyQt6.QtTest import QTest
    from src.gui import sco_overlay
    from tests.event_loop import pump_until

    held, handed = {"button": True}, []
    overlay = _clicked_overlay(monkeypatch, held, handed)
    drawer = overlay.drawer
    try:
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("minerals")
        drawer.open_section("minerals")                         # its tab closes it, button down
        QTest.qWait(80)
        assert not drawer.is_open() and handed == []            # not while it is held
        held["button"] = False                                  # the button comes up
        assert pump_until(lambda: handed == [4242], seconds=2)
        QTest.qWait(80)
        assert handed == [4242]
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_hand_back_still_waiting_goes_after_the_wait(qapp, monkeypatch, slot_errors):
    """A button that never reads as up (a release Qt never saw) holds the
    hand-back for HAND_BACK_WAIT_MS at most."""
    from src.gui import sco_overlay
    from tests.event_loop import pump_until

    monkeypatch.setattr(sco_overlay, "HAND_BACK_WAIT_MS", 60)
    held, handed = {"button": True}, []
    overlay = _clicked_overlay(monkeypatch, held, handed)
    drawer = overlay.drawer
    try:
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("crafting")
        drawer.open_section("crafting")
        assert handed == []
        assert pump_until(lambda: handed == [4242], seconds=2)
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_waiting_hand_back_is_dropped_by_an_open_or_a_stop(qapp, monkeypatch, slot_errors):
    from PyQt6.QtTest import QTest
    from src.gui import sco_overlay

    held, handed = {"button": True}, []
    overlay = _clicked_overlay(monkeypatch, held, handed)
    drawer = overlay.drawer
    try:
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("minerals")
        drawer.open_section("minerals")                         # waits for the button
        drawer.open_section("crafting")                         # opened again meanwhile
        held["button"] = False
        QTest.qWait(80)
        assert handed == []
        drawer.close_drawer()
        held["button"] = True
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("blueprints")
        drawer.open_section("blueprints")                       # waits for the button
        overlay.stop()
        held["button"] = False
        QTest.qWait(80)
        assert handed == []
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_hand_back_refused_or_not_kept_is_logged(qapp, monkeypatch, caplog, slot_errors):
    """Windows refusing the hand-back, or another window in front
    FOCUS_CHECK_MS after it, is logged at INFO; one that stays says nothing."""
    from PyQt6.QtTest import QTest
    from src.gui import sco_overlay

    focus, refused = {"window": 4242}, {"now": True}
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    monkeypatch.setattr(sco_overlay, "give_focus_back", lambda w: not refused["now"])
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: False)
    monkeypatch.setattr(sco_overlay, "FOCUS_CHECK_MS", 0)
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)

    def lines():
        return [r.getMessage() for r in caplog.records if "back to window" in r.getMessage()]

    def click_open_and_close():
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("minerals")
        drawer.open_section("minerals")

    try:
        with caplog.at_level("INFO", logger="src.gui.sco_overlay"):
            click_open_and_close()                              # Windows refuses
            assert lines() == ["SCO: Windows did not hand focus back to window 4242"]
            refused["now"] = False
            click_open_and_close()                              # handed back, and it stays
            QTest.qWait(30)
            assert len(lines()) == 1
            click_open_and_close()
            focus["window"] = 777                               # then another window has it
            QTest.qWait(30)
            assert lines()[1:] == ["SCO: 0 ms after focus went back to window 4242, "
                                   "window 777 is in front"]
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_click_that_names_no_window_keeps_the_kept_one(qapp, monkeypatch, slot_errors):
    """The hotkey keeps the game and Windows leaves focus on it, then a click
    on the open panel comes with nothing in front and nothing noted (the
    panel opened under a pointer that had not moved). The click names no
    window, so the game stays kept and closing by the tab hands focus back."""
    from src.gui import sco_overlay

    focus = {"window": 4242}                                    # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    handed = []
    monkeypatch.setattr(sco_overlay, "give_focus_back", _recording(handed))
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: False)
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)
    named = []
    drawer.taking_focus.connect(named.append)
    try:
        overlay.toggle_drawer()                                 # the hotkey opens it
        focus["window"] = 0                                     # mid-click, nothing in front
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)           # and no pointer move noted
        assert named == [0] and drawer.is_open()
        drawer.open_section(drawer._current)                    # its own tab closes it
        assert handed == [4242]
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_hidden_drawer_forgets_the_window_noted_under_the_pointer(qapp, monkeypatch, slot_errors):
    """Windows may send no WM_MOUSELEAVE for a window hidden under the
    pointer, so hiding the drawer (the overlay stopped, or the drawer switched
    off) drops the note: shown again, a click with nothing in front names no
    window from before."""
    from src.gui import sco_overlay

    focus = {"window": 4242}
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    named = []
    drawer.taking_focus.connect(named.append)
    hides = ((overlay.stop, overlay.start),
             (lambda: overlay.set_options({"drawer": False}), lambda: overlay.set_options({})))
    try:
        for hide, show in hides:
            focus["window"] = 4242
            _native(drawer, sco_overlay.WM_MOUSEMOVE)           # noted under the pointer
            hide()                                              # hidden with the pointer on it
            show()
            assert drawer.isVisible()
            focus["window"] = 0                                 # mid-click, nothing in front
            _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        assert named == [0, 0]
    finally:
        overlay.stop()
    assert not slot_errors


def test_each_hand_back_is_checked_for_its_own_window(qapp, monkeypatch, caplog, slot_errors):
    """Two hand-backs within FOCUS_CHECK_MS are each checked for their own
    window (one shared check named the second window for both, then nothing),
    and a check says nothing once the drawer opened again or the overlay
    stopped."""
    from PyQt6.QtTest import QTest
    from src.gui import sco_overlay

    focus = {"window": 4242}
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    monkeypatch.setattr(sco_overlay, "give_focus_back", lambda window: True)
    monkeypatch.setattr(sco_overlay, "_mouse_button_held", lambda: False)
    monkeypatch.setattr(sco_overlay, "FOCUS_CHECK_MS", 0)
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "isActiveWindow", lambda: True)

    def lines():
        return [r.getMessage() for r in caplog.records if "went back" in r.getMessage()]

    def hand_back_to(window):
        focus["window"] = window                                # in front at the click
        _native(drawer, sco_overlay.WM_MOUSEACTIVATE)
        drawer.open_section("minerals")
        drawer.open_section("minerals")                         # its tab closes it

    try:
        with caplog.at_level("INFO", logger="src.gui.sco_overlay"):
            hand_back_to(4242)
            hand_back_to(5151)                                  # before the first check ran
            focus["window"] = 777                               # then another window has it
            QTest.qWait(30)
            assert lines() == [
                "SCO: 0 ms after focus went back to window 4242, window 777 is in front",
                "SCO: 0 ms after focus went back to window 5151, window 777 is in front"]
            hand_back_to(4242)
            drawer.open_section("crafting")                     # opened again before its check
            focus["window"] = 777
            QTest.qWait(30)
            drawer.close_drawer()
            hand_back_to(4242)
            overlay.stop()                                      # stopped before its check
            focus["window"] = 777
            QTest.qWait(30)
            assert len(lines()) == 2
    finally:
        overlay.stop()
    assert not slot_errors


def test_the_hotkeys_keys_are_looked_at_only_while_the_game_is_in_front(
        qapp, monkeypatch, slot_errors):
    """#587: Star Citizen keeps the hotkey's WM_HOTKEY away while it is in
    front, so the pass-through tick looks at the hotkey's keys then, and
    only then. With another window in front nothing on the keyboard is asked
    about, and a combination down at the first tick after the game came back
    is a press (it may have gone down just then)."""
    from tests.event_loop import pump_until

    game = {"in_front": True}
    monkeypatch.setattr(so, "game_in_front", lambda: game["in_front"])
    monkeypatch.setattr(so, "pointer_hidden", lambda: True)
    monkeypatch.setattr(so, "foreground_window", lambda: 4242)       # the game
    monkeypatch.setattr(so, "give_focus_back", _recording([]))
    overlay, fake = _overlay_with_fake_hotkey()
    overlay.set_drawer_hotkey("Ctrl+Shift+O")
    drawer = overlay.drawer
    try:
        overlay.start()
        overlay._pass_through_timer.stop()                      # the test runs the ticks
        fake.down = {CTRL, SHIFT, O_KEY}
        overlay._sync_pass_through()                            # held as the hotkey was set
        assert fake.asked == [O_KEY] and not drawer.is_open()   # no press, nothing more asked
        game["in_front"] = False                                # another window in front
        overlay._sync_pass_through()
        assert fake.asked == [O_KEY]                            # nothing asked
        game["in_front"] = True                                 # back, the keys still down:
        overlay._sync_pass_through()                            # let go and pressed meanwhile?
        assert pump_until(drawer.is_open, seconds=2)            # a press, after KEY_GRACE_MS
        assert set(fake.asked) == {O_KEY, SHIFT, CTRL, ALT, LWIN, RWIN}
        game["in_front"] = False
        fake.asked.clear()
        overlay._sync_pass_through()
        assert fake.asked == []
    finally:
        overlay.stop()
    assert not slot_errors


def test_a_drawer_opened_without_focus_is_logged(qapp, monkeypatch, caplog):
    """A key check found the press but Windows kept focus on the game: the
    log says so, once the check after the open has run."""
    from PyQt6.QtTest import QTest
    from src.gui import sco_overlay

    focus = {"window": 4242}                                    # the game
    monkeypatch.setattr(sco_overlay, "foreground_window", lambda: focus["window"])
    monkeypatch.setattr(sco_overlay, "FOCUS_CHECK_MS", 0)
    overlay, _fake = _overlay_with_fake_hotkey()
    overlay.start()
    drawer = overlay.drawer
    monkeypatch.setattr(drawer, "activateWindow", lambda: None)
    messages = lambda: [r.getMessage() for r in caplog.records  # noqa: E731
                        if "without focus" in r.getMessage()]
    try:
        with caplog.at_level("INFO", logger="src.gui.sco_overlay"):
            overlay.toggle_drawer()
            QTest.qWait(20)
            assert messages() == ["SCO: the drawer opened without focus: "
                                  "Windows kept it on window 4242"]
            overlay.toggle_drawer()                             # closed
            focus["window"] = int(drawer.winId())               # this time it took focus
            overlay.toggle_drawer()
            QTest.qWait(20)
            assert len(messages()) == 1
            overlay.toggle_drawer()
            focus["window"] = 4242
            overlay.toggle_drawer()
            overlay.toggle_drawer()                             # closed before the check
            QTest.qWait(20)
            assert len(messages()) == 1
    finally:
        overlay.stop()
