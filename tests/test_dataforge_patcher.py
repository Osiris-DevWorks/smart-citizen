"""Tests for src.utils.dataforge_patcher."""
from __future__ import annotations

import json
from pathlib import Path

from utils.dataforge_patcher import (
    LocstringWorkaround,
    apply_locstring_workarounds,
    apply_patches,
    load_locstring_workarounds,
)


def _records_root(tmp_path: Path) -> Path:
    """Create the DataForge records/ layout the patcher expects."""
    root = tmp_path / "dataforge" / "raw" / "libs" / "foundry" / "records"
    root.mkdir(parents=True)
    return root


def _write_patch(patch_dir: Path, subpath: str, body: dict) -> Path:
    p = patch_dir / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


_CONTRACT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<root>
  <Contract debugName="Hockrow_FacilityDelve_P2M4-Stanton4_Repeat">
    <paramOverrides>
      <stringParamOverrides>
        <ContractStringParam param="Title" value="@Hockrow_FacilityDelve_P2M4_Repeat_title" />
        <ContractStringParam param="Description" value="@Hockrow_FacilityDelve_P2M1_Repeat_desc" />
      </stringParamOverrides>
    </paramOverrides>
  </Contract>
  <Contract debugName="UnrelatedContract">
    <paramOverrides>
      <stringParamOverrides>
        <ContractStringParam param="Description" value="@SomeOther_desc" />
      </stringParamOverrides>
    </paramOverrides>
  </Contract>
</root>
"""


def _write_target(records: Path, subpath: str, body: str) -> Path:
    target = records / subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


_P2M4_EDIT = {
    "xpath": ".//Contract[@debugName='Hockrow_FacilityDelve_P2M4-Stanton4_Repeat']//ContractStringParam[@param='Description']",
    "attribute": "value",
    "expected": "@Hockrow_FacilityDelve_P2M1_Repeat_desc",
    "set": "@Hockrow_FacilityDelve_P2M4_Repeat_desc",
}


def test_apply_edit_rewrites_attribute(tmp_path: Path):
    records = _records_root(tmp_path)
    target = _write_target(records, "contracts/hockrowagency.xml", _CONTRACT_XML)
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "contracts/hockrowagency.xml",
        "edits": [_P2M4_EDIT],
    })

    report = apply_patches(patches, tmp_path / "dataforge")

    assert report.edits_applied == 1
    assert report.files_rewritten == 1
    assert "@Hockrow_FacilityDelve_P2M4_Repeat_desc" in target.read_text(encoding="utf-8")
    assert "@Hockrow_FacilityDelve_P2M1_Repeat_desc" not in target.read_text(encoding="utf-8")


def test_apply_edit_is_idempotent(tmp_path: Path):
    records = _records_root(tmp_path)
    _write_target(records, "contracts/hockrowagency.xml", _CONTRACT_XML)
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "contracts/hockrowagency.xml",
        "edits": [_P2M4_EDIT],
    })

    first = apply_patches(patches, tmp_path / "dataforge")
    second = apply_patches(patches, tmp_path / "dataforge")

    assert first.edits_applied == 1
    # Second run: value already matches `set`; should be a clean no-op
    assert second.edits_applied == 0
    assert second.edits_idempotent == 1
    assert second.files_rewritten == 0


def test_expected_mismatch_skips_with_warning(tmp_path: Path):
    records = _records_root(tmp_path)
    target = _write_target(records, "contracts/hockrowagency.xml",
                           _CONTRACT_XML.replace("@Hockrow_FacilityDelve_P2M1_Repeat_desc",
                                                 "@UpstreamAlreadyFixed_desc"))
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "contracts/hockrowagency.xml",
        "edits": [_P2M4_EDIT],
    })

    report = apply_patches(patches, tmp_path / "dataforge")

    assert report.edits_applied == 0
    assert report.edits_skipped_mismatch == 1
    assert report.files_rewritten == 0
    # Target stayed as-is
    assert "@UpstreamAlreadyFixed_desc" in target.read_text(encoding="utf-8")


def test_missing_target_file_records_error(tmp_path: Path):
    _records_root(tmp_path)  # records dir exists but target file doesn't
    patches = tmp_path / "patches"
    _write_patch(patches, "missing.patch.json", {
        "target": "does/not/exist.xml",
        "edits": [_P2M4_EDIT],
    })

    report = apply_patches(patches, tmp_path / "dataforge")

    assert report.patches_seen == 1
    assert report.files_rewritten == 0
    assert any("does/not/exist.xml" in e for e in report.errors)


def test_missing_patches_dir_returns_empty_report(tmp_path: Path):
    _records_root(tmp_path)
    report = apply_patches(tmp_path / "nope", tmp_path / "dataforge")
    assert report.patches_seen == 0
    assert report.errors == []


def test_no_xpath_match_records_no_match(tmp_path: Path):
    records = _records_root(tmp_path)
    _write_target(records, "contracts/hockrowagency.xml", _CONTRACT_XML)
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "contracts/hockrowagency.xml",
        "edits": [{
            **_P2M4_EDIT,
            "xpath": ".//Contract[@debugName='DoesNotExist']//ContractStringParam[@param='Description']",
        }],
    })

    report = apply_patches(patches, tmp_path / "dataforge")

    assert report.edits_no_match == 1
    assert report.edits_applied == 0


def test_unrelated_elements_left_alone(tmp_path: Path):
    records = _records_root(tmp_path)
    target = _write_target(records, "contracts/hockrowagency.xml", _CONTRACT_XML)
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "contracts/hockrowagency.xml",
        "edits": [_P2M4_EDIT],
    })

    apply_patches(patches, tmp_path / "dataforge")

    # UnrelatedContract's Description must remain untouched
    assert "@SomeOther_desc" in target.read_text(encoding="utf-8")


def test_malformed_patch_recorded_as_error(tmp_path: Path):
    _records_root(tmp_path)
    patches = tmp_path / "patches"
    (patches).mkdir(parents=True)
    (patches / "bad.patch.json").write_text("{ not valid json", encoding="utf-8")

    report = apply_patches(patches, tmp_path / "dataforge")

    assert report.patches_seen == 1
    assert report.errors  # at least one error recorded


# ──────────────────────────────────────────────────────────────────────────────
# Loc-string workarounds
# ──────────────────────────────────────────────────────────────────────────────


def test_load_workarounds_from_patch_json(tmp_path: Path):
    patches = tmp_path / "patches"
    _write_patch(patches, "hockrow.patch.json", {
        "target": "dummy.xml",
        "edits": [_P2M4_EDIT],
        "locstring_workarounds": [
            {
                "description": "merge P2M4 onto P2M1",
                "target": "Hockrow_FacilityDelve_P2M1_Repeat_desc",
                "append_from": "Hockrow_FacilityDelve_P2M4_Repeat_desc",
                "separator": "\\n\\n<EM3>sep</EM3>\\n",
            }
        ],
    })

    ws = load_locstring_workarounds(patches)

    assert len(ws) == 1
    assert ws[0].target == "Hockrow_FacilityDelve_P2M1_Repeat_desc"
    assert ws[0].append_from == "Hockrow_FacilityDelve_P2M4_Repeat_desc"
    assert ws[0].separator == "\\n\\n<EM3>sep</EM3>\\n"
    assert ws[0].patch_source == "hockrow.patch.json"


def test_load_workarounds_skips_malformed(tmp_path: Path):
    patches = tmp_path / "patches"
    _write_patch(patches, "a.patch.json", {
        "target": "x.xml",
        "edits": [],
        "locstring_workarounds": [
            {"target": "k1", "append_from": "k2"},        # valid
            {"target": "k3"},                              # missing append_from
            {"append_from": "k4"},                         # missing target
        ],
    })

    ws = load_locstring_workarounds(patches)

    assert len(ws) == 1
    assert ws[0].target == "k1"


def test_load_workarounds_missing_dir_returns_empty(tmp_path: Path):
    assert load_locstring_workarounds(tmp_path / "nope") == []


def test_apply_workaround_appends_content():
    entries = {
        "P2M1_desc": "Energy anomaly flavor text. POTENTIAL BLUEPRINTS\\n- A\\n- B",
        "P2M4_desc": "Power usage flavor text. POTENTIAL BLUEPRINTS\\n- C\\n- D",
    }
    ws = [LocstringWorkaround(target="P2M1_desc", append_from="P2M4_desc", separator="||SEP||")]

    applied = apply_locstring_workarounds(entries, ws)

    assert applied == 1
    assert entries["P2M1_desc"].endswith("||SEP||Power usage flavor text. POTENTIAL BLUEPRINTS\\n- C\\n- D")
    # Source key is unchanged
    assert entries["P2M4_desc"] == "Power usage flavor text. POTENTIAL BLUEPRINTS\\n- C\\n- D"


def test_apply_workaround_is_idempotent():
    entries = {"a": "alpha", "b": "beta"}
    ws = [LocstringWorkaround(target="a", append_from="b", separator="|")]

    first = apply_locstring_workarounds(entries, ws)
    second = apply_locstring_workarounds(entries, ws)

    assert first == 1
    assert second == 0  # second run sees target already ends with "|beta"
    assert entries["a"] == "alpha|beta"


def test_apply_workaround_skips_when_keys_absent():
    # Neither target nor source present — no-op; meant for a different dict.
    entries = {"unrelated": "x"}
    ws = [LocstringWorkaround(target="a", append_from="b")]

    assert apply_locstring_workarounds(entries, ws) == 0
    assert entries == {"unrelated": "x"}


def test_apply_workaround_skips_when_source_missing():
    entries = {"a": "alpha"}  # target present, source missing
    ws = [LocstringWorkaround(target="a", append_from="b")]

    assert apply_locstring_workarounds(entries, ws) == 0
    assert entries["a"] == "alpha"
