"""Tests for _count_enhancement_categories (#399): the Apply success dialog counts
what this apply just merged (sources_dict["enhancements"]), not self.entries,
which is stale after a first-time Simple-mode generation. Each key's category is
the generator's map first, then the key-prefix fallback, since the two disagree
for medical consumables ("Medical Consumables" vs "Gear").
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
    """Drives the real apply_to_game on a MagicMock self, with file I/O and
    message boxes stubbed, and reads the success dialog the user sees. A medical
    consumable must show as "Medical Consumables", not "Gear": that is what
    apply_to_game passing the generator's category map to the count is for."""

    KEY = "item_Desccrlf_consumable_adrenaline_01"

    def test_success_dialog_uses_the_category_map(self, tmp_path, monkeypatch):
        import src.merger.ini_merger as ini_merger
        import src.utils.user_cfg as user_cfg
        import src.utils.user_ini_manager as user_ini_manager
        from src.gui import main_window
        from src.utils.settings import AppSettings

        base = tmp_path / "base.ini"
        base.write_text(f"{self.KEY}=Stock\n", encoding="utf-8")
        shown = []

        class FakeMessageBox:
            class StandardButton:
                Yes = 1
                No = 2

            @staticmethod
            def information(parent, title, text, *args, **kwargs):
                shown.append(("information", text))

            @staticmethod
            def warning(parent, title, text, *args, **kwargs):
                shown.append(("warning", text))

            @staticmethod
            def critical(parent, title, text, *args, **kwargs):
                shown.append(("critical", text))

        monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
        monkeypatch.setattr(main_window, "load_sources_from_settings", lambda: (
            {AppSettings.SOURCE_GLOBAL: {self.KEY: "Stock"},
             AppSettings.SOURCE_ENHANCEMENTS: {self.KEY: "Enhanced"}},
            [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_ENHANCEMENTS,
             AppSettings.SOURCE_USER],
            {self.KEY: "Medical Consumables"},
        ))
        monkeypatch.setattr(AppSettings, "get_game_install_path",
                            staticmethod(lambda: str(tmp_path)))
        monkeypatch.setattr(AppSettings, "get_user_ini_path",
                            staticmethod(lambda: tmp_path / "user.ini"))
        monkeypatch.setattr(AppSettings, "get_global_ini_path",
                            staticmethod(lambda: tmp_path / "game" / "global.ini"))
        monkeypatch.setattr(AppSettings, "get_source_path",
                            staticmethod(lambda name: str(base)))
        monkeypatch.setattr(AppSettings, "is_source_enabled",
                            staticmethod(lambda name: True))
        monkeypatch.setattr(AppSettings, "get_language_languages_ini_path",
                            staticmethod(lambda: None))
        monkeypatch.setattr(user_ini_manager, "save_user_ini", lambda entries, path: 0)
        monkeypatch.setattr(ini_merger, "merge_ini_files", lambda b, m, t: None)
        monkeypatch.setattr(user_cfg, "ensure_user_cfg_language", lambda: None)

        window = MagicMock()
        window.entries = [object()]
        window._build_apply_merged_dict.return_value = {self.KEY: "Enhanced"}
        window._validate_applied_file.return_value = None

        MainWindow.apply_to_game(window)

        assert [kind for kind, _ in shown] == ["information"], shown
        assert "Medical Consumables: 1" in shown[0][1]
        assert "Gear" not in shown[0][1]
        window._mark_applied.assert_called_once()
