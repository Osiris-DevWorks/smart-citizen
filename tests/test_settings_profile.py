"""Export/Import Settings backup (settings_profile.py + AppSettings helpers).

Covers the zip pack/unpack contract (manifest validation, per-channel
overrides, schema forward-compat refusal) and the AppSettings side: the
machine-specific key filter that runs on both export and import, backend
enumeration for either backend shape, the post-import apply flag, and the
per-channel user.ini collection. Ends with the full round-trip: export from
one profile, import into a fresh one.
"""
import json
import zipfile
from datetime import datetime

import pytest

from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings
from src.utils.settings_profile import (
    InvalidProfileError,
    MANIFEST_NAME,
    SCHEMA_VERSION,
    SETTINGS_NAME,
    SOURCE_MODE_PORTABLE,
    SOURCE_MODE_REGISTRY,
    default_backup_filename,
    read_profile_zip,
    write_profile_zip,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


@pytest.fixture
def data_root(tmp_path, json_backend):
    """Point the user-data dir at a tmp folder (via the override key)."""
    root = tmp_path / "userdata"
    root.mkdir()
    json_backend.setValue(AppSettings.USER_DATA_DIR, str(root))
    return root


SETTINGS = {
    "theme": "dark",
    "favorite_prefix": "*",
    "enhancements/categories/ships/enabled": True,
    "tag_builder/components/config": '{"separator": "dash"}',
}
OVERRIDES = {
    "LIVE": "vehicle_Name=Test Ship\n",
    "PTU": "item_Name=Test Item\n",
}


def _write(tmp_path, **kwargs):
    out = tmp_path / "backup.zip"
    defaults = dict(
        settings=SETTINGS,
        overrides=OVERRIDES,
        app_version="2.3.0",
        source_mode=SOURCE_MODE_PORTABLE,
    )
    defaults.update(kwargs)
    write_profile_zip(out, **defaults)
    return out


class TestWriteRead:
    def test_round_trip(self, tmp_path):
        out = _write(tmp_path)
        p = read_profile_zip(out)
        assert p.settings == SETTINGS
        assert p.overrides == OVERRIDES
        assert p.schema_version == SCHEMA_VERSION
        assert p.app_version == "2.3.0"
        assert p.source_mode == SOURCE_MODE_PORTABLE
        assert p.exported_at  # ISO string recorded

    def test_entry_count_and_layout(self, tmp_path):
        out = _write(tmp_path)
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert names == {
            MANIFEST_NAME,
            SETTINGS_NAME,
            "overrides/LIVE/user.ini",
            "overrides/PTU/user.ini",
        }

    def test_no_overrides_is_fine(self, tmp_path):
        out = _write(tmp_path, overrides={})
        p = read_profile_zip(out)
        assert p.overrides == {}
        assert p.settings == SETTINGS

    def test_registry_source_mode_round_trips(self, tmp_path):
        out = _write(tmp_path, source_mode=SOURCE_MODE_REGISTRY)
        assert read_profile_zip(out).source_mode == SOURCE_MODE_REGISTRY

    def test_manifest_channels_listed(self, tmp_path):
        out = _write(tmp_path)
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read(MANIFEST_NAME))
        assert manifest["channels"] == ["LIVE", "PTU"]
        assert manifest["app"] == "SmartCitizen"

    def test_unicode_survives(self, tmp_path):
        out = _write(
            tmp_path,
            settings={"favorite_prefix": "★"},
            overrides={"LIVE": "vehicle_Name=Ærøskøbing — ✓\n"},
        )
        p = read_profile_zip(out)
        assert p.settings["favorite_prefix"] == "★"
        assert "Ærøskøbing — ✓" in p.overrides["LIVE"]


class TestValidation:
    def test_not_a_zip(self, tmp_path):
        bad = tmp_path / "not.zip"
        bad.write_text("this is not a zip")
        with pytest.raises(InvalidProfileError):
            read_profile_zip(bad)

    def test_zip_without_manifest(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("random.txt", "hello")
        with pytest.raises(InvalidProfileError, match="manifest"):
            read_profile_zip(out)

    def test_wrong_app_marker(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SomethingElse", "schema_version": 1}))
        with pytest.raises(InvalidProfileError, match="wasn't made by"):
            read_profile_zip(out)

    def test_newer_schema_refused(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(
                MANIFEST_NAME,
                json.dumps({"app": "SmartCitizen", "schema_version": SCHEMA_VERSION + 1}),
            )
        with pytest.raises(InvalidProfileError, match="newer version"):
            read_profile_zip(out)

    def test_garbled_manifest(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, "{not json")
        with pytest.raises(InvalidProfileError):
            read_profile_zip(out)

    def test_garbled_settings(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr(SETTINGS_NAME, "[1, 2")
        with pytest.raises(InvalidProfileError):
            read_profile_zip(out)

    def test_settings_must_be_object(self, tmp_path):
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr(SETTINGS_NAME, json.dumps([1, 2, 3]))
        with pytest.raises(InvalidProfileError, match="JSON object"):
            read_profile_zip(out)

    def test_nested_override_entry_skipped(self, tmp_path):
        """A crafted zip can't smuggle an override outside a channel dir."""
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr("overrides/LIVE/../evil/user.ini", "x=y\n")
            zf.writestr("overrides/LIVE/nested/user.ini", "x=y\n")
            zf.writestr("overrides/LIVE/user.ini", "good=1\n")
        p = read_profile_zip(out)
        assert p.overrides == {"LIVE": "good=1\n"}

    def test_dot_dot_channel_segment_rejected(self, tmp_path):
        """A bare ".." channel segment has no "/" to trip the old guard, but
        would resolve get_channel_user_ini_path() outside the data root."""
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr("overrides/../user.ini", "evil=1\n")
            zf.writestr("overrides/./user.ini", "evil=1\n")
            zf.writestr("overrides/LIVE/user.ini", "good=1\n")
        p = read_profile_zip(out)
        assert p.overrides == {"LIVE": "good=1\n"}

    def test_backslash_channel_segment_rejected(self, tmp_path):
        """A backslash segment has no forward slash either, but is a real
        path separator on Windows, where get_channel_user_ini_path() runs."""
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr("overrides/..\\evil/user.ini", "evil=1\n")
            zf.writestr("overrides/LIVE/user.ini", "good=1\n")
        p = read_profile_zip(out)
        assert p.overrides == {"LIVE": "good=1\n"}

    def test_drive_qualified_channel_segment_rejected(self, tmp_path):
        """A drive-qualified segment carries no separator at all, but pathlib
        re-anchors on it: "D:evil" joins to D:\\evil, and even same-drive
        "C:.." lands on the data root's parent. Both escape the data root."""
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps({"app": "SmartCitizen", "schema_version": 1}))
            zf.writestr("overrides/D:evil/user.ini", "evil=1\n")
            zf.writestr("overrides/D:/user.ini", "evil=1\n")
            zf.writestr("overrides/C:../user.ini", "evil=1\n")
            zf.writestr("overrides/C:foo/user.ini", "evil=1\n")
            zf.writestr("overrides/LIVE/user.ini", "good=1\n")
        p = read_profile_zip(out)
        assert p.overrides == {"LIVE": "good=1\n"}


class TestDefaultFilename:
    def test_format(self):
        name = default_backup_filename(today=datetime(2026, 7, 24))
        assert name == "SmartCitizen-Settings-Backup-20260724.zip"

    def test_no_version_in_name(self):
        """Backups import across app versions; the name must not imply otherwise."""
        assert "2.3.0" not in default_backup_filename(today=datetime(2026, 7, 24))


class TestExcludedKeys:
    @pytest.mark.parametrize("key", sorted(AppSettings.PROFILE_EXCLUDE_KEYS))
    def test_explicit_exclusions(self, key):
        assert AppSettings.is_profile_excluded_key(key)

    def test_column_widths_are_machine_local(self):
        """Named explicitly rather than left to the parametrized sweep above:
        that one iterates the set, so dropping the key would delete its own
        test case and pass silently.

        Column widths are measured against one screen, exactly like window
        geometry. Carried in an export and adopted verbatim, a wide-monitor
        layout lands on a laptop with columns off the edge, and HELP.md
        promises an export carries no machine-specific layout.
        """
        assert AppSettings.is_profile_excluded_key("string_column_widths")

    def test_migration_markers_excluded(self):
        assert AppSettings.is_profile_excluded_key("_channel_layout_migrated")
        assert AppSettings.is_profile_excluded_key("_retired_url_sources_pruned_v3")

    def test_local_source_path_excluded_url_kept(self):
        key = "data_sources/global/path"
        assert AppSettings.is_profile_excluded_key(key, r"C:\Users\x\Documents\base.ini")
        assert not AppSettings.is_profile_excluded_key(key, "https://example.com/global.ini")

    def test_ordinary_keys_travel(self):
        assert not AppSettings.is_profile_excluded_key("theme", "dark")
        assert not AppSettings.is_profile_excluded_key("merge_hierarchy", ["global", "user"])
        assert not AppSettings.is_profile_excluded_key("data_sources/global/enabled", True)


class TestExportAllValues:
    def test_filters_machine_keys(self, json_backend):
        json_backend.setValue("theme", "dark")
        json_backend.setValue(AppSettings.USER_DATA_DIR, r"C:\Users\x\Documents\SC")
        json_backend.setValue(AppSettings.CACHE_DIR, r"D:\dataforge-cache")
        json_backend.setValue("_channel_layout_migrated", True)
        out = AppSettings.export_all_values()
        assert out["theme"] == "dark"
        # Defaults now travel too (#383), so assert on what must be absent
        # rather than on the whole dict.
        assert AppSettings.USER_DATA_DIR not in out
        assert AppSettings.CACHE_DIR not in out
        assert "_channel_layout_migrated" not in out

    def test_sc_install_path_travels(self, json_backend):
        """The game folder IS carried — reconcile validates it on import."""
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, r"C:\Games\StarCitizen")
        out = AppSettings.export_all_values()
        assert out[AppSettings.SC_INSTALL_ROOT] == r"C:\Games\StarCitizen"

    def test_non_serialisable_value_skipped(self, json_backend):
        json_backend.setValue("theme", "dark")
        # Bypass _persist's own guard by poking the in-memory dict — mimics a
        # backend whose value() hands back a non-JSON type (QSettings can).
        json_backend._data["weird"] = object()
        out = AppSettings.export_all_values()
        assert "weird" not in out
        assert out["theme"] == "dark"

    def test_allkeys_backend_shape(self, monkeypatch):
        """QSettings-shaped backends (allKeys, not keys) enumerate fine."""
        class FakeQSettings:
            def __init__(self):
                self._d = {"theme": "light", "user_data_dir": r"C:\x"}
            def allKeys(self):
                return list(self._d)
            def value(self, key, default=None, type=None):  # noqa: A002
                return self._d.get(key, default)
        saved = AppSettings._backend
        AppSettings._backend = FakeQSettings()
        try:
            out = AppSettings.export_all_values()
        finally:
            AppSettings._backend = saved
        assert out["theme"] == "light"
        assert "user_data_dir" not in out


class TestImportValues:
    def test_applies_and_filters(self, json_backend):
        applied = AppSettings.import_values({
            "theme": "dark",
            "favorite_prefix": "*",
            AppSettings.USER_DATA_DIR: r"D:\Old\PC\Documents",
            "_channel_layout_migrated": True,
        })
        assert applied == 2
        assert json_backend.value("theme") == "dark"
        assert json_backend.value(AppSettings.USER_DATA_DIR) is None
        assert json_backend.value("_channel_layout_migrated") is None

    def test_layers_over_existing(self, json_backend):
        json_backend.setValue("theme", "light")
        json_backend.setValue("favorite_prefix", "*")
        AppSettings.import_values({"theme": "dark"})
        assert json_backend.value("theme") == "dark"
        assert json_backend.value("favorite_prefix") == "*"  # untouched

    def test_non_string_keys_ignored(self, json_backend):
        assert AppSettings.import_values({3: "x", "": "y", "ok": 1}) == 1


class TestPostImportFlag:
    def test_default_false(self, json_backend):
        assert AppSettings.get_post_import_apply_pending() is False

    def test_set_and_clear(self, json_backend):
        AppSettings.set_post_import_apply_pending(True)
        assert AppSettings.get_post_import_apply_pending() is True
        AppSettings.set_post_import_apply_pending(False)
        assert AppSettings.get_post_import_apply_pending() is False
        # Cleared = removed, not stored False — the key never lingers.
        assert AppSettings.POST_IMPORT_APPLY_PENDING not in json_backend.keys()

    def test_flag_never_travels_in_backup(self, json_backend):
        AppSettings.set_post_import_apply_pending(True)
        assert AppSettings.POST_IMPORT_APPLY_PENDING not in AppSettings.export_all_values()


class TestExportChannelOverrides:
    def test_collects_per_channel(self, data_root):
        (data_root / "LIVE").mkdir()
        (data_root / "LIVE" / "user.ini").write_text("a=1\n", encoding="utf-8")
        (data_root / "PTU").mkdir()
        (data_root / "PTU" / "user.ini").write_text("b=2\n", encoding="utf-8")
        assert AppSettings.export_channel_overrides() == {"LIVE": "a=1\n", "PTU": "b=2\n"}

    def test_empty_and_missing_skipped(self, data_root):
        (data_root / "LIVE").mkdir()
        (data_root / "LIVE" / "user.ini").write_text("", encoding="utf-8")
        assert AppSettings.export_channel_overrides() == {}

    def test_legacy_overrides_ini_fallback(self, data_root):
        (data_root / "EPTU").mkdir()
        (data_root / "EPTU" / "overrides.ini").write_text("c=3\n", encoding="utf-8")
        assert AppSettings.export_channel_overrides() == {"EPTU": "c=3\n"}


class TestReconcileInstallPath:
    """The imported SC folder is kept only when it exists on this machine."""

    @staticmethod
    def _make_sc_root(tmp_path, name="StarCitizen"):
        root = tmp_path / name
        (root / "LIVE").mkdir(parents=True)
        return root

    def test_valid_path_restored(self, tmp_path, json_backend):
        root = self._make_sc_root(tmp_path)
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(root))
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_RESTORED
        )
        assert AppSettings.get_sc_install_root() == str(root)

    def test_restore_syncs_legacy_game_path(self, tmp_path, json_backend):
        root = self._make_sc_root(tmp_path)
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(root))
        AppSettings.reconcile_imported_install_path()
        # game_install_path must be re-derived, not left stale from the backup.
        assert json_backend.value(AppSettings.GAME_INSTALL_PATH) == str(
            root / AppSettings.get_active_channel()
        )

    def test_dead_path_cleared(self, tmp_path, json_backend, monkeypatch):
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(tmp_path / "nope"))
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, str(tmp_path / "nope" / "LIVE"))
        # Neutralise the real detection chain so this stays hermetic.
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_NONE
        )
        assert json_backend.value(AppSettings.SC_INSTALL_ROOT) is None
        assert json_backend.value(AppSettings.GAME_INSTALL_PATH) is None

    def test_dead_path_falls_back_to_detection(self, tmp_path, json_backend, monkeypatch):
        other = self._make_sc_root(tmp_path, "DetectedElsewhere")
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(tmp_path / "nope"))
        monkeypatch.setattr(
            AppSettings, "get_sc_install_root", staticmethod(lambda: str(other))
        )
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_REDETECTED
        )

    def test_no_path_in_backup(self, json_backend, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_NONE
        )

    def test_a_file_is_not_a_valid_root(self, tmp_path, json_backend, monkeypatch):
        bogus = tmp_path / "StarCitizen.txt"
        bogus.write_text("not a folder")
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(bogus))
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_NONE
        )

    def test_dir_without_channel_folder_rejected(self, tmp_path, json_backend, monkeypatch):
        empty = tmp_path / "EmptyDir"
        empty.mkdir()
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(empty))
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_NONE
        )


class TestFullRoundTrip:
    def test_export_import_across_profiles(self, tmp_path, data_root, json_backend):
        # Profile A: preferences + the game folder + a LIVE override.
        sc_root = tmp_path / "StarCitizen"
        (sc_root / "LIVE").mkdir(parents=True)
        json_backend.setValue("theme", "dark")
        json_backend.setValue("tag_builder/components/config", '{"separator": "dash"}')
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(sc_root))
        json_backend.setValue(AppSettings.USER_DATA_DIR, str(data_root))
        (data_root / "LIVE").mkdir()
        (data_root / "LIVE" / "user.ini").write_text("vehicle_Name=X\n", encoding="utf-8")

        out = tmp_path / "roundtrip.zip"
        write_profile_zip(
            out,
            settings=AppSettings.export_all_values(),
            overrides=AppSettings.export_channel_overrides(),
            app_version="2.3.0",
            source_mode=SOURCE_MODE_REGISTRY,
        )

        # Profile B: a fresh backend, import the zip.
        AppSettings._backend = JsonSettings(tmp_path / "fresh-config.json")
        profile = read_profile_zip(out)
        applied = AppSettings.import_values(profile.settings)

        # Every key the backup carried is applied. Not a fixed count: the
        # backup now also carries defaults (#383), so it grows whenever a
        # setting is added.
        assert applied == len(profile.settings)
        assert AppSettings.settings().value("theme") == "dark"
        assert AppSettings.settings().value("tag_builder/components/config") == '{"separator": "dash"}'
        # The game folder DID follow the backup, and still exists here.
        assert AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT) == str(sc_root)
        assert (
            AppSettings.reconcile_imported_install_path()
            == AppSettings.INSTALL_PATH_RESTORED
        )
        # The data-root override did NOT follow (machine-local).
        assert AppSettings.settings().value(AppSettings.USER_DATA_DIR) is None
        assert profile.overrides == {"LIVE": "vehicle_Name=X\n"}

    def test_backup_imports_into_a_different_app_version(self, tmp_path, json_backend):
        """A backup made by an older build imports into a newer one."""
        out = tmp_path / "old.zip"
        write_profile_zip(
            out,
            settings={"theme": "dark"},
            overrides={},
            app_version="2.2.0",           # exported by an older release
            source_mode=SOURCE_MODE_REGISTRY,
        )
        profile = read_profile_zip(out)    # running build reads it fine
        assert profile.app_version == "2.2.0"
        assert AppSettings.import_values(profile.settings) == 1


class TestExportFlushesTagBuilder:
    """Export must back up the Tag Builder state the user is *looking at*.

    Tag configs only reach settings via Save Tag Changes / Generate
    Enhancements (`_persist_tag_builder_state`), so exporting without
    flushing would snapshot the previous config — the same trap #215 fixed
    for Generate. Driven on a lightweight stand-in ``self`` with the real
    unbound method, matching tests/test_ui_mode.py (no pytest-qt in dev
    deps — see tests/CLAUDE.md).
    """

    def test_export_flushes_pending_tag_edits_before_reading(self, tmp_path, json_backend):
        from src.gui.main_window import MainWindow

        calls = []

        class FakeTab:
            def flush_pending_tag_edits(self):
                # Mimic the real flush landing the on-screen config.
                calls.append("flushed")
                AppSettings.settings().setValue(
                    "tag_builder/components/config", '{"separator": "underscore"}'
                )

        class FakeStatusBar:
            def showMessage(self, *a, **k):
                pass

        captured = {}

        class Stub:
            enhancements_tab = FakeTab()

            def statusBar(self):
                return FakeStatusBar()

        stub = Stub()

        # Cancel at the file dialog: we only care that the flush already
        # happened by the time values are read.
        import src.gui.main_window as mw

        def fake_save_dialog(*a, **k):
            captured["at_dialog"] = AppSettings.export_all_values()
            return ("", "")

        orig = mw.QFileDialog.getSaveFileName
        mw.QFileDialog.getSaveFileName = staticmethod(fake_save_dialog)
        try:
            MainWindow._handle_export_settings(stub)
        finally:
            mw.QFileDialog.getSaveFileName = orig

        assert calls == ["flushed"], "export must flush Tag Builder edits first"
        assert captured["at_dialog"].get("tag_builder/components/config") == (
            '{"separator": "underscore"}'
        ), "the flushed on-screen tag config must be in the exported values"
