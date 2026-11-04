"""Dynamic tag builder for enhancement name annotations.

Used by both the enhancement generator (CLI / worker thread) and the
Enhancements tab live preview, so it must be pure Python with no Qt
dependency. A `TagConfig` describes one category's tag (element order,
per-element style, separator, enclosing brackets, and the class-variant
mapping when applicable); `render_tag()` produces the final bracketed
string given that config plus a values dict.

Defaults in DEFAULT_TAG_CONFIGS are calibrated to match the previously
hardcoded format strings byte-for-byte so an existing user sees no
change in their generated INIs until they edit a config.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Category + element vocabulary ─────────────────────────────────────────────

CATEGORIES = ("components", "missiles", "ship_weapons", "commodities", "mission_titles", "armor")

# Which element kinds each category supports — order here is the *default*
# order shown in the UI before the user reorders. Each kind maps to a value
# key in the values-dict passed to render_tag. ``mission_titles`` is special:
# it carries a single ``route`` element that acts as the feature's on/off
# toggle; its formatting is driven by the route_* config fields, not by
# element styles/mappings (see render_route / apply_mission_title).
CATEGORY_ELEMENT_KINDS: dict[str, tuple[str, ...]] = {
    "components":   ("class", "size", "grade", "type"),
    "missiles":     ("ordinance", "size"),
    "ship_weapons": ("damage", "size"),
    "commodities":  ("label", "usage", "collection"),
    "mission_titles": ("route",),
    "armor":        ("weight",),
}



# ── Style tables ──────────────────────────────────────────────────────────────
# Each entry is (style_key, human_label). The order here drives the dropdown
# option order; the first entry is what `DEFAULT_TAG_CONFIGS` selects unless
# the default config overrides.

STYLES_CLASS: tuple[tuple[str, str], ...] = (
    ("short", "Short (M)"),
    ("med",   "Medium (MIL)"),
    ("long",  "Long (Military)"),
)
STYLES_SIZE: tuple[tuple[str, str], ...] = (
    ("n",      "Number (2)"),
    ("sn",     "S-prefixed (S2)"),
    ("size_n", "Verbose (Size 2)"),
)
STYLES_GRADE: tuple[tuple[str, str], ...] = (
    ("letter",       "Letter (A)"),
    ("grade_letter", "Verbose (Grade A)"),
)
STYLES_ORDINANCE: tuple[tuple[str, str], ...] = (
    ("short", "Short (I)"),
    ("med",   "Medium (IR)"),
    ("long",  "Long (Infrared)"),
)
STYLES_DAMAGE: tuple[tuple[str, str], ...] = (
    ("short", "Short (E)"),
    ("med",   "Medium (EN)"),
    ("long",  "Long (Energy)"),
)
STYLES_TYPE: tuple[tuple[str, str], ...] = (
    ("short", "Short (SH)"),
    ("med",   "Medium (SHLD)"),
    ("long",  "Long (Shield)"),
)
STYLES_LABEL: tuple[tuple[str, str], ...] = (
    ("short", "Short (CF)"),
    ("med",   "Medium (Craft)"),
    ("long",  "Long (Crafting)"),
)
STYLES_COLLECTION: tuple[tuple[str, str], ...] = (
    ("short", "Short (Col)"),
    ("med",   "Medium (Collect)"),
    ("long",  "Long (Collection)"),
)
STYLES_USAGE: tuple[tuple[str, str], ...] = (
    ("short", "Short (Q)"),
    ("med",   "Medium (QD)"),
    ("long",  "Long (QDRV)"),
)
STYLES_WEIGHT: tuple[tuple[str, str], ...] = (
    ("short", "Short (H)"),
    ("med",   "Medium (HV)"),
    ("long",  "Long (Heavy)"),
)

STYLES_BY_KIND: dict[str, tuple[tuple[str, str], ...]] = {
    "class":      STYLES_CLASS,
    "size":       STYLES_SIZE,
    "grade":      STYLES_GRADE,
    "ordinance":  STYLES_ORDINANCE,
    "damage":     STYLES_DAMAGE,
    "type":       STYLES_TYPE,
    "label":      STYLES_LABEL,
    "collection": STYLES_COLLECTION,
    "usage":      STYLES_USAGE,
    "weight":     STYLES_WEIGHT,
}

# Human-friendly element kind labels for the UI.
ELEMENT_LABELS: dict[str, str] = {
    "class":     "Class",
    "size":      "Size",
    "grade":     "Grade",
    "ordinance": "Ordinance",
    "damage":    "Damage type",
    "type":       "Type",
    "label":      "Label",
    "usage":      "Used To Craft",
    "collection": "Collection",
    "weight":     "Weight",
    "route":      "Route",
}


# ── Separator + enclosing tables ─────────────────────────────────────────────

# (key, label, render_string)
SEPARATORS: tuple[tuple[str, str, str], ...] = (
    ("none",       "None",        ""),
    ("space",      "Space",       " "),
    ("hyphen",     "Hyphen ( - )", "-"),
    ("underscore", "Underscore ( _ )", "_"),
    ("dot",        "Period ( . )", "."),
    ("slash",      "Slash ( / )", "/"),
    ("pipe",       "Pipe ( | )",  "|"),
)

# (key, label, open, close)
ENCLOSINGS: tuple[tuple[str, str, str, str], ...] = (
    ("none",   "None (space only)", "",  ""),
    ("square", "Square [ ]",        "[", "]"),
    ("round",  "Round ( )",         "(", ")"),
    ("curly",  "Curly { }",         "{", "}"),
    ("angle",  "Angle < >",         "<", ">"),
)

_SEPARATOR_BY_KEY = {k: s for k, _, s in SEPARATORS}
_ENCLOSING_BY_KEY = {k: (o, c) for k, _, o, c in ENCLOSINGS}

# Categories that cannot use the "None (space only)" enclosing (#492). An
# armor tag is a single word ("H Field Recon Suit Arms"), and without brackets
# the Blueprint Tracker could not strip it back off a blueprint name read from
# Game.log, so Owned tracking would break. The Armor tab does not offer None,
# and a stored "none" reads as Square (AppSettings.get_tag_config, and the
# generator for hand-edited configs). A known limitation, not an oversight.
NO_NONE_ENCLOSING_CATEGORIES: frozenset[str] = frozenset({"armor"})


def enclosings_for(category: str) -> tuple[tuple[str, str, str, str], ...]:
    """The ENCLOSINGS the Tag Builder offers for *category*: all of them,
    minus "none" for the categories in NO_NONE_ENCLOSING_CATEGORIES."""
    if category not in NO_NONE_ENCLOSING_CATEGORIES:
        return ENCLOSINGS
    return tuple(e for e in ENCLOSINGS if e[0] != "none")

# ── Mission-title route tables (#166 successor) ──────────────────────────────

# The joiner rendered between origin and destination in an A→B route.
# (key, label, render_string)
ROUTE_ARROWS: tuple[tuple[str, str, str], ...] = (
    ("gt",    "Greater-than ( > )", ">"),
    # "->" not "→": mobiGlas has no glyph for U+2192 and draws a box (#200).
    ("arrow", "Arrow ( -> )",  "->"),
    ("to",    "Word ( to )",        "to"),
    # Shape-encoding arrow (#200 follow-up): each side is "-" for one endpoint
    # and "=" for several, so the glyph carries the route shape (->- one to
    # one, ->= one to many, =>- many to one, =>= many to many). The render
    # string below is the 1:1 fallback; render_route builds the real glyph
    # from the endpoint counts. Only characters proven to render in mobiGlas.
    ("shape", "Route shape ( ->- / ->= / =>- / =>= )", "->-"),
)
# The separator between the route and the original title (prepend/append).
# (key, label, render_string) — spaces are part of the render string.
TITLE_SEPARATORS: tuple[tuple[str, str, str], ...] = (
    ("dash",  "Dash ( - )",  " - "),
    ("pipe",  "Pipe ( | )",  " | "),
    ("colon", "Colon ( : )", ": "),
    ("space", "Space",       " "),
)
# How much of a location the route shows — the only game-backed lever
# (‘name’ = ~mission(...|name), ‘address’ = ~mission(...|Address)). "address"
# listed first — it's the default (dropdown order should put the default on
# top so it's the first thing a user sees).
LOCATION_DETAILS: tuple[tuple[str, str], ...] = (
    ("address", "Full address"),
    ("name",    "Name"),
)
# Placement options for the mission-title route (prepend/append/replace). Kept
# separate from PLACEMENTS (which other tabs use) because "replace" only makes
# sense for a whole title, never for a component name tag. "append" listed
# first — it's the default.
MISSION_TITLE_PLACEMENTS: tuple[tuple[str, str], ...] = (
    ("append",  "After title"),
    ("prepend", "Before title"),
    ("replace", "Replace title"),
)

_ROUTE_ARROW_BY_KEY = {k: s for k, _, s in ROUTE_ARROWS}
_TITLE_SEP_BY_KEY = {k: s for k, _, s in TITLE_SEPARATORS}

# Curated phrase toggles that SHORTEN a specific stock phrase to something
# shorter (#200 follow-up, generalized to per-phrase checkboxes). Applied to
# the LITERAL text of stock hauling titles; ~mission(...) tokens are never
# touched — these phrases all contain a space, which never appears inside a
# token (e.g. "CargoGradeToken" has no space). Each entry:
# (key, label, phrase, replacement). Unmapped titles pass through unchanged,
# so a new CIG title can never break.
SHORTEN_PHRASE_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("intro", 'Shorten "Opportunity for Independent Cargo Hauler" to "Intro"',
     "Opportunity for Independent Cargo Hauler", "Intro"),
    # "-" here is a fallback only — abbreviate_title() overrides it with the
    # live rank_separator at render time (see the special-case there).
    ("hauler_needed_for", 'Shorten "Hauler Needed for" to the Rank separator',
     "Hauler Needed for", "-"),
    ("local_shipment_route", 'Shorten "Local Shipment Route" to "Route"',
     "Local Shipment Route", "Route"),
    # Ling Family haul titles ("Ling Family ~mission(ReputationRank) Cargo
    # Haul - ...") put "Cargo" directly after the rank token with no "Rank"
    # word and no separator at all — a third stock phrasing distinct from
    # both the dash/comma RANK_TRIGGERS and "Hauler Needed for". Fallback
    # text here is unused — abbreviate_title() overrides it with the live
    # word + rank_separator at render time (see the special-case there).
    ("ling_family_rank", 'Add the Rank separator to Ling Family haul titles',
     "~mission(ReputationRank) Cargo", "~mission(ReputationRank) Rank Cargo"),
    ("ling_family_prefix", 'Shorten "Ling Family" by removing it',
     "Ling Family ", ""),
)

# Curated word toggles that REMOVE a word outright rather than shortening a
# phrase. "cargo"/"haul" use \b-bounded regex so a bare word can't match
# mid-token (e.g. "Cargo" has no boundary before the "G" in
# "CargoGradeToken"). "rank" is handled separately below (see RANK_TRIGGERS)
# since its removal is context-sensitive, but shares this same key/label/
# phrase/replacement shape for a uniform checkbox list in the UI.
REMOVE_WORD_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("cargo", 'Remove "Cargo"', "Cargo", ""),
    ("haul", 'Remove "Haul"', "Haul", ""),
    ("rank", 'Remove "Rank"', "", ""),  # phrase/replacement unused — see RANK_TRIGGERS
)

# Word transform (not a removal) that wraps "Direct" in EM3 emphasis and
# uppercases it, so direct (single pickup/drop-off) hauls stand out in the
# contract list. Same key/label/phrase/replacement shape as the option
# tables above so it plugs into the same abbreviate_title() loop and UI
# checkbox mechanism; \b-bounded like "cargo"/"haul" for the same
# token-safety reason.
UNDERLINE_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    # Label is UI-facing and deliberately doesn't expose the raw <EM3> tag
    # syntax — the UI renders the effect as an actual underline instead.
    ("underline_direct", 'Underline "Direct"', "Direct", "<EM3>DIRECT</EM3>"),
)

# The two known literal contexts where "Rank" appears in stock titles,
# distinguished by the punctuation CIG's text uses right after it (leading
# space protects tokens like "~mission(ReputationRank)", which has no space
# before "Rank"). Both share the single "rank" checkbox; the punctuation
# itself always re-renders per `TagConfig.rank_separator` regardless of
# whether "Rank" is removed (see `abbreviate_title`).
RANK_TRIGGERS: tuple[str, ...] = (" Rank -", " Rank,")

# Separator rendered after the "Rank" position, independent of whether Rank
# itself was removed. Aliased to TITLE_SEPARATORS rather than a second copy
# of the same four options (dash listed first — it's the default) so the
# two option sets can't drift apart; "space" collapses to the same visible
# result a dedicated "none" option would after whitespace normalization, so
# there's no need for a separate "none" entry either.
# tests/test_mission_title_tag.py::test_rank_separator_matches_title_separator_options
# locks the alias.
RANK_SEPARATORS = TITLE_SEPARATORS
_RANK_SEP_BY_KEY = {k: s for k, _, s in RANK_SEPARATORS}

# "Standardize hauling mission names" (top-of-page toggle, separate from the
# per-word/phrase checkboxes): rewrites a stock haul title into ONE canonical
# shape instead of shortening whatever CIG happened to write. Only titles
# carrying BOTH tokens below are eligible — the procedural Covalex/DeadSaints/
# RedWind/Ling Family archetypes. Fixed one-off titles (region-link specials,
# GoblinG's resource-drive chain, intro/rehire text) have no rank or size to
# build a template from, so they pass through untouched.
_HAUL_RANK_TOKEN = "~mission(ReputationRank)"
_HAUL_SIZE_TOKEN = "~mission(CargoGradeToken)"
_HAUL_DIRECT_RE = re.compile(r"\bDirect\b")
_HAUL_CIRCUIT_RE = re.compile(r"\bCircuit\b")


def _standardize_hauling_title(title: str, remove_rank: bool, sep: str) -> str:
    """Rewrite *title* into the canonical "Rank <sep> [Direct] Size Cargo
    Haul [Circuit]" shape when it carries both the rank and size tokens.

    Ignores whatever wording/order/company-prefix the stock title used
    (e.g. Ling Family's "Ling Family Rank Size Cargo - Size Scale" or
    RedWind's "Rank Hauler Needed for Size Shipment") and rebuilds from
    scratch, preserving only the Direct/Circuit flags detected in the
    original text. `remove_rank` mirrors the same "rank" checkbox the
    RANK_TRIGGERS block below honors, so Standardize composes with it
    instead of always forcing the word "Rank" in.
    """
    if _HAUL_RANK_TOKEN not in title or _HAUL_SIZE_TOKEN not in title:
        return title
    direct = "Direct " if _HAUL_DIRECT_RE.search(title) else ""
    circuit = " Circuit" if _HAUL_CIRCUIT_RE.search(title) else ""
    word = "" if remove_rank else "Rank"
    return (
        f"{_HAUL_RANK_TOKEN} {word}{sep} {direct}{_HAUL_SIZE_TOKEN} "
        f"Cargo Haul{circuit}"
    )


# Keys covered by the legacy `abbreviate_title: true` bool migration — scoped
# to the original shortening feature only. UNDERLINE_OPTIONS is a distinct,
# newer feature and deliberately excluded so upgrading users don't get a
# visual change (EM3 emphasis) they never opted into.
_LEGACY_MIGRATION_KEYS: frozenset[str] = (
    frozenset(k for k, *_ in SHORTEN_PHRASE_OPTIONS)
    | frozenset(k for k, *_ in REMOVE_WORD_OPTIONS)
)

# All valid keys for TagConfig.abbreviated_phrases — used to filter stale
# entries out of persisted config.
_ABBREVIATION_OPTION_KEYS: frozenset[str] = (
    _LEGACY_MIGRATION_KEYS | frozenset(k for k, *_ in UNDERLINE_OPTIONS)
)


# Cargo-grade size words → abbreviations, each independently selectable via
# its own dropdown (None / the preset abbreviation) rather than a single
# bundled toggle. The ~mission(CargoGradeToken) title token resolves through
# the HaulCargo_CargoGrade_* / HaulCargo_CargoScale_* loc keys, so the
# generator overrides those VALUES (exact match only; an unmapped grade passes
# through untouched). Ordered longest-first for literal-text use (preview).
SIZE_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("Extra Small", "XS"),
    ("Extra Large", "XL"),
    ("Small", "S"),
    ("Medium", "M"),
    ("Large", "L"),
)
SIZE_ABBREV_BY_WORD: dict[str, str] = dict(SIZE_ABBREVIATIONS)
_SIZE_WORDS: frozenset[str] = frozenset(SIZE_ABBREV_BY_WORD)


def _replace_word(text: str, word: str, replacement: str) -> str:
    """Replace *word* with *replacement*, \\b-bounded so it can't match
    inside a longer token (e.g. "Cargo" must not match "CargoGradeToken")."""
    return re.sub(rf"\b{re.escape(word)}\b", replacement, text)


def abbreviate_title(title: str, enabled: frozenset[str] = frozenset(),
                      rank_separator: str = "dash",
                      standardize_hauling: bool = False) -> str:
    """Shorten a stock mission title per the *enabled* option keys.

    Each `SHORTEN_PHRASE_OPTIONS` / `REMOVE_WORD_OPTIONS` entry (other than
    "rank") applies only when its key is in *enabled*. The `RANK_TRIGGERS`
    contexts are handled separately and UNCONDITIONALLY on *enabled* — the
    punctuation after "Rank" always re-renders as `rank_separator` on its
    own, whether or not any checkbox is ticked (only the word "Rank" itself
    is conditional on the shared "rank" key). Plain literal / word-boundary
    replacement plus whitespace collapse and a trailing-separator trim (a
    removed phrase can leave a dangling " -"); game tokens pass through
    untouched. Single source for the generator and the tab preview.

    `standardize_hauling` runs FIRST, ahead of every other option — it's a
    template rewrite (see `_standardize_hauling_title`), not a shorten/
    remove pass, so the word/phrase checkboxes below still apply on top of
    its output (e.g. "Remove Cargo" still strips "Cargo" from the freshly
    standardized text).
    """
    out = title
    sep = _RANK_SEP_BY_KEY.get(rank_separator, "")
    remove_rank = "rank" in enabled
    if standardize_hauling:
        out = _standardize_hauling_title(out, remove_rank, sep)
    for key, _label, phrase, short in (*SHORTEN_PHRASE_OPTIONS, *REMOVE_WORD_OPTIONS, *UNDERLINE_OPTIONS):
        if key not in enabled or key == "rank":
            continue
        if key == "hauler_needed_for":
            # CIG's "Hauler Needed for" phrasing (RedWind haul titles) sits
            # in the exact same slot as the literal " Rank -"/" Rank,"
            # triggers below — a separator between the reputation rank and
            # the mission subject — but never spells out the word "Rank"
            # itself. Render it the same way those triggers do: keep the
            # word "Rank" (so "Rookie" reads as "Rookie Rank", matching
            # every other haul title) unless the shared "rank" removal
            # checkbox is also on, then track rank_separator either way
            # instead of the fixed dash the option used to hardcode
            # (whitespace collapse below absorbs the extra padding).
            short = sep if remove_rank else f"Rank{sep}"
        elif key == "ling_family_rank":
            # Ling Family haul titles put "Cargo" directly after the rank
            # token with no "Rank" word and no separator at all — insert
            # both here the same way the dash/comma RANK_TRIGGERS do,
            # anchored on the literal token text since there's no existing
            # word/punctuation to key off of.
            word = "" if remove_rank else "Rank"
            fragment = f" {word}{sep}" if word else f" {sep}"
            short = f"~mission(ReputationRank){fragment}Cargo"
        out = out.replace(phrase, short) if " " in phrase else _replace_word(out, phrase, short)

    for trigger in RANK_TRIGGERS:
        if trigger not in out:
            continue
        word = "" if remove_rank else "Rank"
        fragment = f" {word}{sep}" if word else f" {sep}"
        out = out.replace(trigger, fragment)

    return " ".join(out.split()).rstrip(" -,|:")


# ── Built-in class/ordinance/damage variant mappings ─────────────────────────
# Tuple order is (short, med, long). Categories with only short/long
# (e.g. missiles) repeat the value in the unused slot.

DEFAULT_COMPONENT_CLASS_MAPPING: dict[str, tuple[str, str, str]] = {
    "Competition": ("R", "CMP", "Competition"),
    "Military":    ("M", "MIL", "Military"),
    "Civilian":    ("C", "CIV", "Civilian"),
    "Industrial":  ("I", "IND", "Industrial"),
    "Stealth":     ("S", "STH", "Stealth"),
}

# Missile ordinance: (short=1 char, med=2 chars, long=full word). Bomb's
# canonical shorthand is a single "B" at every length — duplicating it in
# all three slots matches what users expect to see in-game.
DEFAULT_MISSILE_ORDINANCE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Infrared":        ("I", "IR", "Infrared"),
    "Electromagnetic": ("E", "EM", "Electromagnetic"),
    "CrossSection":    ("C", "CS", "CrossSection"),
    "Bomb":            ("B", "B",  "Bomb"),
}

# Keys are the full English damage names users see in the mapping editor.
# The ship-weapon tagger (_ship_weapon_name_tag_factory in
# scripts/generate_enhancements_ini.py) translates the generator's compact
# labels ("Phys", "Distort", "Bio") into these full forms before passing
# the value into render_tag, via DAMAGE_LABEL_TO_MAPPING_KEY below.
DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Energy":      ("E", "EN",  "Energy"),
    "Physical":    ("P", "PHY", "Physical"),
    "Distortion":  ("D", "DIS", "Distortion"),
    "Thermal":     ("T", "THM", "Thermal"),
    "Biochemical": ("B", "BIO", "Biochemical"),
    "Stun":        ("S", "STN", "Stun"),
}

# Compact label (as emitted by _DAMAGE_LABELS in generate_enhancements_ini.py)
# → full English name used as the mapping key. The generator uses short
# labels in description text ("Alpha Dmg: 5.0 (Phys)") for compactness;
# the tag mapping uses the full word so the variant editor reads naturally.
DAMAGE_LABEL_TO_MAPPING_KEY: dict[str, str] = {
    "Phys":    "Physical",
    "Distort": "Distortion",
    "Bio":     "Biochemical",
    # Energy / Thermal / Stun already match between compact and full forms.
}

DEFAULT_COMPONENT_TYPE_MAPPING: dict[str, tuple[str, str, str]] = {
    "Shield Generator": ("SH",  "SHLD", "Shield"),
    "Cooler":           ("CL",  "COOL", "Cooler"),
    "Power Plant":      ("PW",  "POWR", "Power"),
    "Quantum Drive":    ("QD",  "QDRV", "Quantum"),
    "Radar":            ("RD",  "RADR", "Radar"),
    # #266: components with no Class:/Size:/Grade: of their own, tagged via
    # the Type-only fallback (see enhancements_bare_type_tags in
    # generate_enhancements_ini.py) when the user has Type enabled. Same
    # opt-in gate as every other entry here -- not force-shown just because
    # they'd otherwise have no other tag; a user who leaves Type off simply
    # gets these items bare, same as Shield Generator or Cooler.
    "Fuel Nozzle":      ("FN",  "FNoz", "Fuel Nozzle"),
    # #266: mining lasers live in ships/weapons/ (routed through
    # _ship_weapon_name_tag_factory) but aren't combat weapons -- no
    # resolvable damage type, so they're tagged as a component Type+Size
    # instead of the ship-weapon damage-keyed style.
    "Mining Laser":     ("ML",  "MineL", "Mining Laser"),
}

DEFAULT_COMMODITY_LABEL_MAPPING: dict[str, tuple[str, str, str]] = {
    "Crafting": ("CF", "Craft", "Crafting"),
}

# Collection-mission item flag. Combined with the crafting flag inside one
# <EM4>[…]</EM4> wrapper (e.g. "[CF|Collection]") when an item is both (#97).
DEFAULT_COMMODITY_COLLECTION_MAPPING: dict[str, tuple[str, str, str]] = {
    "Collection": ("Col", "Collect", "Collection"),
}

# Craft-usage categories: the item groups a commodity's crafting materials feed
# into (the "usage" element between CF and Collection). Single source of truth
# for the category name, its (short, med, long) codes, and its legend group —
# shared by the tag mapping AND the generator's raw-path classifier
# (_craft_usage_key) so the two can't drift when CIG adds a category. The name
# is the mapping key, so the classifier MUST return these exact strings or
# _style_value would surface the raw name unstyled.
CRAFT_USAGE_CATEGORIES: tuple[tuple[str, str, str, str, str], ...] = (
    # (name, short, med, long, legend group)
    ("Power Plant",              "P",  "PP",  "POWR", "Ship Components"),
    ("Cooler",                   "C",  "CL",  "COOL", "Ship Components"),
    ("Shield",                   "S",  "SH",  "SHLD", "Ship Components"),
    ("Radar",                    "R",  "RD",  "RADR", "Ship Components"),
    ("Quantum Drive",            "Q",  "QD",  "QDRV", "Ship Components"),
    ("Mining Laser",             "M",  "ML",  "MINE", "Ship Components"),
    ("Tractor Beam",             "T",  "TB",  "TRAC", "Ship Components"),
    ("Salvage Module",           "SV", "SLV", "SALV", "Ship Components"),
    ("Refuel Nozzle",            "F",  "RF",  "FUEL", "Ship Components"),
    ("Ship Weapon (Ballistic)",  "B",  "BW",  "BGUN", "Ship Components"),
    ("Ship Weapon (Energy)",     "E",  "EW",  "EGUN", "Ship Components"),
    ("Ship Weapon (Distortion)", "D",  "DW",  "DGUN", "Ship Components"),
    ("FPS Weapon",               "G",  "FW",  "FPSW", "FPS Gear"),
    ("Ammo",                     "A",  "AM",  "AMMO", "FPS Gear"),
    ("Armor",                    "AR", "ARM", "ARMR", "FPS Gear"),
    ("Mission Item",             "MI", "MIT", "MITM", "Other"),
)

DEFAULT_COMMODITY_USAGE_MAPPING: dict[str, tuple[str, str, str]] = {
    name: (short, med, long) for name, short, med, long, _group in CRAFT_USAGE_CATEGORIES
}

# FPS armor weight class (#492). Keys are the class names the generator's
# _armor_weight() resolves an item to: Light/Medium/Heavy/Super Heavy come
# from the stock "Item Type:" line (or the AttachDef SubType when the
# description has none), Utility is CIG's "Heavy Utility" environment suits
# (Novikov, Pembroke), and Clothing is anything in a Char_Clothing_* or
# Char_Accessory_* (eyewear) slot.
# Short/Medium codes are the ones the issue asked for (L/LT, M/MD, H/HV,
# U/UT, S/SH, C/CL). A user who would rather see Utility suits as "H" can
# remap that row in the mapping editor.
DEFAULT_ARMOR_WEIGHT_MAPPING: dict[str, tuple[str, str, str]] = {
    "Light":       ("L", "LT", "Light"),
    "Medium":      ("M", "MD", "Medium"),
    "Heavy":       ("H", "HV", "Heavy"),
    "Super Heavy": ("S", "SH", "Super Heavy"),
    "Utility":     ("U", "UT", "Utility"),
    "Clothing":    ("C", "CL", "Clothing"),
}

# The literal separator used INSIDE a values-dict "usage" entry to delimit the
# category-name list (chosen so it can't collide with a category name). Not the
# rendered separator — that's TagConfig.usage_separator.
USAGE_INPUT_SEP = "\x1f"

DEFAULT_KIND_MAPPINGS: dict[str, dict[str, tuple[str, str, str]]] = {
    "class":     DEFAULT_COMPONENT_CLASS_MAPPING,
    "type":      DEFAULT_COMPONENT_TYPE_MAPPING,
    "ordinance": DEFAULT_MISSILE_ORDINANCE_MAPPING,
    "damage":    DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING,
    "label":     DEFAULT_COMMODITY_LABEL_MAPPING,
    "collection": DEFAULT_COMMODITY_COLLECTION_MAPPING,
    "usage":      DEFAULT_COMMODITY_USAGE_MAPPING,
    "weight":     DEFAULT_ARMOR_WEIGHT_MAPPING,
}

# Element kinds that render a *list* of mapped values (joined by the config's
# usage_separator) rather than a single value.
MULTI_VALUE_KINDS: frozenset[str] = frozenset({"usage"})

# Element kinds whose value resolves through a variant mapping (vs. derived
# kinds like size/grade). Single source of truth — the renderer and the UI's
# mapping-edit affordances both key off this so adding a mapped kind only
# means adding it to DEFAULT_KIND_MAPPINGS above.
MAPPED_KIND_NAMES: frozenset[str] = frozenset(DEFAULT_KIND_MAPPINGS)


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class ElementSpec:
    kind: str          # one of "class", "size", "grade", "ordinance", "damage"
    enabled: bool = True
    style: str = ""    # style key from STYLES_BY_KIND[kind]; "" → first option


PLACEMENTS: tuple[tuple[str, str], ...] = (
    ("prepend", "Before name (default)"),
    ("append",  "After name"),
)


@dataclass
class TagConfig:
    elements: list[ElementSpec] = field(default_factory=list)
    separator: str = "hyphen"      # key from SEPARATORS (between elements)
    enclosing: str = "square"      # key from ENCLOSINGS
    placement: str = "prepend"     # one of "prepend" / "append"
    class_mapping: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    # Separator INSIDE a multi-value element (the commodity "usage" list),
    # independent of `separator`. Key from SEPARATORS. Only commodities use it.
    usage_separator: str = "pipe"
    # Mission-title route config (only the "mission_titles" category uses these).
    route_arrow: str = "gt"        # key from ROUTE_ARROWS (origin > destination)
    title_separator: str = "dash"  # key from TITLE_SEPARATORS (route <-> title)
    # "address" or "name" (token modifier). Address is the default: it is what
    # mission bodies themselves resolve, so it never falls back to raw variable
    # text in-game; |name fails for some mission instances (#200).
    location_detail: str = "address"
    # Which SHORTEN_PHRASE_OPTIONS / REMOVE_WORD_OPTIONS keys are active for
    # the "shorten original titles" feature, so the route plus tags don't
    # overflow the contract list (#200 follow-up; generalized to per-word
    # checkboxes). Empty by default — off until the user opts in.
    abbreviated_phrases: frozenset[str] = field(default_factory=frozenset)
    # Separator rendered after the "Rank" position — key from RANK_SEPARATORS.
    # Independent feature: always applied when a Rank context is detected,
    # regardless of whether the "rank" word-removal checkbox — or any other
    # checkbox on this page — is on. Defaults to "dash" so it's on by itself
    # out of the box, matching what stock dash-led titles already show.
    rank_separator: str = "dash"
    # Which SIZE_ABBREVIATIONS words get shortened. All-or-nothing via the
    # single "Shorten cargo sizes" master checkbox, not per-size. Empty by
    # default — off until the user opts in.
    shortened_sizes: frozenset[str] = field(default_factory=frozenset)
    # "Standardize hauling mission names" (top-of-page toggle, sibling of the
    # route-enable checkbox — not part of `abbreviated_phrases` since it's a
    # template rewrite, not a shorten/remove pass; see
    # `_standardize_hauling_title`). Off by default.
    standardize_hauling_names: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict turns tuple values into lists — keep them as lists in JSON.
        d["class_mapping"] = {k: list(v) for k, v in self.class_mapping.items()}
        d["abbreviated_phrases"] = sorted(self.abbreviated_phrases)
        d["shortened_sizes"] = sorted(self.shortened_sizes)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TagConfig":
        elements_raw = data.get("elements", [])
        elements = [
            ElementSpec(
                kind=e.get("kind", ""),
                enabled=bool(e.get("enabled", True)),
                style=e.get("style", "") or "",
            )
            for e in elements_raw
            if isinstance(e, dict) and e.get("kind")
        ]
        mapping_raw = data.get("class_mapping", {}) or {}
        mapping: dict[str, tuple[str, str, str]] = {}
        for k, v in mapping_raw.items():
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                mapping[k] = (str(v[0]), str(v[1]), str(v[2]))
            elif isinstance(v, (list, tuple)) and len(v) == 2:
                mapping[k] = (str(v[0]), str(v[0]), str(v[1]))
        placement = data.get("placement", "prepend") or "prepend"
        if placement not in ("prepend", "append", "replace"):
            placement = "prepend"
        raw_phrases = data.get("abbreviated_phrases")
        legacy_on = bool(data.get("abbreviate_title", False))
        if raw_phrases is None:
            # Backward compat: pre-redesign blobs stored a single bool. A
            # user who had opted in (`abbreviate_title: true`) gets a
            # superset of the old behavior — every current option key turns
            # on, including the new Ling Family handling ("ling_family_rank"
            # / "ling_family_prefix") that didn't exist to opt into before.
            abbreviated_phrases = frozenset(_LEGACY_MIGRATION_KEYS) if legacy_on else frozenset()
        else:
            abbreviated_phrases = frozenset(
                k for k in raw_phrases if k in _ABBREVIATION_OPTION_KEYS
            )
        rank_separator = data.get("rank_separator", "dash") or "dash"
        if rank_separator not in _RANK_SEP_BY_KEY:
            rank_separator = "dash"
        raw_sizes = data.get("shortened_sizes")
        if raw_sizes is None:
            # Same legacy bool covered per-size shortening pre-redesign too.
            shortened_sizes = frozenset(_SIZE_WORDS) if legacy_on else frozenset()
        else:
            shortened_sizes = frozenset(w for w in raw_sizes if w in _SIZE_WORDS)
        return cls(
            elements=elements,
            separator=data.get("separator", "hyphen") or "hyphen",
            enclosing=data.get("enclosing", "square") or "square",
            placement=placement,
            class_mapping=mapping,
            usage_separator=data.get("usage_separator", "pipe") or "pipe",
            route_arrow=data.get("route_arrow", "gt") or "gt",
            title_separator=data.get("title_separator", "dash") or "dash",
            location_detail=data.get("location_detail", "address") or "address",
            abbreviated_phrases=abbreviated_phrases,
            rank_separator=rank_separator,
            shortened_sizes=shortened_sizes,
            standardize_hauling_names=bool(data.get("standardize_hauling_names", False)),
        )

    @classmethod
    def from_json(cls, blob: str) -> "TagConfig":
        return cls.from_dict(json.loads(blob))


def tag_config_fingerprint(
    tag_configs: "dict[str, TagConfig]", annotate_mission_descs: bool
) -> str:
    """Stable 12-char hex fingerprint of the complete Tag Builder config state.

    Two calls with equivalent config always return the same string, so a
    channel's generated enhancement INIs can be stamped with the config they
    were built from and a later channel switch can tell whether the current
    Tag Builder config still matches (#292/#296 sibling: the Save Tag Changes
    button used to light unconditionally after a switch because nothing
    recorded which config a channel's INIs were generated with). Mirrors the
    hashing shape of test_plan.plan_hash(): canonical JSON (sorted keys,
    ASCII-escaped) → sha256 → first 12 hex chars.

    Covers exactly what the "Save Tag Changes" button tracks in-session and
    what _persist_tag_builder_state() writes: the per-category TagConfigs
    (TagConfig.to_json() is itself canonical — sorted keys, frozensets sorted)
    plus the annotate-mission-descriptions toggle. Deliberately excludes
    generation *scope/target* inputs (which categories are enabled, the
    selected language) since those pick what/where to generate, not the tag
    content this button governs — folding them in would light the button for
    changes it doesn't otherwise react to.

    The armor config (#492) counts only while its tag is on. Switched off it
    shapes no output at all, and leaving it out keeps a stamp written before
    the Armor tab existed matching, so upgrading doesn't light the button for
    every user. Ticking Armor > Weight still changes the fingerprint.
    """
    payload = {
        "configs": {
            cat: cfg.to_json() for cat, cfg in sorted(tag_configs.items())
            if cat != "armor" or tag_enabled(cfg)
        },
        "annotate_mission_descs": bool(annotate_mission_descs),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# ── Default configs (must match the previously hardcoded output) ─────────────

DEFAULT_TAG_CONFIGS: dict[str, TagConfig] = {
    "components": TagConfig(
        elements=[
            ElementSpec("class", True, "med"),     # MIL
            ElementSpec("size",  True, "sn"),      # S2
            ElementSpec("grade", True, "letter"),  # A
            ElementSpec("type",  False, "short"),  # SH (disabled by default)
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping={**DEFAULT_COMPONENT_CLASS_MAPPING, **DEFAULT_COMPONENT_TYPE_MAPPING},
    ),
    # Missiles match the components default look: `[IR-S1]` for guided,
    # `[S2]` for bombs (the renderer's empty-value drop collapses the
    # ordinance + leading separator when seeker is absent). Default style
    # is "med" so the rendered abbreviation stays the familiar 2-letter
    # form even though Short (1 char) is now available too.
    "missiles": TagConfig(
        elements=[
            ElementSpec("ordinance", True, "med"),
            ElementSpec("size",      True, "sn"),
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping=dict(DEFAULT_MISSILE_ORDINANCE_MAPPING),
    ),
    # Ship weapons: new tagging in 1.3.x — short damage letter + S-size,
    # same bracket+hyphen style as components, e.g. `[E-S2]`.
    "ship_weapons": TagConfig(
        elements=[
            ElementSpec("damage", True, "short"),
            ElementSpec("size",   True, "sn"),
        ],
        separator="hyphen",
        enclosing="square",
        class_mapping=dict(DEFAULT_SHIP_WEAPON_DAMAGE_MAPPING),
    ),
    # Commodity tagging: two conditional flags sharing one wrapper. Crafting
    # ("CF") for crafting materials, Collection ("Collection") for items used
    # as Collection-mission objectives. When an item is both, render_tag joins
    # them with the separator, e.g. "[CF|Collection]"; when only one flag
    # applies, the other's empty value is dropped so a single-flag item stays
    # "[CF]" or "[Collection]" (#97). All three elements default off (#325):
    # users reported garbled/unknown text from commodity tagging in-game, so
    # a fresh install now shows plain commodity names until the user opts in
    # from the Tag Builder, instead of tagging being on and surprising them.
    "commodities": TagConfig(
        elements=[
            ElementSpec("label", False, "short"),        # CF
            ElementSpec("usage", False, "long"),         # QDRV|SHLD…
            ElementSpec("collection", False, "long"),    # Collection
        ],
        separator="pipe",
        enclosing="square",
        placement="append",
        usage_separator="pipe",
        class_mapping={
            **DEFAULT_COMMODITY_LABEL_MAPPING,
            **DEFAULT_COMMODITY_COLLECTION_MAPPING,
            **DEFAULT_COMMODITY_USAGE_MAPPING,
        },
    ),
}


DEFAULT_TAG_CONFIGS["mission_titles"] = TagConfig(
    # A single "route" element whose enabled-flag is the feature on/off. The
    # look is driven by route_arrow / title_separator / location_detail +
    # placement, not by element styles. Default: route AFTER the title
    # ("append"), ">", " - " join, full address (2.1.1, #200: short |name
    # can fail to resolve for some mission instances). Absorbs the #166
    # route-in-title toggle.
    elements=[ElementSpec("route", True, "")],
    placement="append",
    route_arrow="gt",
    title_separator="dash",
    location_detail="address",
)

# FPS armor weight class (#492), e.g. `[H] ADP-mk4 Core`. Off by default, like
# the commodity flags (#325): it tags well over a thousand armor and clothing
# names, so a fresh install or an upgrade shows stock names until the user
# opts in from the Tag Builder. Last in CATEGORIES, so its tab is the
# rightmost one.
DEFAULT_TAG_CONFIGS["armor"] = TagConfig(
    elements=[
        ElementSpec("weight", False, "short"),  # H
    ],
    separator="hyphen",
    enclosing="square",
    class_mapping=dict(DEFAULT_ARMOR_WEIGHT_MAPPING),
)


def route_enabled(cfg) -> bool:
    """True when the mission-title route feature is on for *cfg*."""
    if cfg is None:
        return False
    return any(e.kind == "route" and e.enabled for e in cfg.elements)


def tag_enabled(cfg) -> bool:
    """True when *cfg* has at least one element switched on, so it can
    render a tag at all. Used for the armor tag (#492), which is off by
    default, by the generator and by owned_items' enclosing set."""
    return cfg is not None and any(e.enabled for e in cfg.elements)


def render_route(from_disp: str, to_disp: str, arrow_key: str,
                 from_many: bool = False, to_many: bool = False) -> str:
    """Render the route core from two endpoint strings (tokens or names).

    Both present → ``from <arrow> to``; only one → ``from <x>`` / ``to <y>``;
    neither → "". The "shape" arrow builds its glyph from the endpoint
    multiplicity flags ("-" one, "=" several per side); the other arrow keys
    ignore them. Single source for the tab preview and the generator so the
    format can't drift.
    """
    if arrow_key == "shape":
        arrow = ("=" if from_many else "-") + ">" + ("=" if to_many else "-")
    else:
        arrow = _ROUTE_ARROW_BY_KEY.get(arrow_key, ">")
    if from_disp and to_disp:
        return f"{from_disp} {arrow} {to_disp}"
    if from_disp:
        return f"from {from_disp}"
    if to_disp:
        return f"to {to_disp}"
    return ""


def apply_mission_title(original: str, route: str, cfg) -> str:
    """Place *route* relative to *original* per ``cfg.placement``.

    Empty route → *original* unchanged (so "replace" never blanks a title and
    prepend/append no-op). The [BP]/XP tags are appended by the caller AFTER
    this, so "replace" swaps only the title text, never the tags.
    """
    if not route:
        return original
    sep = _TITLE_SEP_BY_KEY.get(cfg.title_separator, " - ")
    if cfg.placement == "replace":
        return route
    if cfg.placement == "append":
        return f"{original}{sep}{route}"
    return f"{route}{sep}{original}"  # prepend (default)


def default_config(category: str) -> TagConfig:
    """Return a fresh copy of the default config for *category*."""
    src = DEFAULT_TAG_CONFIGS[category]
    return TagConfig(
        elements=[ElementSpec(e.kind, e.enabled, e.style) for e in src.elements],
        separator=src.separator,
        enclosing=src.enclosing,
        placement=src.placement,
        class_mapping=dict(src.class_mapping),
        usage_separator=src.usage_separator,
        route_arrow=src.route_arrow,
        title_separator=src.title_separator,
        location_detail=src.location_detail,
        abbreviated_phrases=frozenset(src.abbreviated_phrases),
        rank_separator=src.rank_separator,
        shortened_sizes=frozenset(src.shortened_sizes),
        standardize_hauling_names=src.standardize_hauling_names,
    )


# ── Style application ────────────────────────────────────────────────────────

def _style_value(kind: str, style: str, raw: str,
                 mapping: dict[str, tuple[str, str, str]]) -> str:
    """Render *raw* (e.g. "Military", "2", "A") through *kind*/*style*.

    Missing or empty raw values return "" so the renderer can drop them.
    """
    if not raw:
        return ""

    if kind == "size":
        if style == "n":
            return raw
        if style == "size_n":
            return f"Size {raw}"
        # "sn" and any unknown style fall through to the historical default.
        return f"S{raw}"

    if kind == "grade":
        if style == "grade_letter":
            return f"Grade {raw}"
        return raw  # "letter"

    if kind in MAPPED_KIND_NAMES:
        variants = mapping.get(raw)
        if variants is None:
            # Unknown raw value — surface it verbatim so the user can edit
            # the mapping to add it (better than silently dropping).
            return raw
        idx_by_style = {"short": 0, "med": 1, "long": 2}
        idx = idx_by_style.get(style, 1)
        try:
            return variants[idx]
        except IndexError:
            return variants[0]

    return raw


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_tag(config: TagConfig, values: dict[str, str]) -> str:
    """Render *config* against per-element *values* into a tag string.

    Returns "" when no element resolves to a non-empty value (caller skips
    prepending). The returned string already includes any enclosing brackets;
    callers join it to the item name via :func:`join_tag`, not a bare space.
    """
    if not config.elements:
        return ""

    sep = _SEPARATOR_BY_KEY.get(config.separator, "-")
    open_c, close_c = _ENCLOSING_BY_KEY.get(config.enclosing, ("[", "]"))

    usage_sep = _SEPARATOR_BY_KEY.get(config.usage_separator, "|")

    parts: list[str] = []
    for el in config.elements:
        if not el.enabled:
            continue
        if el.kind in MULTI_VALUE_KINDS:
            # A list element: the value is USAGE_INPUT_SEP-joined category
            # names; style each and join with the element's own separator.
            raw = str(values.get(el.kind, "") or "")
            styled_vals = [
                _style_value(el.kind, el.style or "", name, config.class_mapping)
                for name in raw.split(USAGE_INPUT_SEP) if name
            ]
            styled_vals = [v for v in styled_vals if v]
            if styled_vals:
                parts.append(usage_sep.join(styled_vals))
            continue
        raw = str(values.get(el.kind, "") or "")
        styled = _style_value(el.kind, el.style or "", raw, config.class_mapping)
        if styled:
            parts.append(styled)

    if not parts:
        return ""

    body = sep.join(parts)
    return f"{open_c}{body}{close_c}"


def join_tag(name: str, tag: str, placement: str) -> str:
    """Join a rendered *tag* to an item *name* with a single space, honoring
    *placement*: only the exact value ``"append"`` puts the tag after the
    name, and everything else (including an empty or unrecognized value)
    prepends. Returns *name* unchanged if *tag* is empty.

    Stated that way round deliberately, because it is the way the code reads
    and the two are not interchangeable: describing it as '"prepend" puts the
    tag first, anything else appends' would promise the opposite behaviour for
    every value that is neither, and prepend is the default the Tag Builder
    ships.

    Single source of truth for this join so the 4 call sites in
    generate_enhancements_ini.py (components/missiles/ship weapons/
    commodities) don't each hand-duplicate the placement ternary.

    Reversing this join for "None (space only)" enclosing -- which has no
    delimiter char to mark the boundary -- is handled entirely on the
    matching side (#352): see owned_items.strip_via_stock_diff (compares
    against the item's known pre-tag stock value where available -- fully
    reliable, no guessing) and owned_items._looks_like_none_style_tag_word
    (a conservative heuristic fallback for contexts with no stock value to
    compare against, e.g. mission bullet text). An earlier attempt solved
    this by inserting an extra marker space here at generation time, but
    that touches every applied game file and turned out to collide with
    real messy whitespace already present in some raw item names -- keeping
    this join a plain single space avoids that risk entirely.
    """
    if not tag:
        return name
    return f"{name} {tag}" if placement == "append" else f"{tag} {name}"
