"""Blueprint names left behind by another localization editor (#372).

Star Citizen writes whatever item name it was DISPLAYING into Game.log. A
player who previously ran a different localization editor therefore has that
tool's naming permanently baked into their old logs, and Smart Citizen's log
scan imports it verbatim into the owned set. Those names match nothing on the
mission side, so the blueprints never show as owned.

The reporter had run StarStrings. Their owned set read ``Ind/1/B Colossus``
while every other part of the app called the same item ``Colossus``. Deleting
every Smart Citizen folder and reinstalling did not help, because the bad names
live in the logs rather than in anything Smart Citizen writes, so each re-scan
reintroduced them.

The fix deliberately does not pattern-match StarStrings. Matching ``Ind/1/B``
would fix exactly one tool and need extending for every other editor anyone has
used. It anchors on the real item catalogue instead: if a scanned name ends in
a known real item name on a word boundary, that is the item, whatever
decoration precedes it.

Samples below are the real strings from the reporter's uploaded Game.log and
from tests/fixtures/kraken_global_latest.ini, which is itself a StarStrings-
modified global.ini (451 of its component names carry that tool's tags).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_meta import known_item_names  # noqa: E402
from src.utils.owned_items import (  # noqa: E402
    repair_foreign_owned_names,
    resolve_against_catalogue,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# The six the reporter opened #372 about, as they appear in their own log.
_REPORTER_CATALOGUE = {
    "Defiant", "Colossus", "Endurance", "Huracan", "Sedulity", "Agni",
}


@pytest.mark.parametrize("scanned,expected", [
    ("Ind/0/B Defiant", "Defiant"),
    ("Ind/1/B Colossus", "Colossus"),
    ("Ind/1/B Endurance", "Endurance"),
    ("Ind/2/B Huracan", "Huracan"),
    ("Ind/2/B Sedulity", "Sedulity"),
    ("Ind/3/B Agni", "Agni"),
])
def test_recovers_the_reported_names(scanned, expected):
    assert resolve_against_catalogue(scanned, _REPORTER_CATALOGUE) == expected


def test_recovers_a_different_tools_classes_too():
    """Civ/Mil/Sth/Cmp all appear in the wild alongside Ind. Nothing in the
    resolver knows those tokens, which is the point: it never reads the tag."""
    cat = {"Fridan", "7SA 'Concord'", "Bracer", "Mirage", "IcePlunge"}
    assert resolve_against_catalogue("Civ/0/C Fridan", cat) == "Fridan"
    assert resolve_against_catalogue("Civ/1/A 7SA 'Concord'", cat) == "7SA 'Concord'"
    assert resolve_against_catalogue("Mil/1/C Bracer", cat) == "Bracer"
    assert resolve_against_catalogue("Sth/1/A Mirage", cat) == "Mirage"
    assert resolve_against_catalogue("Cmp/1/C IcePlunge", cat) == "IcePlunge"


def test_works_for_formats_no_tool_uses_yet():
    """The whole reason for anchoring on the catalogue rather than on a known
    tag shape: an editor we have never seen must work with no code change."""
    cat = {"Colossus"}
    for decorated in ("<<IND|1|B>> Colossus", "{industrial-1-b} Colossus",
                      "**IND 1 B** Colossus", "IND.1.B-Colossus"):
        assert resolve_against_catalogue(decorated, cat) == "Colossus"


def test_leaves_an_already_correct_name_alone():
    assert resolve_against_catalogue("Colossus", _REPORTER_CATALOGUE) == "Colossus"


def test_returns_none_when_nothing_matches():
    """An unknown item must stay unresolved so the caller can leave it be,
    rather than being forced onto the nearest catalogue entry."""
    assert resolve_against_catalogue("Ind/1/B Nonesuch", _REPORTER_CATALOGUE) is None
    assert resolve_against_catalogue("", _REPORTER_CATALOGUE) is None


def test_never_matches_mid_word():
    """A word boundary is required, or a short catalogue name would be
    recovered out of the middle of a longer, unrelated one."""
    assert resolve_against_catalogue("MegaColossus", {"Colossus"}) is None
    assert resolve_against_catalogue("Ind/1/B MegaColossus", {"Colossus"}) is None


def test_longest_match_wins():
    """Both are real items in the shipped fixture. The decoration sits at the
    front, so the longer suffix is the truer read of what the log meant."""
    cat = {"Cascade", "Fierell Cascade"}
    assert resolve_against_catalogue("Mil/1/B Fierell Cascade", cat) == "Fierell Cascade"


def test_no_same_length_tie_is_possible_by_construction():
    """A fixed-length trailing slice of the scanned name has exactly one
    value, so at most one *catalogue* member can equal it -- two distinct
    entries can never both match at the same length. Resolution is always
    deterministic whenever anything matches at all, including when a
    same-length decoy that does NOT actually match the tail is also present."""
    assert resolve_against_catalogue("Ind/1/B Alpha", {"Alpha", "BAlpha"}) == "Alpha"
    assert resolve_against_catalogue("x/1/B Beta", {"Beta", "Zeta"}) == "Beta"


def test_recovery_is_idempotent():
    """Running it twice must not walk further down the catalogue."""
    once = resolve_against_catalogue("Ind/1/B Colossus", _REPORTER_CATALOGUE)
    assert resolve_against_catalogue(once, _REPORTER_CATALOGUE) == once


def test_real_fixture_recovers_without_a_single_wrong_answer():
    """End-to-end against the shipped StarStrings-modified global.ini.

    Simulates the real situation: the catalogue holds the true names Smart
    Citizen knows about, the log holds that tool's decorated versions. A wrong
    recovery here would mean marking an item the user does not own, so the
    assertion is zero, not 'mostly'.
    """
    import re
    fixture = Path(__file__).parent / "fixtures" / "kraken_global_latest.ini"
    if not fixture.exists():
        pytest.skip("kraken_global_latest.ini not present")

    prefix = re.compile(r"^[A-Za-z]{2,5}/\d{1,2}/[A-Za-z]\s+")
    decorated = []
    for line in fixture.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("item_Name") and "=" in line:
            v = line.split("=", 1)[1].split("\n")[0].strip()
            if v and prefix.match(v):
                decorated.append(v)
    assert len(decorated) > 100, "fixture should carry plenty of foreign-tagged names"

    truth = {d: prefix.sub("", d) for d in decorated}
    catalogue = set(truth.values())

    wrong, unresolved = [], []
    for d in decorated:
        got = resolve_against_catalogue(d, catalogue)
        if got is None:
            unresolved.append(d)
        elif got != truth[d]:
            wrong.append((d, got, truth[d]))

    assert not wrong, f"{len(wrong)} names recovered to the WRONG item: {wrong[:3]}"
    # A handful may legitimately tie; the bulk must resolve.
    assert len(unresolved) < len(decorated) * 0.05, (
        f"{len(unresolved)} of {len(decorated)} unresolved: {unresolved[:5]}"
    )


# ── boundary characters (review follow-up) ──────────────────────────────────

def test_period_and_colon_are_valid_boundary_characters():
    """StarStrings uses "/", but a tool separating its tag with "." or ":"
    must recover too -- the whole point of anchoring on the catalogue instead
    of a known tag shape is that an editor never seen before still works."""
    assert resolve_against_catalogue("IND.1.B.Colossus", {"Colossus"}) == "Colossus"
    assert resolve_against_catalogue("IND:1:B:Colossus", {"Colossus"}) == "Colossus"


# ── repair_foreign_owned_names: partial-catalogue safety (review follow-up) ─
#
# MainWindow._repair_foreign_owned_names originally anchored on
# self._bp_item_names -- names currently eligible for the Owned star, i.e.
# only items some loaded mission is offering as a blueprint reward right now.
# That excludes any real item CIG has rotated out of every mission's reward
# pool this patch, which is the normal, recurring state for a long-owned
# item, not a rare one. Against that narrower set, a real owned item ending
# in a shorter, currently-listed real item's name would misread as
# "unmatched", get resolved to the shorter item by resolve_against_catalogue,
# and be silently discarded as an "already-owned duplicate" -- permanently
# losing a real ownership record. repair_foreign_owned_names itself is
# generic -- it has no way to know whether its catalogue argument is wide
# or narrow -- so the fix is entirely in what the caller builds and passes:
# known_item_names(entries), not build_blueprint_metadata(entries)'s keys.
# These tests build the catalogue the same way production now does, to lock
# in that a real item with no current mission reward still survives.

def test_partial_catalogue_does_not_delete_a_real_owned_item():
    """The exact incident: both 'Cascade' and 'Fierell Cascade' are real,
    separately-owned items. 'Fierell Cascade' has its own item_Name entry
    (so known_item_names includes it) even though -- unlike 'Cascade' -- no
    mission bullet references it here, standing in for an item CIG has
    rotated out of every current mission's reward pool. Recovery must leave
    it alone, not fold it into 'Cascade' and drop it."""
    entries = [
        _entry("item_NameCascade", "Cascade"),
        _entry("item_NameFierellCascade", "Fierell Cascade"),
    ]
    catalogue = known_item_names(entries)
    owned = {"Cascade", "Fierell Cascade"}

    repaired, renamed = repair_foreign_owned_names(owned, catalogue)

    assert repaired == owned
    assert renamed == {}


def test_the_narrower_bp_item_names_style_catalogue_reproduces_the_bug():
    """Documents WHY the wide catalogue matters: feeding repair_foreign_
    owned_names a catalogue that only contains mission-reward-eligible names
    (the old, pre-fix source) reintroduces the exact incident -- 'Fierell
    Cascade' misreads as unmatched, resolves to 'Cascade', and is dropped as
    a duplicate. Not a passing regression guard; a record of the failure
    mode the production wiring (main_window.py's _known_item_names) exists
    to avoid by never building the catalogue this way for repair."""
    owned = {"Cascade", "Fierell Cascade"}
    narrow_catalogue = {"Cascade"}  # e.g. build_blueprint_metadata(entries)'s keys

    repaired, renamed = repair_foreign_owned_names(owned, narrow_catalogue)

    assert "Fierell Cascade" not in repaired
    assert renamed == {"Fierell Cascade": None}


def test_repair_still_recovers_a_genuinely_foreign_name():
    """Same shape of catalogue as the test above, but the unmatched name
    really is foreign-tagged garbage, not a second real item -- this must
    still recover, so the partial-catalogue fix doesn't just make recovery
    inert."""
    owned = {"Cascade", "Ind/1/B Colossus"}
    catalogue = {"Cascade", "Colossus"}
    repaired, renamed = repair_foreign_owned_names(owned, catalogue)
    assert repaired == {"Cascade", "Colossus"}
    assert renamed == {"Ind/1/B Colossus": "Colossus"}


def test_repair_drops_a_genuine_foreign_duplicate():
    """When the real item is ALREADY separately owned under its clean name,
    the foreign-formatted twin is a true duplicate and should be dropped --
    renamed reports it as None (dropped), not resolved to a new name."""
    owned = {"Colossus", "Ind/1/B Colossus"}
    catalogue = {"Colossus"}
    repaired, renamed = repair_foreign_owned_names(owned, catalogue)
    assert repaired == {"Colossus"}
    assert renamed == {"Ind/1/B Colossus": None}


def test_repair_is_a_noop_on_an_already_clean_owned_set():
    owned = {"Colossus", "Agni"}
    repaired, renamed = repair_foreign_owned_names(owned, {"Colossus", "Agni"})
    assert repaired == owned
    assert renamed == {}


def test_repair_noop_on_empty_catalogue():
    """An empty catalogue means nothing is trustworthy to recover against --
    must leave owned untouched rather than treating everything as foreign."""
    owned = {"Colossus", "Ind/1/B Agni"}
    repaired, renamed = repair_foreign_owned_names(owned, set())
    assert repaired == owned
    assert renamed == {}


def test_repair_leaves_a_truly_unrecoverable_name_alone():
    """A name matching nothing in the catalogue at all (not a real item this
    install can currently see, under any decoration) is left exactly as-is --
    silently deleting it would be worse than one unmatched entry."""
    owned = {"Ind/1/B Nonesuch"}
    repaired, renamed = repair_foreign_owned_names(owned, {"Colossus"})
    assert repaired == owned
    assert renamed == {}


# ── known_item_names: the wider catalogue recovery must anchor on ──────────

def _entry(key, value):
    from src.models.string_model import StringEntry
    return StringEntry(
        key=key, source_file="global", category="Ship Items",
        original_value=value, custom_value="", status="Unmodified",
    )


def test_known_item_names_includes_items_with_no_current_mission_reward():
    """The whole point: a real item's own item_Name entry makes it "known"
    regardless of whether any mission is currently offering it as a
    blueprint reward -- unlike build_blueprint_metadata's returned dict,
    which is scoped to reward-eligible names only."""
    entries = [_entry("item_NameFierellCascade", "Fierell Cascade")]
    assert known_item_names(entries) == {"Fierell Cascade"}


def test_known_item_names_covers_vehicle_and_extra_prefixes():
    entries = [
        _entry("vehicle_NameANVL_Hornet", "Hornet"),
        _entry("item_mining_mininglaser_s1", "Helix I Mining Laser"),
    ]
    assert known_item_names(entries) == {"Hornet", "Helix I Mining Laser"}


def test_known_item_names_ignores_unrelated_keys():
    entries = [
        _entry("item_DescFierellCascade", "A powerful shield generator."),
        _entry("mission_title_001", "Some Mission"),
    ]
    assert known_item_names(entries) == set()
