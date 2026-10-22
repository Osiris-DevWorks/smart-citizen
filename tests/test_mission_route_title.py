"""Hauling/delivery/courier route-in-title derivation (#166 → 2.1 Mission Titles).

The pure route helpers in scripts/generate_enhancements_ini.py
(`_derive_route_fragment`, `_route_token_role`, `_title_route_token`,
`_is_route_title`, `_expand_nested_route_vars`) driven with synthetic bodies.
In 2.1 the route became a Tag Builder feature: `_derive_route_fragment` returns
the route CORE (no ` | ` separator, no placement; the caller places it via
tag_builder.apply_mission_title), the arrow and Location/Destination modifier
come from the mission_titles config, and courier titles are eligible. The 2.1.1
hotfix (#200) reworked the shapes: |Address is the default modifier, endpoint
sides render comma lists, bare ``*Token`` vars expand one level against the loc
table, and per-body intersection guards shared titles. The stale
`kraken_4.7.ini` fixture is deliberately not used as ground truth.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.tag_builder import default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_route_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Endpoint classification ─────────────────────────────────────────────────

@pytest.mark.parametrize("var", ["Location", "location", "Location1", "Pickup1", "pickup2"])
def test_role_from(gen_module, var):
    assert gen_module._route_token_role(var) == "from"


@pytest.mark.parametrize("var", ["Destination", "destination", "Destination2", "Dropoff1"])
def test_role_to(gen_module, var):
    assert gen_module._route_token_role(var) == "to"


@pytest.mark.parametrize("var", ["TargetName", "System", "Item", "Client", "MissionMaxSCUSize"])
def test_role_none(gen_module, var):
    assert gen_module._route_token_role(var) is None


# ── Route CORE shape (no separator; caller places it) ───────────────────────

def test_atob_full_route(gen_module):
    """One source, one dest → ``from > to`` with the |Address modifier
    (2.1.1 default, #200: |name fails to resolve for some instances)."""
    body = "stash at <EM4>~mission(Location|Address)</EM4>, deliver to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Location|Address) > ~mission(Destination|Address)"
    )


def test_multi_to_single_lists_sources(gen_module):
    """#200: multiple pickups render as a comma list, not a degraded 'to'."""
    body = ("grab from ~mission(Location1|Address) and ~mission(Location2|Address), "
            "bring to ~mission(Destination|Address)")
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Location1|Address), ~mission(Location2|Address)"
        " > ~mission(Destination|Address)"
    )


def test_single_to_multi_lists_destinations(gen_module):
    """#200: multiple drop-offs render as a comma list, not 'from X' only."""
    body = ("collect at ~mission(Location|Address), deliver to "
            "~mission(Destination1|Address) and ~mission(Destination2|Address)")
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Location|Address) > "
        "~mission(Destination1|Address), ~mission(Destination2|Address)"
    )


def test_pickup_dropoff_copied_verbatim(gen_module):
    """Non-canonical endpoints keep the body's exact token (which resolves)."""
    body = "pick up ~mission(Pickup1|Address), drop at ~mission(Dropoff1|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Pickup1|Address) > ~mission(Dropoff1|Address)"
    )


def test_source_only_when_no_dest(gen_module):
    body = "objective located at ~mission(Location|Address)"
    assert gen_module._derive_route_fragment([body]) == "from ~mission(Location|Address)"


def test_no_route_tokens_omitted(gen_module):
    body = "eliminate ~mission(TargetName) in the ~mission(System) system"
    assert gen_module._derive_route_fragment([body]) == ""


def test_single_body_multi_multi_lists_both_sides(gen_module):
    """All four vars in ONE body are all registered → both comma lists render
    (#200 rework: the old many-many guard only applies across bodies)."""
    body = ("~mission(Location1|Address) ~mission(Location2|Address) -> "
            "~mission(Destination1|Address) ~mission(Destination2|Address)")
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Location1|Address), ~mission(Location2|Address) > "
        "~mission(Destination1|Address), ~mission(Destination2|Address)"
    )


def test_cross_body_var_disagreement_omits_side(gen_module):
    """Pooled bodies naming the pickup differently can't share a title token:
    the from side is dropped; the agreed Destination survives."""
    bodies = [
        "from ~mission(Location|Address) to ~mission(Destination|Address)",
        "from ~mission(Location1|Address) to ~mission(Destination|Address)",
    ]
    assert gen_module._derive_route_fragment(bodies) == (
        "to ~mission(Destination|Address)"
    )


def test_body_without_side_vars_abstains(gen_module):
    """A pooled body with no endpoint vars (pure Contractor indirection) must
    not veto the route the other bodies agree on."""
    bodies = [
        "~mission(Contractor|HaulCargo_AtoB) plain text, no endpoints",
        "from ~mission(Location|Address) to ~mission(Destination|Address)",
    ]
    assert gen_module._derive_route_fragment(bodies) == (
        "~mission(Location|Address) > ~mission(Destination|Address)"
    )


def test_empty_and_none_bodies_safe(gen_module):
    assert gen_module._derive_route_fragment([]) == ""
    assert gen_module._derive_route_fragment([None, "", "no tokens here"]) == ""


# ── Nested *Token indirection (#200) ─────────────────────────────────────────

_SM_LOC = {
    "HaulCargo_2_SingleToMultiToken": (
        "- Freight elevator at ~mission(Destination|Address)\\n"
        "- Freight elevator at ~mission(Destination1|Address)"
    ),
    "HaulCargo_3_SingleToMultiToken": (
        "- Freight elevator at ~mission(Destination|Address)\\n"
        "- Freight elevator at ~mission(Destination1|Address)\\n"
        "- Freight elevator at ~mission(Destination2|Address)"
    ),
}


def test_nested_token_expansion_lists_guaranteed_drops(gen_module):
    """SingleToMulti hauls hide drop-offs behind ~mission(SingleToMultiToken);
    the title gets the drops EVERY variant registers (intersection: the 3-drop
    variant's Destination2 is excluded, a 2-drop instance can't resolve it)."""
    body = ("cargo at <EM4>~mission(Location|Address)</EM4> "
            "DROP OFF LOCATIONS\\n~mission(SingleToMultiToken)\\nthanks")
    assert gen_module._derive_route_fragment([body], None, _SM_LOC) == (
        "~mission(Location|Address) > "
        "~mission(Destination|Address), ~mission(Destination1|Address)"
    )


def test_nested_expansion_only_follows_token_suffixed_vars(gen_module):
    """Bare vars not ending in 'Token' are never expanded, even when a
    suffix-matching loc key exists."""
    loc = {"HaulCargo_2_DropSpots": "~mission(Destination|Address)"}
    body = "at ~mission(Location|Address), see ~mission(DropSpots)"
    assert gen_module._derive_route_fragment([body], None, loc) == (
        "from ~mission(Location|Address)"
    )


def test_nested_expansion_cache_reused(gen_module):
    cache: dict = {}
    body = "at ~mission(Location|Address) ~mission(SingleToMultiToken)"
    first = gen_module._derive_route_fragment([body], None, _SM_LOC, cache)
    assert "SingleToMultiToken" in cache
    # Same result served from the memo, even against an emptied loc table.
    assert gen_module._derive_route_fragment([body], None, {}, cache) == first


# ── Config-driven arrow + location detail ───────────────────────────────────

def test_arrow_from_config(gen_module):
    """The 'arrow' option renders '->': mobiGlas has no glyph for U+2192 (#200)."""
    cfg = default_config("mission_titles")
    cfg.route_arrow = "arrow"
    body = "at ~mission(Location|Address) to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body], cfg) == (
        "~mission(Location|Address) -> ~mission(Destination|Address)"
    )


def test_size_abbreviation_overrides(gen_module):
    """Each size is independently opted in via `shortened_sizes` (its own
    None/abbreviation dropdown); exact-value loc-key overrides only cover
    sizes the user selected."""
    loc = {
        "HaulCargo_CargoGrade_ExtraSmall": "Extra Small",
        "HaulCargo_CargoGrade_Supply": "Medium",
        "HaulCargo_CargoScale_Large": "Large",
        "HaulCargo_CargoGrade_Odd": "Gargantuan",  # unmapped grade: untouched
        "Unrelated_Key": "Small",                  # wrong prefix: untouched
    }
    all_sizes = frozenset({"Extra Small", "Medium", "Large", "Small", "Extra Large"})
    assert gen_module._size_abbreviation_overrides(loc, all_sizes) == {
        "HaulCargo_CargoGrade_ExtraSmall": "XS",
        "HaulCargo_CargoGrade_Supply": "M",
        "HaulCargo_CargoScale_Large": "L",
    }
    # Only the sizes actually selected produce an override.
    assert gen_module._size_abbreviation_overrides(loc, frozenset({"Medium"})) == {
        "HaulCargo_CargoGrade_Supply": "M",
    }
    # Nothing selected (default) or no loc table: no overrides at all.
    assert gen_module._size_abbreviation_overrides(loc) == {}
    assert gen_module._size_abbreviation_overrides(None, all_sizes) == {}


def test_shape_arrow_from_derivation(gen_module):
    """The shape arrow picks up the derived endpoint counts (#200 follow-up):
    one pickup, two drop-offs renders the one-to-many glyph."""
    cfg = default_config("mission_titles")
    cfg.route_arrow = "shape"
    body = ("collect at ~mission(Location|Address), deliver to "
            "~mission(Destination1|Address) and ~mission(Destination2|Address)")
    assert gen_module._derive_route_fragment([body], cfg) == (
        "~mission(Location|Address) ->= "
        "~mission(Destination1|Address), ~mission(Destination2|Address)"
    )


def test_location_detail_name_covers_canonical_family(gen_module):
    """|name opt-in reaches Location/Destination AND their numbered siblings
    (a mixed name/Address comma list would look broken)..."""
    cfg = default_config("mission_titles")
    cfg.location_detail = "name"
    body = ("at ~mission(Location|Address) to "
            "~mission(Destination|Address) and ~mission(Destination1|Address)")
    assert gen_module._derive_route_fragment([body], cfg) == (
        "~mission(Location|name) > "
        "~mission(Destination|name), ~mission(Destination1|name)"
    )
    # ...but Pickup/Dropoff keep the body's own modifier regardless.
    body2 = "pick up ~mission(Pickup1|Address), drop at ~mission(Dropoff1|Address)"
    assert gen_module._derive_route_fragment([body2], cfg) == (
        "~mission(Pickup1|Address) > ~mission(Dropoff1|Address)"
    )


# ── Deterministic body order at the generator's call sites ──────────────────

_COURIER_LOC = {
    # Two pooled courier bodies that spell the same endpoints both ways.
    "Covalex_courier_dc_small_desc_002":
        "Pick up at ~mission(Pickup1), drop off at ~mission(Dropoff1|Address).",
    "Covalex_courier_dc_small_desc_001":
        "Collect from ~mission(Pickup1|Address) and deliver to ~mission(Dropoff1).",
}


def test_route_bodies_follow_key_order_not_input_order(gen_module):
    """The generator pools a title's desc keys in a set and the first body's
    spelling of an endpoint wins, so the bodies must come back in one stable
    order whatever order the keys arrive in."""
    keys = list(_COURIER_LOC)
    forward = gen_module._route_bodies(keys, _COURIER_LOC)
    backward = gen_module._route_bodies(list(reversed(keys)), _COURIER_LOC)
    as_set = gen_module._route_bodies(set(keys), _COURIER_LOC)
    expected = [
        _COURIER_LOC["Covalex_courier_dc_small_desc_001"],
        _COURIER_LOC["Covalex_courier_dc_small_desc_002"],
    ]
    assert forward == backward == as_set == expected


def test_route_bodies_tolerate_missing_keys_and_no_loc(gen_module):
    assert gen_module._route_bodies({"missing"}, _COURIER_LOC) == [None]
    assert gen_module._route_bodies({"x"}, None) == [None]
    assert gen_module._route_bodies(set(), _COURIER_LOC) == []


def test_pooled_courier_bodies_render_one_route(gen_module):
    """Regression: two Generates on the same cache rendered
    ``Pickup1|Address > Dropoff1`` in one run and ``Pickup1 > Dropoff1|Address``
    in the next, following whichever desc key hashed first in that process.
    The lowest key's spelling must win in every ordering."""
    expected = "~mission(Pickup1|Address) > ~mission(Dropoff1)"
    keys = list(_COURIER_LOC)
    for ordering in (keys, list(reversed(keys)), set(keys)):
        bodies = gen_module._route_bodies(ordering, _COURIER_LOC)
        assert gen_module._derive_route_fragment(bodies, loc=_COURIER_LOC) == expected


def test_generator_feeds_every_route_derivation_through_route_bodies(gen_module):
    """Lock the call sites: a bare ``[loc.get(dk) for dk in <set>]`` at either
    site reintroduces the hash-order flip."""
    src = Path(gen_module.__file__).read_text(encoding="utf-8")
    call_sites = [
        m.end() for m in re.finditer(r"(?<!def )_derive_route_fragment\(", src)
    ]
    assert len(call_sites) >= 2, "expected the contractgen and pu-only call sites"
    for pos in call_sites:
        head = src[pos:pos + 80].lstrip()
        assert head.startswith("_route_bodies("), head


# ── Eligibility (haul / delivery / courier) ─────────────────────────────────

@pytest.mark.parametrize("key", [
    "Foxwell_HaulCargo_AToB_OLP_title_01",
    "Covalex_HaulCargo_SingleToMulti_title",
    "CFP_Delivery_Outpost_title_001",
    "Headhunters_Delivery_Outpost_Multi_title_001",
    "FTL_Courier_Stanton_Easy_Title_001",
    "CleanAir_Courier_title",
])
def test_route_titles_eligible(gen_module, key):
    assert gen_module._is_route_title(key) is True


@pytest.mark.parametrize("key", [
    "BountyHuntersGuild_Bounty_Stanton_Easy_title_001",
    "cfp_defend_cave_Generic_title_001",
    "vaughn_assassination_FPS_UGF_legal_title_001",
])
def test_non_route_keys_not_eligible(gen_module, key):
    assert gen_module._is_route_title(key) is False


def test_title_already_showing_route_token_is_skipped(gen_module):
    assert gen_module._title_has_route_token(
        "Inter-Outpost Delivery at ~mission(Destination)"
    ) is True


def test_title_with_only_non_route_tokens_is_not_flagged(gen_module):
    assert gen_module._title_has_route_token(
        "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul"
    ) is False
    assert gen_module._title_has_route_token("Retrieve Cargo Haul") is False
