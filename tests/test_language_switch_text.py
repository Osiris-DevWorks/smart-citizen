"""#540: a language switch shows what a restart in that language shows.

The Help side panel's HELP.md is loaded once when the window is built and
again on a theme swap. A language switch re-rendered the About, FAQ and Legal
tabs (#314) but not the panel, so after one the panel kept the startup
language's HELP.md, and its title stayed the English "Help" in every
language, until a restart. The theme swap and the language switch kept their
own lists of what to re-render, which is how the panel was missed, so both
now go through `MainWindow._render_document_browsers`.

A check of every other text found more a switch left behind, each written
by a refresh or a load that a switch did not run again: the Blueprint
Tracker filters' "Any" rows, the Config tab's channel hint and Data.p4k status
(and the channel list's not-installed tooltips), and the Log tab's line count.
That check is `test_a_switch_shows_what_a_restart_shows`. It cannot see the
Help panel's old title, a fixed "Help" in both windows, so its control and
`test_a_window_built_in_german_titles_the_panel_in_german` hold that one.

All on a real MainWindow (tests/gui_window.py), switched the way the Config
tab switches it: the language saved, then `_on_language_changed`, with the
base.ini reload that follows (`_apply_language_base_source`) recorded instead
of run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QComboBox,
                             QDockWidget, QDoubleSpinBox, QGroupBox, QLabel,
                             QLineEdit, QListWidget, QMenu, QPlainTextEdit,
                             QSpinBox, QTabWidget, QTextEdit, QTreeWidget,
                             QWidget)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils import i18n  # noqa: E402
from src.utils.i18n import tr  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from tests.gui_window import build_main_window, retire_main_window  # noqa: E402

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
GERMAN = REPO / "languages" / "german"
ADVANCED = AppSettings.UI_MODE_ADVANCED

DOCUMENT_RENDERERS = ("_render_about_html", "_render_faq_html",
                      "_render_legal_html", "_render_help_html")


def _first_heading(doc: Path, marks: str) -> str:
    """The text of a doc's first heading at the level ``marks`` gives
    ("#" or "##"), which its browser shows as a line of its own."""
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.startswith(marks + " "):
            return line[len(marks) + 1:].strip()
    raise AssertionError(f"no {marks} heading in {doc}")


# HELP.md is told apart by its title. ABOUT.md's title is "Smart Citizen" in
# both languages, so the About tab is told apart by its first section.
ENGLISH_HELP = _first_heading(REPO / "docs" / "HELP.md", "#")
GERMAN_HELP = _first_heading(GERMAN / "HELP.md", "#")
ENGLISH_ABOUT = _first_heading(REPO / "docs" / "ABOUT.md", "##")
GERMAN_ABOUT = _first_heading(GERMAN / "ABOUT.md", "##")


def _switch_to(window, language: str) -> None:
    AppSettings.set_selected_language(language)
    window._on_language_changed(language)


def _header_texts(view) -> dict:
    header = None
    if hasattr(view, "horizontalHeader"):
        header = view.horizontalHeader()
    elif hasattr(view, "header"):
        header = view.header()
    if header is None or view.model() is None:
        return {}
    model, columns = view.model(), range(header.count())
    return {
        role_name: [str(model.headerData(c, Qt.Orientation.Horizontal, role)) for c in columns]
        for role_name, role in (("header", Qt.ItemDataRole.DisplayRole),
                                ("header tooltip", Qt.ItemDataRole.ToolTipRole))
    }


def _shown_texts(window) -> list:
    """Every text the window and its children show, as (widget, {field:
    value}) in Qt's child order, which two windows built the same way share."""
    shown = []
    for w in window.findChildren(QWidget):
        fields = {"tooltip": w.toolTip()}
        if isinstance(w, (QLabel, QAbstractButton)):
            fields["text"] = w.text()
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            fields["placeholder"] = w.placeholderText()
        if isinstance(w, (QGroupBox, QMenu)):
            fields["title"] = w.title()
        if isinstance(w, QDockWidget):
            fields["title"] = w.windowTitle()
        if isinstance(w, QTabWidget):
            fields["tabs"] = [w.tabText(i) for i in range(w.count())]
        if isinstance(w, QComboBox):
            fields["items"] = [w.itemText(i) for i in range(w.count())]
            fields["item tooltips"] = [w.itemData(i, Qt.ItemDataRole.ToolTipRole)
                                       for i in range(w.count())]
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            fields["affixes"] = [w.prefix(), w.suffix(), w.specialValueText()]
        if isinstance(w, QAbstractItemView):
            fields.update(_header_texts(w))
        if isinstance(w, QTreeWidget):
            fields["rows"] = [[w.topLevelItem(i).text(c) for c in range(w.columnCount())]
                              for i in range(w.topLevelItemCount())]
        if isinstance(w, QListWidget):
            fields["rows"] = [w.item(i).text() for i in range(w.count())]
        shown.append((f"{type(w).__name__} {w.objectName()!r}", fields))
    for action in window.findChildren(QAction):
        shown.append((f"QAction {action.objectName()!r}",
                      {"text": action.text(), "tooltip": action.toolTip()}))
    return shown


def _open_lazy_panels(window) -> None:
    """Build the String Editor and Test Plan panels, which a window builds
    only when they are first opened, so their texts are read too."""
    window._ensure_editor_dock()
    window._ensure_test_plan_dock()


def _differences(first: list, second: list) -> list:
    widgets = [widget for widget, _ in first], [widget for widget, _ in second]
    if widgets[0] != widgets[1]:
        at = next((i for i, (a, b) in enumerate(zip(*widgets)) if a != b),
                  min(len(w) for w in widgets))
        pytest.fail(f"the windows' widgets differ from position {at}: "
                    f"{widgets[0][at:at + 3]} against {widgets[1][at:at + 3]}, "
                    f"{len(widgets[0])} and {len(widgets[1])} widgets in all")
    return [(widget, field, a[field], b[field])
            for (widget, a), (_, b) in zip(first, second)
            for field in a if a[field] != b[field]]


@pytest.fixture
def reloads(monkeypatch):
    """The languages the switch's base.ini reload was asked for."""
    seen = []
    from src.gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_apply_language_base_source",
                        lambda self, language: seen.append(language))
    return seen


def test_the_headings_tell_the_languages_apart():
    """The checks below tell the two languages apart by these headings, so
    none may be empty or the same in both, and neither language's may turn
    up inside the other's."""
    for english, german in ((ENGLISH_HELP, GERMAN_HELP), (ENGLISH_ABOUT, GERMAN_ABOUT)):
        assert english and german
        assert english not in german and german not in english


@pytest.mark.parametrize("mode", [AppSettings.UI_MODE_ADVANCED, AppSettings.UI_MODE_SIMPLE])
def test_a_switch_shows_what_a_restart_shows(qapp, tmp_path, monkeypatch,
                                             english_ui, reloads, mode):
    """Every text a window started in English shows after a switch to German
    is what a window started in German shows, in either view. The second
    window is built in the same folder after the switch, as a restart would
    find it, and both are read field by field."""
    window = build_main_window(tmp_path, monkeypatch, mode)
    try:
        _open_lazy_panels(window)
        in_english = _shown_texts(window)
        _switch_to(window, "german")
        after_switch = _shown_texts(window)
    finally:
        retire_main_window(window)
    assert reloads == ["german"]

    restarted = build_main_window(tmp_path, monkeypatch, mode, language="german")
    try:
        _open_lazy_panels(restarted)
        after_restart = _shown_texts(restarted)
    finally:
        retire_main_window(restarted)

    # The reading covers what a switch changes: hundreds of texts, the Help
    # panel's title among them.
    switched = _differences(in_english, after_switch)
    assert len(switched) > 200
    assert ("QDockWidget 'helpDock'", "title", "Help", "Hilfe") in switched

    left_behind = _differences(after_switch, after_restart)
    assert not left_behind, "texts a switch left in the old language:\n" + "\n".join(
        f"  {widget} {field}: {a!r} after the switch, {b!r} after a restart"
        for widget, field, a, b in left_behind)


def test_a_switch_reloads_the_help_panel(qapp, tmp_path, monkeypatch,
                                         english_ui, reloads):
    """English, then German, then English again: the panel shows each
    language's HELP.md and title straight after the switch, as the About
    tab beside it does."""
    window = build_main_window(tmp_path, monkeypatch, ADVANCED)
    try:
        browser, dock, about = window.help_browser, window.help_dock, window.about_browser
        assert ENGLISH_HELP in browser.toPlainText()
        assert dock.windowTitle() == "Help"

        _switch_to(window, "german")
        assert reloads == ["german"]
        assert GERMAN_HELP in browser.toPlainText()
        assert ENGLISH_HELP not in browser.toPlainText()
        assert dock.windowTitle() == tr("toolbar.help_btn") == "Hilfe"
        # The tab fixed by #314, as a control that the switch went through.
        assert GERMAN_ABOUT in about.toPlainText()
        assert ENGLISH_ABOUT not in about.toPlainText()

        _switch_to(window, "english")
        assert reloads == ["german", "english"]
        assert ENGLISH_HELP in browser.toPlainText()
        assert GERMAN_HELP not in browser.toPlainText()
        assert dock.windowTitle() == "Help"
        assert ENGLISH_ABOUT in about.toPlainText()
    finally:
        retire_main_window(window)


def test_a_theme_swap_and_a_switch_render_the_same_documents(
        qapp, tmp_path, monkeypatch, english_ui):
    """Both re-render all four documents, so a document added to one cannot
    be left out of the other, as the Help panel was left out of the switch."""
    window = build_main_window(tmp_path, monkeypatch, ADVANCED)
    try:
        rendered = []
        for name in DOCUMENT_RENDERERS:
            monkeypatch.setattr(window, name,
                                lambda name=name: rendered.append(name))

        window.refresh_action_buttons()
        assert sorted(rendered) == sorted(DOCUMENT_RENDERERS)

        rendered.clear()
        window.retranslate_ui()
        assert sorted(rendered) == sorted(DOCUMENT_RENDERERS)
    finally:
        retire_main_window(window)


def test_a_window_built_in_german_titles_the_panel_in_german(
        qapp, tmp_path, monkeypatch, english_ui):
    """A start with German saved names the panel in German too, not only a
    switch to it: the title was a fixed "Help"."""
    i18n.set_language("german")  # as main() does before the window is built
    window = build_main_window(tmp_path, monkeypatch, ADVANCED, language="german")
    try:
        assert AppSettings.get_selected_language() == "german"
        assert window.help_dock.windowTitle() == "Hilfe"
        assert GERMAN_HELP in window.help_browser.toPlainText()
    finally:
        retire_main_window(window)
