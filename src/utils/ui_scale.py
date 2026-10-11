"""UI font size (Config tab → Appearance) applied as a Qt scale factor.

Most labels set their size in px through per-widget stylesheets, and many
controls have fixed widths, so changing only the application font would
leave much of the text unscaled and clip the rest. ``QT_SCALE_FACTOR``
scales text and the controls around it together. Qt reads it once, when
the ``QApplication`` is built, so a new size takes effect after a restart.

Qt-free so it can run before the ``QApplication`` exists and be unit tested.
"""
import logging
import os
from typing import MutableMapping, Optional

from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)

FONT_SCALE_FACTORS = {
    AppSettings.FONT_SIZE_SMALL: 0.9,
    AppSettings.FONT_SIZE_MEDIUM: 1.0,
    AppSettings.FONT_SIZE_LARGE: 1.25,
}

QT_SCALE_ENV = "QT_SCALE_FACTOR"
# Marks QT_SCALE_FACTOR as ours. A restart from the Config tab hands this
# process's environment to the new one, so without the marker a scale we
# set would look like the user's own and block switching back to Medium.
_OWNED_MARKER_ENV = "SMART_CITIZEN_UI_SCALE"


def apply_font_size_env(
    size: str, environ: Optional[MutableMapping[str, str]] = None
) -> Optional[float]:
    """Set ``QT_SCALE_FACTOR`` for ``size`` before the QApplication is built.

    Returns the factor in effect, or ``None`` when a ``QT_SCALE_FACTOR`` the
    user set themselves is left alone. Medium removes our variable entirely,
    so the default size behaves exactly as it did before this setting.
    """
    env = os.environ if environ is None else environ
    if QT_SCALE_ENV in env and _OWNED_MARKER_ENV not in env:
        logger.info(
            f"{QT_SCALE_ENV}={env[QT_SCALE_ENV]} set outside the app; font size setting ignored"
        )
        return None

    factor = FONT_SCALE_FACTORS.get(size, 1.0)
    if factor == 1.0:
        env.pop(QT_SCALE_ENV, None)
        env.pop(_OWNED_MARKER_ENV, None)
    else:
        env[QT_SCALE_ENV] = str(factor)
        env[_OWNED_MARKER_ENV] = str(factor)
    logger.info(f"UI font size: {size} (scale {factor})")
    return factor
