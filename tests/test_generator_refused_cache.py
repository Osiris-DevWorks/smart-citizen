"""#494: the enhancement generator names the DataForge cache folder without
making it.

``EnhancementsGeneratorWorker`` and the generator script's own default
(``_get_default_forge_dir``, used when the script runs from the command line)
named the cache folder through ``get_dataforge_cache_dir()``, which makes it
and raises when Windows refuses it. Both now name it through
``get_dataforge_cache_leaf()``, which makes nothing. Every launcher of the
worker checks that the cache is there first, so a real run never starts
without one. These tests take the cache folder away to show the generator
only names it: a folder that denies new folders (``tests/unusable_folder.py``)
or one not made yet is handed on as it is, nothing is made and nothing is
raised. ``tests/test_cache_dir.py``'s drift guard keeps the rest of the app
off the creating getter. Settings in ``tmp_profile``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

import src.utils.dataforge_patcher as dataforge_patcher
from src.gui.workers import EnhancementsGeneratorWorker
from src.utils.settings import AppSettings
from tests.unusable_folder import new_folders_denied

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_enhancements_ini.py"
# The name EnhancementsGeneratorWorker.run loads the generator script under.
_WORKER_MODULE = "generate_enhancements_ini_worker"


@pytest.fixture
def stand_in_generator(tmp_path, monkeypatch):
    """The worker loads the generator script and runs its ``main()``, which
    needs a real cache. It loads a stand-in instead, whose ``main()`` only
    records the cache folder it is handed. The module the worker leaves in
    ``sys.modules`` is taken out again afterwards. Returns a function that
    gives the folders recorded."""
    script = tmp_path / "stand_in_generator.py"
    script.write_text(
        "FORGE_DIRS = []\n"
        "\n"
        "\n"
        "def main(base_ini, forge_dir, **kwargs):\n"
        "    FORGE_DIRS.append(forge_dir)\n",
        encoding="utf-8")
    real = importlib.util.spec_from_file_location

    def spec_from_file_location(name, location=None, *args, **kwargs):
        if name == _WORKER_MODULE:
            location = script
        return real(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec_from_file_location)
    monkeypatch.setitem(sys.modules, _WORKER_MODULE, None)
    return lambda: sys.modules[_WORKER_MODULE].FORGE_DIRS


def _run(worker) -> tuple[list, list]:
    """Run *worker* on its own thread, as the app does. Returns what it
    emitted on ``finished`` and on ``error``."""
    finished, errors = [], []
    worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
    worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    assert worker.wait(60000), "the generator worker did not finish"
    return finished, errors


@pytest.mark.parametrize("kind", ["refused", "not made yet"])
def test_the_worker_hands_on_the_cache_folder_without_making_it(
    tmp_profile, qapp, stand_in_generator, monkeypatch, caplog, kind
):
    """The patches step and the generator are each handed the cache folder,
    the run finishes, and nothing is made in the folder above it. The
    creating getter raised for the refused folder (the run failed with the
    global error box) and made the one not made yet."""
    base = tmp_profile / "cache"
    base.mkdir()
    AppSettings.set_cache_dir(base)
    leaf = AppSettings.get_dataforge_cache_leaf()
    patched = []
    real_apply_patches = dataforge_patcher.apply_patches

    def apply_patches(patch_root, forge_dir, **kwargs):
        patched.append(forge_dir)
        return real_apply_patches(patch_root, forge_dir, **kwargs)

    monkeypatch.setattr(dataforge_patcher, "apply_patches", apply_patches)
    unusable = new_folders_denied(base) if kind == "refused" else contextlib.nullcontext()

    # The settings the app reads on the main thread and hands the worker.
    worker = EnhancementsGeneratorWorker(
        categories=AppSettings.get_enabled_enhancement_categories(),
        tag_configs=AppSettings.get_all_tag_configs(),
        language=AppSettings.get_selected_language())

    with unusable, caplog.at_level(logging.WARNING):
        finished, errors = _run(worker)

    assert errors == [] and finished == [True]
    assert patched == [leaf]
    assert stand_in_generator() == [leaf]
    assert list(base.iterdir()) == []
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_the_script_names_a_refused_cache_folder_without_making_it(tmp_profile, monkeypatch):
    """Run from the command line, the script takes the cache folder the
    app's settings name. For one that denies new folders it names that
    folder and makes nothing. The creating getter raised there, and the
    script fell back to the default folder under %LOCALAPPDATA%, which is not
    the folder the settings name. The script names it once as it loads
    (``DEFAULT_FORGE_DIR``), so it is loaded here, inside the refusal."""
    base = tmp_profile / "cache"
    base.mkdir()
    AppSettings.set_cache_dir(base)
    leaf = AppSettings.get_dataforge_cache_leaf()
    name = "generate_enhancements_ini_refused_cache_test"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, script)

    with new_folders_denied(base):
        spec.loader.exec_module(script)
        assert script.DEFAULT_FORGE_DIR == leaf
        assert script._get_default_forge_dir() == leaf

    assert list(base.iterdir()) == []
