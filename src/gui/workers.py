"""Background worker threads and shared GUI helpers for the main window.

Extracted from main_window.py so each worker can be reasoned about in
isolation, and so the file size of main_window.py stays manageable.

Contents:
- AnimatedProgressDialog — reusable indeterminate↔determinate progress dialog
- FileLoaderWorker        — loads sources, builds StringEntry list, sort keys
- StartupSyncWorker       — refreshes URL-backed sources on startup
- EnhancementsGeneratorWorker — runs scripts/generate_enhancements_ini.py
- BlueprintLogScanWorker  — scans SC logs for received-blueprint events (#222)
- InstallScanWorker       — finds every Star Citizen install on the machine (2.4)
- P4kExtractWorker        — unp4k extraction of global.ini
- DataForgeExtractWorker  — unp4k + unforge + patch pipeline
- SelectAllDelegate       — Custom Value cell delegate (auto-select, EM3/EM4 wrap)
- OrderSpinBoxDelegate    — Sort Order cell delegate (0-99 spin box, #142)
- TestPlanSubmitWorker    — POSTs a tester's test-plan report to a Discord webhook
"""

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QProgressBar, QProgressDialog, QStyledItemDelegate

from src.parser.ini_parser import load_source_files, load_sources_from_settings
from src.utils.i18n import tr
from src.utils.resource_path import resolve_patches_dir
from src.utils.settings import AppSettings
from src.utils.dataforge_diff import dirty_categories
from src.utils.tag_builder import tag_config_fingerprint
logger = logging.getLogger(__name__)


def elide_middle(text: str, limit: int = 56) -> str:
    r"""Shorten *text* to *limit* chars, dropping the middle.

    For paths fed to a progress label. ``QProgressDialog`` resizes itself to
    fit its label and never shrinks back, so a single long path permanently
    stretches the dialog -- a drive scan across a media drive blew it out to
    most of the screen width. Eliding the middle keeps both the drive letter
    and the current folder name, which is the part that reads as progress:
    ``E:\Anime\01. Love`` stays intact, while a deep path becomes
    ``E:\Games\Some...\deep\folder``.
    """
    if len(text) <= limit:
        return text
    keep = max(0, limit - 3)
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}...{text[-tail:] if tail else ''}"


class AnimatedProgressDialog(QProgressDialog):
    """Reusable progress dialog that toggles between indeterminate and determinate.

    Starts indeterminate (range 0-0, auto-animating). Call `set_progress(completed,
    total, message)` to switch to determinate; pass total=0 to drop back to
    indeterminate for phases with an unknown extent. The phase message shows
    in the label above the bar. In determinate mode the bar displays the
    percent-complete (default Qt ``%p%`` format); indeterminate mode hides
    the bar text since there's no meaningful percentage to show.
    """

    def __init__(
        self, message: str, parent=None, title: str = "Processing",
        cancel_text: str | None = None,
    ):
        # cancel_text=None (every existing caller) makes QProgressDialog omit
        # the button entirely -- most of what this dialog drives (DataForge
        # extraction, generation) isn't safely interruptible mid-phase. Only
        # a caller that actually wires up .canceled and honours it should
        # pass real button text (#385 review: the deep install scan wired
        # the signal but never got a button to emit it from). Text is a
        # caller-supplied string, not a bool + an internal tr() lookup, so
        # this generic/reusable dialog carries no feature-specific string key.
        super().__init__(message, cancel_text, 0, 0, parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        # QProgressDialog defaults to autoClose=True/autoReset=True, which
        # hides the dialog the instant setValue() hits maximum() — e.g. the
        # DataForge cache-snapshot phase ends with completed == total, so
        # the dialog vanished right there while later phases (patching,
        # enhancement generation) kept running and updating the status bar.
        # Callers own the dialog lifecycle explicitly via .close(), so
        # reaching 100% on one phase must not close it out from under them.
        self.setAutoClose(False)
        self.setAutoReset(False)
        self._bar = self.findChild(QProgressBar)
        if self._bar is not None:
            # Start indeterminate — bar text hidden until set_progress flips
            # to determinate and a real percentage exists to display.
            self._bar.setTextVisible(False)
        self.show()

    def set_progress(self, completed: int, total: int, message: str = "") -> None:
        """Drive the bar from a ProgressSink. total=0 ⇒ indeterminate.

        Determinate mode applies a two-tone gradient QSS and shows ``%p%``
        inside the bar. Indeterminate mode clears the QSS so Fusion's
        animated busy indicator still works, and hides the bar text.
        Phase messages go to the label above the bar in both modes.
        """
        if total <= 0:
            if self.maximum() != 0 or self.minimum() != 0:
                self.setRange(0, 0)
            if self._bar is not None:
                self._bar.setTextVisible(False)
                self._bar.setStyleSheet("")
        else:
            if self.maximum() != total:
                self.setRange(0, total)
            self.setValue(min(completed, total))
            if self._bar is not None:
                # Reset format to the Qt default so %p% resolves even if
                # something upstream had set a custom format string.
                self._bar.setFormat("%p%")
                self._bar.setTextVisible(True)
                from src.gui.theme import get_progress_chunk_color, get_progress_groove_color
                chunk = QColor(get_progress_chunk_color())
                light = chunk.lighter(135).name()
                dark  = chunk.darker(125).name()
                mid   = chunk.name()
                self._bar.setStyleSheet(
                    "QProgressBar {"
                    f" background-color: {get_progress_groove_color()};"
                    " border: 1px solid rgba(0,0,0,0.25);"
                    " border-radius: 3px;"
                    " text-align: center;"
                    "}"
                    "QProgressBar::chunk {"
                    " background: qlineargradient("
                    "  x1:0, y1:0, x2:0, y2:1,"
                    f"  stop:0 {light},"
                    f"  stop:0.5 {mid},"
                    f"  stop:1 {dark}"
                    " );"
                    " border-radius: 2px;"
                    "}"
                )
        if message:
            self.setLabelText(message)


class FileLoaderWorker(QThread):
    """Worker thread for loading INI files without blocking UI.

    Loads configured sources from settings and emits the merged entries plus
    pre-computed sort keys so the main thread doesn't need to re-parse base.ini.
    """

    # (entries, default_values dict, pre-computed group sort keys)
    finished = pyqtSignal(list, dict, list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)

    # 3 phase boundaries: sources read → entries built → sort keys computed.
    _PHASE_TOTAL = 3

    def run(self):
        from src.gui.string_table_model import _group_sort_key
        try:
            logger.info("FileLoaderWorker starting...")
            self.progress_pct.emit(0, self._PHASE_TOTAL, tr("progress.reading_sources"))
            self.progress.emit(tr("progress.reading_sources"))

            sources_dict, hierarchy, enhancements_key_categories = load_sources_from_settings()
            logger.info(f"Loaded from settings: sources={list(sources_dict.keys())}, hierarchy={hierarchy}")

            if not (sources_dict and hierarchy):
                raise ValueError("No sources configured")

            self.progress_pct.emit(1, self._PHASE_TOTAL, tr("progress.creating_entries"))
            self.progress.emit(tr("progress.creating_entries"))
            entries = load_source_files(sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories)
            logger.info(f"load_source_files returned {len(entries)} entries")

            default_values = dict(sources_dict.get("global", {}))

            self.progress_pct.emit(2, self._PHASE_TOTAL, tr("progress.computing_sort_keys"))
            self.progress.emit(tr("progress.computing_sort_keys"))
            sort_keys = [_group_sort_key(e.key) for e in entries]

            self.progress_pct.emit(3, self._PHASE_TOTAL, tr("progress.ready"))
            logger.info("FileLoaderWorker finished successfully")
            self.finished.emit(entries, default_values, sort_keys)
        except Exception as e:
            logger.exception(f"Error loading files: {e}")
            self.error.emit(str(e))


class StartupSyncWorker(QThread):
    """Worker thread that syncs all enabled remote sources on startup.

    Uses conditional GET (If-Modified-Since) so only changed files are downloaded.
    Emits source_starting before each download, source_synced after, source_error on
    failure. Always emits finished so loading proceeds even when sources fail.
    """

    source_starting = pyqtSignal(str)        # source_name (about to sync)
    source_synced = pyqtSignal(str, bool)    # (source_name, was_updated)
    source_error = pyqtSignal(str, str)      # (source_name, error_message)
    finished = pyqtSignal()

    def run(self):
        from src.utils.updater import download_file_if_changed

        cache_dir = AppSettings.get_cache_dir()
        cache_mapping = {
            AppSettings.SOURCE_GLOBAL:      "base.ini",
        }

        for source_name in [
            AppSettings.SOURCE_GLOBAL,
        ]:
            if not AppSettings.is_source_enabled(source_name):
                continue
            if not AppSettings.get_source_auto_update(source_name):
                continue

            source_url = AppSettings.get_source_path(source_name)
            if not source_url or not source_url.startswith("http"):
                continue

            self.source_starting.emit(source_name)
            cache_file = cache_dir / cache_mapping.get(source_name, f"{source_name}.ini")
            try:
                updated = download_file_if_changed(source_url, cache_file)
                self.source_synced.emit(source_name, updated)
            except Exception as e:
                logger.warning(f"Startup sync failed for {source_name}: {e}")
                self.source_error.emit(source_name, str(e))

        self.finished.emit()


class LanguageBaseDownloadWorker(QThread):
    """Download a language's global.ini to its per-language base.ini path.

    Uses ``download_file_if_changed`` so an unchanged remote (matched via
    ETag / Last-Modified) is a fast no-op: switching back to a language whose
    base.ini we already cached doesn't re-download the ~10 MB file.
    """

    finished = pyqtSignal(bool)  # True = a base.ini is present and usable
    error = pyqtSignal(str)

    def __init__(self, url: str, dest_path):
        super().__init__()
        self._url = url
        self._dest = dest_path

    def run(self):
        from src.utils.updater import download_file_if_changed
        try:
            changed = download_file_if_changed(self._url, self._dest)
            logger.info(
                f"Language base.ini ready: {self._dest} "
                f"({'downloaded' if changed else 'unchanged, used cache'})"
            )
            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"Language base.ini download failed: {e}")
            self.error.emit(str(e))
            # finished(False): a download failure isn't fatal — the caller
            # falls back to any cached copy, or to English.
            self.finished.emit(False)


class BlueprintLogScanWorker(QThread):
    """Scan a channel's SC logs for received-blueprint events (#222).

    Thin wrapper over ``blueprint_log_scanner.scan_channel``: it does the I/O
    (reading up to hundreds of log files, some tens of MB) off the main thread
    and reports per-file progress. It intentionally does *not* touch the owned
    set or the watermark — the main-thread slot normalizes the returned raw
    names, unions them into the owned set, and advances the watermark, so all
    settings mutation stays on one thread.
    """

    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(object)             # ScanResult, or None on error
    error = pyqtSignal(str)

    def __init__(self, channel_dir, since):
        super().__init__()
        self._channel_dir = channel_dir
        self._since = since  # datetime watermark, or None to use the epoch floor

    def run(self):
        from src.utils.blueprint_log_scanner import scan_channel
        try:
            def _cb(done, total, name):
                msg = (tr("enhancements.bp_scan_progress", file=name)
                       if name else tr("enhancements.bp_scan_finishing"))
                self.progress.emit(msg)
                self.progress_pct.emit(done, total, msg)

            result = scan_channel(self._channel_dir, since=self._since, progress=_cb)
            logger.info(
                "BP Scan: %d new names across %d files (latest=%s)",
                len(result.names), result.files_scanned, result.latest_timestamp,
            )
            self.finished.emit(result)
        except Exception as e:
            logger.exception(f"Blueprint log scan failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(None)


class InstallScanWorker(QThread):
    """Find every Star Citizen install on this machine (2.4).

    Thin wrapper over ``install_scanner.scan_installs``. Both scan modes run
    here, not just the deep one: even the quick scan reads each install's
    applied ``global.ini`` looking for the apply watermark, and on a cold file
    cache that measured 26 s against a real 11 MB file — long enough to freeze
    the window if it ran on the main thread.

    Unlike the tag-config hand-off ``src/utils/CLAUDE.md`` documents (settings
    read on the main thread, frozen before the worker starts, specifically so
    a mid-run edit elsewhere can't half-rewrite the input), the settings this
    worker needs have no such "must be frozen at launch" concern -- nothing
    else can change them mid-scan -- and root ``CLAUDE.md``'s own threading
    section states ``AppSettings`` is thread-safe from either thread. So they
    are read in :meth:`run`, on the worker thread, not ``__init__``: an
    unconfigured profile makes ``get_sc_install_root()`` fall through to
    ``_scan_common_sc_install_locations()``, whose own docstring warns a
    disconnected network drive can hang that call for seconds -- exactly the
    kind of I/O this class exists to keep off the main thread (#385 review).
    """

    progress_pct = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)  # ScanReport, or None on error
    error = pyqtSignal(str)

    def __init__(self, deep: bool = False, parent=None):
        super().__init__(parent)
        self._deep = deep
        self._cancelled = False

    def cancel(self) -> None:
        """Ask a deep scan to stop at the next directory boundary."""
        self._cancelled = True

    def run(self):
        from src.utils.install_scanner import scan_installs
        from src.utils.settings import _path_ends_in_channel

        configured_root = AppSettings.get_sc_install_root()
        registry_root = AppSettings._read_legacy_installer_sc_directory()
        if registry_root and _path_ends_in_channel(registry_root):
            # Reuses settings.py's own stripping helper rather than a second
            # implementation (#385 review: an earlier version of this fix
            # introduced install_scanner.is_channel_name for the same check
            # AppSettings already had). The legacy installer can write a
            # channel-suffixed path (e.g. ...\StarCitizen\LIVE) into this
            # key. Passed through unstripped, read_install() would look for
            # a nested LIVE\LIVE and silently drop this registry evidence
            # for anyone on that older flow.
            registry_root = str(Path(registry_root).parent)

        try:
            def _progress(visited: int, current: str) -> None:
                # total=0: there is no knowable upper bound for either scan
                # mode (a directory walk doesn't know its own size in
                # advance), so this legitimately stays indeterminate rather
                # than faking a percentage. Routing through progress_pct (the
                # signal src/gui/CLAUDE.md documents every worker emitting)
                # rather than a bespoke str signal is still the point: it
                # keeps this worker on the one path AnimatedProgressDialog's
                # callers already use (#385 review).
                self.progress_pct.emit(0, 0, tr(
                    "config.dupe_scan_progress",
                    count=visited,
                    path=elide_middle(current),
                ))

            report = scan_installs(
                configured_root=configured_root or None,
                registry_root=registry_root,
                deep=self._deep,
                progress=_progress if self._deep else None,
                should_cancel=(lambda: self._cancelled) if self._deep else None,
            )
            logger.info(
                "Install scan: %d install(s), verdict=%s, launcher=%s, deep=%s",
                report.count, report.verdict, report.launcher_root, self._deep,
            )
            self.finished.emit(report)
        except Exception as e:
            logger.exception(f"Install scan failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(None)


class EnhancementsGeneratorWorker(QThread):
    """Worker thread for generating enhancements INI files via generate_enhancements_ini.py."""

    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, categories: set[str] | None = None,
                 tag_configs: dict | None = None,
                 annotate_mission_descs: bool = True,
                 rep_xp_label: str = AppSettings.DEFAULT_REP_XP_LABEL,
                 mission_headers: dict[str, str] | None = None,
                 mission_header_em_tag: str = AppSettings.DEFAULT_MISSION_HEADER_EM_TAG,
                 mission_detail_fields: dict | None = None,
                 mission_title_tags: dict | None = None,
                 stats_prepend: bool = False,
                 standardize_earnable_ship_names: bool = False,
                 rs_ore_name_annotations: bool = True,
                 language: str | None = None):
        super().__init__()
        self.categories = categories
        self.tag_configs = tag_configs
        self.annotate_mission_descs = annotate_mission_descs
        self.rep_xp_label = rep_xp_label
        self.mission_headers = mission_headers
        self.mission_header_em_tag = mission_header_em_tag
        self.mission_detail_fields = mission_detail_fields
        self.mission_title_tags = mission_title_tags
        self.stats_prepend = stats_prepend
        self.standardize_earnable_ship_names = standardize_earnable_ship_names
        self.rs_ore_name_annotations = rs_ore_name_annotations
        # Which language's base.ini to generate against. None resolves to the
        # selected language at run time. English uses the P4K base.ini in the
        # channel cache root; other languages use the downloaded per-language
        # base.ini, so output lands beside it in the language dir (#30).
        self.language = language

    def run(self):
        import importlib.util
        import sys as sys_module
        from src.utils.dataforge_patcher import apply_patches
        try:
            if getattr(sys, 'frozen', False):
                script_path = Path(sys._MEIPASS) / 'scripts' / 'generate_enhancements_ini.py'
            else:
                script_path = Path(__file__).parent.parent.parent / 'scripts' / 'generate_enhancements_ini.py'

            if not script_path.exists():
                raise FileNotFoundError(f"Enhancements generator script not found: {script_path}")

            base_ini  = AppSettings.get_base_ini_path(self.language)
            enh_dir   = AppSettings.get_enhancements_dir(self.language)
            forge_dir = AppSettings.get_dataforge_cache_dir()
            # ── Diff-cache check ──────────────────────────────────────────────
            # Compare the current DataForge XMLs against the last-run manifest.
            # None  → no manifest yet, run everything.
            # set() → nothing changed, skip entirely.
            # {...} → only re-run the categories whose source XMLs changed.
            libs_dir = forge_dir / "raw" / "libs"
            diff = dirty_categories(libs_dir)
            # If enhancement files are missing, force regeneration even if the
            # manifest says nothing changed — the manifest may have been written
            # before enhancements were ever successfully generated.
            if diff is not None and not diff:
                missing = [
                    name for name in AppSettings.ENHANCEMENTS_FILES.values()
                    if not (enh_dir / name).exists()
                ]
                if missing:
                    logger.info(
                        f"Diff-cache: manifest clean but {len(missing)} enhancement "
                        f"file(s) missing ({', '.join(missing[:3])}{'…' if len(missing) > 3 else ''}), forcing regeneration."
                    )
                    diff = None  # None = treat as first run, regenerate everything
            # ─────────────────────────────────────────────────────────────────
            # Re-apply DataForge patches before generation. apply_patches is
            # idempotent: already-patched files are a cheap no-op, so running
            # this every regen picks up newly-added patches without forcing
            # the user through a full re-extract. Bar stays indeterminate
            # here — ``mod.main()`` below takes over with determinate ticks
            # once its ProgressSink is wired up.
            self.progress_pct.emit(0, 0, tr("progress.applying_patches"))
            self.progress.emit(tr("progress.applying_patches"))
            patch_report = apply_patches(
                resolve_patches_dir(), forge_dir,
                progress_callback=self.progress.emit,
            )
            logger.info(f"DataForge patches: {patch_report.summary_line()}")
            if patch_report.errors:
                for err in patch_report.errors:
                    logger.warning(f"  patch error: {err}")

            self.progress.emit(tr("progress.loading_generator"))

            module_name = "generate_enhancements_ini_worker"
            if module_name in sys_module.modules:
                del sys_module.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, script_path)
            mod = importlib.util.module_from_spec(spec)
            sys_module.modules[module_name] = mod
            spec.loader.exec_module(mod)

            self.progress.emit(tr("progress.generating_enhancements"))
            logger.info("Enhancements generation worker: calling mod.main()")

            cat_desc = ", ".join(sorted(self.categories)) if self.categories else "all"
            logger.info(f"Enhancements generation: base_ini={base_ini}, forge_dir={forge_dir}, categories={cat_desc}")

            # Bridge the script's ProgressSink callback into a Qt-safe signal.
            # PyQt signal emits are thread-safe across QThread boundaries, so
            # this is safe to call from lookup-pool workers.
            def _on_progress(completed: int, total: int, message: str) -> None:
                self.progress_pct.emit(completed, total, message)

            mod.main(base_ini, forge_dir, categories=self.categories,
                     progress_callback=_on_progress,
                     patches_dir=resolve_patches_dir(),
                     max_workers=1,
                     tag_configs=self.tag_configs,
                     annotate_mission_descs=self.annotate_mission_descs,
                     rep_xp_label=self.rep_xp_label,
                     mission_headers=self.mission_headers,
                     mission_header_em_tag=self.mission_header_em_tag,
                     mission_detail_fields=self.mission_detail_fields,
                     mission_title_tags=self.mission_title_tags,
                     stats_prepend=self.stats_prepend,
                     standardize_earnable_ship_names=self.standardize_earnable_ship_names,
                     rs_ore_name_annotations=self.rs_ore_name_annotations,
                     english_base_ini_path=AppSettings.get_base_ini_path(
                         AppSettings.DEFAULT_LANGUAGE))
            logger.info("Enhancements generation worker: mod.main() completed successfully")

            # Record which DataForge build these (per-language) enhancements
            # were generated against, so a later language switch can tell fresh
            # from stale and skip a redundant regen (#30, Approach 1).
            AppSettings.set_enhancements_stamp(
                AppSettings.get_dataforge_build_key(), self.language
            )
            # And which Tag Builder config they were generated against, so a
            # later channel switch can tell whether the Save Tag Changes button
            # actually needs to light up instead of always lighting it. Uses
            # the configs captured for THIS run (self.*), not live settings, so
            # the stamp reflects exactly what was generated. Belongs beside the
            # DataForge stamp: both mark "what these INIs were built from".
            AppSettings.set_tag_config_stamp(
                tag_config_fingerprint(
                    self.tag_configs, self.annotate_mission_descs
                ),
                self.language,
            )

            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"Enhancements generation failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class P4kExtractWorker(QThread):
    """Worker thread for extracting global.ini from Data.p4k via unp4k.exe."""

    progress = pyqtSignal(str)   # status message
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)  # True = success
    error = pyqtSignal(str)      # error message (emitted before finished(False))

    def __init__(self, p4k_path, output_path, unp4k_exe):
        super().__init__()
        self._p4k = p4k_path
        self._out = output_path
        self._exe = unp4k_exe

    def run(self):
        from src.utils.pak_extractor import P4kLockedError, extract_global_ini
        try:
            extract_global_ini(
                self._p4k, self._out, self._exe,
                progress_callback=self.progress.emit,
                progress_pct_callback=lambda c, t, m: self.progress_pct.emit(c, t, m),
            )
            self.finished.emit(True)
        except P4kLockedError as e:
            # Anticipated, already logged at WARNING by _raise_unp4k_failure
            # with full diagnostic detail — logger.exception() here would
            # independently trigger MainWindow's global ErrorDialogHandler
            # (any ERROR-level record, app-wide) and duplicate the friendly
            # dialog the `error` signal below shows.
            logger.warning(f"P4K extraction: Data.p4k locked, likely updating: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)
        except Exception as e:
            logger.exception(f"P4K extraction failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class DataForgeExtractWorker(QThread):
    """Worker thread for extracting DataForge entity XMLs from Data.p4k."""

    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, p4k_path, unp4k_exe, unforge_exe, cache_dir):
        super().__init__()
        self._p4k       = p4k_path
        self._unp4k_exe = unp4k_exe
        self._unforge_exe = unforge_exe
        self._cache_dir = cache_dir

    def run(self):
        from src.utils.pak_extractor import (
            DataForgeTimeoutError, P4kLockedError, extract_dataforge,
        )
        from src.utils.dataforge_patcher import apply_patches
        try:
            extract_dataforge(
                self._p4k,
                self._unp4k_exe,
                self._unforge_exe,
                self._cache_dir,
                progress_callback=self.progress.emit,
                progress_pct_callback=lambda c, t, m: self.progress_pct.emit(c, t, m),
            )
            # Apply declarative patches over known CIG data bugs so downstream
            # consumers (enhancement generator, future tooling) see corrected
            # data. Patch failures are recorded in the report but don't block
            # the pipeline.
            #
            # Flip the progress bar back to indeterminate (range 0-0, auto-
            # animating) so the user can see we're still working — after
            # extract_dataforge completes, the bar sits at its final 3/3
            # "Done" determinate state, which would look like the dialog is
            # about to close. The patches phase has no useful per-file
            # progress, so indeterminate is the honest signal.
            self.progress_pct.emit(0, 0, tr("progress.applying_patches"))
            self.progress.emit(tr("progress.applying_patches"))
            patch_root = resolve_patches_dir()
            report = apply_patches(patch_root, self._cache_dir,
                                   progress_callback=self.progress.emit)
            logger.info(f"DataForge patches: {report.summary_line()}")
            if report.errors:
                for err in report.errors:
                    logger.warning(f"  patch error: {err}")
            self.finished.emit(True)
        except P4kLockedError as e:
            # See the matching comment in P4kExtractWorker.run(): already
            # logged at WARNING by _raise_unp4k_failure; logger.exception()
            # here would independently trigger the global ErrorDialogHandler
            # and duplicate the friendly dialog the `error` signal shows.
            logger.warning(f"DataForge extraction: Data.p4k locked, likely updating: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)
        except DataForgeTimeoutError as e:
            # Same treatment as P4kLockedError above: _raise_unforge_timeout
            # has already logged the DCB name, its size and unforge's partial
            # output at WARNING, and the message is user-ready. Letting this
            # fall through to the blanket handler would log at ERROR and pop
            # the global ErrorDialogHandler on top of the friendly dialog.
            logger.warning(f"DataForge extraction: unforge timed out: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)
        except Exception as e:
            logger.exception(f"DataForge extraction failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class SelectAllDelegate(QStyledItemDelegate):
    """Custom delegate for the Custom Value column.

    - Selects all text when the editor opens so typing overwrites but Esc keeps it.
    - Extends the editor's right-click menu with <EM3>/<EM4> wrap actions so
      authors can apply Star Citizen emphasis tags around the selected text.
    - Supports ``cursor_at_start`` mode: when set, the editor opens with the
      cursor at position 0 instead of selecting all (used by the double-click-
      on-Current-Value shortcut).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cursor_at_start = False

    def set_cursor_at_start(self, flag: bool) -> None:
        """Next editor will open with the cursor at position 0."""
        self._cursor_at_start = flag

    def createEditor(self, parent, option, index):
        from PyQt6.QtWidgets import QLineEdit
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            editor.customContextMenuRequested.connect(
                lambda pos, ed=editor: SelectAllDelegate._show_editor_menu(ed, pos)
            )
        if self._cursor_at_start:
            self._cursor_at_start = False
            if hasattr(editor, 'setCursorPosition'):
                editor.setCursorPosition(0)
        elif hasattr(editor, 'selectAll'):
            editor.selectAll()
        return editor

    @staticmethod
    def _show_editor_menu(editor, pos):
        menu = editor.createStandardContextMenu()
        menu.addSeparator()
        has_sel = editor.hasSelectedText()
        em3 = menu.addAction(tr("strings_tab.context_underline"))
        em3.setEnabled(has_sel)
        em3.triggered.connect(lambda: SelectAllDelegate._wrap_selection(editor, "EM3"))
        em4 = menu.addAction(tr("strings_tab.context_highlight"))
        em4.setEnabled(has_sel)
        em4.triggered.connect(lambda: SelectAllDelegate._wrap_selection(editor, "EM4"))
        menu.exec(editor.mapToGlobal(pos))

    @staticmethod
    def _wrap_selection(editor, tag: str):
        sel = editor.selectedText()
        if not sel:
            return
        # QLineEdit.insert replaces the current selection. Place the caret
        # just inside the closing tag so successive edits stay near the text.
        wrapped = f"<{tag}>{sel}</{tag}>"
        start = editor.selectionStart()
        editor.insert(wrapped)
        editor.setCursorPosition(start + len(f"<{tag}>") + len(sel))


class OrderSpinBoxDelegate(QStyledItemDelegate):
    """Editor for the Sort Order column (issue #142).

    A 0-99 spin box where 0 means "no order" (shown blank). The model stores
    the order as a zero-padded two-digit string on the ship's custom_value;
    this delegate translates between that string and the spin box's int.
    """

    def createEditor(self, parent, option, index):
        from PyQt6.QtWidgets import QSpinBox
        editor = QSpinBox(parent)
        editor.setRange(0, 99)
        # 0 reads as "clear the order" — show it blank, not as "0".
        editor.setSpecialValueText("")
        return editor

    def setEditorData(self, editor, index):
        text = index.data(Qt.ItemDataRole.EditRole) or ""
        editor.setValue(int(text) if str(text).isdigit() else 0)

    def setModelData(self, editor, model, index):
        editor.interpretText()
        value = editor.value()
        # 0 clears the order; set_order() treats "" as "no order".
        model.setData(index, "" if value == 0 else str(value), Qt.ItemDataRole.EditRole)


class TestPlanSubmitWorker(QThread):
    """Post a tester's test-plan report to a Discord webhook (#144).

    Network I/O off the main thread, per the project threading model. The
    report is pre-split into Discord-sized chunks; each posts as its own
    message in order. Emits finished(ok, message).
    """

    finished = pyqtSignal(bool, str)

    def __init__(self, webhook_url: str, chunks: list, parent=None):
        super().__init__(parent)
        self._webhook_url = webhook_url
        self._chunks = chunks

    def _redact(self, text: str) -> str:
        """Strip the webhook URL (a bearer secret) out of any message so it
        never lands in the Log tab, an exported log bundle, or an error toast."""
        if self._webhook_url:
            return text.replace(self._webhook_url, "<webhook>")
        return text

    def run(self):
        import json as _json
        import urllib.request

        # Only speak HTTPS to a webhook — reject file:// / ftp:// and other
        # schemes rather than hand a user-supplied string straight to urlopen.
        if not str(self._webhook_url).lower().startswith("https://"):
            self.finished.emit(False, "Webhook URL must start with https://")
            return

        try:
            for chunk in self._chunks:
                data = _json.dumps({"content": chunk}).encode("utf-8")
                req = urllib.request.Request(
                    self._webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status >= 300:
                        self.finished.emit(False, f"Discord returned HTTP {resp.status}")
                        return
            self.finished.emit(True, "Report sent to Discord.")
        except Exception as e:
            # Static message + no traceback dump: the webhook URL can appear in
            # a urllib exception's text, so scrub it before it reaches the log.
            logger.error("Test plan report submission failed: %s", self._redact(str(e)))
            self.finished.emit(False, f"Could not send report: {self._redact(str(e))}")
