"""scripts/add_sco_sample.py: SCO crops become DIGIT_SAMPLES entries."""
import importlib.util
from pathlib import Path

import pytest

from src.utils.sco_digit_samples import DIGIT_SAMPLES

ROOT = Path(__file__).parent.parent
CROP = ROOT / "tests" / "fixtures" / "sco" / "live00_15600.png"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location(
        "add_sco_sample_test", ROOT / "scripts" / "add_sco_sample.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _samples_file(tmp_path):
    path = tmp_path / "samples.py"
    path.write_text('DIGIT_SAMPLES = (\n    ("1", 1, 1, "ff", "x"),\n)\n', encoding="utf-8")
    return path


def test_crop_entries_match_the_stored_samples(tool):
    entries = tool.crop_entries(CROP, "15600", "live_00")
    assert entries == [s for s in DIGIT_SAMPLES if s[4] == "live_00"]


def test_crop_entries_need_the_right_digit_count(tool):
    with pytest.raises(ValueError, match="no row of 4 digits"):
        tool.crop_entries(CROP, "1560", "x")


def test_add_entries_appends_new_glyphs_once(tool, tmp_path):
    path = _samples_file(tmp_path)
    entries = tool.crop_entries(CROP, "15600", "live_99")
    assert tool.add_entries(entries, path, existing=()) == 5
    text = path.read_text(encoding="utf-8")
    assert text.endswith(")\n") and tool.format_entry(entries[-1]) + "\n)" in text
    namespace = {}
    exec(text, namespace)
    assert namespace["DIGIT_SAMPLES"][1:] == tuple(entries)
    # Glyphs the set already holds, or that repeat within the batch, are skipped.
    assert tool.add_entries(entries + entries, path, existing=entries) == 0


def test_main_prints_entries_named_after_the_crop(tool, capsys):
    assert tool.main([str(CROP)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 5 and all(line.endswith('"live00"),') for line in lines)
    assert lines[0].startswith('    ("1", ')


def test_main_reports_a_crop_without_digits_in_its_name(tool, tmp_path, capsys):
    crop = tmp_path / "crop_unknown.png"
    crop.write_bytes(CROP.read_bytes())
    assert tool.main([str(crop)]) == 1
    assert "pass --digits" in capsys.readouterr().err
