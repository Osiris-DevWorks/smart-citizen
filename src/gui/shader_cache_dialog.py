"""Clean or remove Star Citizen shader cache folders, one build at a time."""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from src.utils.i18n import tr
from src.utils.shader_cache import find_shader_cache_dirs


class ShaderCacheDialog(QDialog):
    """One row per build folder, each with Clean and Remove.

    Clean deletes the ``shaders`` and ``vulkanshadercache`` subfolders; a build
    with nothing to clean is greyed out and its Clean button disabled. Remove
    hard-deletes the whole folder at once, no prompt. Each action runs in
    ``ShaderCacheWorker`` and the rows are re-scanned when it finishes.
    """

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self._root = root
        self._worker = None
        self._progress = None
        self.setWindowTitle(tr("shader_cache.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        desc = QLabel(tr("shader_cache.desc"))
        desc.setWordWrap(True)
        desc.setProperty("role", "secondary")
        layout.addWidget(desc)

        self._rows_host = QVBoxLayout()
        layout.addLayout(self._rows_host)
        self._rows = None

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close_btn.setText(tr("shader_cache.close_btn"))
        # Close, never a row button, is what Enter presses: Remove deletes
        # without asking, so a stray Enter must not land on it.
        self._close_btn.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_rows()

    def _refresh_rows(self) -> None:
        if self._rows is not None:
            self._rows.deleteLater()
        self._rows = QWidget()
        grid = QGridLayout(self._rows)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)

        cache_dirs = find_shader_cache_dirs(self._root)
        if not cache_dirs:
            grid.addWidget(QLabel(tr("shader_cache.none_found", path=str(self._root))), 0, 0)
        for row, cache_dir in enumerate(cache_dirs):
            label = QLabel(cache_dir.label)
            label.setToolTip(str(cache_dir.path))
            # A disabled label renders in the palette's grey: nothing to clean.
            label.setEnabled(not cache_dir.is_clean)

            clean_btn = QPushButton(tr("shader_cache.clean_btn"))
            clean_btn.setToolTip(tr("shader_cache.clean_tooltip"))
            clean_btn.setEnabled(not cache_dir.is_clean)
            clean_btn.clicked.connect(
                lambda _=False, p=cache_dir.path: self._run(p, remove=False)
            )

            remove_btn = QPushButton(tr("shader_cache.remove_btn"))
            remove_btn.setToolTip(tr("shader_cache.remove_tooltip"))
            remove_btn.clicked.connect(
                lambda _=False, p=cache_dir.path: self._run(p, remove=True)
            )

            for btn in (clean_btn, remove_btn):
                btn.setAutoDefault(False)

            grid.addWidget(label, row, 0)
            grid.addWidget(clean_btn, row, 1)
            grid.addWidget(remove_btn, row, 2)
        self._rows_host.addWidget(self._rows)
        # On open, and after a refresh deletes the focused row button, focus
        # goes to Close rather than the next row's Remove.
        self._close_btn.setFocus()

    def _run(self, path: Path, remove: bool) -> None:
        if self._worker is not None:
            return
        from src.gui.workers import AnimatedProgressDialog, ShaderCacheWorker

        self._progress = AnimatedProgressDialog(
            tr("shader_cache.removing" if remove else "shader_cache.cleaning"),
            self, title=tr("shader_cache.title"),
        )
        # The delete can't be stopped part way, so Esc or the X must not hide
        # the progress box and leave a dialog whose Close does nothing.
        self._progress.set_close_guard(lambda: False)
        self._progress.show()
        self._worker = ShaderCacheWorker(path, remove, self._root)
        self._worker.finished.connect(
            lambda status, p=path, r=remove: self._on_finished(status, p, r)
        )
        self._worker.start()

    def _on_finished(self, status: str, path: Path, remove: bool) -> None:
        from src.gui.workers import ShaderCacheWorker

        self._worker.quit()
        self._worker.wait()
        self._worker = None
        self._progress.close()
        self._progress = None
        self._refresh_rows()
        if status == ShaderCacheWorker.STATUS_GAME_RUNNING:
            QMessageBox.warning(
                self, tr("shader_cache.title"), tr("shader_cache.game_running_body"),
            )
        elif status == ShaderCacheWorker.STATUS_FAILED:
            QMessageBox.warning(
                self, tr("shader_cache.title"),
                tr("shader_cache.remove_failed_body" if remove
                   else "shader_cache.clean_failed_body", folder=str(path)),
            )

    def reject(self) -> None:
        # Close waits for a running delete: the thread must not outlive the dialog.
        if self._worker is not None:
            return
        super().reject()
