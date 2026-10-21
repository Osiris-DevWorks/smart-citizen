"""Combo box behaviour shared by the tabs that sit in a scroll area.

``NoScrollComboBox`` (Enhancements, Blueprint Tracker and Overlay tabs) lets
the mouse wheel scroll the page instead of changing an unfocused combo's
selection, and ``reposition_combo_popup_below_if_it_fits`` keeps the option
list below the box where it fits.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox


def reposition_combo_popup_below_if_it_fits(combo, popup) -> None:
    """Move *popup* to align with *combo*'s bottom-left corner, but only if
    it actually fits on-screen there.

    Qt's default popup placement flips the list above the box when it judges
    there isn't room below (common in a scroll area, even when there visually
    is room) — force it below whenever that actually fits, so the option list
    is where the user expects it. A combo near the bottom of the screen is
    the case Qt's flip logic exists for; forcing "below" there would run the
    popup off the bottom of the display, so only override when there's room.

    Shared by NoScrollComboBox.showPopup below (initial placement) and
    blueprint_tracker_tab.py's _NoWheelComboBox.showPopup (#388, re-checked
    a second time there after forcibly shrinking an overlong popup — the
    first check ran against the original, taller height).
    """
    below_point = combo.mapToGlobal(combo.rect().bottomLeft())
    screen = combo.screen()
    fits_below = (
        screen is None
        or below_point.y() + popup.height() <= screen.availableGeometry().bottom()
    )
    if fits_below:
        popup.move(below_point)


class NoScrollComboBox(QComboBox):
    """A combo box that ignores the mouse wheel unless it has focus (#197).

    The tabs that use it live in scroll areas with many dropdowns; by default
    a wheel scroll over an unfocused combo changes its selection instead of
    scrolling the page. StrongFocus stops the wheel from focusing the combo, and
    wheelEvent passes the scroll through to the page when the combo isn't focused.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def showPopup(self):  # noqa: N802 (Qt override)
        super().showPopup()
        reposition_combo_popup_below_if_it_fits(self, self.view().window())
