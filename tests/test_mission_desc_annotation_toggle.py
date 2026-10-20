"""Tests for the mission-description annotation toggle (issue #31 follow-up).

When ON (default, preserves v1.4.0 behavior) the components Tag Builder
annotation is woven into the POTENTIAL BLUEPRINTS list inside mission
descriptions, e.g. ``[MIL-S1-A] Norfield``. When OFF the BP-list
renders bare names while the inline tag on the actual component name
elsewhere is unaffected.

The toggle is plumbed end-to-end through:
  * AppSettings.{get,set}_tag_annotate_mission_descs (bool, default True)
  * EnhancementsGeneratorWorker.__init__(annotate_mission_descs=True)
  * generate_enhancements_ini.main(annotate_mission_descs=True)
  * _run_gen_missions reads ctx["annotate_mission_descs"] and swaps the
    entity_name_tags dict for {} when off — same back-compat code path
    already locked by test_blueprint_pool_omits_tag_when_dict_unset.

These tests cover the settings round-trip (incl. the default) and the
generator-side dict swap; the worker wiring and UI checkbox plumbing
are exercised manually because EnhancementsGeneratorWorker requires a
populated DataForge cache to exercise meaningfully.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path):
    """Hermetic JsonSettings backend for the settings round-trip tests."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_annotate_toggle_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSettingsDefault:
    def test_default_is_true(self, json_backend):
        """Absent setting → True. Preserves v1.4.0 behavior (annotation
        on) for upgraded users who never touch the new checkbox."""
        assert AppSettings.get_tag_annotate_mission_descs() is True

    def test_set_false_persists(self, json_backend):
        AppSettings.set_tag_annotate_mission_descs(False)
        assert AppSettings.get_tag_annotate_mission_descs() is False

    def test_set_true_persists(self, json_backend):
        AppSettings.set_tag_annotate_mission_descs(False)
        AppSettings.set_tag_annotate_mission_descs(True)
        assert AppSettings.get_tag_annotate_mission_descs() is True

    def test_round_trip_via_get_set(self, json_backend):
        """Belt-and-suspenders: confirm we never lose the bool type
        across set/get even if the backend stringifies booleans."""
        for value in (True, False, True, False):
            AppSettings.set_tag_annotate_mission_descs(value)
            got = AppSettings.get_tag_annotate_mission_descs()
            assert got is value, f"round-trip dropped value: set={value} got={got!r}"


class TestGeneratorDictSwap:
    """The toggle is implemented as a dict swap in _run_gen_missions:
    when True the real entity_name_tags dict is passed to
    build_blueprint_pool_lookup; when False, an empty dict is passed
    so the tag weave produces bare names.

    Verifying the dict swap directly via build_blueprint_pool_lookup
    (which the toggle gates on) is the tightest test we can do without
    a populated DataForge cache."""

    def _write_minimal_pool(self, tmp_path: Path) -> tuple[Path, Path]:
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)
        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-norfield-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_norfield.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-norfield-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-norfield-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )
        return pool_dir, bp_dir

    def test_annotation_on_produces_tagged_name(self, gen_module, tmp_path):
        """Toggle ON: tag dict passed → BP list shows annotated name."""
        pool_dir, bp_dir = self._write_minimal_pool(tmp_path)
        pools, _ = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir,
            entity_names={"ent-norfield-uuid": "Norfield"},
            entity_name_tags={"ent-norfield-uuid": "[MIL-S1-A]"},
        )
        assert pools["pool-uuid"] == ["[MIL-S1-A] Norfield"]

    def test_annotation_off_via_empty_dict_produces_bare_name(self, gen_module, tmp_path):
        """Toggle OFF: empty dict passed (the swap _run_gen_missions
        performs) → BP list shows bare name. Same code path as the
        back-compat case from test_blueprint_pool_omits_tag_when_dict_unset
        — gating via an empty dict (rather than a new kwarg or branch
        inside build_blueprint_pool_lookup) keeps the behavior
        identical to "no tag dict supplied"."""
        pool_dir, bp_dir = self._write_minimal_pool(tmp_path)
        pools, _ = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir,
            entity_names={"ent-norfield-uuid": "Norfield"},
            entity_name_tags={},  # the swap _run_gen_missions does when off
        )
        assert pools["pool-uuid"] == ["Norfield"]


class TestMainAcceptsToggleKwarg:
    """generate_enhancements_ini.main grew an ``annotate_mission_descs``
    kwarg. Pinning the signature here so a future refactor that drops or
    renames it fails CI loudly rather than silently turning the toggle
    into a no-op."""

    def test_main_signature_includes_annotate_kwarg(self, gen_module):
        import inspect
        sig = inspect.signature(gen_module.main)
        assert "annotate_mission_descs" in sig.parameters
        # Default must be True so a CLI invocation without the kwarg
        # matches the on-by-default UI behavior.
        assert sig.parameters["annotate_mission_descs"].default is True
