"""Translations of the text the enhancement generator adds (#579).

The generator writes its stat labels, mission details and journal lines in
English. ``languages/<language>/enhancements.json`` maps each English text to
the language's own, and the generator looks each one up while it writes
(``scripts/generate_enhancements_ini.py``'s ``_t``). The English text is the
key, so a text with no translation stays English and English output never
changes.

File shape, like ``ui.json`` (#182)::

    {
      "_comment": "...",
      "strings": {
        "Max HP": {"ht": "", "at": "Max. TP"},
        "{count} items": {"ht": "", "at": "{count} Gegenstände"}
      }
    }

``ht`` is a human translation and ``at`` an AI draft; ``ht`` wins, then
``at``, and a text with both empty stays English. ``{name}`` placeholders are
filled in by the generator and must be kept as they are.

``languages/english/enhancements.json`` lists every English text, each
mapped to itself, as the list translators work from. It is never loaded.

A leaf module: no Qt, no AppSettings, so the generator can import it.
"""
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Must agree with AppSettings.DEFAULT_LANGUAGE (i18n carries its own copy
# for the same reason).
_DEFAULT_LANG = "english"

TEXT_FILE_NAME = "enhancements.json"


def text_file_path(language: str) -> Path:
    """Where *language*'s table lives, in the source tree or the bundle."""
    from src.utils.resource_path import get_resource_path
    return Path(get_resource_path(f"languages/{language}/{TEXT_FILE_NAME}"))


def parse_table(data: dict) -> dict[str, str]:
    """English text -> translation, from a parsed enhancements.json.

    Leaves with no translation are left out, so they stay English."""
    out: dict[str, str] = {}
    strings = data.get("strings") if isinstance(data, dict) else None
    if not isinstance(strings, dict):
        return out
    for english, leaf in strings.items():
        if isinstance(leaf, dict):
            text = leaf.get("ht") or leaf.get("at") or ""
        elif isinstance(leaf, str):
            text = leaf
        else:
            text = ""
        if text and text != english:
            out[english] = text
    return out


def load_table(language: "str | None") -> dict[str, str]:
    """*language*'s translations, or {} for English, a missing file or a
    file that cannot be read (the run then writes English, as before)."""
    if not language or language == _DEFAULT_LANG:
        return {}
    path = text_file_path(language)
    try:
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as fh:
            return parse_table(json.load(fh))
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read {TEXT_FILE_NAME} for {language!r}: {exc}")
        return {}


def table_fingerprint(language: "str | None") -> str:
    """12 hex characters naming *language*'s translations, or "" when it has
    none (English, or no file).

    Part of the enhancements stamp (``AppSettings.enhancements_stamp_value``),
    so an update that changes a language's table makes that language's
    generated set read as out of date and the app offers to generate it
    again. English has no table, so its stamp stays the plain build key."""
    table = load_table(language)
    if not table:
        return ""
    payload = json.dumps(table, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()[:12]
