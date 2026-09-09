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
