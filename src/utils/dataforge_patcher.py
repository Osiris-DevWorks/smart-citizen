"""Apply declarative JSON patches to DataForge-extracted XML files.

Background: Star Citizen's game data occasionally ships with bugs that affect
our localization enhancements — e.g. a Contract record whose Description param
points at the wrong loc-key. Rather than working around each bug downstream,
we patch the DataForge cache itself immediately after extraction, so every
downstream consumer (the enhancement generator, future tooling) sees corrected
data without needing to know.

Patches live under the repo's ``patches/`` directory, mirroring the DataForge
layout under ``dataforge/raw/libs/foundry/records/``. Each patch is a JSON
file with ``*.patch.json`` suffix describing the target file, a short
description, and a list of edits.

Example patch (patches/contracts/.../hockrowagency_facilitydelve.patch.json):

    {
      "target": "contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.xml",
      "description": "Fix P2M4_Repeat desc-key reference (CIG bug: points to P2M1's desc)",
      "edits": [
        {
          "xpath": ".//Contract[@debugName='Hockrow_FacilityDelve_P2M4-Stanton4_Repeat']//ContractStringParam[@param='Description']",
          "attribute": "value",
          "expected": "@Hockrow_FacilityDelve_P2M1_Repeat_desc",
          "set": "@Hockrow_FacilityDelve_P2M4_Repeat_desc"
        }
      ]
    }

Each edit asserts the current value matches ``expected`` before rewriting.
If it doesn't match, the edit is skipped with a warning — this protects
against CIG-side fixes (if they correct the bug upstream, our patch just
becomes a no-op instead of blindly overwriting the corrected value).

Patches are idempotent: if the target already holds ``set``, the edit is
skipped cleanly and not counted as a mismatch.

A patch file may also declare a ``locstring_workarounds`` list. Each entry
appends one loc key's value onto another — useful when CIG's bug is in a
contract's Description *pointer* (so the game looks up the wrong loc key at
runtime) and our XML edit only realigns the enhancement-generator's
bookkeeping. Merging the intended desc onto the loc key the game actually
reads makes the in-game display correct. See :class:`LocstringWorkaround`
and :func:`apply_locstring_workarounds`.
"""
from __future__ import annotations

import json
import logging
from lxml import etree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.utils.pak_extractor import DATAFORGE_RECORDS_SUBPATH
from src.utils.win_paths import win_long_path

logger = logging.getLogger(__name__)


@dataclass
class PatchReport:
    """Summary of a patch run. Use for logging and UI status."""
    patches_seen: int = 0
    files_rewritten: int = 0
    edits_applied: int = 0
    edits_idempotent: int = 0       # already at target value; no change needed
    edits_skipped_mismatch: int = 0  # current value != expected; skipped with warning
    edits_no_match: int = 0          # xpath found no element; skipped with warning
    errors: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        return (
            f"patched {self.edits_applied} / skipped-ok {self.edits_idempotent} / "
            f"skipped-mismatch {self.edits_skipped_mismatch} / no-match {self.edits_no_match} "
            f"across {self.files_rewritten}/{self.patches_seen} patch files"
        )


@dataclass
class LocstringWorkaround:
    """Append one loc-string's value onto another's.

    The XML edits in this module fix our local DataForge cache so the
    enhancement generator attaches the right blueprint/XP/reward data to the
    right desc key. They do NOT change what the game reads at runtime: Star
    Citizen resolves contract references against its own ``Data.p4k``, which
    still contains the bugged Title/Description pointer. A locstring
    workaround sidesteps that by merging the *intended* desc's content into
    the loc key the game actually looks up, so an in-game contract whose
    Description param points at the wrong key still displays the correct
    content.

    Loses nothing when the upstream bug is fixed — delete the workaround
    declaration (or the whole patch file) and the next regenerate produces
    clean split descs again.
    """
    target: str                # loc key whose value gets the append
    append_from: str           # loc key whose value is appended onto target
    separator: str = ""        # text inserted between target and appended
    description: str = ""      # for logs
    patch_source: str = ""     # source .patch.json filename, for logs


# DataForge XMLs live under {cache}/raw/libs/foundry/records/...
# (pak_extractor.DATAFORGE_RECORDS_SUBPATH) — patch targets are expressed
# relative to that records/ root.


def apply_patches(
    patch_root: Path,
    dataforge_cache_dir: Path,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> PatchReport:
    """Apply every ``*.patch.json`` under *patch_root* to XMLs in *dataforge_cache_dir*.

    Returns a :class:`PatchReport`. Does not raise on patch-level errors —
    individual failures are logged and recorded in the report so a bad patch
    doesn't block the rest.
    """
    report = PatchReport()
    if not patch_root.exists():
        logger.info(f"No patches directory at {patch_root}; skipping")
        return report

    # Wrap once here (not per patch file below) so every path derived from
    # records_root inherits long-path safety — see win_paths.win_long_path
    # (#221; this module hits the same 260-char MAX_PATH limit as
    # pak_extractor's copy/cleanup step).
    records_root = Path(win_long_path(dataforge_cache_dir / DATAFORGE_RECORDS_SUBPATH))
    if not records_root.exists():
        msg = f"DataForge records dir not found: {records_root}"
        logger.warning(msg)
        report.errors.append(msg)
        return report

    patch_files = sorted(patch_root.rglob("*.patch.json"))
    if not patch_files:
        logger.info(f"No patches found under {patch_root}")
        return report

    for patch_file in patch_files:
        report.patches_seen += 1
        try:
            _apply_single_patch(patch_file, records_root, report, progress_callback)
        except Exception as e:
            msg = f"Patch {patch_file.name} failed: {e}"
            logger.exception(msg)
            report.errors.append(msg)

    logger.info(f"DataForge patching complete — {report.summary_line()}")
    return report


def _apply_single_patch(
    patch_file: Path,
    records_root: Path,
    report: PatchReport,
    progress_callback: Optional[Callable[[str], None]],
) -> None:
    with patch_file.open(encoding="utf-8") as f:
        patch = json.load(f)

    target_rel = patch.get("target")
    edits = patch.get("edits", [])
    description = patch.get("description", "")
    if not target_rel or not edits:
        msg = f"Patch {patch_file.name} missing target or edits"
        logger.warning(msg)
        report.errors.append(msg)
        return

    # records_root is already long-path-prefixed (apply_patches wraps it
    # once at entry), so this join inherits long-path safety for free.
    target_path = records_root / target_rel
    if not target_path.exists():
        msg = f"Patch target missing: {target_rel}"
        logger.warning(msg)
        report.errors.append(msg)
        return

    # Keep UI progress short — just the file name, not the description.
    # The full description is logged separately for the Log Tab.
    if description:
        logger.info(f"Applying patch to {target_rel}: {description}")
    if progress_callback:
        progress_callback(f"Patching {Path(target_rel).name}")

    tree = ET.parse(str(target_path))
    root = tree.getroot()
    file_changed = False

    for edit in edits:
        outcome = _apply_edit(root, edit, patch_file.name)
        if outcome == "applied":
            report.edits_applied += 1
            file_changed = True
        elif outcome == "idempotent":
            report.edits_idempotent += 1
        elif outcome == "mismatch":
            report.edits_skipped_mismatch += 1
        elif outcome == "no_match":
            report.edits_no_match += 1

    if file_changed:
        # Preserve the original XML declaration Python's ElementTree emits by
        # default (short_empty_elements=True matches how unforge writes files).
        tree.write(str(target_path), encoding="utf-8", xml_declaration=True)
        report.files_rewritten += 1


def _apply_edit(root: ET.Element, edit: dict, patch_name: str) -> str:
    """Apply one edit. Returns one of: applied, idempotent, mismatch, no_match."""
    xpath = edit.get("xpath")
    attribute = edit.get("attribute")
    expected = edit.get("expected")
    new_value = edit.get("set")
    if xpath is None or attribute is None or new_value is None:
        logger.warning(f"[{patch_name}] edit missing xpath/attribute/set: {edit}")
        return "no_match"

    elements = root.findall(xpath)
    if not elements:
        logger.warning(
            f"[{patch_name}] xpath matched 0 elements (target may have shifted): {xpath}"
        )
        return "no_match"

    applied = False
    idempotent = False
    mismatch = False
    for element in elements:
        current = element.get(attribute)
        if current == new_value:
            idempotent = True
            continue
        if expected is not None and current != expected:
            logger.warning(
                f"[{patch_name}] expected {expected!r} at {xpath}[@{attribute}] "
                f"but found {current!r}; skipping (upstream may have changed)"
            )
            mismatch = True
            continue
        element.set(attribute, new_value)
        applied = True

    if applied:
        return "applied"
    if idempotent:
        return "idempotent"
    if mismatch:
        return "mismatch"
    return "no_match"


def load_locstring_workarounds(patch_root: Path) -> list[LocstringWorkaround]:
    """Scan ``*.patch.json`` files for ``locstring_workarounds`` declarations.

    Returns every valid workaround across all patch files, in file-sorted
    order. Malformed entries are logged and skipped; missing ``patches/``
    directory returns an empty list.
    """
    out: list[LocstringWorkaround] = []
    if not patch_root.exists():
        return out
    for patch_file in sorted(patch_root.rglob("*.patch.json")):
        try:
            with patch_file.open(encoding="utf-8") as f:
                patch = json.load(f)
        except (ValueError, OSError) as e:
            # ValueError covers both JSONDecodeError and UnicodeDecodeError
            # (a patch file with corrupt bytes — #251 bug class).
            logger.warning(f"Could not parse {patch_file.name}: {e}")
            continue
        for entry in patch.get("locstring_workarounds", []):
            target = entry.get("target")
            append_from = entry.get("append_from")
            if not target or not append_from:
                logger.warning(
                    f"[{patch_file.name}] locstring workaround missing target/append_from: {entry}"
                )
                continue
            out.append(LocstringWorkaround(
                target=target,
                append_from=append_from,
                separator=entry.get("separator", ""),
                description=entry.get("description", ""),
                patch_source=patch_file.name,
            ))
    return out


def apply_locstring_workarounds(
    entries: dict[str, str],
    workarounds: list[LocstringWorkaround],
) -> int:
    """Apply each workaround to *entries* in place. Returns count applied.

    Silently skips (with debug/warning logs) when:
    - ``target`` is not in *entries* — this workaround belongs to a
      different output dict; a caller trying every dict is fine.
    - ``append_from`` is not in *entries* — likewise, probably a different
      output dict. Logged at debug.
    - The target value already ends with ``separator + append_from_value``
      (idempotent; safe to re-run).
    """
    applied = 0
    for w in workarounds:
        if w.target not in entries:
            logger.debug(
                f"[{w.patch_source}] locstring workaround target {w.target!r} not in dict; skipping"
            )
            continue
        if w.append_from not in entries:
            logger.debug(
                f"[{w.patch_source}] locstring workaround source {w.append_from!r} not in dict; skipping"
            )
            continue
        from_text = entries[w.append_from]
        target_text = entries[w.target]
        suffix = w.separator + from_text
        if target_text.endswith(suffix):
            logger.debug(
                f"[{w.patch_source}] locstring workaround already applied to {w.target!r}"
            )
            continue
        entries[w.target] = target_text + suffix
        applied += 1
        logger.info(
            f"[{w.patch_source}] appended {w.append_from!r} onto {w.target!r} "
            f"({len(from_text):,} chars)"
        )
    return applied
