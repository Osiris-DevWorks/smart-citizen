"""Tests for _count_enhancement_categories (#399): the Apply success dialog counts
what this apply just merged (sources_dict["enhancements"]), not self.entries,
which is stale after a first-time Simple-mode generation. Each key's category is
the generator's map first, then the key-prefix fallback, since the two disagree
for medical consumables ("Medical Consumables" vs "Gear").
"""
from __future__ import annotations

import inspect
import re

import pytest

from src.gui.main_window import MainWindow, _count_enhancement_categories

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


class TestApplyToGameWiring:
    """apply_to_game can't be driven without a window, so pin by source that it
    fetches the generator's category map and hands it to the helper. Without it
    every medical consumable lands in "Gear" again (the #399 review bug)."""

    @staticmethod
    def _source():
        return inspect.getsource(MainWindow.apply_to_game)

    def test_fetches_the_key_category_map(self):
        assert re.search(
            r"sources_dict, hierarchy, enhancements_key_categories\s*=\s*"
            r"load_sources_from_settings\(\)",
            self._source(),
        ), "apply_to_game dropped the map load_sources_from_settings() returns"

    def test_passes_the_map_to_the_helper(self):
        assert re.search(
            r"_count_enhancement_categories\(\s*sources_dict,"
            r"\s*enhancements_key_categories\s*\)",
            self._source(),
        ), "apply_to_game no longer passes the key-category map to the helper"
