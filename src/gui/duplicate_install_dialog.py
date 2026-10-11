"""The Config tab's *Confirm Install Location* results dialog (2.4, #385).

Renders an ``install_scanner.ScanReport`` as a verdict plus one card per
install found. The verdict is the point of the feature: a bare list of paths
leaves the user to work out which one matters, and the whole reason this
exists is that they could not. Everything below the headline is the evidence
behind it.

Two things the user can do from here:

* **Use this install** repoints Smart Citizen at that root. The dialog only
  emits :attr:`install_selected`; the Config tab owns the ``AppSettings``
  write and the channel-combo refresh, so path-changing logic stays in the
  one place that already handles it.
* **Scan all drives** asks for the opt-in deep scan
  (:attr:`deep_scan_requested`). The Config tab re-runs the worker and calls
  :meth:`set_report` to refresh this dialog in place.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import tr
from src.utils.install_scanner import (
    ScInstall,
    ScanReport,
    VERDICT_MATCH,
    VERDICT_MATCH_LEFTOVER,
    VERDICT_MISMATCH,
    VERDICT_NONE,
    VERDICT_SINGLE,
    VERDICT_SINGLE_ELSEWHERE,
    VERDICT_SINGLE_LEFTOVER,
    VERDICT_UNCONFIGURED,
    VERDICT_UNKNOWN_ACTIVE,
    same_path,
)

logger = logging.getLogger(__name__)

# Accent colours for the verdict banner, matching the status dots already used
# on the Config tab (``_refresh_p4k_status``). Material mid-tones, legible on
# every bundled palette.
_COLOR_OK = "#4caf50"
_COLOR_WARN = "#ff9800"
_COLOR_BAD = "#f44336"

# Which accent each verdict gets. Red means proven wrong: either the user's
# edits are silently going nowhere (a real mismatch), or the install everyone
# agrees on can't run the game at all (a leftover -- #385 review: originally
# warn, moved to bad since it's exactly as "silently going nowhere" as a
# mismatch, just for a different reason). Warn is reserved for genuinely
# unproven states -- nothing configured yet, or no evidence either way.
_VERDICT_COLORS = {
    VERDICT_NONE: _COLOR_WARN,
    VERDICT_SINGLE: _COLOR_OK,
    VERDICT_SINGLE_ELSEWHERE: _COLOR_BAD,
    VERDICT_SINGLE_LEFTOVER: _COLOR_BAD,
    VERDICT_MATCH: _COLOR_OK,
    VERDICT_MATCH_LEFTOVER: _COLOR_BAD,
    VERDICT_MISMATCH: _COLOR_BAD,
    VERDICT_UNCONFIGURED: _COLOR_WARN,
    VERDICT_UNKNOWN_ACTIVE: _COLOR_WARN,
}

# Verdicts where nothing has actually been proven wrong yet -- unconfigured or
# unproven, not misconfigured. _badges() checks this so a card doesn't render
# red (#385 review: badge disagreed with the banner's own, more careful color).
_UNPROVEN_VERDICTS = (VERDICT_UNCONFIGURED, VERDICT_UNKNOWN_ACTIVE)


def format_size(num_bytes: int) -> str:
    """Human-readable byte count. Star Citizen installs are ~150 GB, so this
    only ever needs to reach TB."""
    if num_bytes <= 0:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit not in ("B", "KB") else f"{size:.0f} {unit}"
        size /= 1024
    return ""


def format_date(stamp: Optional[datetime]) -> str:
    """Short date for a build/apply timestamp, or "" when unknown."""
    return stamp.strftime("%d %b %Y") if stamp else ""


class DuplicateInstallDialog(QDialog):
    """Shows every Star Citizen install found, and what to do about them."""

    install_selected = pyqtSignal(str)   # chosen install root
    deep_scan_requested = pyqtSignal()

    def __init__(self, report: ScanReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("config.dupe_title"))
        self.setMinimumSize(680, 420)
        self._report = report

        outer = QVBoxLayout(self)

        self._verdict_label = QLabel()
        self._verdict_label.setWordWrap(True)
        self._verdict_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        outer.addWidget(self._verdict_label)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setProperty("role", "secondary")
        self._summary_label.setStyleSheet("font-size: 11px;")
        outer.addWidget(self._summary_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # Install paths are long and the cards are full of word-wrapped labels.
        # Without this the wrapped labels still report a wide sizeHint, the
        # area grows a horizontal scrollbar, and the per-card buttons get
        # pushed off the right edge instead of the text reflowing.
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer.addWidget(self._scroll, 1)

        button_row = QHBoxLayout()
        self._deep_btn = QPushButton(tr("config.dupe_deep_btn"))
        self._deep_btn.setToolTip(tr("config.dupe_deep_tooltip"))
        self._deep_btn.clicked.connect(self.deep_scan_requested.emit)
        button_row.addWidget(self._deep_btn)
        button_row.addStretch()
        close_btn = QPushButton(tr("config.dupe_close_btn"))
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        outer.addLayout(button_row)

        self.set_report(report)
        # Explicit size, or the dialog adopts the scroll area's content-driven
        # sizeHint and grows to whatever the result list needs -- a drive scan
        # turning up several installs opened a window taller than the screen.
        # The scroll area is there to absorb that; this makes it do its job.
        self.resize(720, 560)

    # -- Rendering -----------------------------------------------------------

    def set_report(self, report: ScanReport) -> None:
        """Swap in a fresh report (after a deep scan) and rebuild the body."""
        self._report = report
        self._verdict_label.setText(self._verdict_text(report))
        self._summary_label.setText(self._summary_text(report))
        # A completed deep scan can't usefully be repeated; a cancelled one can.
        self._deep_btn.setEnabled(not report.deep_scanned or report.cancelled)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        for install in report.installs:
            layout.addWidget(self._build_card(install, report))
        layout.addStretch()
        self._scroll.setWidget(container)

    def _verdict_text(self, report: ScanReport) -> str:
        """The headline. One sentence saying whether anything is wrong."""
        verdict = report.verdict
        color = _VERDICT_COLORS.get(verdict, _COLOR_WARN)
        configured = str(report.configured_root or "")
        launcher = str(report.launcher_root or "")

        if verdict == VERDICT_NONE:
            text = tr("config.dupe_verdict_none")
        elif verdict == VERDICT_SINGLE:
            # No path interpolated: the single card below already shows it.
            text = tr("config.dupe_verdict_single")
        elif verdict == VERDICT_SINGLE_ELSEWHERE:
            found = str(report.installs[0].root) if report.installs else ""
            text = tr(
                "config.dupe_verdict_single_elsewhere",
                configured=configured or tr("config.dupe_no_path_set"),
                found=found,
            )
        elif verdict == VERDICT_SINGLE_LEFTOVER:
            text = tr("config.dupe_verdict_single_leftover")
        elif verdict == VERDICT_MATCH:
            text = tr("config.dupe_verdict_match", count=report.count, path=launcher)
        elif verdict == VERDICT_MATCH_LEFTOVER:
            text = tr("config.dupe_verdict_match_leftover", path=launcher)
        elif verdict == VERDICT_MISMATCH:
            text = tr(
                "config.dupe_verdict_mismatch",
                launcher=launcher,
                configured=configured or tr("config.dupe_no_path_set"),
            )
        elif verdict == VERDICT_UNCONFIGURED:
            text = tr("config.dupe_verdict_unconfigured", launcher=launcher)
        else:
            text = tr("config.dupe_verdict_unknown", count=report.count)

        return (
            f'<div style="color:{color}; font-weight:bold; font-size:12px;">{text}</div>'
        )

    def _summary_text(self, report: ScanReport) -> str:
        """Counts, plus the explicit call-out of installs nothing is driving."""
        parts = [tr("config.dupe_summary_count", count=report.count)]

        leftovers = report.leftovers
        if leftovers:
            parts.append(tr("config.dupe_summary_leftovers", count=len(leftovers)))

        unused = [i for i in report.unused if i.has_game_data]
        if unused:
            freeable = format_size(sum(i.total_game_data_size for i in unused))
            parts.append(tr(
                "config.dupe_summary_unused",
                count=len(unused),
                paths="; ".join(str(i.root) for i in unused),
                size=freeable,
            ))

        if report.deep_scanned and report.cancelled:
            parts.append(tr("config.dupe_summary_cancelled"))
        elif not report.deep_scanned:
            parts.append(tr("config.dupe_summary_quick"))
        if not report.launcher_log_read:
            parts.append(tr("config.dupe_summary_no_launcher_log"))
        return " ".join(parts)

    def _build_card(self, install: ScInstall, report: ScanReport) -> QWidget:
        """One install: path, badges, per-channel facts, and its actions."""
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(card)

        path_label = QLabel(str(install.root))
        path_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(path_label)

        badges = self._badges(install, report)
        if badges:
            badge_label = QLabel(" ".join(badges))
            badge_label.setWordWrap(True)
            badge_label.setStyleSheet("font-size: 11px;")
            layout.addWidget(badge_label)

        for line in self._channel_lines(install):
            channel_label = QLabel(line)
            channel_label.setStyleSheet("font-size: 11px;")
            channel_label.setWordWrap(True)
            layout.addWidget(channel_label)

        applied_label = QLabel(self._applied_text(install))
        applied_label.setProperty("role", "secondary")
        applied_label.setStyleSheet("font-size: 11px;")
        applied_label.setWordWrap(True)
        layout.addWidget(applied_label)

        layout.addLayout(self._card_buttons(install, report))
        return card

    @staticmethod
    def _channel_lines(install: ScInstall) -> list[str]:
        """One line per playable channel, plus ONE line for all the empty ones.

        An install with LIVE, PTU, HOTFIX and TECH-PREVIEW folders but game
        data in only one of them used to spend four lines saying "empty"
        three times over, which is what made a multi-install result scroll
        forever. The empty channels collapse into a single comma-joined line.
        """
        lines = []
        empty = []
        for channel in install.channels:
            if channel.has_game_data:
                lines.append(tr(
                    "config.dupe_channel_line",
                    channel=channel.name,
                    version=channel.version or tr("config.dupe_unknown_version"),
                    size=format_size(channel.game_data_size),
                    date=format_date(channel.game_data_mtime),
                ))
            else:
                empty.append(channel.name)
        if empty:
            lines.append(tr(
                "config.dupe_channel_line_no_data", channel=", ".join(empty)
            ))
        return lines

    def _badges(self, install: ScInstall, report: ScanReport) -> list[str]:
        """Coloured inline tags saying what role this install plays."""
        badges = []
        if same_path(install.root, report.configured_root):
            # Green when Smart Citizen and the launcher agree; unproven
            # verdicts (nothing configured yet, or no launcher evidence)
            # stay warn rather than red -- red is reserved for a verdict
            # that actually proved a mismatch (#385 review: this used to
            # render red under VERDICT_UNKNOWN_ACTIVE, contradicting the
            # banner's own warn-not-bad color for that same verdict).
            if report.verdict in (VERDICT_SINGLE, VERDICT_MATCH):
                badge_color = _COLOR_OK
            elif report.verdict in _UNPROVEN_VERDICTS:
                badge_color = _COLOR_WARN
            else:
                badge_color = _COLOR_BAD
            badges.append(self._badge(tr("config.dupe_badge_configured"), badge_color))
        if same_path(install.root, report.launcher_root):
            badges.append(self._badge(tr("config.dupe_badge_launcher"), _COLOR_OK))
        if install.is_leftover:
            badges.append(self._badge(tr("config.dupe_badge_leftover"), _COLOR_BAD))
        elif not badges and not same_path(install.root, report.active and report.active.root):
            # Real game data, but neither the launcher/configured root nor
            # (when there's no launcher evidence) the recency-guessed active
            # install is this one -- the "other install" case this feature
            # reports. Checking report.active here, not just launcher_root,
            # keeps this in step with report.unused's own count (#385
            # review: the two disagreed about the guessed-active install
            # whenever the launcher log was unavailable).
            badges.append(self._badge(tr("config.dupe_badge_unused"), _COLOR_WARN))
        return badges

    @staticmethod
    def _badge(text: str, color: str) -> str:
        return f'<span style="color:{color};">[{text}]</span>'

    @staticmethod
    def _applied_text(install: ScInstall) -> str:
        """What (if anything) has been applied into this install."""
        languages = sorted({
            lang for channel in install.channels for lang in channel.applied_languages
        })
        if not languages:
            return tr("config.dupe_not_applied")
        stamps = install.applied_stamp_versions
        if stamps:
            return tr(
                "config.dupe_applied_by_us",
                version=", ".join(stamps),
                languages=", ".join(languages),
            )
        return tr("config.dupe_applied_other", languages=", ".join(languages))

    def _card_buttons(self, install: ScInstall, report: ScanReport) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()

        open_btn = QPushButton(tr("config.dupe_open_btn"))
        open_btn.setMaximumWidth(140)
        open_btn.clicked.connect(lambda _=False, p=install.root: self._open_folder(p))
        row.addWidget(open_btn)

        use_btn = QPushButton(tr("config.dupe_use_btn"))
        use_btn.setMaximumWidth(160)
        if install.is_leftover:
            # Checked before the "already configured" case, not after: a
            # leftover that's ALSO the configured install is exactly the
            # silent-no-op this dialog exists to catch, and it's the more
            # urgent fact -- the reassuring "already uses this install"
            # tooltip must not hide it (#385 review).
            use_btn.setEnabled(False)
            use_btn.setToolTip(tr("config.dupe_use_leftover"))
        elif same_path(install.root, report.configured_root):
            use_btn.setEnabled(False)
            use_btn.setToolTip(tr("config.dupe_use_already"))
        else:
            use_btn.setToolTip(tr("config.dupe_use_tooltip"))
            use_btn.clicked.connect(
                lambda _=False, p=str(install.root): self.install_selected.emit(p)
            )
        row.addWidget(use_btn)
        return row

    def _open_folder(self, root) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))
