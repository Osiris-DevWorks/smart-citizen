"""Release notes bundled with the build, for the What's New dialog.

The build bundles ``docs/{VERSION}-RELEASE-NOTES.md`` (the same file the
release workflow publishes as the GitHub release body), so the dialog works
offline and shows exactly what shipped.
"""

from pathlib import Path

from src.utils.resource_path import get_resource_path


def release_notes_path(version: str) -> Path:
    """Where the notes for *version* live, in the bundle or the repo."""
    return Path(get_resource_path(f"docs/{version}-RELEASE-NOTES.md"))


def bundled_release_notes(version: str) -> str:
    """The notes for *version*, from their first ``## `` heading on.

    What comes before that heading (the title, the download links and the
    note on getting past Windows' installer checks) is for someone who has
    not installed yet, so it is left out. Notes with no ``## `` heading are
    returned whole. Returns ``""`` when no notes are bundled or they cannot
    be read.
    """
    try:
        text = release_notes_path(version).read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[i:]).strip()
    return text.strip()
