"""Blueprint metadata builder for the shuttle filters (#157 follow-up).

Joins blueprint bullet names to component name entries (type / class / size /
grade) and to their mission titles, from the loaded strings. Qt-free.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_meta import (  # noqa: E402
    DEFAULT_OWNED_BLUEPRINTS,
    MANUAL_BLUEPRINT_ITEMS,
    blueprint_type_from_key,
    build_blueprint_metadata,
    clean_mission_title,
    component_type_from_key,
    expand_class_full_word,
    parse_component_tag,
    size_from_key,
    strip_size_prefix,
)
from src.utils.owned_items import (  # noqa: E402
    NONE_STYLE_ENCLOSING, normalize_item_name,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _Entry:
    key: str
    original_value: str
    category: str = "Other"


def test_parse_component_tag():
    assert parse_component_tag("[MIL-S3-B] Balandin") == ("MIL", "S3", "B")
    assert parse_component_tag("[ind-s1-a] Palisade") == ("IND", "S1", "A")
    assert parse_component_tag("Balandin") == (None, None, None)
    assert parse_component_tag("") == (None, None, None)


def test_parse_component_tag_robust_to_config(gen_module=None):
    # #196: robust to the user's configurable separator / order / type element.
    assert parse_component_tag("[CMP.S1.B.PW] StarHeart") == ("CMP", "S1", "B")
    assert parse_component_tag("[MIL.S02.C] Foo") == ("MIL", "S2", "C")  # zero-pad stripped
    # A ship-weapon-style [E-S2] (no grade): class E is a lone letter -> grade,
    # class None. That's fine — the builder only keeps attrs for typed components.
    assert parse_component_tag("[E-S2] Gun")[1] == "S2"


def test_parse_component_tag_trailing_placement():
    """A category configured to append (tag after the name) must still
    extract class/size/grade — pre-fix this lost the facets entirely for
    any append-placed category."""
    assert parse_component_tag("Balandin [MIL-S3-B]") == ("MIL", "S3", "B")
    assert parse_component_tag("Palisade [ind-s1-a]") == ("IND", "S1", "A")


def test_parse_component_tag_leading_wins_when_both_present():
    """Extremely unlikely in real data (a name can't legitimately carry two
    tags), but pins that a leading match short-circuits before the trailing
    regex ever runs."""
    assert parse_component_tag("[MIL-S3-B] Balandin [IND-S1-A]") == ("MIL", "S3", "B")


# -- #352: configurable enclosing styles -------------------------------------

def test_parse_component_tag_default_unchanged_from_hardcoded_square():
    """Regression guard: omitting `enclosings` must behave exactly like the
    original hardcoded Square-only implementation."""
    assert parse_component_tag("[MIL-S3-B] Balandin") == ("MIL", "S3", "B")
    assert parse_component_tag("Balandin [MIL-S3-B]") == ("MIL", "S3", "B")


def test_parse_component_tag_round_enclosing():
    assert parse_component_tag(
        "(MIL-S3-B) Balandin", enclosings=(("(", ")"),)
    ) == ("MIL", "S3", "B")


def test_parse_component_tag_curly_and_angle_enclosings():
    assert parse_component_tag(
        "{IND-S1-A} Palisade", enclosings=(("{", "}"),)
    ) == ("IND", "S1", "A")
    assert parse_component_tag(
        "Palisade <IND-S1-A>", enclosings=(("<", ">"),)
    ) == ("IND", "S1", "A")


def test_parse_component_tag_multi_alternative_capture_group_selects_correct_group():
    """Regression test for a bug hit while building this fix: with one
    capture group per enclosing alternative, `m.group(1)` only works for the
    FIRST alternative -- every other alternative's group comes back None.
    This must select whichever group actually matched, not always group 1."""
    enclosings = (("[", "]"), ("(", ")"), ("{", "}"))
    assert parse_component_tag("(MIL-S3-B) Balandin", enclosings=enclosings) == ("MIL", "S3", "B")
    assert parse_component_tag("{IND-S1-A} Palisade", enclosings=enclosings) == ("IND", "S1", "A")


def test_parse_component_tag_none_enclosing_via_stock_diff():
    """A known stock value recovers a "None (space only)" tag's class/size/
    grade authoritatively, no delimiter needed (#352)."""
    assert parse_component_tag("MIL-S3-B Balandin", stock="Balandin") == ("MIL", "S3", "B")


def test_parse_component_tag_none_enclosing_via_heuristic_without_stock():
    """Without a stock value the same conservative heuristic as
    normalize_item_name's fallback still catches the common case -- but only
    when None enclosing is actually configured, which is the parity with that
    sibling this test's docstring used to claim while asserting the opposite.
    """
    none_cfg = (("[", "]"), NONE_STYLE_ENCLOSING)
    assert parse_component_tag("MIL-S3-B Balandin", none_cfg) == ("MIL", "S3", "B")


def test_parse_component_tag_heuristic_is_off_unless_none_configured():
    """Ungated, the heuristic invents facets from ordinary names that merely
    look tag-shaped, because it cannot tell a real hyphenated designator from
    a space-only tag.

    A populated `stock` short-circuits it, so English installs are mostly
    covered by accident. `default_values` is English by design, so on a
    non-English install the diff never matches and every translated name
    reaches this -- systematic, not incidental. Facets only, so no false
    [Owned] tag, but the Class/Size/Grade filters quietly fill with values no
    item actually has.
    """
    assert parse_component_tag("250-E Laser Pointer") == (None, None, None)
    assert parse_component_tag("C-788 Cannon") == (None, None, None)
    assert parse_component_tag("A-18 Shredder") == (None, None, None)
    # ...and still works for a user who did configure None enclosing.
    none_cfg = (("[", "]"), NONE_STYLE_ENCLOSING)
    assert parse_component_tag("MIL-S3-B Balandin", none_cfg) == ("MIL", "S3", "B")


def test_parse_component_tag_gate_holds_on_a_non_english_install():
    """The systematic case: `stock` is English, the value is translated, so
    the authoritative diff cannot match and the gate is all that stands
    between a translated name and a fabricated facet."""
    assert parse_component_tag("C-788 Canon", stock="C-788 Cannon") == (None, None, None)


def test_parse_component_tag_confirmed_untagged_stock_match_skips_heuristic():
    """A stock match with an empty diff means "definitely not tagged" --
    must not fall through to the heuristic and fabricate a false facet from
    a stock name that coincidentally looks tag-shaped (regression: an
    earlier version used a truthy check that treated "" the same as "no
    match at all", letting this fall through)."""
    assert parse_component_tag("Titan-S2 Reactor", stock="Titan-S2 Reactor") == (None, None, None)


def test_size_from_key():
    assert size_from_key("item_NamePOWR_ACOM_S01_StarHeart") == "S1"
    assert size_from_key("item_NameQDRV_RSI_S02_Hemera") == "S2"
    assert size_from_key("item_Name_no_size_here") is None


def test_component_type_from_key():
    assert component_type_from_key("item_NameQDRV_RSI_S02_Hemera") == "Quantum Drive"
    assert component_type_from_key("item_Name_SHLD_Aspirum") == "Shield"
    assert component_type_from_key("item_NameQRDV_typo") == "Quantum Drive"
    # Manufacturer-prefixed name (no recognized type code) -> no type.
    assert component_type_from_key("item_NameAEGS_Eclipse_BombRack_S03") is None


def test_expand_class_full_word():
    # Medium (default Tag Builder style) and Short both expand to the same
    # full word; already-full and unrecognized tokens pass through.
    assert expand_class_full_word("MIL") == "Military"
    assert expand_class_full_word("mil") == "Military"
    assert expand_class_full_word("M") == "Military"
    assert expand_class_full_word("IND") == "Industrial"
    assert expand_class_full_word("I") == "Industrial"
    assert expand_class_full_word("CIV") == "Civilian"
    assert expand_class_full_word("STH") == "Stealth"
    assert expand_class_full_word("CMP") == "Competition"
    assert expand_class_full_word("Military") == "Military"
    assert expand_class_full_word("CustomLabel") == "CustomLabel"
    assert expand_class_full_word(None) is None
    assert expand_class_full_word("") == ""


def test_strip_size_prefix():
    assert strip_size_prefix("S3") == "3"
    assert strip_size_prefix("s10") == "10"
    assert strip_size_prefix("S0") == "0"
    assert strip_size_prefix(None) is None
    assert strip_size_prefix("") == ""
    # Already bare — left alone.
    assert strip_size_prefix("3") == "3"


def test_blueprint_type_buckets():
    # Ship component type wins.
    assert blueprint_type_from_key("item_NameSHLD_Aspirum") == "Shield"
    # FPS weapon and armor by key tokens.
    assert blueprint_type_from_key("item_Name_rifle_behr_p4ar") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_pistol_gmni") == "FPS Weapon"
    assert blueprint_type_from_key("item_Nameutfl_crossbow_ballistic_01") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_armor_rsi_torso") == "Armor"
    assert blueprint_type_from_key("item_Name_helmet_xyz") == "Armor"
    # Ship weapons (#212): uppercase manufacturer + weapon size designator,
    # no recognized subsystem code. Size codes: _S2, _XL, _L-2, ...
    assert blueprint_type_from_key("item_NameKLWE_LaserCannon_S2") == "Ship Weapon"
    assert blueprint_type_from_key("item_NameBEHR_Gatling_S3") == "Ship Weapon"
    assert blueprint_type_from_key("item_NameAEGS_Bulldog_XL") == "Ship Weapon"
    # A recognized subsystem code still wins over the ship-weapon fallback
    # even though shields etc. also carry a _Sx size designator.
    assert blueprint_type_from_key("item_NameSHLD_ACOM_S01") == "Shield"
    # Lowercase (FPS gear) with a size-looking token is NOT a ship weapon.
    assert blueprint_type_from_key("item_Name_pistol_gmni") == "FPS Weapon"
    # Unrecognized / no match -> None (caller folds into "Other").
    # BombRack has no _Sx / _XL size designator, so it stays None.
    assert blueprint_type_from_key("item_NameAEGS_Eclipse_BombRack") is None
    assert blueprint_type_from_key(None) is None


def test_blueprint_type_mining_head_family_not_ship_weapon():
    """Reported: "S0 Helix" showed under Ship Weapon in the Blueprint
    Tracker's Type filter while other mining lasers showed under Other.

    Root cause: every real ship-mounted mining laser shares CIG's generic
    "Mining_Head" entity-model key (item_NameMining_Head_S00_<Name>[_SCItem])
    -- "Mining" starts with an uppercase letter like a manufacturer code, and
    "_S00" is the head's own size-0 designator, so EVERY variant (not just
    Helix) satisfies the #212 ship-weapon heuristic by coincidence. All four
    real variants must land in Other, consistently."""
    assert blueprint_type_from_key("item_NameMining_Head_S00_Arbor_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Helix_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Hofstede_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Klein_SCItem") is None
    # Real ship weapons must still classify correctly -- the carve-out is
    # scoped to the "mining_head" token, not a blanket size-designator skip.
    assert blueprint_type_from_key("item_NameKLWE_LaserCannon_S2") == "Ship Weapon"


def test_build_metadata_mining_head_family_lands_in_other():
    """End-to-end via build_blueprint_metadata, not just the key classifier
    in isolation -- confirms the fix actually reaches the Blueprint Tracker's
    Type filter for a real mission bullet + item_Name pair."""
    desc = ("x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- S0 Helix\\n- S0 Arbor")
    entries = [
        _Entry("M_Desc_001", desc, "Missions"),
        _Entry("item_NameMining_Head_S00_Helix_SCItem", "S0 Helix", "Ship Items"),
        _Entry("item_NameMining_Head_S00_Arbor_SCItem", "S0 Arbor", "Ship Items"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["S0 Helix"].type == "Other"
    assert meta["S0 Arbor"].type == "Other"


def test_blueprint_type_armor_core_pieces():
    """FPS armor torso-platform pieces ("Core") reported showing up in the
    Blueprint Tracker's "Other" bucket instead of "Armor". Newer
    manufacturer-prefixed armor lines carry no "armor" token in the key at
    all (unlike CIG's older sets, which do), only "core"."""
    assert blueprint_type_from_key("item_Name_qrt_specialist_heavy_core_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_kap_combat_light_core_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_GRIN_utility_medium_core_01_01_01") == "Armor"
    # Older sets that DO carry "armor" in the key still work (no regression).
    assert blueprint_type_from_key("item_Name_cds_armor_heavy_core_01_02_01") == "Armor"
    # Ship components sharing the bare "core" word must not be reclassified —
    # their component-type-code prefix (POWR_/COOL_) wins first.
    assert blueprint_type_from_key("item_NamePOWR_ACOM_S02_LuxCore_SCItem") == "Power Plant"
    assert blueprint_type_from_key("item_NameCOOL_JUST_S02_CoolCore") == "Cooler"
    # The word is "_core" (underscore-prefixed), not bare "core" — a bare
    # substring match would misclassify anything with "score"/"scoreboard" in
    # the key ("score" contains "core"), and no armor set actually needs the
    # bare form since every real armor "core" piece carries the underscore.
    assert blueprint_type_from_key("item_Name_gys_scoreboard_01_01_01") is None
    assert blueprint_type_from_key("item_Name_gys_highscore_01_01_01") is None


def test_blueprint_type_ammo_and_magazines():
    """Ammo/magazine blueprints (#249) get their own "Ammo" bucket instead of
    landing in "Other" (or, worse, "FPS Weapon" — many mag keys carry a
    "_rifle_"/"_pistol_"/etc token that would otherwise win first)."""
    assert blueprint_type_from_key("item_Namebehr_rifle_ballistic_01_mag") == "Ammo"
    assert blueprint_type_from_key("item_NameGMNI_smg_ballistic_01_mag") == "Ammo"
    assert blueprint_type_from_key("item_Nameklwe_lmg_energy_01_mag") == "Ammo"
    assert blueprint_type_from_key("item_Nameutfl_crossbow_ballistic_01_mag") == "Ammo"
    # Salvage/healing canister pairs — "_mag" with an _empty/_filled state suffix.
    assert blueprint_type_from_key("item_Namegrin_multitool_01_salvage_mag_empty") == "Ammo"
    assert blueprint_type_from_key("item_Namegrin_multitool_01_salvage_mag_filled") == "Ammo"
    assert blueprint_type_from_key("item_Namegrin_multitool_01_healing_mag") == "Ammo"
    # Keys that merely contain "mag" mid-string (not a trailing _mag token) are
    # NOT ammo — e.g. a physical magazine/poster item.
    assert blueprint_type_from_key("item_NameFlair_Poster_SM_Mag_Cover") is None
    # A recognized ship-component code still wins first (unaffected by this bucket).
    assert blueprint_type_from_key("item_NameSHLD_ACOM_S01") == "Shield"


def test_blueprint_type_ammo_suffix_checked_before_mining_head_carveout():
    """Locks the classifier's ordering (#249 review): component-code -> Ammo
    suffix -> FPS weapon/armor -> mining-head carve-out (#290) -> ship-weapon
    heuristic (#212). Neither #249 nor #290 should ever shadow the other --
    an ammo key ending in one of _AMMO_KEY_SUFFIXES must classify as Ammo
    even if it also happens to contain "mining_head", and a real mining-head
    key with no ammo suffix must still land in Other, not Ammo."""
    assert blueprint_type_from_key("item_NameMining_Head_S00_Test_mag") == "Ammo"
    assert blueprint_type_from_key("item_NameMining_Head_S00_Arbor_SCItem") is None


def test_blueprint_type_gys_jacket_and_pants():
    """Carnifex set torso/leg pieces reported showing up in "Other" — the
    "gys" manufacturer keys these as jacket/pants, not core/legs/armor."""
    assert blueprint_type_from_key("item_Name_gys_jacket_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_gys_pants_01_01_01") == "Armor"
    # Scoped to "gys_" specifically — a bare "jacket"/"pants" match would also
    # catch unrelated civilian wardrobe items from other manufacturers.
    assert blueprint_type_from_key("item_Desc_987_Jacket_01_01_01") is None
    assert blueprint_type_from_key("item_Desc_DMC_Pants_01_01_01") is None


def test_clean_mission_title_strips_reward_tags():
    raw = ("Salvager Needed (Lrg. Special Order) "
           "<EM4>[BP]</EM4> <EM4>[150 REP]</EM4>")
    assert clean_mission_title(raw) == "Salvager Needed (Lrg. Special Order)"


def _sample_entries():
    desc = (
        "Posting body.\\n\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
        "\\n- Balandin\\n- Abrade Scraper Module"
    )
    return [
        _Entry("Adagio_Run_Levski_H_Desc_001", desc, "Missions"),
        _Entry("Adagio_Run_Levski_H_Title_001",
               "Salvager Needed <EM4>[BP]</EM4> <EM4>[150 REP]</EM4>", "Missions"),
        _Entry("item_NameQDRV_WETK_S03_Balandin", "[MIL-S3-B] Balandin", "Ship Items"),
    ]


def test_build_joins_component_attributes():
    meta = build_blueprint_metadata(_sample_entries())
    # Subset, not equality: the manually-curated items (#267) always ride
    # along too now, covered separately in TestManualBlueprintItems.
    assert {"Balandin", "Abrade Scraper Module"} <= set(meta)
    bal = meta["Balandin"]
    assert (bal.type, bal.cls, bal.size, bal.grade) == ("Quantum Drive", "Military", "3", "B")
    # Plain item with no matching name entry -> "Other" type, no class/size/grade.
    scraper = meta["Abrade Scraper Module"]
    assert (scraper.type, scraper.cls, scraper.size, scraper.grade) == ("Other", None, None, None)


def test_build_type_buckets_fps_and_armor():
    desc = ("x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- P4-AR Rifle\\n- RSI Torso Armor\\n- Mystery Widget")
    entries = [
        _Entry("M_Desc_001", desc, "Missions"),
        _Entry("item_Name_rifle_behr_p4ar", "P4-AR Rifle", "Gear"),
        _Entry("item_Name_armor_rsi_torso", "RSI Torso Armor", "Gear"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["P4-AR Rifle"].type == "FPS Weapon"
    assert meta["RSI Torso Armor"].type == "Armor"
    # No matching name entry -> Other.
    assert meta["Mystery Widget"].type == "Other"


def test_build_attaches_mission_name():
    meta = build_blueprint_metadata(_sample_entries())
    assert meta["Balandin"].missions == frozenset({"Salvager Needed"})
    assert meta["Abrade Scraper Module"].missions == frozenset({"Salvager Needed"})


def test_item_in_multiple_missions_unions_titles():
    desc1 = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Balandin"
    desc2 = "y\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Balandin"
    entries = [
        _Entry("M_One_Desc_001", desc1, "Missions"),
        _Entry("M_One_Title_001", "First Job", "Missions"),
        _Entry("M_Two_Desc_001", desc2, "Missions"),
        _Entry("M_Two_Title_001", "Second Job", "Missions"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["Balandin"].missions == frozenset({"First Job", "Second Job"})


def test_renamed_blueprints_header_recognized_when_bp_header_passed():
    """#353: a user-renamed "blueprints" mission header must still populate
    the Blueprint Tracker when the actual configured header is passed
    through -- without it, every mission using the renamed header was
    silently unscanned, not just mis-tagged."""
    desc = "x\\n<EM4>MY LOOT</EM4>\\n- Antium Core"
    meta = build_blueprint_metadata(
        [_Entry("M_Desc_001", desc, "Missions")], bp_header="MY LOOT"
    )
    assert "Antium Core" in meta


def test_renamed_blueprints_header_not_recognized_without_bp_header():
    """Regression guard: omitting bp_header must behave exactly like the
    original hardcoded-default-only implementation."""
    desc = "x\\n<EM4>MY LOOT</EM4>\\n- Antium Core"
    meta = build_blueprint_metadata([_Entry("M_Desc_001", desc, "Missions")])
    assert "Antium Core" not in meta


def test_desc_without_title_yields_no_mission_but_keeps_item():
    desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Orphan Part"
    meta = build_blueprint_metadata([_Entry("Loose_Desc_001", desc, "Missions")])
    assert "Orphan Part" in meta
    assert meta["Orphan Part"].missions == frozenset()


def test_no_blueprint_entries_is_empty():
    """No mission-derived items -- only the manually-curated ones (#267) and
    the starter blueprints (#416), which ride along regardless of what's
    loaded."""
    meta = build_blueprint_metadata([_Entry("vehicle_NameRSI_Polaris", "Polaris", "Ships")])
    assert "Polaris" not in meta
    assert set(meta) == (
        {normalize_item_name(n) for n, _ in MANUAL_BLUEPRINT_ITEMS}
        | {normalize_item_name(n) for _, n in DEFAULT_OWNED_BLUEPRINTS}
    )


def test_non_mission_entry_with_colliding_header_is_not_scanned():
    """#354: the Blueprint Tracker "stacked" fake items like "Power Plants:
    10 items" because a commodity's independently-renameable "Blueprint
    Data" header can collide with the "blueprints" mission header, and
    has_bp_section() ran on every entry's value unconditionally --
    scanning a commodity's crafting-material-usage summary as if it were a
    real mission's blueprint reward list. Only "Missions"-category entries
    should ever be scanned this way."""
    commodity_desc = (
        "Iron Ore is a common metal.\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
        "\\n- Power Plants: 10 items\\n- Quantum Drives: 3 items (S1-S3)"
    )
    meta = build_blueprint_metadata(
        [_Entry("items_commodities_iron_desc", commodity_desc, "Commodities")]
    )
    assert "Power Plants: 10 items" not in meta
    assert "Quantum Drives: 3 items (S1-S3)" not in meta


class TestManualBlueprintItems:
    """#267: XenoThreat "Purgatory Camo" items were never advertised via any
    mission's POTENTIAL BLUEPRINTS text (CIG announced them on their own
    website for a limited-time event), so mission-text scanning alone could
    never surface them -- players only ever saw them in the Owned list, via
    the log scanner's independent "Received Blueprint: ..." matching, never
    in Available. These lock down the manual-item fold-in that fixes that."""

    def test_all_manual_items_present_with_no_source_data(self):
        meta = build_blueprint_metadata([])
        for raw_name, expected_type in MANUAL_BLUEPRINT_ITEMS:
            assert raw_name in meta, f"{raw_name!r} missing from blueprint metadata"
            assert meta[raw_name].type == expected_type

    def test_manual_item_missions_label_explains_itself(self):
        meta = build_blueprint_metadata([])
        assert meta["QuadraCell"].missions == frozenset({"Limited time event reward"})

    def test_manual_item_falls_back_to_bare_name_with_no_match(self):
        meta = build_blueprint_metadata([])
        fr66 = meta["FR-66"]
        assert fr66.tagged_name == "FR-66"
        assert (fr66.cls, fr66.size, fr66.grade) == (None, None, None)

    def test_manual_item_picks_up_real_facets_when_actually_loaded(self):
        """If this install's own loaded strings DO carry a matching
        item_Name entry (the item exists in the base game data, just never
        listed as a mission reward), the manual entry should use its real
        tag/class/size/grade instead of the bare fallback."""
        entries = [_Entry("item_NamePOWR_XNTH_S01_QuadraCell", "[MIL-S1-A] QuadraCell", "Ship Items")]
        meta = build_blueprint_metadata(entries)
        qc = meta["QuadraCell"]
        assert qc.type == "Power Plant"
        assert (qc.cls, qc.size, qc.grade) == ("Military", "1", "A")
        assert qc.tagged_name == "[MIL-S1-A] QuadraCell"
        assert qc.missions == frozenset({"Limited time event reward"})

    def test_manual_item_picks_up_real_facets_under_non_square_enclosing(self):
        """Direct regression test for #352: Round/Curly/Angle enclosing
        styles left QuadraCell/QuadraCell MT/FR-66/FR-76 permanently
        untagged because parse_component_tag/normalize_item_name only ever
        understood Square brackets. With the actual configured enclosing
        threaded through, the real tag/facets resolve correctly."""
        entries = [_Entry("item_NamePOWR_XNTH_S01_QuadraCell", "(MIL-S1-A) QuadraCell", "Ship Items")]
        meta = build_blueprint_metadata(entries, enclosings=(("(", ")"),))
        qc = meta["QuadraCell"]
        assert qc.type == "Power Plant"
        assert (qc.cls, qc.size, qc.grade) == ("Military", "1", "A")
        assert qc.tagged_name == "(MIL-S1-A) QuadraCell"
        assert qc.missions == frozenset({"Limited time event reward"})

    def test_manual_item_picks_up_real_facets_under_none_enclosing_via_stock(self):
        """Direct regression test for #352's originally-unfixable case:
        "None (space only)" enclosing left QuadraCell permanently untagged
        even after Round/Curly/Angle were fixed, since there's no delimiter
        to guess by. With the item's known stock (pre-tag) value passed
        through as `default_values`, the diff-based recovery resolves the
        real tag/facets authoritatively."""
        entries = [_Entry("item_NamePOWR_XNTH_S01_QuadraCell", "MIL-S1-A QuadraCell", "Ship Items")]
        meta = build_blueprint_metadata(
            entries, default_values={"item_NamePOWR_XNTH_S01_QuadraCell": "QuadraCell"}
        )
        qc = meta["QuadraCell"]
        assert qc.type == "Power Plant"
        assert (qc.cls, qc.size, qc.grade) == ("Military", "1", "A")
        assert qc.tagged_name == "MIL-S1-A QuadraCell"
        assert qc.missions == frozenset({"Limited time event reward"})

    def test_mission_derived_item_is_not_overwritten_by_manual_entry(self):
        """If a manual item's name ever DOES turn up in a real mission's
        POTENTIAL BLUEPRINTS text (CIG could add one later), the real
        mission-derived entry must win, not the manual fallback."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- QuadraCell"
        entries = [
            _Entry("M_Title_001", "Real Mission", "Missions"),
            _Entry("M_Desc_001", desc, "Missions"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["QuadraCell"].missions == frozenset({"Real Mission"})

    def test_manual_items_do_not_duplicate_or_error_on_repeated_build(self):
        """Calling build twice (e.g. re-Extract) must be stable -- same
        result, no accumulation."""
        first = build_blueprint_metadata([])
        second = build_blueprint_metadata([])
        assert first == second


class TestBareTypeKeyConventions:
    """#266 follow-up: fuel nozzles and mining lasers don't follow the
    item_Name<code> / vehicle_Name prefix every other component uses, so
    Pass 1 never recognised their key as a Name entry -- tagged_name fell
    back to the untagged bare name in the Blueprint Tracker even though
    the enhancement generator's output (and the String Editor) showed the
    real tag correctly. ("Tags work right in string editor but not in
    blueprint tracker.")"""

    def test_fuel_nozzle_item_fuelnozzle_prefix_gets_tagged_name(self):
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- RN-7s"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_fuelnozzle_MISC_Standard_Name", "[FN] RN-7s", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["RN-7s"].tagged_name == "[FN] RN-7s"

    def test_fuel_nozzle_nozzle_fuelgiver_prefix_gets_tagged_name(self):
        """Regression guard: Greycat/Shubin nozzles ship under the
        Nozzle_FuelGiver_* convention, not item_fuelnozzle_*."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Marlin"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("Nozzle_FuelGiver_GRIN_NozzleSecure_Name", "[FN] Marlin", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Marlin"].tagged_name == "[FN] Marlin"

    def test_mining_laser_bare_key_gets_tagged_name(self):
        """Mining laser Name keys carry no "_Name" suffix at all -- the
        bare key (ending in the size code) IS the Name entry."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Lancet MH1 Mining Laser"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_Mining_MiningLaser_Greycat_1_S1",
                   "[ML-S1] Lancet MH1 Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Lancet MH1 Mining Laser"].tagged_name == "[ML-S1] Lancet MH1 Mining Laser"


class TestBulletNameMismatches:
    """A live mission body ("Crew Hasn't Checked In") reported bullets that
    don't match any real item_Name value at all -- two different root
    causes, both fixed here (#266 follow-up)."""

    def test_key_slug_fallback_resolves_garbled_bullet_name(self):
        """CIG's own bug: the bullet lists the de-slugified loc KEY instead
        of the item's real localized name -- "Nozzle Fuelgiver Grin
        Nozzleveryfast" for a key whose real value is "Lindstrom". This is
        deterministic (title-case each underscore segment, drop a trailing
        "_Name" segment first), so it's resolved generically rather than
        via a hardcoded alias."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- Nozzle Fuelgiver Grin Nozzleveryfast"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("Nozzle_FuelGiver_GRIN_NozzleVeryFast_Name", "Lindstrom", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "Lindstrom" in meta
        assert meta["Lindstrom"].tagged_name == "Lindstrom"
        assert "Nozzle Fuelgiver Grin Nozzleveryfast" not in meta

    def test_known_alias_resolves_helix_mismatch(self):
        """Not every mismatch is the key-slug bug -- "Helix" bears no
        relation to its key's slug at all, just an informal short name a
        mission author typed. The real item is "S0 Helix"."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Helix"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Helix_SCItem", "[Mining Laser] S0 Helix", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "S0 Helix" in meta
        assert meta["S0 Helix"].tagged_name == "[Mining Laser] S0 Helix"
        assert "Helix" not in meta

    @pytest.mark.regression
    def test_known_alias_resolves_hofstede_mismatch(self):
        """Same "Mining Head" bare-name pattern as Helix, reported
        separately in a live mission body -- confirms this isn't a
        one-off, it's the whole item family."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Hofstede"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Hofstede_SCItem", "[Mining Laser] S00 Hofstede", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "S00 Hofstede" in meta
        assert meta["S00 Hofstede"].tagged_name == "[Mining Laser] S00 Hofstede"
        assert "Hofstede" not in meta

    def test_known_aliases_cover_the_whole_mining_head_family(self):
        """Arbor and Klein share the same key convention as Helix/Hofstede
        (item_NameMining_Head_S00_<Name>_SCItem) -- added preemptively
        rather than waiting for each to be reported individually."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- Arbor\\n- Klein"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Arbor_SCItem", "[Mining Laser] S0 Arbor", "Ship Items"),
            _Entry("item_NameMining_Head_S00_Klein_SCItem", "Lawson Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["S0 Arbor"].tagged_name == "[Mining Laser] S0 Arbor"
        assert meta["Lawson Mining Laser"].tagged_name == "Lawson Mining Laser"
        assert "Arbor" not in meta
        assert "Klein" not in meta

    @pytest.mark.regression
    def test_known_aliases_cover_the_three_fuel_nozzles_key_slug_missed(self):
        """Most fuel nozzle variants resolve generically via _key_slug, but
        a live Blueprint Tracker screenshot showed these three still
        untagged/ungarbled after that fix -- their real underlying key
        apparently doesn't follow the Nozzle_FuelGiver_<MFR>_Nozzle
        <Variant>_Name pattern the others do, so they need explicit
        aliases like Helix/Hofstede."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- Nozzle Fuelgiver Grin Nozzlefast"
            "\\n- Nozzle Fuelgiver Grin Nozzleverysecure"
            "\\n- Nozzle Fuelgiver Misc Nozzlestandard"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_fuelnozzle_GRIN_Fast_Name", "Norfield", "Ship Items"),
            _Entry("item_fuelnozzle_GRIN_Safe_Name", "Harkin", "Ship Items"),
            _Entry("item_fuelnozzle_MISC_Standard_Name", "RN-7s", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Norfield"].tagged_name == "Norfield"
        assert meta["Harkin"].tagged_name == "Harkin"
        assert meta["RN-7s"].tagged_name == "RN-7s"
        assert "Nozzle Fuelgiver Grin Nozzlefast" not in meta
        assert "Nozzle Fuelgiver Grin Nozzleverysecure" not in meta
        assert "Nozzle Fuelgiver Misc Nozzlestandard" not in meta

    @pytest.mark.regression
    def test_raw_blueprint_filename_bullet_resolves_via_alias(self):
        """A different root cause than the key-slug bug above: some mission
        text ships the raw blueprint XML filename stem verbatim rather than
        a de-slugified loc key. Confirmed via the real "URGENT REFUEL
        REQUEST" (UWC_Refueling_*) mission bodies in
        tests/fixtures/kraken_global_latest.ini, which list
        "bp_craft_nozzle_fuelgiver_grin_nozzleverysecure" (lowercase, with
        the bp_craft_ prefix, plus the "(Fuel Nozzle)" category annotation)
        instead of "Harkin" -- a shape _key_slug's title-cased-KEY transform
        never produces, so it silently fell through to itself even though
        the alias table already had the right answer."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- bp_craft_nozzle_fuelgiver_grin_nozzlefast (Fuel Nozzle)"
            "\\n- bp_craft_nozzle_fuelgiver_grin_nozzleverysecure (Fuel Nozzle)"
            "\\n- bp_craft_nozzle_fuelgiver_misc_nozzlestandard (Fuel Nozzle)"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_fuelnozzle_GRIN_Fast_Name", "Norfield", "Ship Items"),
            _Entry("item_fuelnozzle_GRIN_Safe_Name", "Harkin", "Ship Items"),
            _Entry("item_fuelnozzle_MISC_Standard_Name", "RN-7s", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Norfield"].tagged_name == "Norfield"
        assert meta["Harkin"].tagged_name == "Harkin"
        assert meta["RN-7s"].tagged_name == "RN-7s"
        assert "bp_craft_nozzle_fuelgiver_grin_nozzlefast" not in meta
        assert "bp_craft_nozzle_fuelgiver_grin_nozzleverysecure" not in meta
        assert "bp_craft_nozzle_fuelgiver_misc_nozzlestandard" not in meta

    def test_direct_match_is_not_overridden_by_alias_or_keyslug(self):
        """A bullet name that already matches a real item directly must
        win outright -- the alias/keyslug fallback only kicks in when the
        direct match fails."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Pitman Mining Laser"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Pitman_SCItem", "Pitman Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Pitman Mining Laser"].tagged_name == "Pitman Mining Laser"

    def test_unresolvable_bullet_name_falls_back_to_other(self):
        """A bullet name matching neither a real item, a known alias, nor
        any key's slug still shows up (as an untagged "Other" entry)
        rather than being silently dropped."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Totally Unknown Widget"
        meta = build_blueprint_metadata([_Entry("M_Desc_001", desc, "Missions")])
        assert "Totally Unknown Widget" in meta
        assert meta["Totally Unknown Widget"].type == "Other"
