"""Smart Citizen - Main entry point."""
import ctypes
import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from src.*` imports work when
# the script is invoked directly as `python src/main.py` (Python only adds
# the script's own directory — src/ — not the project root).
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ── Force Qt to look for platform plugins in OUR bundled Qt6/plugins directory
# ── BEFORE we import anything from PyQt6. The most common source of the
# ── "No Qt platform plugin could be initialized" crash on user machines is a
# ── pre-existing environment variable (QT_PLUGIN_PATH, QT_QPA_PLATFORM_PLUGIN_PATH)
# ── from some other Qt app (IDE, another PyQt install, Anaconda, etc.) that
# ── points at an incompatible Qt version. PyInstaller's runtime hook sets
# ── these env vars but only if they're not already set — we override
# ── unconditionally so the frozen build always uses its own plugins.
if getattr(sys, "frozen", False):
    _bundled_plugins = os.path.join(sys._MEIPASS, "PyQt6", "Qt6", "plugins")
    if os.path.isdir(_bundled_plugins):
        os.environ["QT_PLUGIN_PATH"] = _bundled_plugins
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_bundled_plugins, "platforms")

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.gui.theme import apply_theme, load_application_fonts
from src.utils.version import get_version
from src.utils.settings import AppSettings
from src.utils import i18n
from src.utils.ui_scale import apply_font_size_env

# TODO: LOG_LEVEL only honors the value 'DEBUG'; any other level name
# (WARNING, ERROR, ...) is ignored and falls back to INFO. Consider mapping
# any valid level name, e.g. getattr(logging, name, logging.INFO).
# Setup logging — use --debug flag or LOG_LEVEL env var for perf timing output
_log_level = logging.DEBUG if ('--debug' in sys.argv or os.environ.get('LOG_LEVEL', '').upper() == 'DEBUG') else logging.INFO
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Application entry point."""
    logger.info(f"Starting Smart Citizen v{get_version()}")

    # Portable mode: swap the JSON backend in BEFORE any AppSettings
    # accessor runs. No-op in registry mode (the default). Must run
    # before the migrators below — they all read/write the active
    # backend, and we want the JSON file to be the target in portable
    # mode (or the migrators to skip entirely, which the early-return
    # block right after handles).
    AppSettings.setup_portable_backend_if_needed()

    # Install crash handler as early as possible — must come AFTER
    # setup_portable_backend_if_needed() (so get_logs_dir resolves to the
    # right base in portable mode) but BEFORE the registry migrators run
    # (so a migrator crash gets captured into the dump file rather than
    # vanishing into the swallowed stderr of the frozen build).
    from src.utils.crash_handler import install_crash_handler
    install_crash_handler(AppSettings.get_logs_dir())

    # Skip all registry migrators in portable mode — they migrate
    # state in HKEY_CURRENT_USER, which a portable build never reads.
    # Filesystem migrators (`migrate_docs_folder_rename`,
    # `migrate_data_to_documents`, `migrate_game_path_to_channel_layout`)
    # also skip because portable mode starts fresh under
    # `<exe-dir>/data/` — there's no legacy Documents\Smart Citizen tree
    # to drain.
    from src.utils import build_mode
    installer_data_move = None
    if not build_mode.IS_PORTABLE:
        # Move HKCU\Software\Osiris DevWorks\SC Localization Editor → Smart Citizen
        # on first launch after 0.9.2 (idempotent via marker). Must run FIRST —
        # every subsequent AppSettings call reads QSettings under the new node,
        # so if the legacy settings haven't been copied over yet the app sees
        # an empty registry and loses the user's saved paths / theme / etc.
        AppSettings.migrate_registry_appname()

        # Rename Documents\SC Localization Editor\ → Documents\Smart Citizen\ on
        # first run after the 0.9.0 rebrand (idempotent). Must run before any
        # path-resolving setting is touched.
        AppSettings.migrate_docs_folder_rename()

        # Migrate legacy settings to new data source format
        AppSettings.migrate_legacy_settings()

        # One-shot prune of the four URL-based sources (contracts/components/
        # ships/commodities) retired in 0.7.0 when the app switched to local
        # Data.p4k extraction. They've been silently 404-ing for ~10 versions
        # and produced zero-key rows in the Merge Preview. Marker-gated so it
        # runs exactly once per user.
        AppSettings.migrate_remove_retired_url_sources()

        # Migrate global source from any remote URL to local P4K cache path (v0.6.0+)
        AppSettings.migrate_global_to_p4k_local()

        # #455: a YES on Setup's OneDrive warning moves the data out of the
        # OneDrive folder. Before the channel-layout and cache migrators, so
        # they work on the moved data. The window reports the outcome.
        installer_data_move = AppSettings.migrate_installer_data_move()

        # Split the pre-0.9.3 single-channel layout into channel-aware directories
        # (registry: GAME_INSTALL_PATH → SC_INSTALL_ROOT + ACTIVE_CHANNEL;
        # filesystem: Documents\Smart Citizen\{base.ini,cache,backups,user.ini,...}
        # → Documents\Smart Citizen\LIVE\{...}). One-shot, marker-gated.
        AppSettings.migrate_game_path_to_channel_layout()

        # Move DataForge XML cache from Documents → AppData\Local (idempotent).
        # Runs after channel-layout migration so get_active_channel() is settled.
        AppSettings.migrate_dataforge_cache_to_local()

        # Move user data files from old AppData location to Documents (idempotent)
        AppSettings.migrate_data_to_documents()

        # 2.1: the #166 "route" mission-detail toggle became the Mission Titles
        # Tag Builder tab; carry a user's off-state into the new config (once).
        AppSettings.migrate_route_toggle_to_mission_titles()
    else:
        # Portable mode also seeds defaults — the migrator does both
        # ("seed defaults if no settings exist" + "migrate legacy"); we
        # need the seed half. Check the marker explicitly to skip the
        # registry-cleanup half.
        AppSettings.migrate_legacy_settings()

    # 2.1.1 (#200): flip a 2.1.0-seeded mission_titles location_detail "name"
    # to "address" (|name fails to resolve for some mission instances). Runs
    # in both build modes; portable configs carry the same seeded value.
    AppSettings.migrate_mission_titles_location_detail()

    # 2.2.0: the [BP]/[ACE] mission-title tags used to share their toggle
    # with mission-detail-body settings; split into an independent "General
    # Tags" group. Carries a user's prior blueprint_tag/ace choice forward
    # once. Runs in both build modes.
    AppSettings.migrate_title_tag_settings()

    # Always keep user source path in sync with canonical user.ini location
    AppSettings.set_source_path(AppSettings.SOURCE_USER, str(AppSettings.get_user_ini_path()))

    # Keep the global source path pointing at the active channel's cached
    # base.ini — the channel migrator moved the file into
    # {user_data}\{channel}\cache\ but the stored path in the registry
    # kept pointing at the pre-migration flat location, so the loader
    # would read a file that no longer exists. Do this every startup (not
    # just once post-migration) so channel switches also refresh the
    # path. Skip the rewrite if the current value is a URL — we don't
    # want to clobber a user who's configured a custom remote global
    # source. Points at the selected language's base.ini (#30): English
    # uses the P4K extraction, other languages a downloaded global.ini, and
    # a language not downloaded yet gets the English base so the table
    # still loads, until a language switch in the Config tab fetches it. A
    # channel switch and a data-folder change use the same rule (#502).
    AppSettings.sync_global_source_path("at startup")

    # Ensure user.ini exists (create empty if first run)
    AppSettings.ensure_user_ini_file()

    # Required on Windows so the taskbar groups the app under its own icon
    # instead of the Python interpreter icon.
    if sys.platform == 'win32':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'OsirisDevWorks.SmartCitizen'
        )

    # Load UI strings for the selected language before any window is built.
    # Widgets read tr() at construction time, so this must run before MainWindow().
    i18n.set_language(AppSettings.get_selected_language())

    # Font size is a Qt scale factor, which Qt reads only while building the
    # QApplication — so this must run first, and a change needs a restart.
    apply_font_size_env(AppSettings.get_font_size())

    app = QApplication(sys.argv)
    load_application_fonts()
    apply_theme(app, AppSettings.get_theme())
    window = MainWindow(installer_data_move=installer_data_move)
    window.show()

    logger.info("Application window shown")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()