"""OneDrive data-root detection (#172).

The default data root resolves Documents via the shell Personal folder, which
honors OneDrive Known Folder Move — so on a redirected machine the per-user data
lands inside OneDrive and can be dehydrated/emptied. These tests lock the
detection that drives the in-app warning.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.utils.onedrive import (  # noqa: E402
    is_onedrive_path,
    onedrive_roots,
    suggest_local_data_dir,
)
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved

ENV = {"OneDrive": r"C:\Users\aabou\OneDrive", "USERPROFILE": r"C:\Users\aabou"}


# ── is_onedrive_path ─────────────────────────────────────────────────────────

class TestIsOneDrivePath:
    def test_under_onedrive_root_env(self):
        assert is_onedrive_path(r"C:\Users\aabou\OneDrive\Documents\Smart Citizen", ENV)

    def test_exact_onedrive_root(self):
        assert is_onedrive_path(r"C:\Users\aabou\OneDrive", ENV)

    def test_local_documents_is_not_onedrive(self):
        # %USERPROFILE%\Documents is the local, non-redirected path.
        assert not is_onedrive_path(r"C:\Users\aabou\Documents\Smart Citizen", ENV)

    def test_unrelated_local_path(self):
        assert not is_onedrive_path(r"C:\SmartCitizenData", ENV)

    def test_segment_match_without_env(self):
        # Env var unset, but a OneDrive segment is present → still detected.
        assert is_onedrive_path(r"C:\Users\bob\OneDrive\Documents\SC", {})

    def test_org_onedrive_segment(self):
        assert is_onedrive_path(r"C:\Users\bob\OneDrive - Contoso\SC", {})

    def test_onedrive_dash_org_segment(self):
        assert is_onedrive_path(r"C:\Users\bob\OneDrive-Contoso\SC", {})

    def test_lookalike_segment_not_matched(self):
        # "OneDriveBackups" is not a OneDrive folder.
        assert not is_onedrive_path(r"C:\Users\bob\OneDriveBackups\SC", {})

    def test_case_insensitive(self):
        assert is_onedrive_path(r"c:\users\aabou\onedrive\documents\sc", ENV)

    def test_empty_or_none(self):
        assert not is_onedrive_path("", ENV)
        assert not is_onedrive_path(None, ENV)

    def test_accepts_path_object(self):
        assert is_onedrive_path(Path(r"C:\Users\aabou\OneDrive\x"), ENV)

    def test_sibling_prefix_is_not_a_child(self):
        # "...\OneDriveStuff" must not count as under "...\OneDrive".
        env = {"OneDrive": r"C:\Users\bob\OneDrive"}
        # Has no OneDrive *segment* and isn't under the root either.
        assert not is_onedrive_path(r"C:\Users\bob\OneDriveStuff\x", env)


# ── onedrive_roots ───────────────────────────────────────────────────────────

class TestOneDriveRoots:
    def test_collects_all_vars(self):
        env = {
            "OneDrive": r"C:\a\OneDrive",
            "OneDriveCommercial": r"C:\a\OneDrive - Org",
        }
        roots = [str(p) for p in onedrive_roots(env)]
        assert any("OneDrive" in r for r in roots)
        assert len(roots) == 2

    def test_dedupes(self):
        env = {"OneDrive": r"C:\a\OneDrive", "OneDriveConsumer": r"C:\a\OneDrive"}
        assert len(onedrive_roots(env)) == 1

    def test_empty_env(self):
        assert onedrive_roots({}) == []


# ── suggest_local_data_dir ───────────────────────────────────────────────────

class TestSuggestLocalDataDir:
    def test_uses_userprofile_local_documents(self):
        got = suggest_local_data_dir(ENV)
        assert got == Path(r"C:\Users\aabou") / "Documents" / "Smart Citizen"

    def test_suggestion_is_not_onedrive(self):
        # The whole point: the suggested folder must not itself be in OneDrive.
        assert not is_onedrive_path(suggest_local_data_dir(ENV), ENV)


# ── OneDrive-warning "don't warn me again" flag (#172) ───────────────────────

class TestOneDriveWarningDismissed:
    def test_defaults_false(self, json_backend):
        # Fresh install: the startup warning has not been dismissed.
        assert AppSettings.get_onedrive_warning_dismissed() is False

    def test_set_true_persists(self, json_backend):
        AppSettings.set_onedrive_warning_dismissed(True)
        assert AppSettings.get_onedrive_warning_dismissed() is True

    def test_round_trip_back_to_false(self, json_backend):
        AppSettings.set_onedrive_warning_dismissed(True)
        AppSettings.set_onedrive_warning_dismissed(False)
        assert AppSettings.get_onedrive_warning_dismissed() is False
