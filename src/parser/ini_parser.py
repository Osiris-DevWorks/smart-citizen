"""INI file parser for localization strings."""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from src.models.string_model import CATEGORY_MISSIONS, StringEntry
from src.merger.ini_merger import merge_sources_by_hierarchy
from src.utils.ini_io import read_ini_text
from src.utils.perf import timed

logger = logging.getLogger(__name__)


@timed
def parse_ini_file(path: str | Path, *, strip_values: bool = True) -> Dict[str, str]:
    """Parse INI file line-by-line, preserving efficiency.

    Strips any comma-based metadata suffix from keys (e.g., "key,P" → "key").
    This ensures keys from different sources (especially downloaded base.ini) are
    normalized and don't get written with unwanted suffixes.

    Args:
        path: Path to INI file
        strip_values: When True (default, for base.ini / enhancements) the
            value is whitespace-stripped. Pass False for ``user.ini`` so
            values round-trip verbatim — the favourite prefix can be a
            single space (the "invisible" sort-to-top marker), and stripping
            would silently delete it, dropping the favourite on reload
            (issue #100).

    Returns:
        Dictionary of key-value pairs
    """
    result = {}
    path = Path(path)

    if not path.exists():
        return result

    try:
        # split('\n') + rstrip('\r'), NOT str.splitlines(): splitlines also
        # breaks on U+2028/U+0085 etc., which a loc value could legitimately
        # contain — file iteration never split on those and neither do we.
        # read_ini_text (#251) tolerates non-UTF-8 content; the previous
        # strict streaming decode raised mid-iteration and the except below
        # silently truncated the result at the first bad byte.
        for line in read_ini_text(path).split('\n'):
            line = line.rstrip('\r')

            # Skip empty lines and comments
            if not line.strip() or line.strip().startswith(';'):
                continue

            # Split on first '=' only
            if '=' not in line:
                continue

            key, value = line.split('=', 1)
            key = key.strip()
            if strip_values:
                value = value.strip()

            if key:
                # Strip comma-based metadata suffix (e.g., "key,P" → "key")
                # This is used in some source files to track properties
                clean_key = key.split(',')[0].strip()
                if clean_key:
                    result[clean_key] = value
    except Exception as e:
        logger.warning(f"Error parsing INI file {path}: {e}")

    return result


@timed
def load_source_files(
    sources_dict: Dict[str, Dict[str, str]],
    hierarchy: List[str],
    user_overrides: Optional[Dict[str, str]] = None,
    custom_path: Optional[str | Path] = None,
    enhancements_key_categories: Optional[Dict[str, str]] = None,
) -> List[StringEntry]:
    """Load source files and build StringEntry list using hierarchy merge.

    Merges multiple sources in hierarchy order, then creates StringEntry objects.
    The original_value field contains the merged baseline. The custom_value field
    starts empty and will be populated when user edits in the UI.

    Args:
        sources_dict: Dictionary mapping source names to their key-value dicts.
                     e.g., {"global": {...}, "contracts": {...}, "components": {...}}
        hierarchy: Ordered list of source names to merge.
                  e.g., ["global", "contracts", "components"]
        user_overrides: Optional dict of pre-existing user edits to apply with highest priority.
                       Applied after all sources are merged.
        custom_path: DEPRECATED. Kept for backward compatibility. Use user_overrides instead.

    Returns:
        List of StringEntry objects with merged baseline values and user edits applied.
        custom_value will contain pre-existing edits if user_overrides provided.
    """
    entries = []

    # Handle legacy custom_path parameter
    if custom_path and not user_overrides:
        logger.info(f"Loading user overrides from legacy path: {custom_path}")
        user_overrides = parse_ini_file(custom_path, strip_values=False)

    logger.info(f"Starting merge of {sum(len(d) for d in sources_dict.values())} total keys from {len(sources_dict)} sources")
    logger.info(f"Hierarchy: {hierarchy}, Sources available: {list(sources_dict.keys())}")

    # Filter hierarchy to only include sources that exist in sources_dict
    filtered_hierarchy = [s for s in hierarchy if s in sources_dict]
    logger.info(f"Filtered hierarchy: {filtered_hierarchy}")

    # Filter each source to only include relevant keys based on source type
    from src.utils.settings import AppSettings

    filtered_sources = {}
    for source_name in filtered_hierarchy:
        source_data = sources_dict[source_name]

        # User source is special - never filter it (it's app-generated overrides)
        if source_name == AppSettings.SOURCE_USER:
            filtered_sources[source_name] = source_data
            continue

        # Map source types to their relevant categories
        source_category_filters = {
            AppSettings.SOURCE_GLOBAL: None,           # No filtering - load all
            "language": None,                           # No filtering - language overlay
            AppSettings.SOURCE_ENHANCEMENTS: None,      # No filtering
        }

        category_filter = source_category_filters.get(source_name)

        if category_filter:
            # Filter keys to only those matching the category
            filtered_data = {}
            for key, value in source_data.items():
                if StringEntry.extract_category(key) == category_filter:
                    filtered_data[key] = value
            logger.info(f"Filtered {source_name}: {len(source_data)} keys -> {len(filtered_data)} keys (category: {category_filter})")
            filtered_sources[source_name] = filtered_data
        else:
            # No filtering for this source
            filtered_sources[source_name] = source_data

    # Separate user overrides from the base merge so we can correctly populate
    # custom_value and original_value independently.
    # User data comes either from the explicit user_overrides param or sources_dict["user"].
    effective_user_overrides: Dict[str, str] = {}
    if user_overrides:
        effective_user_overrides = dict(user_overrides)
    elif AppSettings.SOURCE_USER in filtered_sources:
        effective_user_overrides = dict(filtered_sources[AppSettings.SOURCE_USER])

    # Build base-only hierarchy / sources (exclude user so original_value is the
    # pre-user-edit baseline, not the already-overridden value).
    base_hierarchy = [s for s in filtered_hierarchy if s != AppSettings.SOURCE_USER]
    base_sources = {k: v for k, v in filtered_sources.items() if k != AppSettings.SOURCE_USER}

    try:
        logger.info("Calling merge_sources_by_hierarchy (base only, no user)...")
        base_merged = merge_sources_by_hierarchy(base_sources, base_hierarchy, None)
        logger.info(f"Base merge complete. Result has {len(base_merged)} keys")
    except Exception as e:
        logger.exception(f"Error during merge: {e}")
        raise

    # Track which base source each key came from (for status of non-user entries)
    logger.info("Tracking source origin for each key...")
    source_origin: Dict[str, str] = {}
    for source_name in base_hierarchy:
        source_data = base_sources[source_name]
        for key in source_data.keys():
            source_origin[key] = source_name
    logger.info(f"Source origin tracking complete. {len(source_origin)} keys tracked")

    # Build the full key universe: all base keys + user-only "New" keys
    all_keys = set(base_merged.keys()) | set(effective_user_overrides.keys())

    # Create StringEntry for each key
    logger.info("Creating StringEntry objects...")
    base_source = base_hierarchy[0] if base_hierarchy else 'global'
    entry_count = 0
    for key in all_keys:
        # Skip abbreviated ship name entries (e.g. vehicle_Name*_short, vehicle_name*_short,P)
        if key.lower().startswith("vehicle_name") and "_short" in key:
            continue

        entry_count += 1
        if entry_count % 10000 == 0:
            logger.debug(f"Processing entry {entry_count} of ~{len(all_keys)}...")

        original_value = base_merged.get(key, '')
        custom_value = effective_user_overrides.get(key, '')

        # Determine status
        key_in_base = key in base_merged
        in_global_source = key in base_sources.get(base_source, {})
        if custom_value and key_in_base:
            status = 'Modified'
        else:
            source = source_origin.get(key, base_source)
            status = _determine_status_from_source(
                source, base_source,
                key_in_base=key_in_base,
                in_global_source=in_global_source,
            )

        source = source_origin.get(key, 'user' if key not in base_merged else base_source)

        # Determine category: source-based override first, then key-prefix fallback
        if source == 'contracts':
            category = CATEGORY_MISSIONS
        elif 'journal' in key.lower():
            category = 'Journal'
        elif enhancements_key_categories and key in enhancements_key_categories:
            category = enhancements_key_categories[key]
        else:
            category = StringEntry.extract_category(key)

        entry = StringEntry(
            key=key,
            source_file=source,
            category=category,
            original_value=original_value,
            custom_value=custom_value,
            status=status,
        )
        entries.append(entry)

    logger.info(f"Created {len(entries)} StringEntry objects successfully")
    return entries


@timed
def load_sources_from_settings() -> tuple[Dict[str, Dict[str, str]], List[str], Dict[str, str]]:
    """Load all sources from application settings.

    For remote URLs, loads from cached local files if available.
    For local paths, loads directly.
    Remote sources are downloaded asynchronously by the update checker, not here.

    Returns:
        Tuple of (sources_dict, hierarchy) where:
        - sources_dict: Dict mapping source names to key-value dicts
        - hierarchy: List of source names in merge order
    """
    from src.utils.settings import AppSettings

    sources_dict: Dict[str, Dict[str, str]] = {}
    hierarchy = AppSettings.get_merge_hierarchy()

    # Map source names to their cached file names in Documents cache
    cache_mapping = {
        AppSettings.SOURCE_GLOBAL:      "base.ini",
    }

    cache_dir = AppSettings.get_cache_dir()

    # Load each configured source
    logger.info(f"Loading sources from settings. Available sources: {AppSettings.AVAILABLE_SOURCES}")
    for source_name in AppSettings.AVAILABLE_SOURCES:
        if not AppSettings.is_source_enabled(source_name):
            logger.debug(f"Source {source_name} is disabled")
            continue

        source_path = AppSettings.get_source_path(source_name)
        if not source_path:
            logger.debug(f"Source {source_name} has no path configured")
            continue

        logger.info(f"Processing source {source_name}: {source_path}")

        try:
            # Handle URLs vs local files
            if source_path.startswith('http://') or source_path.startswith('https://'):
                # For remote sources, load from cached local file in AppData (must exist)
                if source_name in cache_mapping:
                    cache_file = cache_dir / cache_mapping[source_name]
                    logger.info(f"Looking for cache file: {cache_file}")

                    if cache_file.exists():
                        logger.info(f"Cache file found, parsing {source_name}...")
                        source_data = parse_ini_file(cache_file)
                        if source_data:
                            sources_dict[source_name] = source_data
                            logger.info(f"Loaded {len(source_data)} entries from {source_name}")
                        else:
                            logger.warning(f"Parsed {source_name} but got empty result")
                    else:
                        logger.error(f"Remote source {source_name} requires download. Cache not found: {cache_file}")
                        raise FileNotFoundError(f"Source {source_name} cache not found. Run auto-update to download: {cache_file}")
                continue

            # Local file path
            logger.info(f"Loading local file {source_path}...")
            local_file = Path(source_path)

            # User source can be empty on first run
            if source_name == AppSettings.SOURCE_USER:
                if local_file.exists():
                    # strip_values=False so a space favourite prefix survives (#100)
                    source_data = parse_ini_file(source_path, strip_values=False)
                    if source_data:
                        sources_dict[source_name] = source_data
                        logger.info(f"Loaded {len(source_data)} entries from {source_name}")
                    else:
                        logger.info(f"User overrides file is empty: {source_path}")
                else:
                    logger.info(f"No user overrides yet: {source_path}")
                continue

            # Other local sources must exist
            if not local_file.exists():
                logger.error(f"Local file not found: {source_path}")
                raise FileNotFoundError(f"Source {source_name} file not found: {source_path}")

            source_data = parse_ini_file(source_path)
            if source_data:
                sources_dict[source_name] = source_data
                logger.info(f"Loaded {len(source_data)} entries from {source_name}")
        except Exception as e:
            logger.exception(f"Failed to load source {source_name} from {source_path}: {e}")

    # ── Language overlay ─────────────────────────────────────────────────────
    # If a non-English language is selected, load its global.ini on top of the
    # English base so keys missing from the translation fall back to English.
    # The language source is inserted just before the user source (or at the
    # end of the base hierarchy if there is no user entry).
    _SOURCE_LANGUAGE = "language"
    selected_language = AppSettings.get_selected_language()
    if selected_language != AppSettings.DEFAULT_LANGUAGE:
        lang_path = AppSettings.get_language_global_ini_path(selected_language)
        if lang_path is not None:
            lang_data = parse_ini_file(lang_path)
            if lang_data:
                sources_dict[_SOURCE_LANGUAGE] = lang_data
                logger.info(
                    f"Loaded {len(lang_data)} entries from language overlay: {selected_language}"
                )
                if AppSettings.SOURCE_USER in hierarchy:
                    idx = hierarchy.index(AppSettings.SOURCE_USER)
                    hierarchy = hierarchy[:idx] + [_SOURCE_LANGUAGE] + hierarchy[idx:]
                else:
                    hierarchy = hierarchy + [_SOURCE_LANGUAGE]
            else:
                logger.warning(
                    f"Language overlay file for '{selected_language}' exists but parsed empty; "
                    f"falling back to English strings"
                )
        else:
            logger.warning(
                f"Language global.ini not found for '{selected_language}'; using English only"
            )

    # ── Enhancements ────────────────────────────────────────────────────────
    # Derived from AppSettings so adding a new enhancement type in ENHANCEMENT_CATEGORY_FILES
    # automatically produces a correct category here — no manual sync required.
    _ENHANCEMENTS_LABEL_CATEGORY = {
        file_label: AppSettings.ENHANCEMENT_LABELS[cat_key]
        for cat_key, file_labels in AppSettings.ENHANCEMENT_CATEGORY_FILES.items()
        for file_label in file_labels
        if cat_key in AppSettings.ENHANCEMENT_LABELS
    }
    enhancements_key_categories: Dict[str, str] = {}
    enabled_categories = AppSettings.get_enabled_enhancement_categories()
    if enabled_categories:
        # Enhancements live next to the active language's base.ini, so a
        # non-English language reads its own (language-prose + English stats)
        # files instead of the English ones bleeding through (#30, Approach 1).
        enhancements_dir = AppSettings.get_enhancements_dir(selected_language)
        enhancements_combined: Dict[str, str] = {}
        for label, filename in AppSettings.ENHANCEMENTS_FILES.items():
            if label not in enabled_categories:
                continue
            enhancements_file = enhancements_dir / filename
            if enhancements_file.exists():
                data = parse_ini_file(enhancements_file)
                category = _ENHANCEMENTS_LABEL_CATEGORY.get(label)
                if category:
                    for key in data:
                        enhancements_key_categories[key] = category
                else:
                    logger.warning(
                        f"Enhancement label {label!r} has no category mapping — "
                        "add it to AppSettings.ENHANCEMENT_CATEGORY_FILES"
                    )
                enhancements_combined.update(data)
                logger.info(f"Loaded {len(data)} enhancement entries from {filename}")
            else:
                logger.debug(f"Enhancements file not found (skipping): {enhancements_file}")

        if enhancements_combined:
            sources_dict[AppSettings.SOURCE_ENHANCEMENTS] = enhancements_combined
            logger.info(f"Enhancements: {len(enhancements_combined)} total entries loaded")
            # Insert "enhancements" just before "user" in the hierarchy (or at end if no user)
            if AppSettings.SOURCE_USER in hierarchy:
                idx = hierarchy.index(AppSettings.SOURCE_USER)
                hierarchy = hierarchy[:idx] + [AppSettings.SOURCE_ENHANCEMENTS] + hierarchy[idx:]
            else:
                hierarchy = hierarchy + [AppSettings.SOURCE_ENHANCEMENTS]

    logger.info(f"load_sources_from_settings complete. Loaded sources: {list(sources_dict.keys())}")
    return sources_dict, hierarchy, enhancements_key_categories


@timed
def load_overrides(target_path: str | Path) -> Dict[str, str]:
    """Load override strings from target_strings.ini.

    Args:
        target_path: Path to target_strings.ini

    Returns:
        Dictionary of overrides
    """
    # strip_values=False: user.ini values round-trip verbatim so a space
    # favourite prefix is not silently stripped away on reload (#100).
    return parse_ini_file(target_path, strip_values=False)


def _determine_status(original_value: str, custom_value: str) -> str:
    """Determine status of an entry (legacy, kept for compatibility)."""
    if not custom_value:
        return 'Unmodified'
    if custom_value != original_value:
        return 'Modified'
    return 'Unmodified'


def _determine_status_from_source(
    source_name: str, base_source: str, *,
    key_in_base: bool, in_global_source: bool = True,
) -> str:
    """Determine status based on which source provided the value.

    Args:
        source_name: Name of the source that provided this value
        base_source: Name of the base source (usually 'global')
        key_in_base: Whether the key exists in the merged base (i.e. in
            base.ini or a non-user source). False means the key was
            added by the user and has no base value.
        in_global_source: Whether the key exists in the stock base
            source (e.g. base.ini). False when the key was discovered
            from DataForge XML via the enhancements pipeline and has
            no entry in the global source.

    Returns:
        One of:
        - 'New': key absent from the stock base — either XML-discovered
          via the enhancements pipeline or user-added
        - 'Modified': user explicitly customized this value
        - 'Enhanced': Smart Citizen's enhancements pipeline produced
          this value (ship stats, mission rewards, etc.) without user
          intervention. Distinct from 'Modified' so the user can see
          at a glance what they changed vs. what the app generated.
        - 'Unmodified': from the stock base source (global), unchanged
        - 'Modified' (fallback): some other higher-priority source
          overrode the base — kept generic since this branch is rare
          post-1.0 (the four URL-based sources retired in 0.7.0).
    """
    from src.utils.settings import AppSettings

    if not key_in_base:
        return 'New'  # Not in any base source — user-added
    if not in_global_source:
        return 'New'  # Only in enhancements, not in stock base — XML-discovered
    if source_name == AppSettings.SOURCE_USER:
        return 'Modified'  # User explicitly customized
    if source_name == AppSettings.SOURCE_ENHANCEMENTS:
        return 'Enhanced'  # Generated by Smart Citizen's enhancement pipeline
    if source_name == base_source:
        return 'Unmodified'  # From base, not overridden
    return 'Modified'  # Overridden by higher-priority source
