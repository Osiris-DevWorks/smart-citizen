"""What's New dialog, shown once after an install or an update.

The caller renders the notes to HTML (``MainWindow.markdown_to_html``, which
supplies palette colours), as for ``UpdateDialog``.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.utils.i18n import tr


class WhatsNewDialog(QDialog):
    def __init__(self, parent, version: str, notes_html: str):
        super().__init__(parent)
        self.setWindowTitle(tr("dialogs.whats_new_title"))
        self.setModal(True)
        self.resize(560, 480)

        layout = QVBoxLayout(self)

        headline = QLabel(tr("dialogs.whats_new_body", version=version))
        headline.setWordWrap(True)
        layout.addWidget(headline)

        notes = QTextBrowser(self)
        notes.setHtml(notes_html)
        notes.setOpenExternalLinks(True)
        layout.addWidget(notes, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(tr("dialogs.whats_new_close"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
