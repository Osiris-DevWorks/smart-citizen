"""Karolinger Guides (#602): the footer logo, the Help panel's guides link and
the guided tour's last step all use the links in ``src/utils/karolinger.py``."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.utils.karolinger import (
    GUIDES_URL_TOKEN,
    KAROLINGER_GUIDES_URL,
    KAROLINGER_VIDEO_TUTORIAL_URL,
    with_guides_url,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parent.parent
HELP_FILES = [ROOT / "docs" / "HELP.md", *sorted((ROOT / "languages").glob("*/HELP.md"))]


@pytest.mark.parametrize("path", HELP_FILES, ids=lambda p: p.parent.name)
def test_every_help_links_the_guides_through_the_token(path):
    text = path.read_text(encoding="utf-8")
    assert text.count(f"]({GUIDES_URL_TOKEN})") == 1
    rendered = with_guides_url(text)
    assert GUIDES_URL_TOKEN not in rendered
    assert f"]({KAROLINGER_GUIDES_URL})" in rendered


def test_the_tour_ends_on_the_guides_step_with_the_video_link():
    from src.gui.main_window import MainWindow

    steps = json.loads((ROOT / "assets" / "tutorial.json").read_text(encoding="utf-8"))["steps"]
    assert steps[-1]["id"] == "guides"
    assert steps[-1]["link_text"]
    logo = object()
    wiring = MainWindow._tutorial_step_wiring(SimpleNamespace(karolinger_label=logo))
    assert wiring["guides"]["target"]() is logo
    assert wiring["guides"]["link_url"] == KAROLINGER_VIDEO_TUTORIAL_URL


def test_the_footer_logo_is_scaled_to_the_footer_height(qapp):
    from src.gui.main_window import MainWindow

    pixmap = MainWindow._footer_pixmap("karolinger-guides.png")
    assert pixmap is not None
    assert pixmap.height() == MainWindow._FOOTER_IMAGE_HEIGHT
    assert MainWindow._footer_pixmap("no-such-image.png") is None


def test_a_coach_mark_shows_a_step_link_only_when_it_has_one(qapp):
    from PyQt6.QtWidgets import QWidget

    from src.gui.coach_mark import CoachMarkOverlay, CoachMarkStep

    root = QWidget()
    root.resize(800, 600)
    overlay = CoachMarkOverlay(root)
    linked = CoachMarkStep(target=lambda: None, title="T", description="D",
                           link_url="https://example.com/a?b=1&c=2", link_text="Watch <it>")
    overlay.show_step(linked, 0, 2, has_back=False, is_last=False)
    assert not overlay._link_label.isHidden()
    assert 'href="https://example.com/a?b=1&amp;c=2"' in overlay._link_label.text()
    assert "Watch &lt;it&gt;" in overlay._link_label.text()

    overlay.show_step(CoachMarkStep(target=lambda: None, title="T", description="D"),
                      1, 2, has_back=True, is_last=True)
    assert overlay._link_label.isHidden()
    root.deleteLater()
