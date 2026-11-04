"""Mission Titles Tag Builder feature (2.1): route formatting, placement,
config persistence, and the #166-toggle migration."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import (  # noqa: E402
    REMOVE_WORD_OPTIONS,
    SHORTEN_PHRASE_OPTIONS,
    SIZE_ABBREV_BY_WORD,
    SIZE_ABBREVIATIONS,
    UNDERLINE_OPTIONS,
    TagConfig,
    abbreviate_title,
    apply_mission_title,
    default_config,
    render_route,
    route_enabled,
)

_ALL_ABBREVIATION_KEYS = frozenset(k for k, *_ in SHORTEN_PHRASE_OPTIONS) | \
    frozenset(k for k, *_ in REMOVE_WORD_OPTIONS)
_ALL_SIZE_WORDS = frozenset(SIZE_ABBREV_BY_WORD)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestRouteFormatting:
    def test_render_route_both_single_and_arrow(self):
        assert render_route("A", "B", "gt") == "A > B"
        # "->" not U+2192: mobiGlas has no glyph for the real arrow (#200).
        assert render_route("A", "B", "arrow") == "A -> B"
        assert render_route("A", "B", "to") == "A to B"
        assert render_route("A", "", "gt") == "from A"
        assert render_route("", "B", "gt") == "to B"
        assert render_route("", "", "gt") == ""

    def test_shape_arrow_encodes_multiplicity(self):
        """#200 follow-up: "-" one endpoint, "=" several, per side."""
        assert render_route("A", "B", "shape") == "A ->- B"
        assert render_route("A", "B, C", "shape", to_many=True) == "A ->= B, C"
        assert render_route("A, B", "C", "shape", from_many=True) == "A, B =>- C"
        assert render_route("A, B", "C, D", "shape", True, True) == "A, B =>= C, D"
        # One-sided degenerates carry no arrow, so no shape glyph.
        assert render_route("A", "", "shape", to_many=True) == "from A"
        # Non-shape arrows ignore the multiplicity flags.
        assert render_route("A", "B, C", "gt", to_many=True) == "A > B, C"

    def test_apply_placements(self):
        cfg = default_config("mission_titles")  # dash separator, prepend
        cfg.placement = "prepend"
        assert apply_mission_title("Job", "A > B", cfg) == "A > B - Job"
        cfg.placement = "append"
        assert apply_mission_title("Job", "A > B", cfg) == "Job - A > B"
        cfg.placement = "replace"
        assert apply_mission_title("Job", "A > B", cfg) == "A > B"

    def test_empty_route_keeps_original_under_replace(self):
        cfg = default_config("mission_titles")
        cfg.placement = "replace"
        assert apply_mission_title("Job", "", cfg) == "Job"


class TestDefaultAndPersistence:
    def test_default_config_shape(self):
        cfg = default_config("mission_titles")
        assert route_enabled(cfg) is True
        # location_detail defaults to "address" since 2.1.1 (#200): |name
        # fails to resolve for some mission instances in-game. placement
        # defaults to "append" (route after the title, not before).
        assert (cfg.placement, cfg.route_arrow, cfg.title_separator, cfg.location_detail) \
            == ("append", "gt", "dash", "address")

    def test_from_dict_missing_location_detail_defaults_to_address(self):
        """Pre-2.1 saved blobs have no location_detail key at all; they must
        land on the safe |Address default, not the 2.1.0 "name" (#200)."""
        cfg = TagConfig.from_dict({"elements": [{"kind": "route", "enabled": True}]})
        assert cfg.location_detail == "address"

    def test_route_fields_round_trip(self):
        cfg = default_config("mission_titles")
        cfg.placement = "replace"
        cfg.route_arrow = "arrow"
        cfg.location_detail = "address"
        cfg.title_separator = "pipe"
        back = TagConfig.from_json(cfg.to_json())
        assert (back.placement, back.route_arrow, back.location_detail, back.title_separator) \
            == ("replace", "arrow", "address", "pipe")


class TestAbbreviateTitle:
    """#200 follow-up, generalized to per-word/phrase toggles: curated
    stock-title shortening for hauling titles."""

    def test_phrase_map_on_real_title_shapes(self):
        # "Haul" is dropped entirely from shortened titles, not abbreviated.
        # Default rank_separator is "dash", so the dash after Rank survives
        # even with "rank" enabled (word removed, separator stays).
        assert abbreviate_title(
            "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul",
            _ALL_ABBREVIATION_KEYS,
        ) == "~mission(ReputationRank) - ~mission(CargoGradeToken)"
        assert abbreviate_title(
            "~mission(ReputationRank) Rank - Direct ~mission(CargoGradeToken) Cargo Haul",
            _ALL_ABBREVIATION_KEYS,
        ) == "~mission(ReputationRank) - Direct ~mission(CargoGradeToken)"
        # No Rank trigger in this shape, so it's unaffected by rank_separator.
        assert abbreviate_title(
            "~mission(ReputationRank) Hauler Needed for ~mission(CargoGradeToken) Shipment",
            _ALL_ABBREVIATION_KEYS,
        ) == "~mission(ReputationRank) - ~mission(CargoGradeToken) Shipment"
        assert abbreviate_title(
            "Covalex Local Shipment Route", _ALL_ABBREVIATION_KEYS
        ) == "Covalex Route"
        assert abbreviate_title(
            "Opportunity for Independent Cargo Hauler", _ALL_ABBREVIATION_KEYS
        ) == "Intro"

    def test_removed_phrase_never_leaves_dangling_separator(self):
        assert abbreviate_title("Something - Cargo Haul", _ALL_ABBREVIATION_KEYS) == "Something"

    def test_size_abbreviations_order_and_content(self):
        # Longest-first so a literal-text pass can't turn "Extra Small"
        # into "Extra S".
        words = [w for w, _ in SIZE_ABBREVIATIONS]
        assert words.index("Extra Small") < words.index("Small")
        assert words.index("Extra Large") < words.index("Large")
        assert SIZE_ABBREV_BY_WORD["Extra Small"] == "XS"
        assert SIZE_ABBREV_BY_WORD["Medium"] == "M"

    def test_unmapped_title_passes_through(self):
        assert abbreviate_title(
            "Quantum Sensitive Delivery", _ALL_ABBREVIATION_KEYS
        ) == "Quantum Sensitive Delivery"

    def test_tokens_never_touched(self):
        # No phrase/word in the map may rewrite inside a ~mission(...) token.
        s = "~mission(CargoGradeToken) and ~mission(ReputationRank)"
        assert abbreviate_title(s, _ALL_ABBREVIATION_KEYS) == s

    def test_nothing_enabled_is_a_no_op_for_dash_titles(self):
        # Default rank_separator "dash" matches what stock dash-led titles
        # already show, so nothing checked + a dash-led title is a true
        # no-op (the Rank separator is always-on, but "dash" -> "dash" is
        # invisible). The separator is still independently applied though —
        # see test_rank_separator_normalizes_comma_titles_by_default.
        title = "Master Rank - Direct Medium Cargo Haul"
        assert abbreviate_title(title) == title
        assert abbreviate_title(title, frozenset()) == title
        plain = "Quantum Sensitive Delivery"
        assert abbreviate_title(plain) == plain

    def test_rank_separator_normalizes_comma_titles_by_default(self):
        # Nothing checked, but the always-on separator (default "dash")
        # still re-renders the comma-context punctuation — it doesn't
        # require any checkbox to be ticked.
        comma_title = "Master Rank, Direct Medium Cargo Haul"
        assert abbreviate_title(comma_title) == "Master Rank - Direct Medium Cargo Haul"

    def test_cargo_and_haul_are_independently_toggleable(self):
        # Split from the old combined "Cargo Haul" phrase so each word can
        # be dropped on its own. Default rank_separator "dash" leaves the
        # existing dash untouched since "rank" isn't in enabled here.
        title = "Master Rank - Direct Medium Cargo Haul"
        assert abbreviate_title(title, frozenset({"cargo"})) == \
            "Master Rank - Direct Medium Haul"
        assert abbreviate_title(title, frozenset({"haul"})) == \
            "Master Rank - Direct Medium Cargo"
        assert abbreviate_title(title, frozenset({"cargo", "haul"})) == \
            "Master Rank - Direct Medium"

    def test_word_split_never_touches_tokens(self):
        # "Cargo" alone is a substring of "CargoGradeToken" — the \b-bounded
        # word match must not corrupt the token even with both keys on.
        s = "~mission(CargoGradeToken) Haul and ~mission(ReputationRank)"
        assert abbreviate_title(s, frozenset({"cargo", "haul"})) == \
            "~mission(CargoGradeToken) and ~mission(ReputationRank)"

    def test_rank_checkbox_covers_both_dash_and_comma_contexts(self):
        # A single "rank" key removes the word in either context; default
        # separator "dash" applies to both.
        dash_title = "Master Rank - Direct Medium Cargo Haul"
        comma_title = "Master Rank, Direct Medium Cargo Haul"
        assert abbreviate_title(dash_title, frozenset({"rank"})) == \
            "Master - Direct Medium Cargo Haul"
        assert abbreviate_title(comma_title, frozenset({"rank"})) == \
            "Master - Direct Medium Cargo Haul"

    def test_rank_separator_always_applies_regardless_of_removal(self):
        title = "Master Rank - Direct Medium Cargo Haul"
        # Rank word kept (checkbox off) but separator swapped to Pipe.
        assert abbreviate_title(title, frozenset(), "pipe") == \
            "Master Rank | Direct Medium Cargo Haul"
        # Rank word removed, separator swapped to Colon.
        assert abbreviate_title(title, frozenset({"rank"}), "colon") == \
            "Master : Direct Medium Cargo Haul"
        # "space" collapses to nothing visible after whitespace
        # normalization, with or without word removal — same effect a
        # dedicated "none" option would have had.
        assert abbreviate_title(title, frozenset(), "space") == \
            "Master Rank Direct Medium Cargo Haul"
        assert abbreviate_title(title, frozenset({"rank"}), "space") == \
            "Master Direct Medium Cargo Haul"

    def test_hauler_needed_for_tracks_rank_separator(self):
        # RedWind haul titles use "Hauler Needed for" in the exact slot
        # other titles fill with a literal " Rank -"/" Rank," — CIG's
        # phrasing just never spells "Rank" there. The word "Rank" is
        # re-inserted so "Rookie" reads as "Rookie Rank", matching every
        # other haul title shape, unless the shared "rank" removal
        # checkbox is also on. Regression: this used to be hardcoded to a
        # bare "-" (no word, wrong separator) regardless of rank_separator.
        title = "~mission(ReputationRank) Hauler Needed for ~mission(CargoGradeToken) Shipment"
        enabled = frozenset({"hauler_needed_for"})
        assert abbreviate_title(title, enabled, "dash") == \
            "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Shipment"
        assert abbreviate_title(title, enabled, "pipe") == \
            "~mission(ReputationRank) Rank | ~mission(CargoGradeToken) Shipment"
        assert abbreviate_title(title, enabled, "colon") == \
            "~mission(ReputationRank) Rank: ~mission(CargoGradeToken) Shipment"
        assert abbreviate_title(title, enabled, "space") == \
            "~mission(ReputationRank) Rank ~mission(CargoGradeToken) Shipment"
        # "rank" removal checkbox also on: word drops, separator remains.
        assert abbreviate_title(title, enabled | {"rank"}, "dash") == \
            "~mission(ReputationRank) - ~mission(CargoGradeToken) Shipment"

    def test_ling_family_rank_inserts_word_and_separator(self):
        # Ling Family haul titles put "Cargo" directly after the rank token
        # with no "Rank" word and no separator at all (unlike the dash/comma
        # RANK_TRIGGERS shapes and unlike "Hauler Needed for", which at
        # least sits between two spaced-out pieces of text). Both the word
        # and the separator have to be inserted from scratch.
        title = "Ling Family ~mission(ReputationRank) Cargo Haul - ~mission(CargoGradeToken) Scale"
        enabled = frozenset({"ling_family_rank"})
        assert abbreviate_title(title, enabled, "dash") == \
            "Ling Family ~mission(ReputationRank) Rank - Cargo Haul - ~mission(CargoGradeToken) Scale"
        assert abbreviate_title(title, enabled, "pipe") == \
            "Ling Family ~mission(ReputationRank) Rank | Cargo Haul - ~mission(CargoGradeToken) Scale"
        assert abbreviate_title(title, enabled, "colon") == \
            "Ling Family ~mission(ReputationRank) Rank: Cargo Haul - ~mission(CargoGradeToken) Scale"
        assert abbreviate_title(title, enabled, "space") == \
            "Ling Family ~mission(ReputationRank) Rank Cargo Haul - ~mission(CargoGradeToken) Scale"
        # "rank" removal checkbox also on: word drops, separator remains.
        assert abbreviate_title(title, enabled | {"rank"}, "dash") == \
            "Ling Family ~mission(ReputationRank) - Cargo Haul - ~mission(CargoGradeToken) Scale"
        # Untouched when the option isn't enabled.
        assert abbreviate_title(title, frozenset(), "dash") == title

    def test_ling_family_prefix_removed_with_rank_intact(self):
        # "Ling Family" is the contract-giver name prefixed onto the haul
        # title itself (unlike Covalex/RedWind/DeadSaints, which don't
        # prefix a company name onto the title text). Removing it is a
        # separate opt-in from the rank-separator fix above, but both share
        # the "shorten original titles" checkbox family so ticking one
        # master checkbox turns both on together.
        title = "Ling Family ~mission(ReputationRank) Cargo Haul - ~mission(CargoGradeToken) Scale"
        enabled = frozenset({"ling_family_rank", "ling_family_prefix"})
        assert abbreviate_title(title, enabled, "dash") == \
            "~mission(ReputationRank) Rank - Cargo Haul - ~mission(CargoGradeToken) Scale"
        # Prefix removal alone (rank option off) leaves the un-normalized
        # rank-adjacent text as-is — the two options are independent.
        assert abbreviate_title(title, frozenset({"ling_family_prefix"}), "dash") == \
            "~mission(ReputationRank) Cargo Haul - ~mission(CargoGradeToken) Scale"

    def test_config_default_off_and_round_trip(self):
        cfg = default_config("mission_titles")
        assert cfg.abbreviated_phrases == frozenset()
        # rank_separator defaults "dash" (independent, always-on feature —
        # not gated by abbreviated_phrases being empty).
        assert cfg.rank_separator == "dash"
        assert cfg.shortened_sizes == frozenset()
        cfg.abbreviated_phrases = frozenset({"cargo", "rank"})
        cfg.rank_separator = "pipe"
        cfg.shortened_sizes = frozenset({"Small", "Medium"})
        back = TagConfig.from_json(cfg.to_json())
        assert back.abbreviated_phrases == frozenset({"cargo", "rank"})
        assert back.rank_separator == "pipe"
        assert back.shortened_sizes == frozenset({"Small", "Medium"})
        # Pre-2.1.1 blobs have no key at all: word/size options default off,
        # but rank_separator still defaults on ("dash").
        assert TagConfig.from_dict({}).abbreviated_phrases == frozenset()
        assert TagConfig.from_dict({}).rank_separator == "dash"
        assert TagConfig.from_dict({}).shortened_sizes == frozenset()

    def test_legacy_bool_migrates_to_all_phrases_and_sizes_enabled(self):
        """Pre-redesign saved configs stored `abbreviate_title: true/false`.
        A user who had opted in keeps equivalent shortening after upgrade,
        including every cargo size (previously bundled, not independently
        selectable)."""
        cfg_on = TagConfig.from_dict({"abbreviate_title": True})
        assert cfg_on.abbreviated_phrases == _ALL_ABBREVIATION_KEYS
        assert cfg_on.shortened_sizes == _ALL_SIZE_WORDS
        cfg_off = TagConfig.from_dict({"abbreviate_title": False})
        assert cfg_off.abbreviated_phrases == frozenset()
        assert cfg_off.shortened_sizes == frozenset()

    def test_unknown_persisted_keys_are_dropped(self):
        cfg = TagConfig.from_dict({"abbreviated_phrases": ["cargo", "made_up_key"]})
        assert cfg.abbreviated_phrases == frozenset({"cargo"})

    def test_unknown_persisted_sizes_are_dropped(self):
        cfg = TagConfig.from_dict({"shortened_sizes": ["Small", "Gargantuan"]})
        assert cfg.shortened_sizes == frozenset({"Small"})

    def test_underline_direct_wraps_and_uppercases(self):
        title = "Master Rank - Direct Medium Cargo Haul"
        assert abbreviate_title(title, frozenset({"underline_direct"})) == \
            "Master Rank - <EM3>DIRECT</EM3> Medium Cargo Haul"

    def test_underline_direct_word_boundary_safe(self):
        # A hypothetical word containing "Direct" as a substring must not
        # be corrupted by the \b-bounded match.
        s = "Direction Directive Direct"
        assert abbreviate_title(s, frozenset({"underline_direct"})) == \
            "Direction Directive <EM3>DIRECT</EM3>"

    def test_underline_direct_excluded_from_legacy_migration(self):
        # A brand-new visual feature — legacy `abbreviate_title: true` users
        # must not silently gain it on upgrade.
        cfg = TagConfig.from_dict({"abbreviate_title": True})
        assert "underline_direct" not in cfg.abbreviated_phrases

    def test_underline_direct_key_persists_and_round_trips(self):
        cfg = default_config("mission_titles")
        cfg.abbreviated_phrases = frozenset({"underline_direct"})
        back = TagConfig.from_json(cfg.to_json())
        assert back.abbreviated_phrases == frozenset({"underline_direct"})

    def test_underline_options_shape(self):
        keys = {k for k, *_ in UNDERLINE_OPTIONS}
        assert keys == {"underline_direct"}

    def test_rank_separator_matches_title_separator_options(self):
        from src.utils.tag_builder import RANK_SEPARATORS, TITLE_SEPARATORS
        assert RANK_SEPARATORS == TITLE_SEPARATORS
        assert [k for k, *_ in RANK_SEPARATORS] == ["dash", "pipe", "colon", "space"]


class TestStandardizeHaulingNames:
    """Top-of-page "Standardize hauling mission names" toggle: rewrites any
    title carrying both the rank + cargo-size tokens into one canonical
    "Rank <sep> [Direct] Size Cargo Haul [Circuit]" shape, regardless of
    company wording. Real stock title shapes pulled from base.ini."""

    # Real stock title text per company (2.1.2 base.ini), covering every
    # distinct phrasing this feature has to normalize.
    _COVALEX_PLAIN = "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul"
    _COVALEX_DIRECT = "~mission(ReputationRank) Rank - Direct ~mission(CargoGradeToken) Cargo Haul"
    _COVALEX_CIRCUIT = "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul Circuit"
    _DEADSAINTS = "DEAD SAINTS -- ~mission(ReputationRank) Rank, ~mission(CargoGradeToken) Scale Cargo Run"
    _REDWIND_PLAIN = "~mission(ReputationRank) Hauler Needed for ~mission(CargoGradeToken) Shipment"
    _REDWIND_DIRECT = "~mission(ReputationRank) Hauler Needed for Direct ~mission(CargoGradeToken) Shipment"
    _LING_FAMILY = "Ling Family ~mission(ReputationRank) Cargo Haul - ~mission(CargoGradeToken) Scale"
    _NO_TOKENS = "RESOURCE DRIVE: MEDIUM SHIPMENT"  # GoblinG — no rank/size data to standardize with
    _ONE_TOKEN_ONLY = "Red Wind Direct Cargo Haul"    # one-off, neither token present

    def test_covalex_shapes_are_already_canonical(self):
        # Covalex's stock phrasing already matches the target template, so
        # standardizing is a no-op (aside from whitespace normalization).
        assert abbreviate_title(self._COVALEX_PLAIN, frozenset(), "dash", True) == \
            self._COVALEX_PLAIN
        assert abbreviate_title(self._COVALEX_DIRECT, frozenset(), "dash", True) == \
            self._COVALEX_DIRECT
        assert abbreviate_title(self._COVALEX_CIRCUIT, frozenset(), "dash", True) == \
            self._COVALEX_CIRCUIT

    def test_deadsaints_prefix_and_wording_normalized(self):
        # "DEAD SAINTS --" prefix dropped; "Scale Cargo Run" -> "Cargo Haul".
        assert abbreviate_title(self._DEADSAINTS, frozenset(), "dash", True) == \
            self._COVALEX_PLAIN

    def test_redwind_wording_normalized_and_direct_preserved(self):
        # "Hauler Needed for" -> "Rank -"; "Shipment" -> "Cargo Haul".
        assert abbreviate_title(self._REDWIND_PLAIN, frozenset(), "dash", True) == \
            self._COVALEX_PLAIN
        assert abbreviate_title(self._REDWIND_DIRECT, frozenset(), "dash", True) == \
            self._COVALEX_DIRECT

    def test_ling_family_prefix_dropped_and_reordered(self):
        # Company prefix dropped; Size+"Scale" duplicate collapses into the
        # single CargoGradeToken already carrying the size.
        assert abbreviate_title(self._LING_FAMILY, frozenset(), "dash", True) == \
            self._COVALEX_PLAIN

    def test_titles_without_both_tokens_pass_through_untouched(self):
        # No rank/size data to build a template from — GoblinG's fixed
        # resource-drive text and one-off titles with only one (or no)
        # token are left exactly as CIG wrote them.
        assert abbreviate_title(self._NO_TOKENS, frozenset(), "dash", True) == self._NO_TOKENS
        assert abbreviate_title(self._ONE_TOKEN_ONLY, frozenset(), "dash", True) == \
            self._ONE_TOKEN_ONLY

    def test_disabled_by_default_leaves_company_wording_untouched(self):
        # standardize_hauling defaults False — company prefixes and each
        # company's own wording survive. (The always-on Rank-separator
        # normalization is independent and still runs regardless — that's
        # covered by TestAbbreviateTitle, not re-asserted here.)
        assert "DEAD SAINTS" in abbreviate_title(self._DEADSAINTS, frozenset())
        assert "Scale Cargo Run" in abbreviate_title(self._DEADSAINTS, frozenset())
        assert "Hauler Needed for" in abbreviate_title(self._REDWIND_PLAIN, frozenset())
        assert abbreviate_title(self._LING_FAMILY, frozenset()) == self._LING_FAMILY

    def test_composes_with_rank_separator(self):
        assert abbreviate_title(self._LING_FAMILY, frozenset(), "pipe", True) == \
            "~mission(ReputationRank) Rank | ~mission(CargoGradeToken) Cargo Haul"
        assert abbreviate_title(self._LING_FAMILY, frozenset(), "colon", True) == \
            "~mission(ReputationRank) Rank: ~mission(CargoGradeToken) Cargo Haul"
        assert abbreviate_title(self._LING_FAMILY, frozenset(), "space", True) == \
            "~mission(ReputationRank) Rank ~mission(CargoGradeToken) Cargo Haul"

    def test_composes_with_rank_removal_checkbox(self):
        # Runs first, so "Remove Rank" still strips the word Standardize
        # just inserted — the two checkboxes stay independently toggleable.
        assert abbreviate_title(self._LING_FAMILY, frozenset({"rank"}), "dash", True) == \
            "~mission(ReputationRank) - ~mission(CargoGradeToken) Cargo Haul"

    def test_composes_with_cargo_and_haul_removal(self):
        assert abbreviate_title(self._LING_FAMILY, frozenset({"cargo"}), "dash", True) == \
            "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Haul"
        assert abbreviate_title(self._LING_FAMILY, frozenset({"haul"}), "dash", True) == \
            "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo"

    def test_composes_with_underline_direct(self):
        # The word "Direct" standardize inserts is a real word other
        # checkboxes can act on — underline still finds and wraps it.
        assert abbreviate_title(self._COVALEX_DIRECT, frozenset({"underline_direct"}), "dash", True) == \
            "~mission(ReputationRank) Rank - <EM3>DIRECT</EM3> ~mission(CargoGradeToken) Cargo Haul"

    def test_config_default_off_and_round_trip(self):
        cfg = default_config("mission_titles")
        assert cfg.standardize_hauling_names is False
        cfg.standardize_hauling_names = True
        back = TagConfig.from_json(cfg.to_json())
        assert back.standardize_hauling_names is True
        # Pre-2.2.0 blobs have no key at all: defaults off.
        assert TagConfig.from_dict({}).standardize_hauling_names is False


class TestLocationDetailMigration:
    """2.1.1 (#200): a 2.1.0-seeded location_detail "name" flips to "address"
    exactly once; a deliberate Name pick afterward survives."""
    _CFG_KEY = "tag_builder/mission_titles/config"
    _MARKER = "tag_builder/mission_titles/location_detail_migrated"

    def test_seeded_name_flips_to_address(self, json_backend):
        cfg = default_config("mission_titles")
        cfg.location_detail = "name"     # what every saved 2.1.0 config holds
        cfg.placement = "replace"        # other fields must survive the flip
        AppSettings.set_tag_config("mission_titles", cfg)
        AppSettings.migrate_mission_titles_location_detail()
        back = AppSettings.get_tag_config("mission_titles")
        assert back.location_detail == "address"
        assert back.placement == "replace"
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_no_saved_config_only_sets_marker(self, json_backend):
        # Fresh install: nothing to flip, defaults are already address.
        AppSettings.migrate_mission_titles_location_detail()
        assert not json_backend.value(self._CFG_KEY, "", type=str)
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_runs_once_so_deliberate_name_survives(self, json_backend):
        AppSettings.migrate_mission_titles_location_detail()
        cfg = default_config("mission_titles")
        cfg.location_detail = "name"     # deliberate post-2.1.1 choice
        AppSettings.set_tag_config("mission_titles", cfg)
        AppSettings.migrate_mission_titles_location_detail()
        assert AppSettings.get_tag_config("mission_titles").location_detail == "name"


class TestRouteToggleMigration:
    _CFG_KEY = "tag_builder/mission_titles/config"
    _MARKER = "mission_field/route_migrated"

    def test_old_route_off_disables_new_element(self, json_backend):
        json_backend.setValue("mission_field/route", "false")
        AppSettings.migrate_route_toggle_to_mission_titles()
        cfg = AppSettings.get_tag_config("mission_titles")
        assert route_enabled(cfg) is False
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_old_route_on_or_unset_leaves_default_on(self, json_backend):
        # Unset (user never touched it) -> no config written, feature stays on.
        AppSettings.migrate_route_toggle_to_mission_titles()
        assert not json_backend.value(self._CFG_KEY, "", type=str)
        assert route_enabled(AppSettings.get_tag_config("mission_titles")) is True

    def test_migration_runs_once(self, json_backend):
        json_backend.setValue("mission_field/route", "false")
        AppSettings.migrate_route_toggle_to_mission_titles()
        # A later flip of the new config must survive a second migrate call.
        cfg = default_config("mission_titles")
        AppSettings.set_tag_config("mission_titles", cfg)  # re-enable
        AppSettings.migrate_route_toggle_to_mission_titles()
        assert route_enabled(AppSettings.get_tag_config("mission_titles")) is True
