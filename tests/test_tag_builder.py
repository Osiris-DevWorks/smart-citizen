"""Unit tests for the dynamic tag builder.

Covers ``render_tag`` end-to-end (style application, enable toggling,
reordering, enclosing + separator combinations) and locks the
default-config output to be byte-equivalent to the pre-builder hardcoded
format strings — that regression test is the safety net that lets us
ship this refactor without changing any existing user's generated INIs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.tag_builder import (  # noqa: E402
    CATEGORIES,
    DEFAULT_TAG_CONFIGS,
    ElementSpec,
    TagConfig,
    default_config,
    join_tag,
    render_tag,
    tag_config_fingerprint,
)

pytestmark = pytest.mark.unit


# ── Style application ────────────────────────────────────────────────────────

class TestStyleApplication:
    def test_class_short_renders_single_letter(self):
        cfg = TagConfig(
            elements=[ElementSpec("class", True, "short")],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Military"}) == "[M]"

    def test_class_med_renders_three_letter(self):
        cfg = TagConfig(
            elements=[ElementSpec("class", True, "med")],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Civilian"}) == "[CIV]"

    def test_class_long_renders_full_word(self):
        cfg = TagConfig(
            elements=[ElementSpec("class", True, "long")],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Industrial"}) == "[Industrial]"

    def test_size_styles(self):
        for style, expected in [("n", "2"), ("sn", "S2"), ("size_n", "Size 2")]:
            cfg = TagConfig(
                elements=[ElementSpec("size", True, style)],
                separator="hyphen", enclosing="square", class_mapping={},
            )
            assert render_tag(cfg, {"size": "2"}) == f"[{expected}]"

    def test_grade_styles(self):
        for style, expected in [("letter", "A"), ("grade_letter", "Grade A")]:
            cfg = TagConfig(
                elements=[ElementSpec("grade", True, style)],
                separator="hyphen", enclosing="square", class_mapping={},
            )
            assert render_tag(cfg, {"grade": "A"}) == f"[{expected}]"

    def test_unknown_class_value_falls_through_verbatim(self):
        """User-customizable mapping: if CIG ships a new class name we don't
        recognize, surface the raw value rather than dropping silently — the
        user can add it to the mapping later."""
        cfg = TagConfig(
            elements=[ElementSpec("class", True, "short")],
            separator="hyphen", enclosing="square", class_mapping={},
        )
        assert render_tag(cfg, {"class": "Unknown"}) == "[Unknown]"

    def test_empty_class_mapping_falls_back_to_raw(self):
        cfg = TagConfig(
            elements=[ElementSpec("class", True, "med")],
            separator="hyphen", enclosing="square", class_mapping={},
        )
        assert render_tag(cfg, {"class": "Military"}) == "[Military]"


# ── Element enable + empty-value behavior ────────────────────────────────────

class TestElementToggles:
    def test_disabled_element_is_skipped(self):
        cfg = TagConfig(
            elements=[
                ElementSpec("class", True,  "med"),
                ElementSpec("size",  False, "sn"),    # disabled
                ElementSpec("grade", True,  "letter"),
            ],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "[MIL-A]"

    def test_missing_value_is_dropped_from_output(self):
        """Empty value collapses without leaving a dangling separator."""
        cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "med"),
                ElementSpec("size",  True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": ""}) == "[MIL-S2]"

    def test_all_empty_yields_empty_string(self):
        cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "med"),
                ElementSpec("size",  True, "sn"),
            ],
            separator="hyphen", enclosing="square", class_mapping={},
        )
        assert render_tag(cfg, {"class": "", "size": ""}) == ""

    def test_no_elements_yields_empty_string(self):
        cfg = TagConfig(elements=[], separator="hyphen", enclosing="square", class_mapping={})
        assert render_tag(cfg, {"class": "Military"}) == ""


# ── Ordering ─────────────────────────────────────────────────────────────────

class TestOrdering:
    def test_reorder_changes_output_order(self):
        # Default order: class size grade → [MIL-S2-A]. Move size first.
        cfg = TagConfig(
            elements=[
                ElementSpec("size",  True, "sn"),
                ElementSpec("class", True, "med"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="hyphen", enclosing="square",
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "[S2-MIL-A]"


# ── Separator + enclosing combos ─────────────────────────────────────────────

class TestSeparatorEnclosing:
    def _components_cfg(self, sep: str, enc: str) -> TagConfig:
        return TagConfig(
            elements=[
                ElementSpec("class", True, "short"),
                ElementSpec("size",  True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator=sep, enclosing=enc,
            class_mapping=DEFAULT_TAG_CONFIGS["components"].class_mapping,
        )

    def test_no_separator_concatenates_parts(self):
        cfg = self._components_cfg(sep="none", enc="square")
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "[MS2A]"

    def test_space_separator(self):
        cfg = self._components_cfg(sep="space", enc="square")
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "[M S2 A]"

    def test_no_enclosing_renders_bare(self):
        cfg = self._components_cfg(sep="hyphen", enc="none")
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "M-S2-A"

    def test_round_enclosing(self):
        cfg = self._components_cfg(sep="hyphen", enc="round")
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == "(M-S2-A)"


# ── join_tag: shared tag/name join helper (#352) ─────────────────────────────

class TestJoinTag:
    def test_prepend_places_tag_before_name(self):
        assert join_tag("Norfield", "[MIL-S1-A]", "prepend") == "[MIL-S1-A] Norfield"

    def test_append_places_tag_after_name(self):
        assert join_tag("Norfield", "[MIL-S1-A]", "append") == "Norfield [MIL-S1-A]"

    def test_empty_tag_returns_name_unchanged(self):
        assert join_tag("Norfield", "", "prepend") == "Norfield"

    def test_em4_wrapped_tag_joins_like_any_other(self):
        assert join_tag("Titanium", "<EM4>[CF]</EM4>", "prepend") == "<EM4>[CF]</EM4> Titanium"


# ── Regression: defaults match the pre-builder hardcoded format ──────────────

class TestDefaultBackwardsCompat:
    """The default configs must reproduce today's hardcoded output exactly.

    This is the contract that lets us refactor the generator without
    silently changing any existing user's INI output.
    """

    @pytest.mark.parametrize("klass,size,grade,expected", [
        ("Military",   "1", "A", "[MIL-S1-A]"),
        ("Civilian",   "2", "B", "[CIV-S2-B]"),
        ("Industrial", "3", "C", "[IND-S3-C]"),
        ("Competition","1", "D", "[CMP-S1-D]"),
        ("Stealth",    "2", "A", "[STH-S2-A]"),
    ])
    def test_component_default_matches_old_format(self, klass, size, grade, expected):
        cfg = default_config("components")
        assert render_tag(cfg, {"class": klass, "size": size, "grade": grade}) == expected

    @pytest.mark.parametrize("ordinance,size,expected", [
        ("Infrared",        "1", "[IR-S1]"),
        ("Electromagnetic", "2", "[EM-S2]"),
        ("CrossSection",    "3", "[CS-S3]"),
    ])
    def test_missile_guided_default_includes_ordinance_and_size(self, ordinance, size, expected):
        """Guided missiles in v1: default config shows ordinance + size in
        the components-style `[X-Y]` form. Deliberate change from the
        pre-refactor `[IR]` output per issue #31 feedback — users asked
        to identify missile size at a glance. Users can disable Size in
        the Tag Builder UI to revert to the historical `[IR]` form."""
        cfg = default_config("missiles")
        assert render_tag(cfg, {"ordinance": ordinance, "size": size}) == expected

    def test_missile_empty_ordinance_drops_to_size_only(self):
        """When the ordinance value is empty, render_tag's empty-drop
        should collapse to the size element alone (`[S2]`). The
        ``_missile_name_tag`` caller no longer feeds empty for bombs —
        it resolves them to ``"Bomb"`` so they render through the
        ordinance mapping — but the renderer's behaviour for a literal
        empty input is still covered here as an isolated unit."""
        cfg = default_config("missiles")
        assert render_tag(cfg, {"ordinance": "", "size": "2"}) == "[S2]"

    def test_missile_bomb_ordinance_renders_via_mapping(self):
        """``"Bomb"`` is in DEFAULT_MISSILE_ORDINANCE_MAPPING as
        ("B", "B", "Bomb"). Under the default missile config (med style)
        that resolves to ``B``, giving ``[B-S3]`` for a size-3 bomb —
        the user-visible distinguisher between bombs and seekerless
        ordinance the new detection path produces."""
        cfg = default_config("missiles")
        assert render_tag(cfg, {"ordinance": "Bomb", "size": "3"}) == "[B-S3]"

    def test_missile_size_disabled_preserves_legacy_guided_output(self):
        """Locks the path back to the pre-refactor `[IR]` output — users
        who prefer that disable the Size element and get this behavior."""
        cfg = default_config("missiles")
        for el in cfg.elements:
            if el.kind == "size":
                el.enabled = False
        assert render_tag(cfg, {"ordinance": "Infrared", "size": "1"}) == "[IR]"


# ── JSON roundtrip ───────────────────────────────────────────────────────────

class TestJsonRoundtrip:
    def test_default_components_survives_roundtrip(self):
        cfg = default_config("components")
        revived = TagConfig.from_json(cfg.to_json())
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A"}) == \
               render_tag(revived, {"class": "Military", "size": "2", "grade": "A"})

    def test_edited_config_survives_roundtrip(self):
        # Default class style is "med", so editing the medium variant is
        # what the roundtrip should observe in the rendered tag.
        cfg = default_config("components")
        for el in cfg.elements:
            if el.kind == "grade":
                el.enabled = False
        cfg.class_mapping["Military"] = ("X", "XMIL", "X-Military")
        revived = TagConfig.from_json(cfg.to_json())
        assert render_tag(revived, {"class": "Military", "size": "2", "grade": "A"}) == "[XMIL-S2]"

    def test_short_variant_tuple_is_padded(self):
        """Older saves may have 2-tuple variants (short, long); from_dict
        should pad them to the 3-tuple shape without crashing."""
        blob = (
            '{"elements": [{"kind": "class", "enabled": true, "style": "med"}], '
            '"separator": "hyphen", "enclosing": "square", '
            '"class_mapping": {"Military": ["M", "Military"]}}'
        )
        cfg = TagConfig.from_json(blob)
        # med == index 1; the pad duplicates short into the missing middle slot.
        assert render_tag(cfg, {"class": "Military"}) == "[M]"


# ── Ship-weapon defaults sanity ──────────────────────────────────────────────

class TestShipWeaponDefaults:
    def test_default_ship_weapon_produces_short_damage_plus_S_size(self):
        cfg = default_config("ship_weapons")
        assert render_tag(cfg, {"damage": "Energy", "size": "2"}) == "[E-S2]"

    def test_unknown_damage_label_falls_through(self):
        cfg = default_config("ship_weapons")
        # If the dominant damage label is one we don't have in the mapping,
        # surface it verbatim so the user can edit the mapping.
        assert render_tag(cfg, {"damage": "Plasma", "size": "1"}) == "[Plasma-S1]"


# ── Component type element ──────────────────────────────────────────────────

class TestComponentTypeElement:
    """render_tag with the ``type`` element kind (new in 1.4.2)."""

    def test_type_short_shield_generator(self):
        cfg = default_config("components")
        for el in cfg.elements:
            if el.kind == "type":
                el.enabled = True
                el.style = "short"
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A", "type": "Shield Generator"}) == "[MIL-S2-A-SH]"

    def test_type_med_cooler(self):
        cfg = default_config("components")
        for el in cfg.elements:
            if el.kind == "type":
                el.enabled = True
                el.style = "med"
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A", "type": "Cooler"}) == "[MIL-S2-A-COOL]"

    def test_type_disabled_no_change(self):
        """Default config has type disabled; output matches the pre-1.4.2 format."""
        cfg = default_config("components")
        # type is disabled by default -- verify
        type_spec = next(e for e in cfg.elements if e.kind == "type")
        assert type_spec.enabled is False
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A", "type": "Shield Generator"}) == "[MIL-S2-A]"

    def test_type_long_power_plant(self):
        cfg = default_config("components")
        for el in cfg.elements:
            if el.kind == "type":
                el.enabled = True
                el.style = "long"
        assert render_tag(cfg, {"class": "Military", "size": "2", "grade": "A", "type": "Power Plant"}) == "[MIL-S2-A-Power]"


# ── Commodity label element ─────────────────────────────────────────────────

class TestCommodityLabelElement:
    """render_tag with the ``label`` element kind for commodities.

    default_config("commodities") ships every element disabled (#325), so
    each test enables ``label`` explicitly -- this class exercises render
    logic, independent of that default."""

    def test_label_short_crafting(self):
        cfg = default_config("commodities")
        for el in cfg.elements:
            if el.kind == "label":
                el.enabled = True
        assert render_tag(cfg, {"label": "Crafting"}) == "[CF]"

    def test_label_med_crafting(self):
        cfg = default_config("commodities")
        for el in cfg.elements:
            if el.kind == "label":
                el.enabled = True
                el.style = "med"
        assert render_tag(cfg, {"label": "Crafting"}) == "[Craft]"

    def test_label_long_crafting(self):
        cfg = default_config("commodities")
        for el in cfg.elements:
            if el.kind == "label":
                el.enabled = True
                el.style = "long"
        assert render_tag(cfg, {"label": "Crafting"}) == "[Crafting]"

    def test_label_round_enclosing(self):
        cfg = default_config("commodities")
        for el in cfg.elements:
            if el.kind == "label":
                el.enabled = True
        cfg.enclosing = "round"
        assert render_tag(cfg, {"label": "Crafting"}) == "(CF)"


# ── Config fingerprint (Save Tag Changes per-channel freshness, #292/#296 sibling) ──

class TestTagConfigFingerprint:
    """tag_config_fingerprint must be a stable, sensitive digest: identical
    config -> identical hash regardless of dict order, and any tag-affecting
    change -> a different hash. This is what lets a channel's INIs be stamped
    with the config they were built from so the Save Tag Changes button can do
    a real freshness check on channel switch instead of always lighting up."""

    def _all(self):
        return {c: default_config(c) for c in CATEGORIES}

    def test_deterministic(self):
        cfgs = self._all()
        assert tag_config_fingerprint(cfgs, True) == tag_config_fingerprint(cfgs, True)

    def test_is_twelve_hex_chars(self):
        fp = tag_config_fingerprint(self._all(), True)
        assert len(fp) == 12
        int(fp, 16)  # raises if not hex

    def test_dict_order_independent(self):
        cfgs = self._all()
        reordered = {c: cfgs[c] for c in reversed(list(CATEGORIES))}
        assert tag_config_fingerprint(reordered, True) == tag_config_fingerprint(cfgs, True)

    def test_annotate_toggle_changes_hash(self):
        cfgs = self._all()
        assert tag_config_fingerprint(cfgs, True) != tag_config_fingerprint(cfgs, False)

    def test_config_edit_changes_hash(self):
        cfgs = self._all()
        baseline = tag_config_fingerprint(cfgs, True)
        edited = dict(cfgs)
        comp = default_config("components")
        comp.separator = "pipe" if comp.separator != "pipe" else "hyphen"
        edited["components"] = comp
        assert tag_config_fingerprint(edited, True) != baseline

    def test_element_reorder_changes_hash(self):
        # elements is an ordered list — reordering is a real, visible change.
        cfgs = self._all()
        baseline = tag_config_fingerprint(cfgs, True)
        comp = default_config("components")
        if len(comp.elements) >= 2:
            comp.elements[0], comp.elements[1] = comp.elements[1], comp.elements[0]
            edited = dict(cfgs)
            edited["components"] = comp
            assert tag_config_fingerprint(edited, True) != baseline

    def test_equivalent_frozenset_order_same_hash(self):
        # abbreviated_phrases is a frozenset — insertion order must not matter,
        # since to_dict() sorts it. Two configs built with different insertion
        # orders of the same phrases must fingerprint identically.
        a = default_config("mission_titles")
        b = default_config("mission_titles")
        a.abbreviated_phrases = frozenset({"rank", "delivery"})
        b.abbreviated_phrases = frozenset({"delivery", "rank"})
        cfgs_a = {c: default_config(c) for c in CATEGORIES}
        cfgs_b = {c: default_config(c) for c in CATEGORIES}
        cfgs_a["mission_titles"] = a
        cfgs_b["mission_titles"] = b
        assert tag_config_fingerprint(cfgs_a, True) == tag_config_fingerprint(cfgs_b, True)
