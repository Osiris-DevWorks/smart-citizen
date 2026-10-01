"""Manages Star Citizen user.cfg file for language and other settings."""
import logging
import re
from pathlib import Path

from src.utils.settings import AppSettings, SC_LANGUAGE_IDS

logger = logging.getLogger(__name__)

# Match any ``g_language`` assignment regardless of spacing, case, or value.
# SC's user.cfg parser is lenient: ``g_language=english``, ``G_Language =
# English``, and ``g_language = "english"`` are all valid. The previous
# exact-string check missed those and appended a duplicate line on every
# apply, which is the bug this regex fixes.
_LANGUAGE_KEY_RE = re.compile(r"^\s*g_language\s*=", re.IGNORECASE)
_LANGUAGE_KV_RE = re.compile(
    r'^\s*g_language\s*=\s*"?([^";\r\n]+?)"?\s*(?:[;#].*)?$',
    re.IGNORECASE,
)


def get_user_cfg_language(channel_path: str | Path | None = None) -> str | None:
    """Read user.cfg's current g_language value, without modifying anything.

    Returns None if the channel path/user.cfg is missing or unreadable, or
    no g_language line is present. Pure read -- unlike ensure_user_cfg_
    language, which also writes. Added for MainWindow._entries_already_
    applied (#398 review): switching the language selector in Smart
    Citizen's own UI never touches user.cfg by itself (ensure_user_cfg_
    language only ever runs at window init and apply-to-game time), so a
    merged-file-content comparison alone can look "already applied" (green)
    for a language switched back to from another one, while the game's
    user.cfg still points at the OTHER language entirely -- green with
    nothing actually fixable, since Apply (the only path that corrects
    g_language) is now disabled by that same false-green verdict.
    """
    if channel_path is None:
        channel_path = AppSettings.get_game_install_path()
    if not channel_path:
        return None
    user_cfg_path = Path(channel_path) / "user.cfg"
    if not user_cfg_path.exists():
        return None
    try:
        content = user_cfg_path.read_text(encoding="utf-8")
    except Exception:
        return None
    for line in content.splitlines():
        if _LANGUAGE_KEY_RE.match(line):
            match = _LANGUAGE_KV_RE.match(line)
            return match.group(1).strip() if match else None
    return None


def ensure_user_cfg_language(language: str | None = None) -> bool:
    """Ensure Star Citizen's user.cfg has the correct g_language setting.

    Uses *language* if provided, otherwise reads :meth:`AppSettings.get_selected_language`.
    Creates the file if absent, adds the key if missing, or updates it if
    the existing value differs from the desired language.

    Returns:
        True if successful, False if the channel's install dir isn't
        accessible (channel not installed, path misconfigured, etc.).
    """
    if language is None:
        language = AppSettings.get_selected_language()

    language = SC_LANGUAGE_IDS.get(language, language)

    channel_path = AppSettings.get_game_install_path()
    if not channel_path:
        logger.warning("Game install path not configured — skipping user.cfg setup")
        return False

    channel_dir = Path(channel_path)
    if not channel_dir.exists():
        logger.warning(
            f"{AppSettings.get_active_channel()} directory not found at {channel_dir} "
            f"— skipping user.cfg setup"
        )
        return False

    user_cfg_path = channel_dir / "user.cfg"
    language_line = f"g_language = {language}"

    try:
        if not user_cfg_path.exists():
            logger.info(f"Creating user.cfg at {user_cfg_path}")
            user_cfg_path.write_text(language_line + "\n", encoding="utf-8")
            logger.info(f"Created user.cfg with '{language_line}'")
            return True

        content = user_cfg_path.read_text(encoding="utf-8")
        existing_value: str | None = None
        for line in content.splitlines():
            if _LANGUAGE_KEY_RE.match(line):
                match = _LANGUAGE_KV_RE.match(line)
                existing_value = match.group(1).strip() if match else ""
                break

        if existing_value is not None:
            if existing_value.lower() == language.lower():
                logger.info(f"user.cfg already has g_language={language}; not modifying")
                return True
            # Update the existing line to the selected language.
            logger.info(
                f"Updating user.cfg g_language: {existing_value!r} → {language!r}"
            )
            new_lines = []
            for line in content.splitlines():
                if _LANGUAGE_KEY_RE.match(line):
                    new_lines.append(language_line)
                else:
                    new_lines.append(line)
            user_cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return True

        logger.info(f"Adding language setting to {user_cfg_path}")
        lines = content.splitlines()
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(language_line)
        user_cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"Added '{language_line}' to user.cfg")
        return True
    except Exception as e:
        logger.exception(f"Failed to manage user.cfg at {user_cfg_path}: {e}")
        return False
