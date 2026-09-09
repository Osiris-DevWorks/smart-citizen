"""Tests for the #389 mitigation: main() must not spin up a ThreadPoolExecutor
when exactly one lookup/generator job is selected.

A pool of one buys no parallelism, and issue #389 traced a native heap-
corruption fault (0xC0000374) to a background thread nested under another
background thread doing lxml-based XML parsing. The single-job branches in
both the lookup-jobs and gen-jobs sections of main() (scripts/
generate_enhancements_ini.py) now run the job inline instead of through a
pool. These tests prove that branch is real -- not just present in the
source -- by patching ThreadPoolExecutor and asserting it's never
constructed for a single-category run, while still producing correct output.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_single_job_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def forge_layout(tmp_path):
    """A base.ini plus a minimal, empty DataForge cache tree -- enough for
    main() to pass its up-front validation without any real DataForge
    records (medical_consumables reads only loc/base.ini, no XML)."""
    repo_root = Path(__file__).resolve().parent.parent
    base_ini = tmp_path / "base.ini"
    shutil.copy(repo_root / "tests" / "fixtures" / "kraken_global_latest.ini", base_ini)
    forge_dir = tmp_path / "forge"
    (forge_dir / "raw" / "libs" / "foundry" / "records").mkdir(parents=True)
    return base_ini, forge_dir


class TestSingleJobSkipsThreadPool:
    def test_single_category_never_constructs_a_pool(self, gen_module, forge_layout):
        base_ini, forge_dir = forge_layout
        with patch.object(gen_module, "ThreadPoolExecutor") as pool_cls:
            gen_module.main(
                base_ini_path=base_ini,
                forge_dir=forge_dir,
                categories={"medical_consumables"},
                max_workers=6,
            )
        pool_cls.assert_not_called()

    def test_single_category_still_writes_correct_output(self, gen_module, forge_layout):
        base_ini, forge_dir = forge_layout
        gen_module.main(
            base_ini_path=base_ini,
            forge_dir=forge_dir,
            categories={"medical_consumables"},
            max_workers=6,
        )
        out_path = base_ini.parent / "medical_consumables_enhancements.ini"
        assert out_path.exists()
        assert out_path.read_text(encoding="utf-8").strip() != ""
