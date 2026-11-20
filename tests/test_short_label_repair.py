"""Items' short labels and the #372 name repair (#570).

The game names some items twice: by the item's own name, and by a short label
for tight spaces under the same key plus "_short", such as an armour set's name
on its own (item_Name_srvl_armor_heavy_armor_02_short = "Dust Devil"). The
repair's item list, known_item_names, took both, so an old logged name that ends
in a set's name was saved as that label: older Spanish logs say "Piernas de la
armadura Dust Devil" where today's file says "Dust Devil (Piernas)", and the
repair turned 14 of #564's reporter's armour pieces into 8 labels, which match
no blueprint. The label keys and the items with "short" inside their keys are
real ones from the game's global.ini.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_meta import known_item_names, short_label_names  # noqa: E402
from src.utils.owned_items import (  # noqa: E402
    drop_short_labels,
    normalize_item_name,
    repair_foreign_owned_names,
    resolve_against_catalogue,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _entry(key, value):
    from src.models.string_model import StringEntry
    return StringEntry(
        key=key, source_file="global", category="Gear",
        original_value=value, custom_value="", status="Unmodified",
    )


# A Dust Devil set: its short label under the real key, and two of its pieces
# under today's Spanish names.
_DUST_DEVIL = [
    _entry("item_Name_srvl_armor_heavy_armor_02_short", "Dust Devil"),
    _entry("item_Name_srvl_armor_heavy_legs_02", "Dust Devil (Piernas)"),
    _entry("item_Name_srvl_armor_heavy_arms_02", "Dust Devil (Brazos)"),
]
_OLD_PIECE_NAMES = {"Piernas de la armadura Dust Devil", "Brazos de la armadura Dust Devil"}


@pytest.mark.parametrize("key", [
    "item_Name_srvl_armor_heavy_armor_02_short",
    "Item_NameSTOR_opencontainer_1SCU_short",
    "item_NameAEGS_EMP_Device_short,P",
    "item_Name_qrt_combat_heavy_armor_02_short_0",
    "item_NameKRIG_LaserRepeater_Bespoke_S2_Short",
])
def test_a_short_label_is_not_an_item(key):
    entries = [_entry(key, "Label")]
    assert known_item_names(entries) == set()
    assert short_label_names(entries) == {"Label"}


@pytest.mark.parametrize("key, value", [
    # "short" inside a real item's own key, never at its end.
    ("item_Namecrlf_medgun_01_short_grey01", 'ParaMed "Amalgam"'),
    ("item_NameRSI_DefaultRadar_ShortRange", "RSI Short Range Radar"),
    ("item_NameM_shortcrop_hair_01", "Disconnected Fade"),
    ("item_Name_nvy_training_shorts_01_01_01", "ActiveWear Training Shorts"),
])
def test_an_item_with_short_in_its_key_stays_an_item(key, value):
    entries = [_entry(key, value)]
    assert known_item_names(entries) == {normalize_item_name(value)}
    assert short_label_names(entries) == set()


def test_a_label_that_is_also_an_items_name_is_that_item():
    """The same text as a short label and as an item's own name: the item
    stays in the catalogue, and the text is not a label to drop."""
    entries = [
        _entry("item_Name_qrt_combat_heavy_armor_02_short", "Bokto"),
        _entry("vehicle_NameQRT_Bokto", "Bokto"),
    ]
    assert known_item_names(entries) == {"Bokto"}
    assert short_label_names(entries) == set()


def test_the_repair_leaves_old_piece_names_alone():
    """The reporter's case: a name whose piece is worded otherwise today stays
    as it was logged, not folded into the set's label."""
    catalogue = known_item_names(_DUST_DEVIL)
    assert resolve_against_catalogue("Piernas de la armadura Dust Devil", catalogue) is None
    assert repair_foreign_owned_names(set(_OLD_PIECE_NAMES), catalogue) == (_OLD_PIECE_NAMES, {})


def test_with_the_labels_in_the_repair_folds_the_pieces_into_one():
    """The bug, kept as a record: a catalogue that holds the label turns both
    pieces into it, the second dropped as a duplicate of the first."""
    catalogue = known_item_names(_DUST_DEVIL) | short_label_names(_DUST_DEVIL)
    repaired, renamed = repair_foreign_owned_names(set(_OLD_PIECE_NAMES), catalogue)
    assert repaired == {"Dust Devil"}
    assert sorted(map(str, renamed.values())) == ["Dust Devil", "None"]


def test_a_foreign_tag_on_a_real_name_is_still_repaired():
    """#372 still works with the labels left out."""
    catalogue = known_item_names(_DUST_DEVIL + [_entry("item_NameColossus", "Colossus")])
    assert resolve_against_catalogue("Ind/1/B Colossus", catalogue) == "Colossus"


def test_drop_short_labels_takes_only_the_labels():
    owned = {"Dust Devil", "Colossus", "Piernas de la armadura Testudo"}
    kept, dropped = drop_short_labels(owned, {"Dust Devil", "Testudo"})
    assert kept == {"Colossus", "Piernas de la armadura Testudo"}
    assert dropped == {"Dust Devil"}


def test_drop_short_labels_with_none_owned():
    assert drop_short_labels({"Colossus"}, {"Dust Devil"}) == ({"Colossus"}, set())
