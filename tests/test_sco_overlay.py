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
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.sco_overlay import (  # noqa: E402
    DEFAULT_OVERLAY_COLORS, SCAN_REGION, BlueprintDrawer, OverlayColors,
    ScoOverlay, format_matches, hud_signature_reader, scan_region_rect,
)
from src.utils.blueprint_meta import BlueprintItem  # noqa: E402
from src.utils.mining_signatures import decode_signature  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


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


def test_arrow_flips_with_the_drawer(qapp):
    drawer = BlueprintDrawer()
    assert drawer._handle.points_left and not drawer._panel.isVisibleTo(drawer)
    drawer.toggle()
    assert not drawer._handle.points_left and drawer._panel.isVisibleTo(drawer)
    drawer.toggle()
    assert drawer._handle.points_left


def test_drawer_takes_theme_colours(qapp):
    gold = OverlayColors(background="#12100c", text="#e8e0cc", accent="#C9A961", secondary="#A08C5A")
    drawer = BlueprintDrawer(gold)
    assert drawer._handle.colors == gold
    assert "#C9A961" in drawer._panel.styleSheet()
    assert "rgba(18, 16, 12," in drawer._panel.styleSheet()   # see-through window colour
    drawer.apply_colors(DEFAULT_OVERLAY_COLORS)
    assert drawer._handle.colors == DEFAULT_OVERLAY_COLORS


def test_no_reader_means_no_capture(qapp, monkeypatch):
    # Keep the test off the registry-backed theme setting.
    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    overlay = ScoOverlay()
    overlay.set_reader(None)
    overlay.start()
    assert not overlay._timer.isActive()
    overlay.set_reader(lambda image: None)
    assert overlay._timer.isActive()
    overlay.stop()
    assert not overlay._timer.isActive()


def test_default_reader_is_the_hud_reader(qapp, monkeypatch):
    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
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


def test_sample_saved_once_per_reading(qapp, monkeypatch, tmp_path):
    from PyQt6.QtGui import QImage

    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    overlay = ScoOverlay(sample_dir=tmp_path / "samples")
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    overlay._save_sample(image, "7,200", QRect(50, 40, 30, 11))
    overlay._save_sample(image, "7,200", QRect(50, 40, 30, 11))
    saved = list((tmp_path / "samples").iterdir())
    assert len(saved) == 1 and saved[0].name.endswith("_7200.png")


def test_one_frame_misread_does_not_replace_the_label(qapp, monkeypatch):
    from PyQt6.QtCore import QPoint

    monkeypatch.setattr(OverlayColors, "from_theme", classmethod(lambda cls: DEFAULT_OVERLAY_COLORS))
    overlay = ScoOverlay()
    at = QPoint(10, 10)
    overlay._on_reading(7200, at)
    assert not overlay.label.isVisible()            # first sighting: wait
    overlay._on_reading(7200, at)
    assert overlay.label._label.text() == "2 × Bexalite"
    overlay._on_reading(7208, at)                   # one misread frame
    assert overlay.label._label.text() == "2 × Bexalite"
    overlay._on_reading(7200, at)
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
    assert label.y() == 300
    assert label._label.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert ODW_OVERLAY_COLORS.accent in label._label.styleSheet()
    label.hide()
