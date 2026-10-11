"""Settings backups carry defaults, not just changed-from-default keys (#383).

A setting is only written to the backend when the user changes it, so
anything still at its default had no key for ``export_all_values`` to
enumerate. That made a backup silently partial: importing it could not put a
preference *back* to its default, because the backup never recorded what the
default was. The reported symptom was Mission Labels (rename Blueprints, then
import an older backup, and the rename survived), but the same held for every
setting with an implicit default.

Two kinds of test here:

* Behaviour — a default-valued setting travels in the backup, a stored value
  still wins over it, and the issue's own scenario now restores.
* Drift — :func:`test_every_getter_default_is_accounted_for` replays every
  no-arg ``AppSettings.get_*`` against a recording backend and asserts each
  key it reads is either materialised or deliberately excluded. Without it a
  newly added setting would quietly reintroduce exactly this bug, since
  nothing else forces an author to think about backups.
"""
import inspect
from pathlib import Path

import pytest

from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings
from src.utils.settings_profile import (
    SOURCE_MODE_PORTABLE,
    read_profile_zip,
    write_profile_zip,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class _RecordingBackend:
    """Backend that answers every read with the caller's own default.

    Records the (key, default) pair each getter asks for, which is how the
    drift test learns the full set of defaulted keys without a second
    hand-maintained list to fall out of step with the getters.
    """

    def __init__(self):
        self.seen: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings API
        self.seen.setdefault(key, default)
        return default

    def setValue(self, key, value):
        pass

    def remove(self, key):
        pass

    def sync(self):
        pass

    def keys(self):
        return []

    def allKeys(self):
        return []


class TestDefaultsInExport:
    def test_untouched_default_is_exported(self, json_backend):
        """The bug: a setting never changed still belongs in the backup."""
        exported = AppSettings.export_all_values()
        assert exported["mission_header/blueprints"] == "POTENTIAL BLUEPRINTS"
        assert exported["mission_header/blueprint_data"] == "BLUEPRINT DATA"

    def test_stored_value_overrides_the_default(self, json_backend):
        AppSettings.set_mission_header("blueprints", "MY BLUEPRINTS")
        exported = AppSettings.export_all_values()
        assert exported["mission_header/blueprints"] == "MY BLUEPRINTS"

    def test_every_materialised_default_is_json_safe(self, json_backend):
        """Backups are JSON, so a default that can't serialise breaks export."""
        import json

        json.dumps(AppSettings.export_all_values())

    @pytest.mark.parametrize("key", [
        "sc_install_root",       # clearing it can re-detect the wrong install (#370)
        "game_install_path",
        "owned_items",           # the player's collection, not a preference
        "test_plan/tester_name",
        "tutorial_completed_version",
    ])
    def test_state_keys_are_not_materialised(self, json_backend, key):
        assert key not in AppSettings.export_all_values()

    @pytest.mark.parametrize("key", [
        "user_data_dir", "cache_dir", "window_geometry", "string_column_widths",
    ])
    def test_machine_keys_stay_excluded(self, json_backend, key):
        """PROFILE_EXCLUDE_KEYS still wins over default materialisation."""
        assert key not in AppSettings.export_all_values()

    def test_watermark_prefix_is_not_materialised(self, json_backend):
        exported = AppSettings.export_all_values()
        assert not [k for k in exported if k.startswith("blueprint_log_watermark")]


class TestRestoreToDefault:
    def test_issue_383_scenario(self, json_backend, tmp_path):
        """Export at defaults, change a label, import: the change is undone.

        This is the exact sequence from #383. Before the fix the imported
        backup had no ``mission_header/blueprints`` key at all, so import
        left the later rename in place.
        """
        AppSettings.set_mission_header("details", "DETAILS")
        AppSettings.set_mission_header("items", "REWARDS")

        backup = tmp_path / "backup.zip"
        write_profile_zip(
            backup,
            settings=AppSettings.export_all_values(),
            overrides={},
            app_version="test",
            source_mode=SOURCE_MODE_PORTABLE,
        )

        AppSettings.set_mission_header("blueprints", "stuff")
        AppSettings.set_mission_header("blueprint_data", "stuff")

        AppSettings.import_values(read_profile_zip(backup).settings)

        headers = AppSettings.get_mission_headers()
        assert headers["blueprints"] == "POTENTIAL BLUEPRINTS"
        assert headers["blueprint_data"] == "BLUEPRINT DATA"
        # The customised ones are restored to their backed-up values, not wiped.
        assert headers["details"] == "DETAILS"
        assert headers["items"] == "REWARDS"

    def test_restore_to_default_covers_more_than_mission_labels(
        self, json_backend, tmp_path
    ):
        """The same fix has to hold for the other implicit-default settings."""
        backup = tmp_path / "backup.zip"
        write_profile_zip(
            backup,
            settings=AppSettings.export_all_values(),
            overrides={},
            app_version="test",
            source_mode=SOURCE_MODE_PORTABLE,
        )

        AppSettings.set_favorite_prefix("~")
        AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)

        AppSettings.import_values(read_profile_zip(backup).settings)

        assert AppSettings.get_favorite_prefix() == AppSettings.DEFAULT_FAVORITE_PREFIX
        assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


class TestNoDrift:
    """Guards that keep profile_default_values() honest as settings are added."""

    def test_every_getter_default_is_accounted_for(self, monkeypatch):
        """Every defaulted key a getter reads must be materialised or excluded.

        Replays the real getters rather than reading a list, so adding a
        setting with an implicit default fails here until its author decides
        whether it belongs in a backup.

        ``_RecordingBackend`` only mocks the settings store -- it does not
        stop a getter's own filesystem side effects. Several no-arg getters
        (``get_user_data_dir``, ``get_logs_dir``, ``get_dataforge_cache_dir``,
        ``get_backups_dir``) call ``Path.mkdir()`` on the resolved path as
        part of just reading it, which without this patch would create real
        directories under the developer's actual Documents/AppData on every
        run of this "hermetic" test.
        """
        monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)
        saved = AppSettings._backend
        recorder = _RecordingBackend()
        AppSettings._backend = recorder
        try:
            for name, fn in inspect.getmembers(AppSettings, callable):
                if not name.startswith("get_"):
                    continue
                params = inspect.signature(fn).parameters.values()
                if any(
                    p.default is inspect.Parameter.empty
                    and p.kind
                    in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    for p in params
                ):
                    continue  # needs an argument; not a plain profile read
                try:
                    fn()
                except Exception:  # noqa: BLE001 - a getter needing real I/O
                    continue
        finally:
            AppSettings._backend = saved

        materialised = set(AppSettings.profile_default_values())
        unaccounted = [
            key
            for key in recorder.seen
            if key not in materialised
            and AppSettings.is_profile_default_materialised(key)
        ]
        assert not unaccounted, (
            "These settings have a default but would not travel in a backup, "
            "so an import could not restore them to it (#383). Add each to "
            "AppSettings.profile_default_values(), or to "
            "PROFILE_DEFAULT_EXCLUDE_KEYS with a reason: "
            f"{sorted(unaccounted)}"
        )

    def test_materialised_defaults_match_the_getters(self, json_backend):
        """A materialised default must equal what the getter returns unset.

        Catches the table drifting away from the getter it mirrors, which
        would export a default the app never actually uses.
        """
        defaults = AppSettings.profile_default_values()
        backend = AppSettings.settings()
        mismatches = {
            key: (declared, backend.value(key, "<<unset>>"))
            for key, declared in defaults.items()
            if backend.value(key, "<<unset>>") != "<<unset>>"
        }
        assert not mismatches, (
            f"declared default != stored value on a fresh profile: {mismatches}"
        )

    def test_mission_header_map_matches_its_defaults(self):
        """_MISSION_HEADER_SETTING and MISSION_HEADER_DEFAULTS share field names."""
        assert set(AppSettings._MISSION_HEADER_SETTING) == set(
            AppSettings.MISSION_HEADER_DEFAULTS
        )
