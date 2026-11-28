"""INI file merger for combining base and custom strings."""
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.ini_io import read_ini_text
from src.utils.perf import timed

# Component type codes used to canonicalize item_name*/item_desc* key variants.
# Hoisted to module scope so _get_canonical_key doesn't rebuild this list on
# each of its ~87k calls per merge. Kept as a tuple for both the C-level
# ``any(code in …)`` membership check and the sequential ``.replace()`` pass
# (order-sensitive by design — see the function comment).
_COMPONENT_CODES = ("shld", "powr", "cool", "qdrv", "jump", "misl", "gmisl", "bomb")


@timed
def merge_sources_by_hierarchy(
    sources_dict: Dict[str, Dict[str, str]],
    hierarchy: List[str],
    user_overrides: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Merge multiple INI sources in specified hierarchy order.

    Sources earlier in hierarchy have lower priority. Sources later in hierarchy
    overwrite earlier ones. User overrides (if provided) always have highest priority
    and are applied last.

    Syncs values across item_Name*/item_Desc* key variants (e.g.,
    item_Name_QDRV_RSI_S02_Hemera and item_nameQDRV_RSI_S02_Hemera_SCItem get
    the same value) — see sync_key_variants for why this is scoped to that
    namespace and not the whole table (#255).

    Args:
        sources_dict: Dictionary mapping source name to its key-value pairs.
                     e.g., {"global": {"key1": "val1", ...}, "contracts": {...}}
        hierarchy: Ordered list of source names to merge in order.
                  e.g., ["global", "contracts", "components"]
                  Earlier = lower priority, later = higher priority
        user_overrides: Optional dict of user edits (highest priority).
                       Applied last, overwrites all other sources.

    Returns:
        Merged dictionary with final values from all sources applied in order,
        with variant keys synced to have matching values.

    Example:
        >>> sources = {
        ...     "global": {"key1": "base_val", "key2": "val2"},
        ...     "contracts": {"key1": "override_val", "key3": "val3"},
        ...     "components": {"key4": "val4"}
        ... }
        >>> hierarchy = ["global", "contracts", "components"]
        >>> user = {"key1": "user_val"}
        >>> result = merge_sources_by_hierarchy(sources, hierarchy, user)
        >>> result["key1"]
        'user_val'  # User override always wins
        >>> result["key3"]
        'val3'      # From contracts (overrides global)
        >>> result["key2"]
        'val2'      # From global (only source for this key)
    """
    result: Dict[str, str] = {}

    # Process each source in hierarchy order
    # Earlier sources are base, later sources overwrite
    for source_name in hierarchy:
        if source_name not in sources_dict:
            continue

        source_data = sources_dict[source_name]
        for key, value in source_data.items():
            result[key] = value

    # Apply user overrides last (highest priority)
    if user_overrides:
        for key, value in user_overrides.items():
            result[key] = value

    # Sync values across key variants (e.g., item_Name_QDRV vs item_nameQDRV_SCItem).
    # Pass along which keys the user explicitly edited so a user's edit to a
    # variant never gets silently outvoted by a longer sibling value — see
    # sync_key_variants' docstring.
    sync_key_variants(result, user_edited_keys=set(user_overrides) if user_overrides else None)

    return result


@lru_cache(maxsize=None)
def _get_canonical_key(key: str) -> str:
    """Get the canonical form of a key for variant matching.

    Variant keys like:
      - item_Name_QDRV_RSI_S02_Hemera
      - item_nameQDRV_RSI_S02_Hemera_SCItem

    Both normalize to: item_name_qdrv_rsi_s02_hemera

    Steps:
    1. Remove _SCItem suffix (case-insensitive)
    2. Lowercase
    3. Remove underscores
    4. Insert underscores only before SHLD/POWR/COOL/QDRV/JUMP/MISL/GMISL/BOMB component codes

    Fast paths:
    - Cached via lru_cache — Load populates it, Apply reuses it for the
      same merged dict.
    - ~98% of keys in a real base.ini contain no component code at all, so
      the 8 sequential replaces + the split/join cleanup are skipped after
      the underscore strip. The remaining ~2% take the full canonicalization
      pass with identical semantics to the original (order-sensitive replace
      preserved).
    """
    # Remove _SCItem suffix (case-insensitive). Avoid the ``key.lower()`` call
    # on the happy path where the suffix isn't present by checking length +
    # the common uppercase variant first.
    if len(key) >= 7 and key[-7:].lower() == "_scitem":
        key = key[:-7]

    key = key.lower()
    key_no_underscore = key.replace("_", "")

    # Fast path: check for component codes AFTER underscore stripping — a code
    # can hide across an underscore boundary in the original (e.g.
    # ``powpow_reaction`` → after strip ``powpowreaction`` which contains
    # ``powr``). The happy path is ~98% of real keys; in that case the
    # sequential replace loop is a no-op and the final split/join is just an
    # identity on a string that has no remaining underscores.
    if not any(c in key_no_underscore for c in _COMPONENT_CODES):
        return key_no_underscore

    for comp in _COMPONENT_CODES:
        key_no_underscore = key_no_underscore.replace(comp, f"_{comp}")

    # Clean up: replace multiple underscores with single, strip leading underscore
    return "_".join(p for p in key_no_underscore.split("_") if p)


@timed
def sync_key_variants(
    merged_dict: Dict[str, str],
    user_edited_keys: Optional[set] = None,
) -> None:
    """Sync values across key variants in a merged dictionary.

    If item_Name_QDRV_RSI_S02_Hemera has value X, then
    item_nameQDRV_RSI_S02_Hemera_SCItem also gets value X.

    This modifies merged_dict in-place.

    Scoped to item_Name*/item_Desc* keys only (#255). Canonicalization
    strips ALL underscores and lowercases, which is exactly right for the
    ship-item naming quirks this function targets — but running it over
    every key in the ~90k-key table let two completely unrelated CIG loc
    keys collide by coincidence: ``Stanton2`` (the Crusader planet's name
    key) and ``Stanton_2`` (a different key, the star, holding "Stanton
    (Star)") both canonicalize to "stanton2". The longest-value tie-break
    then overwrote the planet's name with the star's. An audit of a real
    base.ini found 14 more live collisions of this shape (comm-array
    button text, a mission title, ship-interior area names, Options-menu
    turret labels, two different thruster names merged into one, …) —
    this was silently corrupting shipped content anywhere in the table,
    not just item names. The item_Name/item_Desc prefix is exactly the
    boundary every existing test case here already lives inside; nothing
    outside it was ever an intentional target of this sync.

    Args:
        merged_dict: Dictionary of keys to values from merged sources
        user_edited_keys: Keys the user explicitly edited (user.ini
            overrides), if any. This function runs *after* user overrides
            are applied in merge_sources_by_hierarchy, so without this a
            user's edit to a variant shorter than its sibling's stock value
            would get silently reverted on the very next merge — user
            overrides are supposed to "apply last and survive" (root
            CLAUDE.md, Merge hierarchy). A user-edited variant always wins
            over the longest-value heuristic below; when more than one
            variant of the same canonical key was user-edited, the longest
            of *those* wins (same tie-break as the no-override case — we
            have no ordering signal between two deliberate edits).
    """
    # Build a mapping of canonical → list of actual keys with that canonical
    # form, restricted to the item_Name*/item_Desc* namespace this sync is
    # actually for (#255) — any other key (locations, missions, UI labels,
    # options-menu strings, ...) is left completely untouched by this pass.
    canonical_keys: Dict[str, List[str]] = {}

    for key in list(merged_dict.keys()):
        if not key.lower().startswith(("item_name", "item_desc")):
            continue
        canonical = _get_canonical_key(key)
        if canonical not in canonical_keys:
            canonical_keys[canonical] = []
        canonical_keys[canonical].append(key)

    user_edited_keys = user_edited_keys or ()

    # For each canonical form with multiple variants, sync their values
    for canonical, variants in canonical_keys.items():
        if len(variants) > 1:
            # Prefer the longest value among ALL variants — no _SCItem
            # pre-filter. Stripping every underscore (and lowercasing) to
            # build the canonical form means two genuinely DIFFERENT CIG loc
            # keys can collapse onto the same canonical string even though
            # they hold different text — e.g. item_Name_SHLD_BEHR_S01_7SA
            # (fully tagged/enhanced) and item_NameSHLD_BEHR_S01_7sa (a
            # distinct, never-enhanced sibling CIG ships with just the bare
            # stock name) both canonicalize to "itemnameshldbehrs017sa".
            # Picking an arbitrary "first" variant let the short, unenhanced
            # sibling silently overwrite the correctly tagged one. A
            # non-_SCItem pre-filter doesn't work either: the Taiga cooler
            # case has item_NameCOOL_WCPR_S02_Taiga_SCItem holding the
            # correctly tagged value while its non-_SCItem sibling is the
            # bare one, so "prefer non-_SCItem" picks the wrong side there.
            # Comparing length across *all* variants with no pre-filter is a
            # no-op for the genuine same-entity variant case this function
            # targets (the generator's own sibling mirroring already gives
            # those matching values, so length ties and either wins).
            #
            # A user-edited variant is excluded from that "arbitrary first
            # duplicate" problem entirely — it's a deliberate choice, not a
            # data artifact — so it takes priority over the length heuristic.
            edited_variants = [v for v in variants if v in user_edited_keys]
            candidates = edited_variants or variants
            preferred_key = max(candidates, key=lambda v: len(merged_dict[v]))
            synced_value = merged_dict[preferred_key]

            # Apply this value to all variants
            for var in variants:
                merged_dict[var] = synced_value


@timed
def merge_ini_files(
    source_path: str | Path,
    overrides_dict: Dict[str, str],
    output_path: str | Path
) -> None:
    """Merge source INI with overrides, preserving all lines.

    Reads source file line-by-line, replaces values for matching keys,
    and writes to output as UTF-8 **with a BOM** (#261). Strips comma-based
    metadata suffixes (e.g., "key,P") from keys to match normalized
    override keys.

    Note: Variant key syncing happens in merge_sources_by_hierarchy(), so
    the overrides_dict already has synced values when this is called.

    Args:
        source_path: Path to base file (base.ini or game's global.ini)
        overrides_dict: Dictionary of key-value overrides (with clean keys, already synced)
        output_path: Path to write merged output
    """
    source_path = Path(source_path)
    output_path = Path(output_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # read_ini_text (#251) tolerates non-UTF-8 content — the previous
        # strict open() meant one corrupt byte in base.ini failed the whole
        # Apply to Game. It also strips a source BOM if present (Data.p4k's
        # own extracted base.ini has one) via its own utf-8-sig decode,
        # instead of leaking it into the first key's name. Normalize
        # newlines to match the old open() default (universal newlines
        # translated \r\n and \r to \n on read), then re-attach a trailing
        # \n per line like file iteration yielded.
        source_lines = (
            read_ini_text(source_path)
            .replace('\r\n', '\n').replace('\r', '\n')
            .split('\n')
        )
        # split('\n') yields one trailing '' when the file ends with a
        # newline — file iteration never yielded that empty last line.
        if source_lines and source_lines[-1] == '':
            trailing_newline = True
            source_lines.pop()
        else:
            trailing_newline = False

        # utf-8-sig on write (#261) WRITES a BOM — Star Citizen's own
        # loc-string loader appears to need it to reliably detect the
        # file's encoding; without it the game can fail to resolve every
        # key (shown as raw @KeyName placeholders) rather than degrading
        # per-key. Every prior release wrote plain utf-8 (no BOM) here; our
        # own readers are utf-8-sig-aware so they never noticed the
        # mismatch, but the game's own parser does — see
        # validate_applied_file's BOM check for the safety net half of
        # this fix.
        with open(output_path, 'w', encoding='utf-8-sig') as outfile:
            for i, line_rstrip in enumerate(source_lines):
                # Match the old per-line shape: every line ended with '\n'
                # except a final line with no trailing newline.
                is_last = i == len(source_lines) - 1
                original_ending = '\n' if (not is_last or trailing_newline) else ''
                line = line_rstrip + original_ending

                # Skip processing for comments and empty lines
                if not line_rstrip.strip() or line_rstrip.strip().startswith(';'):
                    outfile.write(line)
                    continue

                # Try to split on first '='
                if '=' not in line_rstrip:
                    outfile.write(line)
                    continue

                key, value = line_rstrip.split('=', 1)
                key_stripped = key.strip()

                # Strip comma-based metadata suffix (e.g., "key,P" → "key")
                # This ensures keys from different sources match up correctly
                clean_key = key_stripped.split(',')[0].strip()

                # Check if we have an override for this key (using clean key)
                if clean_key in overrides_dict:
                    # Replace value with override, using clean key without metadata
                    new_value = overrides_dict[clean_key]
                    new_line = f"{clean_key}={new_value}{original_ending}"
                    outfile.write(new_line)
                else:
                    # Keep original line (but with clean key, no metadata)
                    new_line = f"{clean_key}={value}{original_ending}"
                    outfile.write(new_line)

    except PermissionError:
        # Kept as it is so Apply to Game can tell a refused game folder (a
        # running game, Program Files, Controlled folder access) from a
        # merge bug and say what to try.
        raise
    except Exception as e:
        raise IOError(f"Error merging INI files: {e}")
