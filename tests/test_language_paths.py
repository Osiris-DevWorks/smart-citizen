"""Per-language cache paths, enhancement stamps, and base.ini URL resolution
(src/utils/settings.py language layer, 2.0 #30).

These helpers decide where files land on disk and whether a language switch
regenerates enhancements, so the layout is locked here:

  * English base.ini stays at the channel cache root; every other language
    caches under ``cache/lang/{language}/`` (created on demand).
  * Enhancements always live next to the base.ini they were generated from
    (``get_enhancements_dir`` is just the base.ini's parent).
  * The ``.dataforge_stamp`` marker round-trips per language and is isolated
    between languages — French's stamp must not satisfy Portuguese's check.
  * ``get_language_base_url`` resolves user override first, then the bundled
    sources.json map, then ''.
  * ``get_sc_language_id`` maps app folder names to SC identifiers and falls
    back to the raw name for unknown languages.
"""
from __future__ import annotations

import errno
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils import atomic_io  # noqa: E402
from src.utils import settings as settings_module  # noqa: E402
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic settings: tmp cache dir + tmp JsonSettings backend."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(AppSettings, "get_cache_dir", staticmethod(lambda: cache))
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield cache
    AppSettings._backend = saved


class TestBaseIniPath:
    def test_english_uses_cache_root(self, env):
        assert AppSettings.get_base_ini_path("english") == env / "base.ini"

    def test_english_does_not_create_lang_dir(self, env):
        AppSettings.get_base_ini_path("english")
        assert not (env / "lang").exists()

    def test_non_english_nests_under_lang(self, env):
        path = AppSettings.get_base_ini_path("french")
        assert path == env / "lang" / "french" / "base.ini"

    def test_non_english_creates_parent_dir(self, env):
        path = AppSettings.get_base_ini_path("french")
        assert path.parent.is_dir()

    def test_default_argument_uses_selected_language(self, env, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        assert AppSettings.get_base_ini_path() == env / "lang" / "french" / "base.ini"


class TestEnhancementsDir:
    def test_is_base_ini_parent_for_english(self, env):
        assert AppSettings.get_enhancements_dir("english") == env

    def test_is_base_ini_parent_for_non_english(self, env):
        assert (
            AppSettings.get_enhancements_dir("portuguese_br")
            == env / "lang" / "portuguese_br"
        )


class TestEnhancementsStamp:
    def test_absent_stamp_reads_empty(self, env):
        assert AppSettings.get_enhancements_stamp("french") == ""

    def test_round_trip(self, env):
        AppSettings.set_enhancements_stamp("p4k-2024-key", "french")
        assert AppSettings.get_enhancements_stamp("french") == "p4k-2024-key"

    def test_stamps_are_per_language(self, env):
        AppSettings.set_enhancements_stamp("french-key", "french")
        assert AppSettings.get_enhancements_stamp("portuguese_br") == ""

    def test_stamp_file_lives_in_enhancements_dir(self, env):
        AppSettings.set_enhancements_stamp("k", "french")
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.ENHANCEMENTS_STAMP_NAME
        )
        assert stamp.is_file()


class TestTagConfigStamp:
    """The .tag_config_stamp marker mirrors .dataforge_stamp: per-language,
    round-trips, isolated between languages, and a corrupt (non-UTF-8) stamp
    reads as missing rather than crashing (#251 bug class). Backs the Save Tag
    Changes button's per-channel freshness check on switch."""

    def test_absent_stamp_reads_empty(self, env):
        assert AppSettings.get_tag_config_stamp("french") == ""

    def test_round_trip(self, env):
        AppSettings.set_tag_config_stamp("abc123def456", "french")
        assert AppSettings.get_tag_config_stamp("french") == "abc123def456"

    def test_stamps_are_per_language(self, env):
        AppSettings.set_tag_config_stamp("french-fp", "french")
        assert AppSettings.get_tag_config_stamp("portuguese_br") == ""

    def test_independent_of_dataforge_stamp(self, env):
        # Both stamps live in the same dir but must not read each other.
        AppSettings.set_enhancements_stamp("p4k-key", "french")
        AppSettings.set_tag_config_stamp("tag-fp", "french")
        assert AppSettings.get_enhancements_stamp("french") == "p4k-key"
        assert AppSettings.get_tag_config_stamp("french") == "tag-fp"

    def test_stamp_file_lives_in_enhancements_dir(self, env):
        AppSettings.set_tag_config_stamp("fp", "french")
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.TAG_CONFIG_STAMP_NAME
        )
        assert stamp.is_file()

    def test_corrupt_stamp_reads_empty(self, env):
        # A non-UTF-8 stamp must be treated as missing, not raise (#251).
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.TAG_CONFIG_STAMP_NAME
        )
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_bytes(b"stamp\xa0value")
        assert AppSettings.get_tag_config_stamp("french") == ""


_STAMPS = [
    pytest.param(
        AppSettings.ENHANCEMENTS_STAMP_NAME,
        AppSettings.set_enhancements_stamp, AppSettings.get_enhancements_stamp,
        id="dataforge",
    ),
    pytest.param(
        AppSettings.TAG_CONFIG_STAMP_NAME,
        AppSettings.set_tag_config_stamp, AppSettings.get_tag_config_stamp,
        id="tag_config",
    ),
]


def _hold_exclusively(path: Path):
    """Open *path* with no sharing at all, as a swap briefly does, and return
    an idempotent release."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, open_existing, attribute_normal = 0x80000000, 3, 0x80
    handle = k32.CreateFileW(str(path), generic_read, 0, None, open_existing,
                             attribute_normal, None)
    assert handle not in (None, wintypes.HANDLE(-1).value), ctypes.get_last_error()
    released = threading.Lock()

    def release():
        if released.acquire(blocking=False):
            k32.CloseHandle(handle)

    return release


@pytest.mark.regression
class TestStampsAreWrittenWhole:
    """Both stamps are written in one step and read with a short retry
    (src/utils/atomic_io.py), like the INIs beside them: a cut-off write
    never leaves half a key, and a reader that opens a stamp while it is
    swapped in does not take it as missing."""

    @pytest.mark.parametrize("name, setter, getter", _STAMPS)
    def test_a_failed_stamp_write_keeps_the_old_stamp(
        self, env, monkeypatch, caplog, name, setter, getter
    ):
        setter("old-key", "french")
        stamp = AppSettings.get_enhancements_dir("french") / name
        old_bytes = stamp.read_bytes()

        def disk_full(source, destination):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(atomic_io.os, "replace", disk_full)
        setter("new-key", "french")   # logged, not raised

        assert stamp.read_bytes() == old_bytes
        assert getter("french") == "old-key"
        assert not list(stamp.parent.glob(".sc-*.tmp"))
        assert any(r.levelname == "WARNING" for r in caplog.records)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing rules")
    @pytest.mark.parametrize("name, setter, getter", _STAMPS)
    def test_a_stamp_held_for_a_moment_is_not_read_as_missing(
        self, env, monkeypatch, name, setter, getter
    ):
        setter("p4k-key", "french")
        stamp = AppSettings.get_enhancements_dir("french") / name
        monkeypatch.setattr(atomic_io, "READ_DELAY_S", 0.2)
        release = _hold_exclusively(stamp)
        timer = threading.Timer(0.1, release)
        try:
            # Control: a plain read while the stamp is held fails.
            with pytest.raises(PermissionError):
                stamp.read_text(encoding="utf-8")
            timer.start()
            assert getter("french") == "p4k-key"
        finally:
            timer.cancel()
            if timer.ident is not None:
                timer.join()
            release()


@pytest.mark.regression
class TestStampsGoWhereTheRunStarted:
    """A generation captures its folder and DataForge build key when it
    starts, so a channel, data-folder or cache-folder change during a hidden
    run cannot stamp a set that run never wrote. The setters take that folder
    and the build key takes that cache folder."""

    @pytest.mark.parametrize("name, setter, getter", _STAMPS)
    def test_a_stamp_folder_overrides_the_language_dir(
        self, env, tmp_path, name, setter, getter
    ):
        elsewhere = tmp_path / "where-the-run-started"
        setter("run-key", "french", folder=elsewhere)
        assert (elsewhere / name).read_text(encoding="utf-8") == "run-key"
        assert getter("french") == ""
        assert not (AppSettings.get_enhancements_dir("french") / name).exists()

    def test_invalidate_empties_the_dataforge_stamp_only(self, env):
        AppSettings.set_enhancements_stamp("p4k-key", "french")
        AppSettings.set_tag_config_stamp("tag-fp", "french")
        folder = AppSettings.get_enhancements_dir("french")

        AppSettings.invalidate_enhancements_stamp(folder)

        assert (folder / AppSettings.ENHANCEMENTS_STAMP_NAME).read_bytes() == b""
        assert AppSettings.get_enhancements_stamp("french") == ""
        # The tag stamp has its own button, which already lights when the
        # live config differs from it.
        assert AppSettings.get_tag_config_stamp("french") == "tag-fp"
        # Session-only Skip: nothing but the stamp is written.
        assert sorted(p.name for p in folder.iterdir()) == sorted(
            [AppSettings.ENHANCEMENTS_STAMP_NAME, AppSettings.TAG_CONFIG_STAMP_NAME]
        )

    def test_a_failed_invalidation_is_only_logged(self, env, monkeypatch, caplog):
        AppSettings.set_enhancements_stamp("p4k-key", "french")

        def disk_full(source, destination):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(atomic_io.os, "replace", disk_full)
        AppSettings.invalidate_enhancements_stamp(AppSettings.get_enhancements_dir("french"))
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_the_build_key_reads_the_given_cache_folder(self, env, tmp_path, monkeypatch):
        from src.utils.pak_extractor import P4K_MTIME_STAMP

        current, given = tmp_path / "current-cache", tmp_path / "run-cache"
        for folder, key in ((current, "current-build"), (given, "run-build")):
            folder.mkdir()
            (folder / P4K_MTIME_STAMP).write_text(key, encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_dataforge_cache_dir", staticmethod(lambda: current))
        assert AppSettings.get_dataforge_build_key() == "current-build"
        assert AppSettings.get_dataforge_build_key(given) == "run-build"


class TestLanguageBaseUrl:
    def test_unset_and_unbundled_resolves_empty(self, env, monkeypatch):
        monkeypatch.setattr(settings_module, "_bundled_language_sources", lambda: {})
        assert AppSettings.get_language_base_url("french") == ""

    def test_bundled_map_is_the_fallback(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/bundled.ini"
        )

    def test_user_override_wins_over_bundled(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        AppSettings.set_language_source_override(
            "french", "https://example.test/override.ini"
        )
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/override.ini"
        )

    def test_clearing_override_restores_bundled(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        AppSettings.set_language_source_override("french", "https://x.test/o.ini")
        AppSettings.set_language_source_override("french", "")
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/bundled.ini"
        )

    def test_overrides_are_per_language(self, env, monkeypatch):
        monkeypatch.setattr(settings_module, "_bundled_language_sources", lambda: {})
        AppSettings.set_language_source_override("french", "https://x.test/fr.ini")
        assert AppSettings.get_language_base_url("portuguese_br") == ""


class TestLocalizedDocPath:
    @pytest.fixture
    def docs_env(self, tmp_path, monkeypatch):
        """Fake languages/ tree with a translated HELP.md for french only."""
        langs = tmp_path / "languages"
        (langs / "french").mkdir(parents=True)
        (langs / "french" / "HELP.md").write_text("# Aide", encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_languages_dir", staticmethod(lambda: langs))
        return langs

    def test_translated_doc_wins_for_non_english(self, docs_env):
        path = AppSettings.get_localized_doc_path("HELP.md", "french")
        assert path == docs_env / "french" / "HELP.md"

    def test_english_always_uses_bundled_docs(self, docs_env):
        path = AppSettings.get_localized_doc_path("HELP.md", "english")
        assert path.parts[-2:] == ("docs", "HELP.md")

    def test_missing_translation_falls_back_to_bundled_docs(self, docs_env):
        # french ships no LEGAL.md in this fixture → bundled English copy.
        path = AppSettings.get_localized_doc_path("LEGAL.md", "french")
        assert path.parts[-2:] == ("docs", "LEGAL.md")

    def test_default_argument_uses_selected_language(self, docs_env, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        path = AppSettings.get_localized_doc_path("HELP.md")
        assert path == docs_env / "french" / "HELP.md"


class TestIssue306FaqBackfill:
    """#306: french/spanish/portuguese_br predate docs/FAQ.md (#152) and never
    got a translated copy, so get_localized_doc_path silently fell back to
    the English FAQ for those three languages. italian, chinese, and german
    shipped a translated FAQ from day one; japanese missed it too and was
    backfilled separately (#334). Locks that the gap is closed and stays
    closed for all four languages."""

    REPO = Path(__file__).resolve().parent.parent
    _ENGLISH_HEADINGS = None

    @classmethod
    def _english_headings(cls):
        if cls._ENGLISH_HEADINGS is None:
            text = (cls.REPO / "docs" / "FAQ.md").read_text(encoding="utf-8")
            cls._ENGLISH_HEADINGS = [
                line for line in text.splitlines() if line.startswith("## ")
            ]
        return cls._ENGLISH_HEADINGS

    @pytest.mark.parametrize(
        "language", ["french", "spanish", "portuguese_br", "japanese"]
    )
    def test_faq_exists_and_is_not_the_english_fallback(self, language):
        faq_path = self.REPO / "languages" / language / "FAQ.md"
        assert faq_path.exists(), f"languages/{language}/FAQ.md is missing"
        translated = faq_path.read_text(encoding="utf-8")
        english = (self.REPO / "docs" / "FAQ.md").read_text(encoding="utf-8")
        assert translated != english, f"{language} FAQ.md is just the English source"

    @pytest.mark.parametrize(
        "language", ["french", "spanish", "portuguese_br", "japanese"]
    )
    def test_faq_section_count_matches_english(self, language):
        faq_path = self.REPO / "languages" / language / "FAQ.md"
        headings = [
            line
            for line in faq_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("## ")
        ]
        assert len(headings) == len(self._english_headings()), (
            f"{language} FAQ.md has {len(headings)} sections, "
            f"English has {len(self._english_headings())}"
        )


class TestGlobalIniPath:
    """get_global_ini_path(language=...) (#409 follow-up): the apply target
    for a specific language, independent of get_selected_language(). Needed
    so Map Language File can check a mapped path against the language being
    mapped, not whichever language happens to be active right now."""

    def test_language_argument_overrides_selected_language(self, env, tmp_path, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        monkeypatch.setattr(AppSettings, "get_selected_language", staticmethod(lambda: "english"))
        path = AppSettings.get_global_ini_path("korean")
        assert path == tmp_path / "data" / "Localization" / "korean_(south_korea)" / "global.ini"

    def test_default_argument_uses_selected_language(self, env, tmp_path, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        monkeypatch.setattr(AppSettings, "get_selected_language", staticmethod(lambda: "french"))
        path = AppSettings.get_global_ini_path()
        assert path == tmp_path / "data" / "Localization" / "french_(france)" / "global.ini"


class TestIsLocalSourceSameAsApplyTarget:
    """Guards Map Language File against mapping a language's own apply
    target as its source (#409 follow-up) — see is_local_source_same_as_apply_target."""

    @pytest.fixture(autouse=True)
    def _channel(self, env, tmp_path, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_channel_install_path", staticmethod(lambda: str(tmp_path)))
        self.channel_root = tmp_path

    def test_exact_match_is_blocked(self):
        target = self.channel_root / "data" / "Localization" / "korean_(south_korea)" / "global.ini"
        assert AppSettings.is_local_source_same_as_apply_target(str(target), "korean") is True

    def test_case_insensitive_match_is_blocked(self):
        target = self.channel_root / "data" / "Localization" / "korean_(south_korea)" / "global.ini"
        assert AppSettings.is_local_source_same_as_apply_target(str(target).upper(), "korean") is True

    def test_relative_path_resolving_to_target_is_blocked(self, monkeypatch):
        korean_dir = self.channel_root / "data" / "Localization" / "korean_(south_korea)"
        korean_dir.mkdir(parents=True)
        monkeypatch.chdir(korean_dir)
        assert AppSettings.is_local_source_same_as_apply_target("global.ini", "korean") is True

    def test_different_language_in_same_tree_is_not_blocked(self):
        # The user's own copy under a sibling language folder is a different
        # file on disk and must not trip the guard.
        other = self.channel_root / "data" / "Localization" / "french_(france)" / "global.ini"
        assert AppSettings.is_local_source_same_as_apply_target(str(other), "korean") is False

    def test_unrelated_path_is_not_blocked(self):
        unrelated = self.channel_root / "Downloads" / "global.ini"
        assert AppSettings.is_local_source_same_as_apply_target(str(unrelated), "korean") is False


class TestScLanguageId:
    def test_known_mapping(self):
        assert AppSettings.get_sc_language_id("portuguese_br") == "portuguese_(brazil)"
        assert AppSettings.get_sc_language_id("english") == "english"

    def test_unknown_language_falls_back_to_raw_name(self):
        assert AppSettings.get_sc_language_id("klingon") == "klingon"

    def test_default_argument_uses_selected_language(self, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        assert AppSettings.get_sc_language_id() == "french_(france)"
