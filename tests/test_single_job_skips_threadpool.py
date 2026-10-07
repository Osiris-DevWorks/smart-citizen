"""Tests for the #389 mitigation: main() must not spin up a ThreadPoolExecutor
whenever the pool would have exactly one worker, i.e.
min(max_workers, len(jobs)) == 1.

A pool of one buys no parallelism, and issue #389 traced a native heap-
corruption fault (0xC0000374) to a background thread nested under another
background thread doing lxml-based XML parsing. Both the lookup-jobs and
gen-jobs sections of main() (scripts/generate_enhancements_ini.py) run their
jobs inline in that case. EnhancementsGeneratorWorker always passes
max_workers=1, so the real GUI path is several jobs at one worker, not one job.
These tests patch ThreadPoolExecutor to prove no pool is built, and check the
inline paths still run every job and write their output.
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


def _assert_no_pool(pool_cls):
    # Not assert_not_called(): its failure message repeats every call's arguments,
    # and main()'s ctx holds the whole parsed base.ini (about 20 MB of output).
    assert pool_cls.call_count == 0


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
        _assert_no_pool(pool_cls)

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

    def test_max_workers_one_never_constructs_a_pool_even_with_several_jobs(
        self, gen_module, forge_layout
    ):
        """#389 follow-up (Osiris review on #395): the real GUI path always
        calls main(..., max_workers=1) via EnhancementsGeneratorWorker
        (src/gui/workers.py), however many categories are selected, so a
        multi-category run must not build ThreadPoolExecutor(max_workers=1)
        either.

        categories={"medical_consumables", "ship_descs"} gives two gen_jobs
        (medical_consumables, ships) and two lookup_jobs (controller, armor,
        both populated by the ship_descs branch). The ships generator and the
        two lookup builders are stubbed with empty results, so this needs no
        real ship XML and can see that each one ran.
        """
        base_ini, forge_dir = forge_layout
        with patch.object(gen_module, "_run_gen_ships", return_value={}) as ships, \
             patch.object(gen_module, "build_controller_lookup",
                          return_value={}) as controller, \
             patch.object(gen_module, "build_armor_lookup",
                          return_value={}) as armor, \
             patch.object(gen_module, "ThreadPoolExecutor") as pool_cls:
            gen_module.main(
                base_ini_path=base_ini,
                forge_dir=forge_dir,
                categories={"medical_consumables", "ship_descs"},
                max_workers=1,
            )
        _assert_no_pool(pool_cls)
        # The inline paths still ran every lookup and generator and wrote their output.
        controller.assert_called_once()
        armor.assert_called_once()
        ships.assert_called_once()
        out_path = base_ini.parent / "medical_consumables_enhancements.ini"
        assert out_path.read_text(encoding="utf-8").strip() != ""

    def test_one_lookup_with_several_workers_never_constructs_a_pool(
        self, gen_module, forge_layout
    ):
        """The other half of min(max_workers, len(jobs)) == 1 at the lookup
        pool: one job, several workers. commodity_crafting needs only the
        scitem lookup, and its generator is stubbed, so this needs no XML."""
        base_ini, forge_dir = forge_layout
        with patch.object(gen_module, "build_scitem_lookups",
                          return_value=({}, {}, {}, {})) as scitem, \
             patch.object(gen_module, "_run_gen_commodity_journal",
                          return_value=({}, {})) as commodity, \
             patch.object(gen_module, "ThreadPoolExecutor") as pool_cls:
            gen_module.main(
                base_ini_path=base_ini,
                forge_dir=forge_dir,
                categories={"commodity_crafting"},
                max_workers=6,
            )
        _assert_no_pool(pool_cls)
        scitem.assert_called_once()
        commodity.assert_called_once()
