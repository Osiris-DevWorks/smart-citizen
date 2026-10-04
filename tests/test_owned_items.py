"""Owned-blueprint tagging core (#157)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.owned_items import (  # noqa: E402
    BULLET_NAME_ALIASES,
    NONE_STYLE_ENCLOSING,
    apply_owned_to_value,
    enclosings_from_tag_configs,
    extract_bp_item_names,
    has_bp_section,
    normalize_item_name,
    strip_via_stock_diff,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# A realistic BP-bearing mission description value (literal \n separators).
_DESC = (
    "POSTING: salvage run.\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
    "\\n- Antium Core\\n- [Mil-S1-A] Norfield\\n- Abrade Scraper Module"
    "\\n\\n<EM3>MISSION DETAILS</EM3>\\n<EM4>Difficulty:</EM4> 3"
)

# A mission body reproducing the real false-positive bug: a stray "- Stows"
# bullet in the prose BEFORE the header, multi-region sub-headers WITHIN the
# blueprints section (which must still work), and a real bullet in a LATER
# section (ITEM REWARDS' "- Council Scrip") that isn't a blueprint either.
_DESC_WITH_FALSE_POSITIVES = (
    "Handle this right and I'll give the main contractor Council Scrip."
    "\\n\\n- Stows"
    "\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
    "\\n<EM4>[Nyx]</EM4>\\n- Cryo-Star SL\\n- Kelvid"
    "\\n\\n<EM4>[Pyro]</EM4>\\n- DuraJet\\n- ZapJet"
    "\\n\\n<EM3>ITEM REWARDS</EM3>\\n- Council Scrip"
    "\\n\\n<EM3>MISSION DETAILS</EM3>\\n<EM4>Difficulty:</EM4> 3"
)


class TestNormalize:
    def test_strips_leading_component_tag(self):
        assert normalize_item_name("[Mil-S1-A] Norfield") == "Norfield"

    def test_strips_owned_tag(self):
        assert normalize_item_name("Antium Core <EM4>[Owned]</EM4>") == "Antium Core"

    def test_bare_name_unchanged(self):
        assert normalize_item_name("Antium Core") == "Antium Core"

    def test_folds_short_bullet_name_onto_real_item_name(self):
        """#346: the generator strips CIG's leading size prefix from
        blueprint-list output, so a mission bullet reads "Hofstede" while
        the item (and therefore the owned set) is "S00 Hofstede". Both
        sides must fold to the same key or the bullet never matches."""
        assert normalize_item_name("Hofstede") == "S00 Hofstede"
        assert normalize_item_name("Helix") == "S0 Helix"
        assert normalize_item_name("Klein") == "Lawson Mining Laser"

    def test_alias_fold_is_idempotent(self):
        """The real name must not itself be an alias key, or normalizing
        twice would walk the chain and land somewhere else."""
        for real in BULLET_NAME_ALIASES.values():
            assert normalize_item_name(real) == real

    def test_alias_fold_runs_after_tag_and_annotation_strips(self):
        """A decorated bullet reduces to the bare name first, then aliases."""
        assert normalize_item_name("[Mining Laser-S0] Hofstede") == "S00 Hofstede"
        assert normalize_item_name("Hofstede (Mining Laser)") == "S00 Hofstede"
        assert normalize_item_name("Hofstede <EM4>[Owned]</EM4>") == "S00 Hofstede"

    def test_unaliased_names_pass_through(self):
        assert normalize_item_name("Norfield") == "Norfield"
        assert normalize_item_name("Ferron Repeater") == "Ferron Repeater"

    def test_tagged_bullet_matches_bare_row(self):
        # The whole point: a tagged bullet and the bare item row normalize equal.
        assert normalize_item_name("[Mil-S1-A] Norfield") == normalize_item_name("Norfield")

    # ── #222: fold log-imported blueprint names onto the same identity ────────
    def test_strips_trailing_component_tag(self):
        # SC's blueprint log puts the tag after some ship-component names.
        assert normalize_item_name("Barbican [IND-S3-B]") == "Barbican"

    def test_nfkc_folds_non_breaking_space(self):
        # Log names arrive with U+00A0 where loc data has a plain space.
        assert normalize_item_name("Lynx" + chr(0xA0) + "Legs") == "Lynx Legs"

    def test_collapses_internal_whitespace(self):
        assert normalize_item_name("F55  LMG   Magazine") == "F55 LMG Magazine"

    def test_leading_and_trailing_tag_together(self):
        assert normalize_item_name("[E-S2] Omnisky VI Cannon") == "Omnisky VI Cannon"

    def test_empty_value(self):
        assert normalize_item_name("") == ""

    def test_log_name_matches_mission_bullet(self):
        # The #222 contract: a raw log name folds to the same key a mission
        # bullet does, so importing the log name lights up the bullet.
        nbsp = normalize_item_name("Lynx" + chr(0xA0) + "Legs")
        assert nbsp == normalize_item_name("- Lynx Legs".lstrip("- "))
        assert normalize_item_name("Barbican [IND-S3-B]") == \
            normalize_item_name("[IND-S3-B] Barbican")

    # ── #266 follow-up: bullet-only category annotations ──────────────────────
    def test_strips_trailing_category_annotation(self):
        """CIG's own POTENTIAL BLUEPRINTS bullet text appends a category
        annotation to some items (confirmed via tests/fixtures/
        kraken_global_latest.ini) that never appears on the item's own
        item_Name value -- left unstripped, the bullet never matches the
        real (tagged) item."""
        assert normalize_item_name("Bendix (Fuel Nozzle)") == "Bendix"
        assert normalize_item_name("Arbor MH1 Mining Laser (Mining Laser)") == "Arbor MH1 Mining Laser"
        assert normalize_item_name("Trawler Scraper Module (Salvage Mod)") == "Trawler Scraper Module"
        assert normalize_item_name("5CA 'Akura' (Shield)") == "5CA 'Akura'"

    def test_category_annotation_matches_bare_item_name(self):
        assert normalize_item_name("Bendix (Fuel Nozzle)") == normalize_item_name("Bendix")

    def test_unrecognized_parenthetical_is_kept(self):
        """Not every trailing parenthetical is a bullet-only annotation --
        some are part of the item's own real distinguishing name (e.g. a
        "(Modified)" armor variant). Only the small allow-listed category
        words get stripped; anything else survives untouched."""
        assert normalize_item_name("Artimex Arms (Modified)") == "Artimex Arms (Modified)"
        assert normalize_item_name("Ballistic Gatling (x2)") == "Ballistic Gatling (x2)"

    # -- #352: configurable enclosing styles ---------------------------------

    def test_default_enclosings_unchanged_from_hardcoded_square(self):
        """Regression guard: omitting `enclosings` must behave exactly like
        the original hardcoded Square-only implementation."""
        assert normalize_item_name("[Mil-S1-A] Norfield") == "Norfield"
        assert normalize_item_name("Barbican [IND-S3-B]") == "Barbican"

    def test_strips_leading_tag_round_enclosing(self):
        assert normalize_item_name(
            "(Mil-S1-A) Norfield", enclosings=(("(", ")"),)
        ) == "Norfield"

    def test_strips_trailing_tag_curly_enclosing(self):
        assert normalize_item_name(
            "Barbican {IND-S3-B}", enclosings=(("{", "}"),)
        ) == "Barbican"

    def test_strips_leading_tag_angle_enclosing(self):
        assert normalize_item_name(
            "<Mil-S1-A> Norfield", enclosings=(("<", ">"),)
        ) == "Norfield"

    def test_square_tag_untouched_when_only_round_configured(self):
        """A style NOT in the active set is never stripped -- proves this
        fix targets only the actually-configured style(s), not "any bracket
        shape at all"."""
        assert normalize_item_name(
            "[Mil-S1-A] Norfield", enclosings=(("(", ")"),)
        ) == "[Mil-S1-A] Norfield"

    def test_configured_non_square_enclosing_can_collide_with_real_parenthetical_name(self):
        """Accepted, documented residual risk: Round/Curly/Angle punctuation
        sometimes appears in a REAL item name (unlike Square, which never
        does in Star Citizen's own text). If a category is actively
        reconfigured to Round, a real "(...)" suffix in that same context
        will be stripped as if it were a tag -- this is an inherent, opt-in
        ambiguity from the user's own configuration choice, not a bug."""
        assert normalize_item_name(
            "Artimex Arms (Modified)", enclosings=(("(", ")"),)
        ) == "Artimex Arms"

    def test_none_enclosing_stripped_via_stock_diff(self):
        """A known stock (pre-tag) value recovers a "None (space only)" tag
        authoritatively via diffing -- no delimiter needed at all (#352)."""
        assert normalize_item_name("Mil-S1-A Norfield", stock="Norfield") == "Norfield"

    def test_none_enclosing_stripped_via_heuristic_without_stock(self):
        """Without a stock value, the conservative heuristic still catches
        the common case: a leading/trailing word with an embedded Tag
        Builder separator char plus a size/grade-shaped sub-token.

        Requires the None style to actually be among the configured
        enclosings -- see test_none_style_heuristic_is_off_unless_configured
        for why it is no longer unconditional.
        """
        none_cfg = (("[", "]"), NONE_STYLE_ENCLOSING)
        assert normalize_item_name("Mil-S1-A Norfield", none_cfg) == "Norfield"
        assert normalize_item_name("Norfield Mil-S1-A", none_cfg) == "Norfield"

    def test_none_style_heuristic_is_off_unless_configured(self):
        """The heuristic strips a word carrying a separator char plus an
        S<digits>/lone-A-F token, and real item names can take that shape.
        Running it for users who never selected None enclosing spent that
        risk on people who got nothing back for it, so it is now gated on
        the style actually being configured.

        "F-4 Blaster" is the demonstration: realistic in shape (single-letter
        designators are common), and reduced to "Blaster" by the ungated
        version. Two names collapsing onto one key is a wrong [Owned] tag on
        an item the user does not own.
        """
        assert normalize_item_name("F-4 Blaster") == "F-4 Blaster"
        assert normalize_item_name("Mil-S1-A Norfield") == "Mil-S1-A Norfield"
        # ...and still stripped for a user who did configure None style.
        none_cfg = (("[", "]"), NONE_STYLE_ENCLOSING)
        assert normalize_item_name("Mil-S1-A Norfield", none_cfg) == "Norfield"

    def test_none_style_pair_does_not_break_bracket_matching(self):
        """The delimiter-less pair rides along in the same tuple as the real
        bracket pairs, so _build_tag_patterns has to skip it rather than
        build a degenerate alternative from two empty strings."""
        cfg = (("[", "]"), NONE_STYLE_ENCLOSING)
        assert normalize_item_name("[Mil-S1-A] Norfield", cfg) == "Norfield"
        assert normalize_item_name("Norfield [Mil-S1-A]", cfg) == "Norfield"

    def test_none_enclosing_without_separator_or_stock_is_unrecoverable(self):
        """A "None"-style tag whose elements are joined by a plain space
        (separator="space") has no embedded punctuation for the heuristic to
        key off, and with no stock value to diff against either, this stays
        a genuine, accepted gap -- not every configuration is recoverable."""
        assert normalize_item_name("Military S2 A Norfield") == "Military S2 A Norfield"

    def test_empty_enclosings_tuple_is_a_noop(self):
        assert normalize_item_name("[X] Name", enclosings=()) == "[X] Name"

    def test_heuristic_does_not_misfire_on_leading_numeric_hyphen_word(self):
        """Regression guard: an earlier, looser heuristic (bare digit runs
        counted as "size-shaped") misfired on this exact real item name --
        "10-Series" has a hyphen but its digits aren't S-prefixed, so it
        must NOT be treated as a tag word (#352)."""
        assert normalize_item_name("10-Series Greatsword Cannon") == "10-Series Greatsword Cannon"

    def test_heuristic_does_not_misfire_on_messy_raw_whitespace(self):
        """Regression guard for an earlier marker-based attempt at this fix,
        which broke on exactly this case: real Game.log-scraped names can
        already carry irregular multi-space runs unrelated to any tag."""
        assert normalize_item_name("F55  LMG   Magazine") == "F55 LMG Magazine"

    def test_stock_diff_takes_priority_over_bracket_and_heuristic(self):
        """When a stock value is available, it wins outright -- even over a
        bracketed tag, since diffing is authoritative and bracket-matching
        is still a guess by comparison."""
        assert normalize_item_name(
            "[Mil-S1-A] Norfield", stock="Norfield"
        ) == "Norfield"

    def test_stock_not_found_falls_back_to_bracket_stripping(self):
        """A stock value that doesn't actually appear in the tagged value
        (e.g. a non-English install, where default_values is always
        English) must not corrupt the result -- falls through to the
        existing bracket-based path instead."""
        assert normalize_item_name(
            "[Mil-S1-A] Norfield", stock="Something Else Entirely"
        ) == "Norfield"

    def test_stock_diff_prepend_and_append(self):
        assert strip_via_stock_diff("Mil-S1-A Norfield", "Norfield") == "Mil-S1-A"
        assert strip_via_stock_diff("Norfield Mil-S1-A", "Norfield") == "Mil-S1-A"

    def test_stock_diff_no_match_returns_none(self):
        assert strip_via_stock_diff("Something Unrelated", "Norfield") is None

    def test_stock_diff_untagged_returns_empty_string(self):
        assert strip_via_stock_diff("Norfield", "Norfield") == ""

    def test_stock_diff_empty_stock_returns_none(self):
        assert strip_via_stock_diff("Mil-S1-A Norfield", "") is None


class TestEnclosingsFromTagConfigs:
    class _FakeCfg:
        def __init__(self, enclosing):
            self.enclosing = enclosing

    def test_default_categories_ignore_commodities_and_mission_titles(self):
        tag_configs = {
            "components": self._FakeCfg("square"),
            "missiles": self._FakeCfg("square"),
            "ship_weapons": self._FakeCfg("square"),
            "commodities": self._FakeCfg("round"),
            "mission_titles": self._FakeCfg("curly"),
        }
        result = enclosings_from_tag_configs(tag_configs)
        assert ("(", ")") not in result
        assert ("{", "}") not in result

    def test_square_always_present_even_when_unconfigured(self):
        tag_configs = {
            "components": self._FakeCfg("round"),
            "missiles": self._FakeCfg("round"),
            "ship_weapons": self._FakeCfg("round"),
        }
        result = enclosings_from_tag_configs(tag_configs)
        assert ("[", "]") in result

    def test_dedups_shared_style(self):
        tag_configs = {
            "components": self._FakeCfg("round"),
            "missiles": self._FakeCfg("round"),
            "ship_weapons": self._FakeCfg("square"),
        }
        result = enclosings_from_tag_configs(tag_configs)
        assert result.count(("(", ")")) == 1

    def test_fresh_install_defaults_to_square_only(self):
        tag_configs = {
            "components": self._FakeCfg("square"),
            "missiles": self._FakeCfg("square"),
            "ship_weapons": self._FakeCfg("square"),
        }
        assert enclosings_from_tag_configs(tag_configs) == (("[", "]"),)


class TestExtract:
    def test_finds_normalized_bullet_names(self):
        names = extract_bp_item_names(_DESC)
        assert names == {"Antium Core", "Norfield", "Abrade Scraper Module"}

    def test_no_section_returns_empty(self):
        assert extract_bp_item_names("Just a plain description, no rewards.") == set()

    def test_empty_value(self):
        assert extract_bp_item_names("") == set()

    # -- #353: renamed "blueprints" mission header ---------------------------

    def test_renamed_header_not_recognized_by_default(self):
        """Regression guard: without bp_header, a renamed header is invisible
        -- pins the pre-fix behavior so the fix below is a real change."""
        renamed = _DESC.replace("POTENTIAL BLUEPRINTS", "MY LOOT")
        assert extract_bp_item_names(renamed) == set()

    def test_renamed_header_recognized_when_bp_header_passed(self):
        renamed = _DESC.replace("POTENTIAL BLUEPRINTS", "MY LOOT")
        names = extract_bp_item_names(renamed, bp_header="MY LOOT")
        assert names == {"Antium Core", "Norfield", "Abrade Scraper Module"}

    def test_bp_header_matching_is_case_insensitive(self):
        renamed = _DESC.replace("POTENTIAL BLUEPRINTS", "my loot")
        names = extract_bp_item_names(renamed, bp_header="My Loot")
        assert names == {"Antium Core", "Norfield", "Abrade Scraper Module"}

    def test_bp_header_still_recognizes_default_when_not_renamed(self):
        """Passing bp_header must not stop the built-in default from still
        working for missions that never got regenerated since the rename."""
        names = extract_bp_item_names(_DESC, bp_header="MY LOOT")
        assert names == {"Antium Core", "Norfield", "Abrade Scraper Module"}

    def test_renamed_header_word_appearing_unwrapped_in_prose_is_not_a_false_positive(self):
        """Real report: renaming the header to a short/common word ("stuff")
        let it accidentally match an unrelated, unwrapped occurrence of that
        same word elsewhere in the mission's own prose (a stray "- <name>"
        bullet list), starting the scan window too early and sweeping
        unrelated prose bullets ("Ed", "H", "Wallace", ...) into the item
        set as if they were real blueprints. The header match must be
        anchored to the actual <EM3>/<EM4> wrapper the generator always uses
        (see _build_bp_header_re), not a bare substring search, so an
        earlier unwrapped occurrence of the same text is correctly ignored.
        """
        desc = (
            "Grab that stuff for me.\\n- Ed\\n- H\\n- Wallace"
            "\\n\\n<EM3>stuff</EM3>\\n- Antium Core"
        )
        names = extract_bp_item_names(desc, bp_header="stuff")
        assert names == {"Antium Core"}

    # CIG qualifies its own headers, and every one of these appears in
    # tests/fixtures/kraken_global_latest.ini. Anchoring the match to an
    # <EM3>/<EM4> wrapper that may hold ONLY the header text dropped all of
    # them (20 of the fixture's 292 header-bearing lines), which is the same
    # "mission silently absent from the Blueprint Tracker" failure #353 is
    # about, just for a different subset. Every hand-written test above still
    # passed, because none of them used a real CIG header.
    @pytest.mark.parametrize("header_text", [
        "Potential Blueprints (Repeat Only)",
        "Potential Blueprints (BitZeros Only)",
        "Potential Blueprints (Nyx Only)",
        "Potential Blueprints (Pyro IV/V Area Only)",
        "Multiple Blueprint Pools (Repeat Only)",
        "Multiple Blueprint Pools (Yormandi Eye Only)",
    ])
    def test_cig_qualified_headers_are_recognized(self, header_text):
        nl = chr(92) + "n"
        val = f"flavor text{nl}<EM4>{header_text}</EM4>{nl}- Antium Core"
        assert extract_bp_item_names(val) == {"Antium Core"}

    def test_qualifier_tolerance_does_not_admit_unrelated_wrapped_text(self):
        """The optional qualifier must stay bounded to a parenthesised run, or
        it would undo the very false-positive guard the wrapper anchor exists
        for: a header renamed to a common word must not match prose that
        merely starts with it."""
        nl = chr(92) + "n"
        val = f"x{nl}<EM3>stuffed animals</EM3>{nl}- Antium Core"
        assert extract_bp_item_names(val, bp_header="stuff") == set()

    def test_fixture_header_recognition_matches_bare_substring_search(self):
        """Parity guard against the real CIG data.

        The regression this pins was invisible to every hand-written case, so
        it is checked against the shipped fixture instead: whatever the
        anchored pattern does, it must not recognise FEWER header-bearing
        lines than a naive substring search for the two built-in headers.
        """
        import re
        from pathlib import Path
        # Same `utils.` import path this module already uses at the top --
        # `utils.owned_items` and `src.utils.owned_items` are distinct module
        # objects under this repo's dual pythonpath.
        from utils.owned_items import (
            _ALT_BP_SECTION_HEADER, _build_bp_header_re, BP_SECTION_HEADER,
        )

        fixture = Path(__file__).parent / "fixtures" / "kraken_global_latest.ini"
        if not fixture.exists():                       # optional large fixture
            pytest.skip("kraken_global_latest.ini not present")
        lines = [l for l in fixture.read_text(encoding="utf-8", errors="replace")
                 .splitlines() if "=" in l]
        bare = re.compile(
            "(?:" + re.escape(BP_SECTION_HEADER) + "|"
            + re.escape(_ALT_BP_SECTION_HEADER) + ")", re.IGNORECASE)
        anchored = _build_bp_header_re(None)
        missed = [l for l in lines if bare.search(l) and not anchored.search(l)]
        assert not missed, (
            f"{len(missed)} header-bearing lines in the real fixture are no "
            f"longer recognised, e.g. {missed[0][:160]!r}"
        )

    def test_excludes_prose_bullet_before_header_and_later_section_bullet(self):
        """A stray "- Stows" line in the mission's flavor-text prose (before
        the POTENTIAL BLUEPRINTS header) and a real bullet in a later ITEM
        REWARDS section ("- Council Scrip") must not be picked up as
        blueprint items — only bullets between the header and the next real
        section boundary count."""
        names = extract_bp_item_names(_DESC_WITH_FALSE_POSITIVES)
        assert names == {"Cryo-Star SL", "Kelvid", "DuraJet", "ZapJet"}
        assert "Stows" not in names
        assert "Council Scrip" not in names

    def test_multi_region_sub_headers_still_included(self):
        """<EM4>[System]</EM4> per-region sub-headers inside the blueprints
        section must not be mistaken for a section boundary."""
        names = extract_bp_item_names(_DESC_WITH_FALSE_POSITIVES)
        assert {"Cryo-Star SL", "Kelvid"} <= names  # [Nyx] region
        assert {"DuraJet", "ZapJet"} <= names        # [Pyro] region

    @pytest.mark.regression
    def test_awarded_from_tier_sub_headers_not_mistaken_for_section_end(self):
        """Reputation-tiered contracts (Adagio Industrial salvage, Bounty
        Hunters Guild, Security, ...) group POTENTIAL BLUEPRINTS bullets
        under an "Awarded from X level variants" sub-header *inside* the
        section, sometimes repeated for multiple tiers in one mission body.
        Pre-fix, the first such sub-header was mistaken for a genuine
        section boundary (it doesn't start with "[" like a region label
        does), truncating the span before any bullets were ever reached --
        so items awarded this way (Scraper Modules among others) never
        surfaced in the Blueprint Tracker at all, tag or no tag."""
        desc = (
            "Adagio Holdings...\\n\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n<EM4>Awarded from Contractor level variants</EM4>"
            "\\n- Trawler Scraper Module (Salvage Mod)"
            "\\n- Abrade Scraper Module (Salvage Mod)"
            "\\n- Cinch Scraper Module (Salvage Mod)"
        )
        names = extract_bp_item_names(desc)
        assert names == {"Trawler Scraper Module", "Abrade Scraper Module", "Cinch Scraper Module"}

    @pytest.mark.regression
    def test_multiple_awarded_from_tiers_in_one_body_all_included(self):
        """Some missions list several reputation tiers, each with its own
        sub-header + bullet group, in a single POTENTIAL BLUEPRINTS section."""
        desc = (
            "\\n\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n<EM4>Awarded from Jr. Contractor level variants</EM4>"
            "\\n- Cinch Scraper Module (Salvage Mod)"
            "\\n<EM4>Awarded from Contractor level variants</EM4>"
            "\\n- Trawler Scraper Module (Salvage Mod)"
            "\\n- Abrade Scraper Module (Salvage Mod)"
            "\\n\\n<EM3>MISSION DETAILS</EM3>\\n<EM4>Difficulty:</EM4> 2"
        )
        names = extract_bp_item_names(desc)
        assert names == {"Cinch Scraper Module", "Trawler Scraper Module", "Abrade Scraper Module"}

    @pytest.mark.regression
    def test_multiple_blueprint_pools_header_recognised(self):
        """CIG uses a second, entirely different section header ("MULTIPLE
        BLUEPRINT POOLS") for missions offering more than one blueprint
        pool -- confirmed via tests/fixtures/kraken_global_latest.ini: 35
        missions use it (e.g. mining-laser purchase-order contracts that
        award a weapon/armor Pool 1 alongside a mining-laser/radar Pool 2).
        Pre-fix, only "POTENTIAL BLUEPRINTS" was recognised at all, so
        these missions were never scanned -- not just untagged, their
        items were entirely absent from the Blueprint Tracker."""
        desc = (
            "POSTING: Purchase Order...\\n\\n<EM4>Multiple Blueprint Pools</EM4>"
            "\\n<EM4>Awarded from Sr. Contractor level variants</EM4>"
            "\\n<EM4>Pool 1</EM4>"
            "\\n- Arclight Pistol\\n- Venture Arms Base"
            "\\n\\n<EM4>Pool 2</EM4>"
            "\\n- Helix I Mining Laser (Mining Laser)\\n- BroadSpec (Radar)"
        )
        names = extract_bp_item_names(desc)
        assert names == {
            "Arclight Pistol", "Venture Arms Base",
            "Helix I Mining Laser", "BroadSpec",
        }

    def test_has_bp_section_recognises_both_headers(self):
        assert has_bp_section("x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Foo")
        assert has_bp_section("x\\n<EM4>Multiple Blueprint Pools</EM4>\\n- Foo")
        assert not has_bp_section("A description with no rewards section")
        assert not has_bp_section("")


class TestApply:
    def test_tags_only_owned_bullets(self):
        out = apply_owned_to_value(_DESC, {"Antium Core"})
        assert "- Antium Core <EM4>[Owned]</EM4>" in out
        assert "- [Mil-S1-A] Norfield\\n" in out  # not owned -> untagged

    def test_tags_owned_via_normalized_match_through_component_tag(self):
        out = apply_owned_to_value(_DESC, {"Norfield"})
        assert "- [Mil-S1-A] Norfield <EM4>[Owned]</EM4>" in out

    def test_idempotent(self):
        once = apply_owned_to_value(_DESC, {"Antium Core"})
        twice = apply_owned_to_value(once, {"Antium Core"})
        assert once == twice
        assert once.count("[Owned]") == 1

    def test_unowning_removes_tag(self):
        tagged = apply_owned_to_value(_DESC, {"Antium Core"})
        cleared = apply_owned_to_value(tagged, set())
        assert "[Owned]" not in cleared
        assert cleared == _DESC

    def test_tags_size_prefixed_item_from_its_short_bullet(self):
        """#346 end to end: the user owns "S00 Hofstede" (the tracker's
        name for it), the mission bullet says "Hofstede", and the [Owned]
        tag must still land. Before the fix the two never matched, so the
        item showed as owned in the tracker but its in-game bullet stayed
        untagged."""
        desc = (
            "POSTING: mining run.\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
            "\\n- Hofstede\\n- Helix\\n- Norfield"
        )
        out = apply_owned_to_value(desc, {normalize_item_name("S00 Hofstede")})
        assert "- Hofstede <EM4>[Owned]</EM4>" in out
        assert "- Helix\\n" in out          # owned set doesn't include it
        assert out.count("[Owned]") == 1

    def test_no_bp_section_only_strips_stale_owned(self):
        v = "A plain line\\n- not a blueprint bullet <EM4>[Owned]</EM4>"
        out = apply_owned_to_value(v, {"whatever"})
        assert "[Owned]" not in out

    def test_empty_owned_set_strips_and_returns(self):
        tagged = apply_owned_to_value(_DESC, {"Antium Core"})
        assert "[Owned]" not in apply_owned_to_value(tagged, set())

    def test_does_not_retag_bullets_outside_the_blueprints_section(self):
        """Even if a user's owned set happens to contain "Council Scrip" or
        "Stows" (e.g. imported from a stray log line), retagging must stay
        scoped to the POTENTIAL BLUEPRINTS section — a prose bullet or a
        later-section bullet is never a real blueprint slot to tag."""
        out = apply_owned_to_value(_DESC_WITH_FALSE_POSITIVES, {"Kelvid", "Council Scrip", "Stows"})
        assert "- Kelvid <EM4>[Owned]</EM4>" in out
        assert "- Council Scrip <EM4>[Owned]</EM4>" not in out
        assert "- Stows <EM4>[Owned]</EM4>" not in out
        # Untouched text still present, just not retagged.
        assert "- Council Scrip" in out
        assert "- Stows" in out

    def test_tags_bullets_with_nbsp_and_trailing_tag(self):
        # #222: a bullet carrying a non-breaking space or a trailing component
        # tag still matches an owned entry stored in bare/plain form.
        nl = chr(92) + "n"
        val = ("<EM3>POTENTIAL BLUEPRINTS</EM3>" + nl + "- Lynx" + chr(0xA0) + "Legs"
               + nl + "- Barbican [IND-S3-B]" + nl + "- Norfield")
        out = apply_owned_to_value(val, {"Lynx Legs", "Barbican"})
        assert out.count("<EM4>[Owned]</EM4>") == 2
        assert "Norfield <EM4>[Owned]" not in out  # not owned
        assert apply_owned_to_value(out, {"Lynx Legs", "Barbican"}) == out  # idempotent


# ── AppSettings owned-set persistence + model rendering ──────────────────────

import os as _os  # noqa: E402
_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class TestOwnedSettings:
    def test_default_empty(self, isolated_settings):
        assert AppSettings.get_owned_items() == set()

    def test_roundtrip_single_item(self, isolated_settings):
        # The JSON-string backing must survive a single-item set (a raw list in
        # QSettings would come back mangled).
        AppSettings.set_owned_items({"Antium Core"})
        assert AppSettings.get_owned_items() == {"Antium Core"}

    def test_toggle(self, isolated_settings):
        assert AppSettings.toggle_owned_item("Norfield") is True
        assert "Norfield" in AppSettings.get_owned_items()
        assert AppSettings.toggle_owned_item("Norfield") is False
        assert "Norfield" not in AppSettings.get_owned_items()


class TestBlueprintWatermark:
    """#222: per-channel BP Scan watermark round-trip."""

    def test_default_none(self, isolated_settings):
        assert AppSettings.get_blueprint_log_watermark() is None

    def test_roundtrip_preserves_utc_instant(self, isolated_settings):
        from datetime import datetime, timezone
        when = datetime(2026, 3, 26, 17, 15, 41, 684000, tzinfo=timezone.utc)
        AppSettings.set_blueprint_log_watermark(when)
        assert AppSettings.get_blueprint_log_watermark() == when

    def test_per_channel_isolation(self, isolated_settings, monkeypatch):
        from datetime import datetime, timezone
        live = datetime(2026, 4, 1, tzinfo=timezone.utc)
        ptu = datetime(2026, 5, 1, tzinfo=timezone.utc)

        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))
        AppSettings.set_blueprint_log_watermark(live)
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "PTU"))
        assert AppSettings.get_blueprint_log_watermark() is None  # PTU untouched
        AppSettings.set_blueprint_log_watermark(ptu)

        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))
        assert AppSettings.get_blueprint_log_watermark() == live  # LIVE unchanged by PTU write

    def test_garbage_value_returns_none(self, isolated_settings):
        AppSettings.settings().setValue(
            AppSettings._blueprint_watermark_key(), "not-a-timestamp"
        )
        assert AppSettings.get_blueprint_log_watermark() is None

    def test_explicit_channel_param_isolated_from_active_channel(self, isolated_settings, monkeypatch):
        """#268: a multi-channel scan targets LIVE's and HOTFIX's watermarks
        by explicit channel name, without ever touching active_channel."""
        from datetime import datetime, timezone
        live = datetime(2026, 4, 1, tzinfo=timezone.utc)
        hotfix = datetime(2026, 5, 1, tzinfo=timezone.utc)

        # Active channel is something else entirely, so the no-arg (default)
        # form reading "None" below proves these explicit writes never fell
        # through to active_channel's own slot.
        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "PTU"))

        AppSettings.set_blueprint_log_watermark(live, channel="LIVE")
        AppSettings.set_blueprint_log_watermark(hotfix, channel="HOTFIX")

        assert AppSettings.get_blueprint_log_watermark(channel="LIVE") == live
        assert AppSettings.get_blueprint_log_watermark(channel="HOTFIX") == hotfix
        # Neither write touched the active (PTU) channel's own watermark.
        assert AppSettings.get_blueprint_log_watermark() is None

    def test_explicit_channel_param_matches_active_channel_default(self, isolated_settings, monkeypatch):
        """Passing the active channel's own name explicitly must read/write
        the exact same slot as the no-argument (default) form."""
        from datetime import datetime, timezone
        when = datetime(2026, 6, 1, tzinfo=timezone.utc)

        monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))
        AppSettings.set_blueprint_log_watermark(when, channel="LIVE")
        assert AppSettings.get_blueprint_log_watermark() == when


class TestModelOwnedColumn:
    def _model(self, qapp):
        from src.gui.string_table_model import StringTableModel
        from src.models.string_model import StringEntry
        m = StringTableModel()
        item = StringEntry(key="item_NameNorfield", source_file="global",
                           category="Components", original_value="Norfield",
                           custom_value="", status="Unmodified")
        other = StringEntry(key="misc", source_file="global", category="Misc",
                            original_value="not an item", custom_value="", status="Unmodified")
        m.set_data_source([item, other], {}, "*")
        return m, item, other

    def test_star_only_on_bp_item_rows(self, qapp):
        from src.gui.string_table_model import COL_OWNED
        m, item, other = self._model(qapp)
        m.set_owned_state({"Norfield"}, set())
        item_row = m.source_row_for_entry_index(0)
        other_row = m.source_row_for_entry_index(1)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "☆"   # empty star
        assert m.data(m.index(other_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == ""        # non-item: blank

    def test_filled_star_when_owned(self, qapp):
        from src.gui.string_table_model import COL_OWNED
        m, item, other = self._model(qapp)
        m.set_owned_state({"Norfield"}, {"Norfield"})
        item_row = m.source_row_for_entry_index(0)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "★"   # filled star

    def test_filled_star_when_owned_under_non_square_enclosing(self, qapp):
        """#352: the Owned star must still resolve when an entry's own value
        carries a non-Square Tag Builder tag, provided the model was told
        about the active enclosing via set_owned_state."""
        from src.gui.string_table_model import COL_OWNED, StringTableModel
        from src.models.string_model import StringEntry
        m = StringTableModel()
        item = StringEntry(key="item_NameNorfield", source_file="global",
                           category="Components", original_value="(Mil-S1-A) Norfield",
                           custom_value="", status="Unmodified")
        m.set_data_source([item], {}, "*")
        m.set_owned_state({"Norfield"}, {"Norfield"}, enclosings=(("(", ")"),))
        item_row = m.source_row_for_entry_index(0)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "★"

    def test_filled_star_when_owned_under_none_enclosing_via_stock(self, qapp):
        """#352: "None (space only)" enclosing resolves via the entry's own
        stock (pre-tag) value, which the model already carries as
        `default_values` from set_data_source -- no enclosings config
        needed for this path since the diff is authoritative."""
        from src.gui.string_table_model import COL_OWNED, StringTableModel
        from src.models.string_model import StringEntry
        m = StringTableModel()
        item = StringEntry(key="item_NameNorfield", source_file="global",
                           category="Components", original_value="Mil-S1-A Norfield",
                           custom_value="", status="Unmodified")
        m.set_data_source([item], {"item_NameNorfield": "Norfield"}, "*")
        m.set_owned_state({"Norfield"}, {"Norfield"})
        item_row = m.source_row_for_entry_index(0)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "★"

    def test_sort_by_owned_floats_owned_to_top(self, qapp):
        # #189: clicking the Owned header must group owned items, like Favorites,
        # not sort stably by key. "Zeta" is owned but sorts after "Alpha"
        # alphabetically, so owned-first ordering is the only thing that puts
        # its row on top.
        from src.gui.string_table_model import COL_OWNED, StringTableModel
        from src.models.string_model import StringEntry

        owned = StringEntry(key="item_NameZeta", source_file="global",
                            category="Components", original_value="Zeta",
                            custom_value="", status="Unmodified")
        not_owned = StringEntry(key="item_NameAlpha", source_file="global",
                                category="Components", original_value="Alpha",
                                custom_value="", status="Unmodified")
        m = StringTableModel()
        m.set_data_source([owned, not_owned], {}, "*")
        m.set_owned_state({"Zeta", "Alpha"}, {"Zeta"})

        m.sort(COL_OWNED, Qt.SortOrder.AscendingOrder)
        assert m.entry_index_for_row(0) == 0   # owned "Zeta" on top despite key

        # The header arrow flips it: descending puts owned at the bottom.
        m.sort(COL_OWNED, Qt.SortOrder.DescendingOrder)
        assert m.entry_index_for_row(1) == 0
