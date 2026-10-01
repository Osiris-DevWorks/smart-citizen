"""Tests for _count_enhancement_categories (#399): the Apply-success-dialog
summary must count what THIS apply actually just merged, not self.entries.

Simple mode's one-button flow calls apply_to_game() before the reload that
refreshes self.entries with newly-generated content (that reload runs
afterward, to update the hidden Advanced view). On a profile that skipped
the startup "Generate Enhancements?" prompt and generated for the first time
via Simple mode's own click, self.entries was still whatever loaded before
generation ran -- typically nothing tagged "enhancements" yet, so counting
from self.entries reported 0 even though the game file itself was written
correctly (apply_to_game's own merge is independent of self.entries).
sources_dict["enhancements"] reflects exactly what was just merged, so
counting from its own keys is correct regardless of self.entries' staleness.

Also covers the #399 review follow-up: each key's category must prefer the
enhancements_key_categories map (what load_sources_from_settings() builds
from each generator's real output category) over StringEntry.extract_
category's key-prefix guess. The two disagree for every medical-consumable
key, which the prefix rules misclassify as "Gear".
"""
from __future__ import annotations

import pytest

from src.gui.main_window import _count_enhancement_categories

pytestmark = pytest.mark.unit


class TestCountEnhancementCategories:
    def test_empty_sources_dict_yields_empty_counter(self):
        assert _count_enhancement_categories({}) == {}

    def test_no_enhancements_key_yields_empty_counter(self):
        """Sources loaded, but nothing under "enhancements" -- e.g. every
        category disabled."""
        assert _count_enhancement_categories({"global": {"a": "1"}}) == {}

    def test_counts_by_category_not_by_source_dict_key_count(self):
        sources_dict = {
            "enhancements": {
                "vehicle_NameANVL_Carrack": "Carrack",
                "vehicle_DescANVL_Carrack": "A big ship",
                "item_NameSHLD_01": "Shield",
                "random_unrelated_key": "Other stuff",
            }
        }
        counts = _count_enhancement_categories(sources_dict)
        assert counts["Ships"] == 2
        assert counts["Ship Items"] == 1
        assert counts["Other"] == 1
        assert sum(counts.values()) == 4

    def test_ignores_every_other_source(self):
        """Only "enhancements" is counted -- global/user/etc. keys must not
        inflate the reported enhancement count."""
        sources_dict = {
            "global": {"vehicle_NameSABR_Sabre": "Sabre"},
            "user": {"vehicle_NameSABR_Sabre": "My Sabre"},
            "enhancements": {"vehicle_NameANVL_Carrack": "Carrack"},
        }
        counts = _count_enhancement_categories(sources_dict)
        assert sum(counts.values()) == 1
        assert counts["Ships"] == 1

    def test_enhancements_key_categories_map_wins_over_key_prefix(self):
        """#399 review: StringEntry.extract_category and
        enhancements_key_categories are not equivalent. Every medical-
        consumable key is item_Desccrlf_consumable_*, which extract_
        category's prefix rules land in "Gear" (no recognized ship-
        component code), but enhancements_key_categories correctly has it
        as "Medical Consumables" from the generator that actually produced
        it. Without the map, all 7 real medical-consumable keys silently
        land in "Gear" in the success-dialog breakdown."""
        sources_dict = {
            "enhancements": {
                "item_Desccrlf_consumable_adrenaline_01": "Reduces concussion symptoms...",
                "vehicle_NameANVL_Carrack": "Carrack",
            }
        }
        enhancements_key_categories = {
            "item_Desccrlf_consumable_adrenaline_01": "Medical Consumables",
        }
        counts = _count_enhancement_categories(sources_dict, enhancements_key_categories)
        assert counts["Medical Consumables"] == 1
        assert counts["Ships"] == 1
        assert "Gear" not in counts

    def test_missing_map_falls_back_to_key_prefix(self):
        """No map at all (the old call-site shape) still works -- every key
        falls back to extract_category, same as before this fix."""
        sources_dict = {
            "enhancements": {
                "item_Desccrlf_consumable_adrenaline_01": "Reduces concussion symptoms...",
            }
        }
        counts = _count_enhancement_categories(sources_dict)
        assert counts["Gear"] == 1

    def test_key_absent_from_map_falls_back_to_key_prefix(self):
        """A map that doesn't cover every key (e.g. a key the generator
        didn't tag) still categorizes that key via the prefix fallback,
        not a KeyError or miscount."""
        sources_dict = {
            "enhancements": {
                "vehicle_NameANVL_Carrack": "Carrack",
                "item_Desccrlf_consumable_adrenaline_01": "Reduces concussion symptoms...",
            }
        }
        enhancements_key_categories = {
            "vehicle_NameANVL_Carrack": "Ships",
            # adrenaline key deliberately absent from the map
        }
        counts = _count_enhancement_categories(sources_dict, enhancements_key_categories)
        assert counts["Ships"] == 1
        assert counts["Gear"] == 1

    def test_reflects_a_post_strip_enhancements_dict(self):
        """_build_apply_merged_dict strips "New" keys from sources_dict
        ["enhancements"] in place when "Include discovered items" is off,
        before this ever runs -- confirm counting from that already-
        stripped dict naturally picks up the reduced set, no double logic
        needed here."""
        sources_dict = {
            "enhancements": {
                "vehicle_NameANVL_Carrack": "Carrack",
                # "kept_new_key" was stripped upstream and is simply absent
            }
        }
        counts = _count_enhancement_categories(sources_dict)
        assert sum(counts.values()) == 1
