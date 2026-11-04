"""Tests for src.utils.resource_path — get_resource_path / resolve_patches_dir."""

import os.path as _osp
import sys
from pathlib import Path

import pytest

from src.utils.resource_path import get_resource_path, resolve_patches_dir

pytestmark = pytest.mark.unit


class TestGetResourcePath:
    def test_unfrozen_returns_path_under_project_root(self):
        """Outside a PyInstaller bundle, the path is rooted at the project dir."""
        result = get_resource_path("patches")
        assert Path(result).name == "patches"
        assert Path(result).is_absolute()

    def test_unfrozen_no_meipass_set(self):
        """Sanity check: tests should not run inside a frozen build."""
        assert not hasattr(sys, "_MEIPASS"), (
            "_MEIPASS should not be set in the test process (would mean tests "
            "are running inside a frozen build)"
        )

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        """When _MEIPASS is set, get_resource_path uses it as the base."""
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = get_resource_path("patches")
        assert result == str(tmp_path / "patches")

    def test_nested_relative_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = get_resource_path("assets/fonts")
        # os.path.join preserves the slash style from the relative arg —
        # normalise both sides before comparing.
        assert _osp.normpath(result) == _osp.normpath(str(tmp_path / "assets" / "fonts"))

    def test_meipass_cleanup_doesnt_leak_between_tests(self, monkeypatch, tmp_path):
        """Confirm monkeypatch's setattr(_, raising=False) reverts cleanly."""
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert hasattr(sys, "_MEIPASS")
        monkeypatch.undo()
        assert not hasattr(sys, "_MEIPASS")


class TestResolvePatchesDir:
    def test_returns_path_instance(self):
        result = resolve_patches_dir()
        assert isinstance(result, Path)

    def test_name_is_patches(self):
        assert resolve_patches_dir().name == "patches"

    def test_is_absolute(self):
        assert resolve_patches_dir().is_absolute()

    def test_uses_meipass_when_frozen(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = resolve_patches_dir()
        assert result == tmp_path / "patches"
