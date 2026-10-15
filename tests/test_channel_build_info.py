"""Channel build-info helper and toolbar switcher widget.

Two layers:

* ``AppSettings.get_channel_build_info()``: reads ``build_manifest.id`` for a
  channel and returns ``(branch_version, build_number)``.  Pure file I/O
  against a temp directory tree — no Qt settings backend needed.
* ``MainWindow._refresh_channel_switcher`` / ``_populate_channel_switcher_menu``:
  driven on a lightweight stub ``self`` (same pattern as ``test_ui_mode.py``)
  so we don't construct the whole window.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_manifest(channel_dir: Path, *, branch: str = "sc-alpha-4.10.2",
                    version: str = "4.10.196.36804",
                    p4_changelist: str = "12881860",
                    build_date: str = "Wed Oct 07 2026") -> None:
    """Write a ``build_manifest.id`` with the given fields."""
    data: dict = {"Data": {}}
    block = data["Data"]
    if branch is not _SENTINEL:
        block["Branch"] = branch
    if version is not _SENTINEL:
        block["Version"] = version
    if p4_changelist is not _SENTINEL:
        block["RequestedP4ChangeNum"] = p4_changelist
    if build_date is not _SENTINEL:
        block["BuildDateStamp"] = build_date
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "build_manifest.id").write_text(
        json.dumps(data), encoding="utf-8"
    )


_SENTINEL = object()  # marks a field to omit entirely


# ── get_channel_build_info ───────────────────────────────────────────────────

class TestGetChannelBuildInfo:
    """``AppSettings.get_channel_build_info`` against a temp install tree."""

    @pytest.fixture(autouse=True)
    def _install_root(self, tmp_path, monkeypatch):
        self.root = tmp_path / "SC"
        self.root.mkdir()
        monkeypatch.setattr(
            AppSettings, "get_sc_install_root",
            staticmethod(lambda: str(self.root)),
        )

    # -- Happy path --

    def test_returns_branch_version_and_build_number(self):
        _write_manifest(self.root / "LIVE")
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == "4.10.2"
        assert num == "12881860"

    def test_strips_sc_beta_prefix(self):
        _write_manifest(self.root / "PTU", branch="sc-beta-4.11.0")
        ver, _ = AppSettings.get_channel_build_info("PTU")
        assert ver == "4.11.0"

    def test_strips_sc_prefix(self):
        _write_manifest(self.root / "EPTU", branch="sc-4.12.0")
        ver, _ = AppSettings.get_channel_build_info("EPTU")
        assert ver == "4.12.0"

    def test_unknown_prefix_returned_as_is(self):
        _write_manifest(self.root / "LIVE", branch="custom-1.0.0")
        ver, _ = AppSettings.get_channel_build_info("LIVE")
        assert ver == "custom-1.0.0"

    # -- Missing / malformed --

    def test_missing_manifest_returns_empty(self):
        (self.root / "LIVE").mkdir()
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""
        assert num == ""

    def test_corrupt_json_returns_empty(self):
        (self.root / "LIVE").mkdir(parents=True, exist_ok=True)
        (self.root / "LIVE" / "build_manifest.id").write_text("{bad", encoding="utf-8")
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""
        assert num == ""

    def test_missing_data_block_returns_empty(self):
        (self.root / "LIVE").mkdir(parents=True, exist_ok=True)
        (self.root / "LIVE" / "build_manifest.id").write_text(
            json.dumps({"Other": {}}), encoding="utf-8"
        )
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""
        assert num == ""

    def test_missing_branch_returns_empty_version(self):
        _write_manifest(self.root / "LIVE", branch=_SENTINEL)
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""
        assert num == "12881860"

    def test_missing_p4_changelist_returns_empty_number(self):
        _write_manifest(self.root / "LIVE", p4_changelist=_SENTINEL)
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == "4.10.2"
        assert num == ""

    def test_empty_branch_string_returns_empty_version(self):
        _write_manifest(self.root / "LIVE", branch="")
        ver, _ = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""

    def test_nonexistent_channel_returns_empty(self):
        ver, num = AppSettings.get_channel_build_info("NOPE")
        assert ver == ""
        assert num == ""

    # -- No install root --

    def test_no_install_root_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_sc_install_root",
            staticmethod(lambda: ""),
        )
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == ""
        assert num == ""

    # -- UTF-8 BOM tolerance --

    def test_utf8_bom_manifest_is_read(self):
        (self.root / "LIVE").mkdir(parents=True, exist_ok=True)
        content = json.dumps({
            "Data": {
                "Branch": "sc-alpha-4.10.2",
                "RequestedP4ChangeNum": "999",
                "Version": "1.0.0.0",
            }
        })
        (self.root / "LIVE" / "build_manifest.id").write_text(
            "﻿" + content, encoding="utf-8"
        )
        ver, num = AppSettings.get_channel_build_info("LIVE")
        assert ver == "4.10.2"
        assert num == "999"

    # -- Default channel --

    def test_defaults_to_active_channel(self, monkeypatch):
        _write_manifest(self.root / "PTU")
        monkeypatch.setattr(
            AppSettings, "get_active_channel",
            staticmethod(lambda: "PTU"),
        )
        ver, num = AppSettings.get_channel_build_info()  # no arg
        assert ver == "4.10.2"
        assert num == "12881860"


# ── Channel switcher widget (stub self) ──────────────────────────────────────

class TestChannelSwitcherWidget:
    """``MainWindow._refresh_channel_switcher`` and
    ``_on_channel_switcher_clicked`` driven on a lightweight stub."""

    @pytest.fixture(autouse=True)
    def _install_root(self, tmp_path, monkeypatch):
        self.root = tmp_path / "SC"
        self.root.mkdir()
        monkeypatch.setattr(
            AppSettings, "get_sc_install_root",
            staticmethod(lambda: str(self.root)),
        )

    @pytest.fixture
    def stub(self, qapp):
        from PyQt6.QtWidgets import QToolButton

        from src.gui.main_window import MainWindow

        class _Stub:
            _refresh_channel_switcher = MainWindow._refresh_channel_switcher

            def __init__(self):
                self._channel_switcher = QToolButton()
                self.config_tab = None  # not needed for refresh tests

        return _Stub()

    def test_refresh_sets_channel_name(self, stub, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_active_channel",
            staticmethod(lambda: "LIVE"),
        )
        _write_manifest(self.root / "LIVE")
        stub._refresh_channel_switcher()
        assert stub._channel_switcher.text() == "LIVE"

    def test_refresh_no_crash_without_labels(self, qapp):
        from src.gui.main_window import MainWindow

        class _Empty:
            pass

        # Should be a no-op, not an AttributeError.
        MainWindow._refresh_channel_switcher(_Empty())

    def test_menu_disables_unavailable_channels(self, qapp, monkeypatch):
        """The popup menu greys out channels with no Data.p4k."""
        from PyQt6.QtWidgets import QMenu, QWidget

        from src.gui.main_window import MainWindow

        _write_manifest(self.root / "LIVE")
        # Only LIVE has Data.p4k
        (self.root / "LIVE" / "Data.p4k").write_bytes(b"pk")

        monkeypatch.setattr(
            AppSettings, "get_active_channel",
            staticmethod(lambda: "LIVE"),
        )

        class _ComboStub:
            def count(self):
                return len(AppSettings.AVAILABLE_CHANNELS)
            def itemData(self, i):
                return AppSettings.AVAILABLE_CHANNELS[i]
            def model(self):
                return self
            def item(self, i):
                from PyQt6.QtGui import QStandardItem
                it = QStandardItem(AppSettings.AVAILABLE_CHANNELS[i])
                if AppSettings.AVAILABLE_CHANNELS[i] != "LIVE":
                    from PyQt6.QtCore import Qt
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                return it
            def findText(self, text):
                try:
                    return AppSettings.AVAILABLE_CHANNELS.index(text)
                except ValueError:
                    return -1
            def setCurrentIndex(self, idx):
                pass

        class _ConfigStub:
            channel_combo = _ComboStub()

        class _Stub(QWidget):
            config_tab = _ConfigStub()
            _populate_channel_switcher_menu = MainWindow._populate_channel_switcher_menu

        stub = _Stub()
        menu = QMenu(stub)
        menu.setToolTipsVisible(True)
        stub._channel_switcher_menu = menu
        stub._populate_channel_switcher_menu()

        actions = menu.actions()
        # LIVE should be enabled and checked; others should be disabled.
        live_action = next(a for a in actions if a.text() == "LIVE")
        assert live_action.isChecked()
        assert live_action.isEnabled()

        ptu_action = next(a for a in actions if a.text() == "PTU")
        assert not ptu_action.isEnabled()
