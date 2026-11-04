"""#494: Smart Citizen opens with a DataForge cache folder it cannot make.

Building the main window builds the Enhancements tab, which read the cache
status through ``get_dataforge_cache_dir()``, and that creates the folder.
When Windows refused it (a folder whose permissions deny new folders,
Controlled folder access) or its drive was gone (the external drive the cache
folder setting is meant for, unplugged), ``MainWindow()`` raised: the crash
dialog opened and the app exited with code 1 before its window appeared, on
every launch, because the setting stays saved. The way out was outside the
app (the registry, ``config.json``, the folder's permissions). Status checks
now read the folder without creating it, so the app opens and shows the
cache as not extracted.

Each case starts the real ``src.main.main()`` in a process of its own, as a
launch does, with everything it reads or writes under tmp_path: settings in a
JsonSettings file, %APPDATA%, %LOCALAPPDATA% and the user profile folder
pointed there, and the parts of startup that would reach the real machine
replaced in the child before ``main()`` runs: the registry rename, the old
installer's registry key and the Documents lookup (any other registry use
fails the case), install detection as tests/conftest.py stubs it, and the
network. ``QApplication.exec`` returns at once, so the event loop never runs
and no startup task (the update check, the source sync) starts. The crash
dialog is modal, so the child prints that it would have opened instead.
Every case exited 1 with a crash dump before the fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.i18n import tr
from src.utils.json_settings import JsonSettings
from src.utils.settings import AppSettings
from tests.unusable_folder import missing_drive_folder, new_folders_denied

pytestmark = [
    pytest.mark.integration,
    pytest.mark.regression,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows folder permissions"),
]

REPO = Path(__file__).resolve().parent.parent
# What the child prints when the window was shown (then the cache status it
# shows), and in place of the crash dialog.
_SHOWN = "SMART CITIZEN WINDOW SHOWN: "
_CRASH = "SMART CITIZEN CRASH DIALOG: "


def _start_smart_citizen(spec_file: str) -> None:
    """Runs in the child process (see ``_launch``): replaces what would reach
    the real machine, then runs the real ``main()``."""
    import socket

    spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))

    def no_network(*args, **kwargs):
        raise OSError("no network in this test")

    socket.socket.connect = no_network
    socket.getaddrinfo = no_network

    import src.utils.settings as settings_module
    from src.utils import build_mode

    build_mode.IS_PORTABLE = spec["portable"]
    if spec["portable"]:
        portable_data = Path(spec["portable_data"])
        AppSettings._portable_data_dir = staticmethod(lambda: portable_data)
    else:
        AppSettings._backend = JsonSettings(Path(spec["config"]))
    documents = Path(spec["documents"])
    AppSettings._resolve_docs_base = staticmethod(lambda: documents)
    AppSettings.migrate_registry_appname = staticmethod(lambda: None)
    AppSettings._read_legacy_installer_sc_directory = staticmethod(lambda: None)

    class NoRegistry:
        def __getattr__(self, name):
            raise AssertionError(f"startup used the registry: winreg.{name}")

    def no_qsettings(*args, **kwargs):
        raise AssertionError("startup used the registry: QSettings")

    settings_module.winreg = NoRegistry()
    settings_module.QSettings = no_qsettings
    settings_module.read_launcher_installs = lambda log_path=None: ({}, False)
    settings_module.iter_shallow_sc_install_locations = lambda drives=None: iter(())

    import src.utils.crash_logger as crash_logger

    crash_logger.show_crash_dialog = lambda exc_type, exc_value, crash_path: print(
        f"{_CRASH}{exc_type.__name__}: {exc_value}", flush=True)

    import src.main as app_main
    from PyQt6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow

    class App(QApplication):
        def exec(self):
            for window in self.topLevelWidgets():
                if isinstance(window, MainWindow) and window.isVisible():
                    status = window.enhancements_tab._forge_status_label.text()
                    print(f"{_SHOWN}{status}", flush=True)
            return 0

    app_main.QApplication = App
    try:
        app_main.main()
    except SystemExit as stop:
        # main() ends in sys.exit(app.exec()). Leave without the interpreter
        # tearing the window and the app down, which is not under test.
        sys.stdout.flush()
        os._exit(stop.code or 0)


def _launch(tmp_path, monkeypatch, *, cache_dir=None, channel="LIVE", portable=False):
    """Save a profile under tmp_path, as the app would have saved it, then
    start Smart Citizen on it in a child process. Returns the finished
    process and the folder its crash dumps would go to."""
    home = tmp_path / "home"
    for folder in ("AppData/Roaming", "AppData/Local", "Documents"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    install = tmp_path / "StarCitizen"
    for name in ("LIVE", "PTU"):
        (install / name).mkdir(parents=True, exist_ok=True)
    portable_data = tmp_path / "portable_data"
    config = (portable_data if portable else tmp_path / "settings") / "config.json"
    monkeypatch.setattr(AppSettings, "_backend", JsonSettings(config))
    if not portable:
        AppSettings.set_user_data_dir(tmp_path / "data")
    AppSettings.set_sc_install_root(str(install))
    AppSettings.set_active_channel(channel)
    if cache_dir is not None:
        AppSettings.set_cache_dir(cache_dir)

    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "portable": portable, "portable_data": str(portable_data), "config": str(config),
        "documents": str(home / "Documents"),
    }), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", USERPROFILE=str(home),
               APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"), PYTHONIOENCODING="utf-8")
    run = subprocess.run(
        [sys.executable, "-c",
         "import sys; from tests.test_startup_refused_cache import _start_smart_citizen; "
         "_start_smart_citizen(sys.argv[1])", str(spec)],
        cwd=REPO, env=env, capture_output=True, encoding="utf-8", errors="replace",
        timeout=180,
    )
    logs = (portable_data if portable else tmp_path / "data") / "logs"
    return run, logs


def _opened_and_reads_not_extracted(run, logs) -> None:
    output = run.stdout + run.stderr
    assert _CRASH not in run.stdout, output
    assert run.returncode == 0, output
    assert f"{_SHOWN}{tr('enhancements.forge_status_not_extracted')}" in run.stdout, output
    assert list(logs.glob("crash_*.log")) == []


class TestAppOpensWithUnusableCacheFolder:
    def test_a_cache_folder_that_refuses_new_folders(self, tmp_path, monkeypatch, english_ui):
        base = tmp_path / "cache"
        base.mkdir()
        with new_folders_denied(base):
            run, logs = _launch(tmp_path, monkeypatch, cache_dir=base)
        _opened_and_reads_not_extracted(run, logs)
        assert list(base.iterdir()) == []

    def test_a_cache_folder_on_a_drive_that_is_gone(self, tmp_path, monkeypatch, english_ui):
        run, logs = _launch(tmp_path, monkeypatch, cache_dir=missing_drive_folder())
        _opened_and_reads_not_extracted(run, logs)

    def test_a_saved_channel_whose_cache_folder_cannot_be_made(
        self, tmp_path, monkeypatch, english_ui
    ):
        """LIVE's cache is there and PTU's cannot be made: a switch to PTU
        saved the channel before the switch failed, so the next launch
        opened on PTU."""
        base = tmp_path / "cache"
        (base / "LIVE" / "cache" / "dataforge").mkdir(parents=True)
        with new_folders_denied(base):
            run, logs = _launch(tmp_path, monkeypatch, cache_dir=base, channel="PTU")
        _opened_and_reads_not_extracted(run, logs)
        assert [p.name for p in base.iterdir()] == ["LIVE"]

    def test_the_portable_default_cache_folder_refusing_new_folders(
        self, tmp_path, monkeypatch, english_ui
    ):
        """The portable build's cache folder, ``data\\cache`` beside the exe,
        with no override: a copy run from a folder Windows guards."""
        base = tmp_path / "portable_data" / "cache"
        base.mkdir(parents=True)
        with new_folders_denied(base):
            run, logs = _launch(tmp_path, monkeypatch, portable=True)
        _opened_and_reads_not_extracted(run, logs)
        assert list(base.iterdir()) == []
