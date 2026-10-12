"""generate_enhancements_ini.main() needs the DataForge cache.

With no cache folder, or a cache folder without its records folder
(raw/libs/foundry/records, DATAFORGE_RECORDS_SUBPATH), main() raises
FileNotFoundError naming the folder and asking for Extract DataForge first,
before it reads any XML or writes any enhancement file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    """Load scripts/generate_enhancements_ini.py (lives outside src/)."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("gen_dataforge_cache_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cache_folder_made", [
    pytest.param(False, id="no-cache-folder"),
    pytest.param(True, id="no-records-folder"),
])
def test_main_stops_when_the_cache_has_no_records_folder(gen_module, tmp_path, cache_folder_made):
    base_ini = tmp_path / "base.ini"
    base_ini.write_text("some_key=Some Value\n", encoding="utf-8")
    forge_dir = tmp_path / "dataforge"
    records = forge_dir / gen_module.DATAFORGE_RECORDS_SUBPATH
    if cache_folder_made:
        records.parent.mkdir(parents=True)   # everything but the records folder
    with pytest.raises(FileNotFoundError, match="DataForge cache not found at") as raised:
        gen_module.main(base_ini, forge_dir, categories=set())
    assert str(forge_dir) in str(raised.value)
    assert "Extract DataForge" in str(raised.value)

    # With the records folder in place the same run goes through, so only
    # the missing folder stopped it.
    records.mkdir(parents=True, exist_ok=True)
    gen_module.main(base_ini, forge_dir, categories=set())
