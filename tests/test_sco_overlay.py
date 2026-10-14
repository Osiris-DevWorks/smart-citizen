"""Smart Citizen Overlay (SCO) windows, driven headlessly.

``QT_QPA_PLATFORM=offscreen``, same pattern as test_restore_backup.py — no
pytest-qt. Covers the drawer's list/filter/owned-toggle behaviour, the
signature label text, the capture loop only running with a reader set, and
the default reader working on a real QImage.
"""
from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect, Qt  # noqa: E402

from src.gui.sco_overlay import (  # noqa: E402
    DEFAULT_OVERLAY_COLORS, DRAWER_HANDLE_HEIGHT, DRAWER_HANDLE_OVERLAP, DRAWER_HANDLE_WIDTH,
    LABEL_GAP,
    SCAN_REGION, SECTION_ICONS, BlueprintDrawer, OverlayColors, SectionTabBar, drawer_edge,
    ScoOverlay, format_matches, hud_signature_reader, scan_region_rect,
)
from src.utils.blueprint_meta import BlueprintItem  # noqa: E402
from src.utils.mining_catalog import CraftingIndex, MineralInfo  # noqa: E402
from src.utils.mining_signatures import decode_signature  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_overlay(monkeypatch, tmp_path):
    """No real theme or samples-folder reads: the overlay takes its colours
    from settings on every start and resolves the samples folder per save."""
    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    monkeypatch.setattr("src.gui.sco_overlay.AppSettings.get_sco_samples_dir",
                        staticmethod(lambda: tmp_path / "default_samples"))


def _meta():
    return {
        "Agni": BlueprintItem("Agni", frozenset({"Haul cargo"}), "Quantum Drive", "Industrial", "S3", "B"),
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
    assert format_matches(decode_signature(12000)).splitlines() == [
        "3 × ROC Mineable", "4 × FPS Mineable", "6 × Salvage",
    ]


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

    mid, near, far = DRAWER_HANDLE_WIDTH / 2, DRAWER_HANDLE_HEIGHT / 2, length - DRAWER_HANDLE_HEIGHT / 2
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


def test_drawer_takes_theme_colours(qapp):
    gold = OverlayColors(background="#12100c", text="#e8e0cc", accent="#C9A961", secondary="#A08C5A")
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


def test_sample_saved_once_per_reading(qapp, tmp_path):
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
    rows = {tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
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
    drawer.set_catalog({"Hadanite": MineralInfo("Hadanite", "Gems", ("Aberdeen",))}, CraftingIndex())
    assert drawer._mineral_tree.topLevelItem(0).data(1, Qt.ItemDataRole.CheckStateRole) is None


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


def test_save_samples_off_saves_nothing(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    overlay = ScoOverlay(sample_dir=tmp_path / "samples")
    overlay.set_options({"save_samples": False})
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
    assert drawer._mineral_tree.topLevelItem(0).text(0).startswith("No minerals match")
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


def test_a_failed_sample_save_is_logged(qapp, tmp_path, caplog, monkeypatch):
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


def test_samples_folder_is_resolved_at_save_time(qapp, tmp_path, monkeypatch):
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


def test_the_first_save_of_a_session_prunes_the_folder(qapp, tmp_path, monkeypatch):
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
