"""Shader cache finder and deleter behind the Config tab's Clear Shader Cache button."""
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import shader_cache  # noqa: E402
from src.utils.shader_cache import (  # noqa: E402
    _rmtree,
    clean_shader_cache,
    find_shader_cache_dirs,
    get_shader_cache_root,
    humanize_cache_name,
    is_star_citizen_running,
    remove_build_folder,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name, label", [
    ("starcitizen_(sc-alpha-4.10.2)_hg78hb_0", "Star Citizen Alpha 4.10.2 (hg78hb)"),
    ("starcitizen_(sc-alpha-4.10.0)_2cb9p_0", "Star Citizen Alpha 4.10.0 (2cb9p)"),
    ("starcitizen_(sc-patch-inc)_hy3lrc_0", "Star Citizen Tech Preview (hy3lrc)"),
    ("crashes", "crashes"),
])
def test_humanize_cache_name(name, label):
    assert humanize_cache_name(name) == label


def _make_cache(root: Path, name: str) -> Path:
    path = root / name
    for sub in ("shaders", "vulkanshadercache"):
        (path / sub).mkdir(parents=True)
        (path / sub / "a.bin").write_bytes(b"x")
    (path / "GraphicsSettings").mkdir()
    (path / "GraphicsSettings" / "GraphicsSettings.json").write_text("{}")
    return path


def test_find_lists_only_cache_folders(tmp_path):
    _make_cache(tmp_path, "starcitizen_(sc-patch-inc)_hy3lrc_0")
    _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")
    (tmp_path / "crashes").mkdir()
    (tmp_path / "starcitizen_(sc-alpha-4.10.1)_x_0.txt").write_text("not a dir")

    found = find_shader_cache_dirs(tmp_path)

    assert [d.label for d in found] == [
        "Star Citizen Alpha 4.10.2 (hg78hb)",
        "Star Citizen Tech Preview (hy3lrc)",
    ]
    assert not any(d.is_clean for d in found)


def test_build_with_no_or_empty_cache_is_clean(tmp_path):
    only_settings = tmp_path / "starcitizen_(sc-alpha-4.10.0)_aaa_0"
    (only_settings / "GraphicsSettings").mkdir(parents=True)
    empty_cache = tmp_path / "starcitizen_(sc-alpha-4.10.1)_bbb_0"
    (empty_cache / "shaders").mkdir(parents=True)
    (empty_cache / "vulkanshadercache").mkdir()
    _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_ccc_0")

    clean = {d.label: d.is_clean for d in find_shader_cache_dirs(tmp_path)}

    assert clean == {
        "Star Citizen Alpha 4.10.0 (aaa)": True,
        "Star Citizen Alpha 4.10.1 (bbb)": True,
        "Star Citizen Alpha 4.10.2 (ccc)": False,
    }


def test_find_missing_root_returns_empty(tmp_path):
    assert find_shader_cache_dirs(tmp_path / "nope") == []


def test_root_follows_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert get_shader_cache_root() == tmp_path / "Star Citizen"
    monkeypatch.delenv("LOCALAPPDATA")
    assert get_shader_cache_root() is None


def test_clean_removes_only_cache_subfolders(tmp_path):
    keep = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.0)_hg78hb_0")
    drop = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")

    assert clean_shader_cache(drop, tmp_path)
    assert not (drop / "shaders").exists()
    assert not (drop / "vulkanshadercache").exists()
    assert (drop / "GraphicsSettings" / "GraphicsSettings.json").exists()
    assert (keep / "shaders" / "a.bin").exists()
    assert find_shader_cache_dirs(tmp_path)[1].is_clean


def test_clean_tolerates_missing_subfolder(tmp_path):
    drop = tmp_path / "starcitizen_(sc-patch-inc)_hg78hb_0"
    (drop / "shaders").mkdir(parents=True)

    assert clean_shader_cache(drop, tmp_path)
    assert drop.exists()
    assert not (drop / "shaders").exists()


def test_clean_clears_read_only_files(tmp_path):
    drop = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")
    os.chmod(drop / "shaders" / "a.bin", stat.S_IREAD)

    assert clean_shader_cache(drop, tmp_path)
    assert not (drop / "shaders").exists()


def test_remove_deletes_whole_folder_only(tmp_path):
    keep = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.0)_hg78hb_0")
    drop = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")
    os.chmod(drop / "GraphicsSettings" / "GraphicsSettings.json", stat.S_IREAD)

    assert remove_build_folder(drop, tmp_path)
    assert not drop.exists()
    assert keep.exists()


def test_both_refuse_non_cache_folder(tmp_path):
    other = tmp_path / "crashes"
    (other / "shaders").mkdir(parents=True)

    assert not clean_shader_cache(other, tmp_path)
    assert not remove_build_folder(other, tmp_path)
    assert (other / "shaders").exists()


def test_both_refuse_build_folder_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = _make_cache(tmp_path / "elsewhere", "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")

    assert not clean_shader_cache(elsewhere, root)
    assert not remove_build_folder(elsewhere, root)
    assert (elsewhere / "shaders" / "a.bin").exists()


def test_default_root_refuses_temp_folder(tmp_path):
    drop = _make_cache(tmp_path, "starcitizen_(sc-alpha-4.10.2)_hg78hb_0")

    assert not remove_build_folder(drop)  # not under %LOCALAPPDATA%\Star Citizen
    assert drop.exists()


def test_clean_unlinks_stray_file_named_like_cache(tmp_path):
    drop = tmp_path / "starcitizen_(sc-alpha-4.10.2)_hg78hb_0"
    drop.mkdir()
    (drop / "shaders").write_text("stray")

    assert clean_shader_cache(drop, tmp_path)
    assert not (drop / "shaders").exists()


def _make_junction(link: Path, target: Path) -> None:
    _winapi = pytest.importorskip("_winapi")
    _winapi.CreateJunction(str(target), str(link))


def test_junction_build_folder_not_listed_or_removed(tmp_path):
    target = _make_cache(tmp_path / "other_drive", "real")
    link = tmp_path / "starcitizen_(sc-alpha-4.10.2)_hg78hb_0"
    _make_junction(link, target)

    assert find_shader_cache_dirs(tmp_path) == []
    assert not remove_build_folder(link, tmp_path)
    assert (target / "shaders" / "a.bin").exists()


def test_junction_cache_subfolder_is_left_alone(tmp_path):
    target = tmp_path / "other_drive"
    target.mkdir()
    (target / "a.bin").write_text("x")
    build = tmp_path / "starcitizen_(sc-alpha-4.10.2)_hg78hb_0"
    build.mkdir()
    _make_junction(build / "shaders", target)

    assert find_shader_cache_dirs(tmp_path)[0].is_clean
    assert clean_shader_cache(build, tmp_path)
    assert (target / "a.bin").exists()


def test_rmtree_deletes_nested_tree_with_read_only_entries(tmp_path):
    top = tmp_path / "tree"
    for d in range(3):
        sub = top / f"d{d}" / "deeper"
        sub.mkdir(parents=True)
        for i in range(50):
            (sub / f"{i}.bin").write_bytes(b"x")
    os.chmod(top / "d0" / "deeper" / "0.bin", stat.S_IREAD)

    _rmtree(top)

    assert not top.exists()


def test_rmtree_removes_inner_junction_without_following_it(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.bin").write_text("x")
    top = tmp_path / "tree"
    top.mkdir()
    _make_junction(top / "link", target)

    _rmtree(top)

    assert not top.exists()
    assert (target / "keep.bin").exists()


def test_rmtree_refuses_a_link_root(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.bin").write_text("x")
    _make_junction(tmp_path / "link", target)

    with pytest.raises(OSError):
        _rmtree(tmp_path / "link")
    assert (target / "keep.bin").exists()


def test_rmtree_deletes_the_rest_when_one_file_is_locked(tmp_path, monkeypatch):
    top = tmp_path / "tree"
    top.mkdir()
    for i in range(20):
        (top / f"{i}.bin").write_text("x")
    real_unlink = os.unlink

    def unlink(path, *a, **k):
        if os.path.basename(path) == "7.bin":
            raise PermissionError("locked")
        return real_unlink(path, *a, **k)
    monkeypatch.setattr(shader_cache.os, "unlink", unlink)
    monkeypatch.setattr(shader_cache.os, "chmod", lambda *a, **k: None)

    with pytest.raises(OSError):
        _rmtree(top)
    assert [p.name for p in top.iterdir()] == ["7.bin"]


class _Done:
    def __init__(self, stdout):
        self.stdout = stdout


@pytest.mark.parametrize("stdout, running", [
    ('"StarCitizen.exe","1234","Console","1","4,000,000 K"\n', True),
    ("INFO: No tasks are running which match the specified criteria.\n", False),
])
def test_is_star_citizen_running(monkeypatch, stdout, running):
    monkeypatch.setattr(shader_cache.subprocess, "run", lambda *a, **k: _Done(stdout))
    assert is_star_citizen_running() is running


def test_is_star_citizen_running_false_when_tasklist_fails(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("tasklist")
    monkeypatch.setattr(shader_cache.subprocess, "run", boom)
    assert is_star_citizen_running() is False
