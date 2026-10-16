"""Tests for the DataForge cache-directory split (1.4.1).

Pre-1.4.1 ``AppSettings.get_dataforge_cache_dir()`` was hard-pinned to
``%LOCALAPPDATA%\\Smart Citizen\\{channel}\\cache\\dataforge\\`` with no
way to redirect it. The motivation for LOCALAPPDATA was sound
(OneDrive churn on the ~1.2 GB / ~31k-file XML tree) but it ignored
two cases the user could reasonably control:

  * **Registry-mode override** — a user who has explicitly moved
    USER_DATA_DIR off OneDrive Documents has already opted out of
    OneDrive, but the cache stayed in LOCALAPPDATA regardless.
  * **Portable mode** — the whole point is everything-next-to-exe,
    but the cache still landed in LOCALAPPDATA, breaking relocatability.

The fix introduces a CACHE_DIR setting independent from USER_DATA_DIR
and routes ``get_dataforge_cache_dir`` through a base resolver that
checks override → portable → LOCALAPPDATA in that order. The historic
LOCALAPPDATA default is preserved so unchanged installs see no path
movement on upgrade. These tests lock the resolution order and the
override I/O contract, deferred cleanup for custom cache locations, and
staged migration to the default LOCALAPPDATA location.
"""
from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from tests.unusable_folder import missing_drive_folder, new_folders_denied  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Use a tmp JsonSettings so each test gets a clean key-value store
    and never touches the real registry. Also pins the active channel so
    path comparisons are deterministic across machines."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    monkeypatch.setattr(AppSettings, "get_active_channel", staticmethod(lambda: "LIVE"))
    yield AppSettings._backend
    AppSettings._backend = saved


@pytest.fixture
def registry_mode(monkeypatch):
    """Ensure build_mode.IS_PORTABLE is False for registry-mode tests.

    Patches via the dotted-string form so the attribute lookup happens
    at apply-time against ``sys.modules["src.utils.build_mode"]``. A
    module-level ``build_mode`` import would go stale when
    test_build_info_fallback.py reloads the module via ``sys.modules.pop``
    — keying the patch by string instead avoids that staleness.
    """
    monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", False)


@pytest.fixture
def portable_mode(monkeypatch, tmp_path):
    """Flip IS_PORTABLE and pin _portable_data_dir to a tmp path so the
    next-to-exe resolution becomes hermetic. Dotted-string patch to
    survive test_build_info_fallback's sys.modules reload (see
    ``registry_mode`` for the same reason)."""
    monkeypatch.setattr("src.utils.build_mode.IS_PORTABLE", True)
    monkeypatch.setattr(
        AppSettings, "_portable_data_dir",
        staticmethod(lambda: tmp_path / "portable_data"),
    )


class TestOverrideIO:
    def test_get_returns_empty_when_unset(self, json_backend):
        assert AppSettings.get_cache_dir_override() == ""

    def test_set_then_get_roundtrips(self, json_backend, tmp_path):
        target = tmp_path / "my-cache"
        AppSettings.set_cache_dir(target)
        assert AppSettings.get_cache_dir_override() == str(target)

    def test_set_none_clears_override(self, json_backend, tmp_path):
        AppSettings.set_cache_dir(tmp_path / "x")
        AppSettings.set_cache_dir(None)
        assert AppSettings.get_cache_dir_override() == ""

    def test_set_empty_string_clears_override(self, json_backend, tmp_path):
        AppSettings.set_cache_dir(tmp_path / "x")
        AppSettings.set_cache_dir("")
        assert AppSettings.get_cache_dir_override() == ""

    def test_set_whitespace_only_clears_override(self, json_backend, tmp_path):
        """A user who blanks the input shouldn't end up with a literal
        whitespace path stored. Mirrors the user-data-dir guard."""
        AppSettings.set_cache_dir(tmp_path / "x")
        AppSettings.set_cache_dir("   ")
        assert AppSettings.get_cache_dir_override() == ""


class TestRegistryModeDefault:
    """No override + registry mode → unchanged %LOCALAPPDATA% path.

    Locks the back-compat contract: a user upgrading from 1.4.0 with no
    CACHE_DIR set must continue to read/write the same path so their
    existing ~1.2 GB cache stays valid without re-extraction.
    """

    def test_default_uses_localappdata(self, json_backend, registry_mode, monkeypatch, tmp_path):
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        path = AppSettings.get_dataforge_cache_dir()
        assert path == fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert path.exists(), "get_dataforge_cache_dir should mkdir on the leaf"

    def test_base_resolver_strips_channel(self, json_backend, registry_mode, monkeypatch, tmp_path):
        """get_dataforge_cache_base returns the *base* (no channel suffix)
        so the Config tab can show the user the "root" they configured
        rather than a per-channel leaf."""
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        assert AppSettings.get_dataforge_cache_base() == fake_local / "Smart Citizen"

    def test_the_default_base_is_named_with_an_override_set(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """The folder the Config tab names when a reset to the default fails
        (#494): the default whatever the override, made nowhere."""
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_cache_dir(tmp_path / "ssd-cache")
        assert AppSettings.get_default_dataforge_cache_base() == fake_local / "Smart Citizen"
        AppSettings.set_cache_dir(None)
        assert AppSettings.get_dataforge_cache_base() == fake_local / "Smart Citizen"
        assert not fake_local.exists()


class TestRegistryModeOverride:
    def test_override_redirects_base(self, json_backend, registry_mode, tmp_path):
        target = tmp_path / "ssd-cache"
        AppSettings.set_cache_dir(target)
        assert AppSettings.get_dataforge_cache_base() == target.resolve()

    def test_override_preserves_channel_nesting(self, json_backend, registry_mode, tmp_path):
        target = tmp_path / "ssd-cache"
        AppSettings.set_cache_dir(target)
        path = AppSettings.get_dataforge_cache_dir()
        assert path == target.resolve() / "LIVE" / "cache" / "dataforge"

    def test_override_expands_env_vars(self, json_backend, registry_mode, monkeypatch, tmp_path):
        """%CUSTOM_VAR% in the override should expand at resolution time.
        Users pasting registry-style paths shouldn't be surprised by a
        literal '%' surviving."""
        target_root = tmp_path / "expanded-root"
        monkeypatch.setenv("MY_SC_CACHE", str(target_root))
        AppSettings.set_cache_dir("%MY_SC_CACHE%")
        assert AppSettings.get_dataforge_cache_base() == target_root.resolve()

    def test_override_independent_of_user_data_dir(self, json_backend, registry_mode, tmp_path):
        """The whole point of the split: setting one doesn't move the other."""
        user_data = tmp_path / "documents-sc"
        cache = tmp_path / "ssd-sc"
        AppSettings.set_user_data_dir(user_data)
        AppSettings.set_cache_dir(cache)
        assert AppSettings.get_user_data_dir() == user_data.resolve()
        assert AppSettings.get_dataforge_cache_base() == cache.resolve()


class TestPortableMode:
    def test_default_is_next_to_exe(self, json_backend, portable_mode, tmp_path):
        """Portable + no override = next to exe. This was the user-reported
        bug: pre-fix, portable builds still pointed at LOCALAPPDATA."""
        path = AppSettings.get_dataforge_cache_dir()
        # tmp_path/portable_data/cache/LIVE/cache/dataforge
        assert path == tmp_path / "portable_data" / "cache" / "LIVE" / "cache" / "dataforge"

    def test_override_wins_over_portable_default(self, json_backend, portable_mode, tmp_path):
        """Portable users still get the override option (e.g. cache off
        a slow USB stick onto a fast local SSD)."""
        target = tmp_path / "ssd-cache"
        AppSettings.set_cache_dir(target)
        assert AppSettings.get_dataforge_cache_base() == target.resolve()

    def test_the_default_base_is_named_with_an_override_set(
        self, json_backend, portable_mode, tmp_path
    ):
        """As in registry mode (#494), the default here being next to the exe."""
        AppSettings.set_cache_dir(tmp_path / "ssd-cache")
        assert AppSettings.get_default_dataforge_cache_base() == (
            tmp_path / "portable_data" / "cache")
        AppSettings.set_cache_dir(None)
        assert AppSettings.get_dataforge_cache_base() == tmp_path / "portable_data" / "cache"
        assert not (tmp_path / "portable_data").exists()


class TestPendingCleanup:
    """When the user changes the cache path and opts to delete the old
    cache after re-extraction, the old path is stashed in a setting that
    MainWindow consumes after the next successful P4K extraction."""

    def test_get_returns_empty_when_unset(self, json_backend):
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_set_then_get_roundtrips(self, json_backend, tmp_path):
        AppSettings.set_pending_cache_cleanup(tmp_path / "old-cache")
        assert AppSettings.get_pending_cache_cleanup() == str(tmp_path / "old-cache")

    def test_set_none_clears(self, json_backend, tmp_path):
        AppSettings.set_pending_cache_cleanup(tmp_path / "old-cache")
        AppSettings.set_pending_cache_cleanup(None)
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_set_empty_string_clears(self, json_backend, tmp_path):
        AppSettings.set_pending_cache_cleanup(tmp_path / "old-cache")
        AppSettings.set_pending_cache_cleanup("")
        assert AppSettings.get_pending_cache_cleanup() == ""


def _seed_cache(path: Path, stamp_value: str = "123") -> Path:
    """Create a DataForge-cache-shaped dir with a valid freshness stamp."""
    from src.utils.pak_extractor import P4K_MTIME_STAMP

    path.mkdir(parents=True, exist_ok=True)
    (path / P4K_MTIME_STAMP).write_text(stamp_value)
    (path / "raw").mkdir(exist_ok=True)
    (path / "raw" / "record.xml").write_text("<x/>")
    return path


def _has_stamp(path: Path) -> bool:
    from src.utils.pak_extractor import P4K_MTIME_STAMP

    return (path / P4K_MTIME_STAMP).exists()


class TestMigrateRespectsConfiguredCacheDir:
    """``migrate_dataforge_cache_to_local`` must target the *resolved*
    cache dir, not a hardcoded %LOCALAPPDATA%.

    Regression: the migrator computed its destination as
    ``%LOCALAPPDATA%\\Smart Citizen\\{channel}\\cache\\dataforge`` directly
    while ``get_dataforge_cache_dir()`` honoured CACHE_DIR. A user who
    pointed the Config tab's DataForge Cache Folder at another drive got
    the cache silently dragged back to LOCALAPPDATA on the next launch,
    undoing the setting every single time.
    """

    def test_override_equal_to_user_data_dir_is_left_alone(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """The exact reported case: CACHE_DIR == USER_DATA_DIR makes the
        migrator's source and destination the same path. It must no-op
        instead of moving the cache out to LOCALAPPDATA."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        root = tmp_path / "data" / "Smart Citizen"
        AppSettings.set_user_data_dir(root)
        AppSettings.set_cache_dir(root)

        cache = _seed_cache(root / "LIVE" / "cache" / "dataforge")

        AppSettings.migrate_dataforge_cache_to_local()

        assert _has_stamp(cache), "configured cache must stay put"
        assert AppSettings.get_pending_cache_cleanup() == ""
        stray = tmp_path / "LocalAppData" / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert not _has_stamp(stray), "must not be dragged back to LOCALAPPDATA"

    @pytest.mark.parametrize("destination_state", ["empty", "stamped", "partial"])
    def test_override_queues_cleanup_without_copying_or_deleting(
        self, json_backend, registry_mode, monkeypatch, tmp_path, destination_state
    ):
        import shutil

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        AppSettings.set_user_data_dir(tmp_path / "userdata")
        AppSettings.set_cache_dir(tmp_path / "fast-ssd")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "456")
        dest = AppSettings.get_dataforge_cache_dir()
        if destination_state == "stamped":
            _seed_cache(dest, "789")
        elif destination_state == "partial":
            (dest / "partial.xml").write_text("<partial/>")
        before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
        mutations = {
            name: Mock(side_effect=AssertionError(f"Unexpected startup {name}"))
            for name in ("move", "copytree", "rmtree")
        }
        for name, mutation in mutations.items():
            monkeypatch.setattr(shutil, name, mutation)

        AppSettings.migrate_dataforge_cache_to_local()

        assert AppSettings.get_pending_cache_cleanup() == str(old)
        assert _has_stamp(old), "old cache must survive until re-extraction succeeds"
        assert (old / "raw" / "record.xml").read_text() == "<x/>"
        assert {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()} == before
        assert not dest.with_name("dataforge.migrating").exists()
        assert not (tmp_path / "LocalAppData").exists()
        for mutation in mutations.values():
            mutation.assert_not_called()

    def test_override_cleanup_stays_deferred_on_relaunch(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        AppSettings.set_user_data_dir(tmp_path / "userdata")
        AppSettings.set_cache_dir(tmp_path / "fast-ssd")
        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge")

        AppSettings.migrate_dataforge_cache_to_local()
        AppSettings.migrate_dataforge_cache_to_local()

        assert AppSettings.get_pending_cache_cleanup() == str(old)
        assert _has_stamp(old)
        assert not _has_stamp(AppSettings.get_dataforge_cache_dir())

    def test_missing_source_does_not_queue_cleanup_or_create_destination(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        AppSettings.set_user_data_dir(tmp_path / "userdata")
        target = tmp_path / "fast-ssd"
        AppSettings.set_cache_dir(target)

        AppSettings.migrate_dataforge_cache_to_local()

        assert AppSettings.get_pending_cache_cleanup() == ""
        assert not target.exists()

    def test_no_override_still_moves_to_localappdata(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """Back-compat: an unchanged install (no CACHE_DIR) keeps the
        historic Documents -> LOCALAPPDATA behaviour."""
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "Documents" / "Smart Citizen")

        old = _seed_cache(
            tmp_path / "Documents" / "Smart Citizen" / "LIVE" / "cache" / "dataforge", "789"
        )

        AppSettings.migrate_dataforge_cache_to_local()

        dest = fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert _has_stamp(dest)
        assert not old.exists()
        assert not (dest / "dataforge").exists(), "must rename, not nest inside dest"
        assert not dest.with_name("dataforge.migrating").exists()
        assert AppSettings.get_pending_cache_cleanup() == ""

    def test_no_override_stamped_destination_removes_stale_source(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "userdata")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "old")
        dest = _seed_cache(
            fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge", "new"
        )

        AppSettings.migrate_dataforge_cache_to_local()

        assert not old.exists(), "stale source should be cleaned up"
        from src.utils.pak_extractor import P4K_MTIME_STAMP
        assert (dest / P4K_MTIME_STAMP).read_text() == "new"

    def test_no_override_is_idempotent(self, json_backend, registry_mode, monkeypatch, tmp_path):
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "userdata")
        _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "abc")

        AppSettings.migrate_dataforge_cache_to_local()
        AppSettings.migrate_dataforge_cache_to_local()

        dest = fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert _has_stamp(dest)
        assert not (dest / "dataforge").exists()


class TestMigrateDoesNotDestroyCache:
    """Destructive-path guards for ``migrate_dataforge_cache_to_local``.

    The function moves and then deletes a ~1.2 GB user cache, so every
    branch that can reach an ``rmtree`` needs a test. With no CACHE_DIR
    override, Documents on another drive still needs a cross-volume move,
    which shutil implements as a non-atomic copytree + rmtree. An interrupted
    copy must never masquerade as a complete cache on the following launch.
    """

    def test_unstamped_nonempty_destination_is_left_alone(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """A partial extraction already sitting at the destination must not
        cost the user their good source cache."""
        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "userdata")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "good")
        dest = fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "partial.xml").write_text("<x/>")

        AppSettings.migrate_dataforge_cache_to_local()

        assert _has_stamp(old), "source must survive an unusable destination"
        assert (dest / "partial.xml").exists(), "destination must be untouched"

    def test_interrupted_move_never_strands_a_stamped_partial(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """Simulates a cross-volume copy dying after the stamp made it across
        (stamps sort ahead of ``raw/`` in scandir order). The destination must
        not end up looking like a valid cache."""
        import shutil

        from src.utils.pak_extractor import P4K_MTIME_STAMP

        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "userdata")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "good")
        dest = fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        staging = dest.with_name("dataforge.migrating")

        def exploding_move(src, dst):
            assert Path(dst) == staging
            Path(dst).mkdir(parents=True, exist_ok=True)
            (Path(dst) / P4K_MTIME_STAMP).write_text("partial")
            raise OSError("No space left on device")

        monkeypatch.setattr(shutil, "move", exploding_move)
        AppSettings.migrate_dataforge_cache_to_local()

        assert _has_stamp(old), "source must survive a failed move"
        assert not _has_stamp(dest), "no stamped partial may be left at the destination"
        assert not staging.exists(), "failed copy should be discarded while source is intact"

    def test_source_survives_relaunch_after_interrupted_move(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """The regression that makes the previous case dangerous: on the next
        launch a stamped partial would send the stamp branch straight into
        rmtree(old_dir), destroying the only complete copy."""
        import shutil

        from src.utils.pak_extractor import P4K_MTIME_STAMP

        fake_local = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
        AppSettings.set_user_data_dir(tmp_path / "userdata")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "good")

        def exploding_move(src, dst):
            Path(dst).mkdir(parents=True, exist_ok=True)
            (Path(dst) / P4K_MTIME_STAMP).write_text("partial")
            raise OSError("No space left on device")

        with monkeypatch.context() as patch:
            patch.setattr(shutil, "move", exploding_move)
            AppSettings.migrate_dataforge_cache_to_local()

        AppSettings.migrate_dataforge_cache_to_local()

        dest = fake_local / "Smart Citizen" / "LIVE" / "cache" / "dataforge"
        assert _has_stamp(dest), "retry should complete the migration"
        assert (dest / P4K_MTIME_STAMP).read_text() == "good"
        assert not old.exists()

    def test_unavailable_destination_does_not_raise(
        self, json_backend, registry_mode, monkeypatch, tmp_path
    ):
        """An override pointing at absent removable/network storage must not
        abort startup — the migrator runs before any window exists."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        AppSettings.set_user_data_dir(tmp_path / "userdata")
        AppSettings.set_cache_dir(tmp_path / "gone")

        old = _seed_cache(tmp_path / "userdata" / "LIVE" / "cache" / "dataforge", "good")

        def boom():
            raise OSError(3, "The system cannot find the path specified")

        monkeypatch.setattr(
            AppSettings, "get_dataforge_cache_dir", staticmethod(boom)
        )

        AppSettings.migrate_dataforge_cache_to_local()

        assert _has_stamp(old), "source must be untouched when the target is gone"
        assert AppSettings.get_pending_cache_cleanup() == ""


class TestCachePathDoesNotCreate:
    """#494. ``get_dataforge_cache_leaf()`` names the active channel's cache
    folder without creating it, for every check that only reads (the cache
    status, its freshness, the build key). ``get_dataforge_cache_dir()`` is
    the same folder plus the ``mkdir``, kept for the code about to write the
    cache, and still raises when the folder cannot be made: the migrator and
    the global.ini extraction depend on that. Status checks used the creating
    one, so a cache folder Windows refused, or one on a drive that is gone,
    stopped Smart Citizen opening."""

    @staticmethod
    def _named_then_made(expected: Path) -> None:
        leaf = AppSettings.get_dataforge_cache_leaf()
        assert leaf == expected
        assert not leaf.exists(), "naming the cache folder must not create it"
        assert AppSettings.get_dataforge_cache_dir() == leaf
        assert leaf.is_dir()

    def test_registry_default(self, json_backend, registry_mode, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        self._named_then_made(
            tmp_path / "LocalAppData" / "Smart Citizen" / "LIVE" / "cache" / "dataforge")

    def test_override(self, json_backend, registry_mode, tmp_path):
        AppSettings.set_cache_dir(tmp_path / "fast-ssd")
        self._named_then_made(
            (tmp_path / "fast-ssd").resolve() / "LIVE" / "cache" / "dataforge")

    def test_portable(self, json_backend, portable_mode, tmp_path):
        self._named_then_made(
            tmp_path / "portable_data" / "cache" / "LIVE" / "cache" / "dataforge")

    def test_a_refused_folder_is_named_and_only_the_writer_raises(
        self, json_backend, registry_mode, tmp_path
    ):
        base = tmp_path / "refused"
        base.mkdir()
        AppSettings.set_cache_dir(base)
        with new_folders_denied(base):
            leaf = AppSettings.get_dataforge_cache_leaf()
            assert leaf == base.resolve() / "LIVE" / "cache" / "dataforge"
            assert AppSettings.get_dataforge_build_key() == "unknown"
            with pytest.raises(PermissionError):
                AppSettings.get_dataforge_cache_dir()
        assert list(base.iterdir()) == []

    def test_a_missing_drive_is_named_and_only_the_writer_raises(
        self, json_backend, registry_mode
    ):
        base = missing_drive_folder()
        AppSettings.set_cache_dir(base)
        assert AppSettings.get_dataforge_cache_leaf() == base / "LIVE" / "cache" / "dataforge"
        assert AppSettings.get_dataforge_build_key() == "unknown"
        with pytest.raises(FileNotFoundError):
            AppSettings.get_dataforge_cache_dir()

    def test_a_cache_already_there_under_refusing_folders_still_works(
        self, json_backend, registry_mode, tmp_path
    ):
        """Every folder down to the cache denies new folders: the cache is
        found by both, and its build key read."""
        base = tmp_path / "refused"
        leaf = _seed_cache(base / "LIVE" / "cache" / "dataforge", "1700000000.0")
        AppSettings.set_cache_dir(base)
        with new_folders_denied(base, base / "LIVE", base / "LIVE" / "cache", leaf):
            assert AppSettings.get_dataforge_cache_leaf() == leaf.resolve()
            assert AppSettings.get_dataforge_cache_dir() == leaf.resolve()
            assert AppSettings.get_dataforge_build_key() == "1700000000.0"


# The method that creates the cache folder, and the code allowed to call it:
# what is about to write the cache, each calling it once.
_CREATING_GETTER = "get_dataforge_cache_dir"
_CACHE_WRITERS = {
    # Moves an old cache into the new location.
    "src/utils/settings.py::AppSettings.migrate_dataforge_cache_to_local": 1,
    # Extracts DataForge into the cache.
    "src/gui/main_window.py::MainWindow._run_dataforge_extraction": 1,
    # Works beside the cache folder (#471), in %TEMP% when it cannot be made.
    "src/gui/main_window.py::MainWindow._run_p4k_extraction": 1,
    # Makes the new cache folder the user just picked, for the re-extract.
    "src/gui/config_tab.py::ConfigTab._maybe_apply_cache_change": 1,
}

# Where the guard looks: the app and the scripts, the enhancement generator
# among them.
_SCANNED_FOLDERS = ("src", "scripts")
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _scanned_sources() -> list[Path]:
    """Every .py file the drift guard reads."""
    return [path for folder in _SCANNED_FOLDERS
            for path in sorted((_REPO_ROOT / folder).rglob("*.py"))]


def _uses_of_the_creating_getter(source: str, label: str) -> Counter:
    """Every use of ``get_dataforge_cache_dir`` in *source* (a call, a bare
    reference handed on, or its name as a string for ``getattr``), counted by
    the function it sits in, as ``<label>::<Class.method>``."""
    found: Counter = Counter()

    def visit(node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = f"{scope}.{node.name}" if scope else node.name
        if ((isinstance(node, ast.Attribute) and node.attr == _CREATING_GETTER)
                or (isinstance(node, ast.Name) and node.id == _CREATING_GETTER)
                or (isinstance(node, ast.Constant) and node.value == _CREATING_GETTER)):
            found[f"{label}::{scope or '<module>'}"] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(ast.parse(source), "")
    return found


class TestOnlyWritersCreateTheCache:
    """#494 drift guard. ``get_dataforge_cache_dir()`` creates the cache
    folder, so a status check that calls it fails when Windows refuses the
    folder or its drive is gone, and building the Enhancements tab is such a
    check: Smart Citizen could not open. Only the code about to write the
    cache may call it, once each; anything that only reads uses
    ``get_dataforge_cache_leaf()``. A new use anywhere in ``src/`` or
    ``scripts/`` fails here: read through the leaf instead, or add a writer
    to ``_CACHE_WRITERS`` with the reason it writes."""

    def test_only_the_writers_call_the_creating_getter(self):
        found: Counter = Counter()
        for path in _scanned_sources():
            found += _uses_of_the_creating_getter(
                path.read_text(encoding="utf-8"), path.relative_to(_REPO_ROOT).as_posix())
        assert dict(found) == _CACHE_WRITERS

    def test_every_module_that_names_the_cache_folder_is_scanned(self):
        """The modules that read or make the cache folder today. The
        generator script is the one outside src/, so a scan narrowed to
        src/ would let it make the cache folder again unseen."""
        scanned = {path.relative_to(_REPO_ROOT).as_posix() for path in _scanned_sources()}
        assert {
            "scripts/generate_enhancements_ini.py",
            "src/gui/config_tab.py",
            "src/gui/enhancements_tab.py",
            "src/gui/main_window.py",
            "src/gui/workers.py",
            "src/utils/settings.py",
        } <= scanned

    def test_every_kind_of_use_is_counted(self):
        source = (
            "class Tab:\n"
            "    def check(self):\n"
            "        AppSettings.get_dataforge_cache_dir()\n"
            "        def later():\n"
            "            return get_dataforge_cache_dir\n"
            "        getattr(AppSettings, 'get_dataforge_cache_dir')\n"
            "        '''Mentions get_dataforge_cache_dir in prose only.'''\n"
            "AppSettings.get_dataforge_cache_leaf()\n"
        )
        assert _uses_of_the_creating_getter(source, "x.py") == Counter({
            "x.py::Tab.check": 2, "x.py::Tab.check.later": 1,
        })
