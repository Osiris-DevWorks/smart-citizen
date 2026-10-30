"""Smart Citizen Overlay (SCO) windows, driven headlessly.

``QT_QPA_PLATFORM=offscreen``, same pattern as test_restore_backup.py — no
pytest-qt. Covers the drawer's list/filter/owned-toggle behaviour, the
signature label text, the capture loop only running with a reader set, and
the default reader working on a real QImage.
"""
from __future__ import annotations

import sys

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor

from src.gui.sco_overlay import (
    DEFAULT_OVERLAY_COLORS, DRAWER_HANDLE_HEIGHT, DRAWER_HANDLE_OVERLAP, DRAWER_HANDLE_WIDTH,
    LABEL_GAP, SAVE_SAMPLES_ENV,
    SCAN_REGION, SECTION_ICONS, BlueprintDrawer, OverlayColors, SectionTabBar, drawer_edge,
    ScoOverlay, format_matches, hud_signature_reader, scan_region_rect,
)
from src.utils.blueprint_meta import BlueprintItem
from src.utils.mining_catalog import CraftingIndex, MineralInfo
from src.utils.mining_signatures import decode_signature
from src.utils.settings import AppSettings


@pytest.fixture(autouse=True)
def _hermetic_overlay(monkeypatch, tmp_path):
    """No real theme or samples-folder reads: the overlay takes its colours
    from settings on every start and resolves the samples folder per save."""
    monkeypatch.setattr(OverlayColors, "from_theme",
                        classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    monkeypatch.setattr("src.gui.sco_overlay.AppSettings.get_sco_samples_dir",
                        staticmethod(lambda: tmp_path / "default_samples"))


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
    monkeypatch.setattr("src.gui.sco_overlay.play_alert_sound", lambda: chimes.append(True))
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
        assert chimes == [True]
        overlay._on_reading(10200, QPoint(500, 300))            # still showing: no more
        assert chimes == [True]
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


class _FakeUser32:
    """RegisterHotKey, UnregisterHotKey and the raw input switch, recorded
    instead of called."""

    def __init__(self, refuse=False):
        self.calls, self.refuse, self.raw = [], refuse, []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802
        self.calls.append(("register", modifiers, key))
        return not self.refuse

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802
        self.calls.append(("unregister",))
        return True

    def RegisterRawInputDevices(self, device, count, size):  # noqa: N802
        self.raw.append(device._obj.dwFlags)
        return True

    def CreateWindowExW(self, *args):  # noqa: N802
        return 0x5150

    def DestroyWindow(self, hwnd):  # noqa: N802
        return True


def _overlay_with_fake_hotkey(refuse=False):
    from src.gui.global_hotkey import GlobalHotkey

    overlay = ScoOverlay()
    overlay.set_reader(None)
    fake = _FakeUser32(refuse)
    overlay._hotkey = GlobalHotkey(overlay, user32=fake)
    overlay._hotkey.activated.connect(overlay.toggle_drawer)
    return overlay, fake


CTRL_SHIFT_O = ("register", 0x2 | 0x4 | 0x4000, 0x4F)


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
    monkeypatch.setattr(sco_overlay, "give_focus_back", handed.append)
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
        drawer.open_section("crafting")                         # opened by a click
        drawer.close_drawer()
        assert handed == [4242]                                 # the hotkey took nothing
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
    monkeypatch.setattr(sco_overlay, "give_focus_back", handed.append)
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
    monkeypatch.setattr(sco_overlay, "give_focus_back", handed.append)
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


def test_the_hotkey_watches_raw_input_only_while_it_is_held(qapp):
    from src.gui.global_hotkey import RIDEV_INPUTSINK, RIDEV_REMOVE

    overlay, fake = _overlay_with_fake_hotkey()
    overlay.set_drawer_hotkey("Ctrl+Shift+O")
    assert fake.raw == []                                       # not running
    overlay.start()
    assert fake.raw == [RIDEV_INPUTSINK]
    overlay.set_options({"drawer": False})
    assert fake.raw == [RIDEV_INPUTSINK, RIDEV_REMOVE]
    overlay.set_options({})
    overlay.stop()
    assert fake.raw == [RIDEV_INPUTSINK, RIDEV_REMOVE, RIDEV_INPUTSINK, RIDEV_REMOVE]


def test_a_drawer_opened_without_focus_is_logged(qapp, monkeypatch, caplog):
    """Raw input saw the hotkey but Windows kept focus on the game: the log
    says so, once the check after the open has run."""
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
