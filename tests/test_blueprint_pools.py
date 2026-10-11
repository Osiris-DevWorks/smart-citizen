"""Tests for the blueprint-pool side of the mission rewards pipeline.

Covers two changes shipped in 1.4.0:

1. ``scan_contract_generators`` previously kept only the first blueprint
   pool per ``(title_key, system_name)`` — subsequent ``BlueprintRewards``
   elements in the same contract were dropped on the floor. 4.8-era
   Adagio mining missions reward BOTH FPS gear (one pool) and ship
   components (another pool) from a single contract, so the old
   single-pool assumption silently lost half the loot list. The fix
   merges with order-preserving de-dup; the regression tests below
   guard that.

2. ``build_scitem_lookups`` now also returns an ``entity_name_tags``
   dict — UUID → ``[CLASS-Sx-grade]`` tag — that ``build_blueprint_pool_lookup``
   weaves into ship-component blueprint names. So a mission's POTENTIAL
   BLUEPRINTS list reads "[MIL-S1-A] Norfield" instead of bare
   "Norfield", mirroring the inline tag the components pipeline writes
   onto stock component titles. The placement (prepend vs append)
   mirrors the components Tag Builder's ``placement`` setting so the
   blueprint list stays visually consistent with the strings tab —
   pre-1.4.1 the BP path always appended regardless of user choice
   (issue #31 follow-up). FPS gear / weapons / ships get no tag.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    """Load scripts/generate_enhancements_ini.py as an importable module."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_blueprint_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_contractgen_xml(dir_path: Path, filename: str, contract_xml: str) -> Path:
    """Write a minimal ContractGenerator XML containing the given contract body."""
    path = dir_path / filename
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<root>\n'
        + contract_xml +
        '\n</root>\n',
        encoding="utf-8",
    )
    return path


class TestMultiSourcePoolMerge:
    """Regression guard for the 1.4.0 Adagio-mining multi-pool bug.

    Pre-fix: only the first ``BlueprintRewards`` per system was kept;
    subsequent pools (FPS gear + ship components in the same contract)
    were silently dropped.
    """

    @pytest.mark.regression
    def test_two_blueprint_rewards_in_one_contract_merge(self, gen_module, tmp_path):
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()

        # Adagio-style contract: one Contract, two BlueprintRewards pointing
        # at different pools (FPS gear + ship components).
        contract_xml = '''
<ContractGeneratorHandler_List debugName="Adagio_Stanton_HandMining">
    <Contract debugName="Adagio_Stanton_HandMining_T1">
        <Title>
            <ContractStringParam param="Title" value="@adagio_mining_title"/>
            <ContractStringParam param="Description" value="@adagio_mining_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-fps-uuid" chance="1.0"/>
        <BlueprintRewards blueprintPool="pool-comp-uuid" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "adagio.xml", contract_xml)

        blueprint_pools = {
            "pool-fps-uuid":  ["Pyro Pickaxe", "FPS Mining Helmet"],
            "pool-comp-uuid": ["Norfield Power Plant", "Harkin Cooler"],
        }

        _missions, mission_blueprints, _chance, _items = gen_module.scan_contract_generators(
            contractgen_dir,
            reputation_lookup={},
            blueprint_pools=blueprint_pools,
            entity_names={},
        )

        assert "adagio_mining_title" in mission_blueprints, (
            "title_key missing from mission_blueprints — contract parser failed"
        )
        per_system = mission_blueprints["adagio_mining_title"]
        assert "Stanton" in per_system, f"expected 'Stanton' system, got {list(per_system)}"

        # mission_blueprints is now {title: {system: {pool_key: (label, [items])}}},
        # pool_key being a UUID or (since both pools here share the same
        # contract and label) a combined tuple of the contract's pool UUIDs
        # (#360). No rank-tier names supplied here, so both pools land under
        # the empty label and — being from the SAME contract — merge into
        # one entry, same as before the #360 fix. The bug originally guarded
        # against here was the second pool's items being silently dropped —
        # gather across all entries to assert both pools' items survived.
        items = [it for _label, items_list in per_system["Stanton"].values() for it in items_list]
        assert "Pyro Pickaxe" in items
        assert "FPS Mining Helmet" in items
        assert "Norfield Power Plant" in items
        assert "Harkin Cooler" in items
        assert len(items) == 4, f"expected 4 merged items, got {len(items)}: {items}"

    @pytest.mark.regression
    def test_merge_dedups_duplicate_items_across_pools(self, gen_module, tmp_path):
        """When two pools share an item, the merged list should list it once."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="DupeTest_Stanton">
    <Contract debugName="DupeTest_Stanton_T1">
        <Title>
            <ContractStringParam param="Title" value="@dupe_title"/>
            <ContractStringParam param="Description" value="@dupe_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-a" chance="1.0"/>
        <BlueprintRewards blueprintPool="pool-b" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "dupe.xml", contract_xml)

        blueprint_pools = {
            "pool-a": ["Shared Item", "Unique A"],
            "pool-b": ["Shared Item", "Unique B"],
        }

        _, mission_blueprints, _, _ = gen_module.scan_contract_generators(
            contractgen_dir, reputation_lookup={},
            blueprint_pools=blueprint_pools, entity_names={},
        )
        # Both pools come from the SAME contract and share the empty label,
        # so they merge into one entry keyed by their combined pool-UUID
        # tuple (#360) — the merge+dedup happens within that entry as before.
        per_system = mission_blueprints["dupe_title"]["Stanton"]
        assert len(per_system) == 1, f"expected one merged entry, got {per_system}"
        _label, items = next(iter(per_system.values()))
        assert items.count("Shared Item") == 1, (
            f"de-dup failed — 'Shared Item' appears {items.count('Shared Item')}× in {items}"
        )
        assert sorted(items) == ["Shared Item", "Unique A", "Unique B"]

    def test_single_pool_unchanged(self, gen_module, tmp_path):
        """Single-BlueprintRewards contracts behave identically to pre-fix."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="SingleTest_Stanton">
    <Contract debugName="SingleTest_Stanton_T1">
        <Title>
            <ContractStringParam param="Title" value="@single_title"/>
            <ContractStringParam param="Description" value="@single_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-only" chance="0.5"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "single.xml", contract_xml)

        _, mission_blueprints, mission_bp_chance, _ = gen_module.scan_contract_generators(
            contractgen_dir, reputation_lookup={},
            blueprint_pools={"pool-only": ["Only Item"]},
            entity_names={},
        )
        per_system = mission_blueprints["single_title"]["Stanton"]
        assert len(per_system) == 1, f"expected one entry, got {per_system}"
        label, items = next(iter(per_system.values()))
        assert label == ""
        assert items == ["Only Item"]
        assert mission_bp_chance["single_title"] == pytest.approx(0.5)


class TestDistinctContractVariantsStaySeparate:
    """Regression guard for #360: a Discord user reported a "Yormandi Eye"
    collection mission's POTENTIAL BLUEPRINTS list showing Prism Shotgun
    items mixed in with an unrelated Palatino-armor/P8-AR-rifle set, with
    third-party trackers only ever showing the latter.

    Root cause: CIG can generate the SAME mission title from multiple
    distinct <Contract> variants (e.g. different randomized reward-pool
    rolls), each with its own <BlueprintRewards> pool. Pre-fix,
    ``_merge_blueprint_pool`` keyed only on (title, system, pool_label),
    and non-rank-tiered pools all share the empty label — so two totally
    unrelated variants' pools landed in the same bucket and got flattened
    into one list with no way to tell them apart. The fix keys by the
    pool's own identity instead, while still merging pools a single
    contract legitimately awards together (see TestMultiSourcePoolMerge's
    Adagio case) and still separating rank-tiered pools by label (see
    TestPoolRankLabels)."""

    @pytest.mark.regression
    def test_two_contract_variants_same_title_stay_separate(self, gen_module, tmp_path):
        """Two DIFFERENT <Contract> elements (distinct variants, as CIG's
        contractgen produces for a randomized mission) sharing one title,
        each with its own single non-rank-tiered pool, must NOT merge into
        one list -- unlike TestMultiSourcePoolMerge's Adagio case, these
        are two separate contracts, not one contract's simultaneous pools."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="YormandiEye_Stanton">
    <Contract debugName="YormandiEye_Stanton_VariantA">
        <Title>
            <ContractStringParam param="Title" value="@yormandi_eye_title"/>
            <ContractStringParam param="Description" value="@yormandi_eye_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-palatino-p8ar" chance="1.0"/>
    </Contract>
    <Contract debugName="YormandiEye_Stanton_VariantB">
        <Title>
            <ContractStringParam param="Title" value="@yormandi_eye_title"/>
            <ContractStringParam param="Description" value="@yormandi_eye_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-prism" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "yormandi.xml", contract_xml)

        blueprint_pools = {
            "pool-palatino-p8ar": ["Palatino Arms", "Palatino Core", "P8-AR Rifle"],
            "pool-prism": ['Prism "Irradiated" Laser Shotgun', "Prism Laser Shotgun Battery (20 cap)"],
        }

        _, mission_blueprints, _, _ = gen_module.scan_contract_generators(
            contractgen_dir, reputation_lookup={},
            blueprint_pools=blueprint_pools, entity_names={},
        )

        per_system = mission_blueprints["yormandi_eye_title"]["Stanton"]
        assert len(per_system) == 2, (
            f"expected the two variants' pools to stay as separate entries, "
            f"got {len(per_system)}: {per_system}"
        )
        item_sets = [frozenset(items) for _label, items in per_system.values()]
        assert frozenset(blueprint_pools["pool-palatino-p8ar"]) in item_sets
        assert frozenset(blueprint_pools["pool-prism"]) in item_sets
        # The bug's exact symptom: no single entry should contain items
        # from BOTH pools.
        for items_set in item_sets:
            assert not (items_set & frozenset(blueprint_pools["pool-prism"])
                        and items_set & frozenset(blueprint_pools["pool-palatino-p8ar"])), (
                f"a Palatino/P8-AR item and a Prism item ended up in the same "
                f"entry — pools were incorrectly merged: {items_set}"
            )

    def test_two_contract_variants_identical_pool_still_dedupes(self, gen_module, tmp_path):
        """Two variants that happen to award the EXACT same pool (e.g. the
        same reward set spawned under two debugName suffixes) should still
        collapse into one entry, not double up -- the fix must not turn
        legitimate re-encounters of the identical pool into duplicates."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="SamePool_Stanton">
    <Contract debugName="SamePool_Stanton_VariantA">
        <Title>
            <ContractStringParam param="Title" value="@samepool_title"/>
            <ContractStringParam param="Description" value="@samepool_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-shared" chance="1.0"/>
    </Contract>
    <Contract debugName="SamePool_Stanton_VariantB">
        <Title>
            <ContractStringParam param="Title" value="@samepool_title"/>
            <ContractStringParam param="Description" value="@samepool_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-shared" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "samepool.xml", contract_xml)

        _, mission_blueprints, _, _ = gen_module.scan_contract_generators(
            contractgen_dir, reputation_lookup={},
            blueprint_pools={"pool-shared": ["Shared Item A", "Shared Item B"]},
            entity_names={},
        )
        per_system = mission_blueprints["samepool_title"]["Stanton"]
        assert len(per_system) == 1, (
            f"identical pool re-encountered across variants should dedupe "
            f"into one entry, got {len(per_system)}: {per_system}"
        )
        _label, items = next(iter(per_system.values()))
        assert items == ["Shared Item A", "Shared Item B"]


class TestBlueprintBodyPartsRendering:
    """Regression guard for the #360 follow-up: separating distinct pools
    (TestDistinctContractVariantsStaySeparate above) fixed the merged-list
    bug, but a live report showed the fix's OWN output looked broken for
    Rayari research missions -- two sections both rendering the bare
    ``<EM4>[Rayari_ResourceGathering]</EM4>`` header (same system, neither
    pool rank-tiered so both labels are empty) sitting over two different
    item lists, reading as a duplicate/bug rather than two distinct reward
    sets. ``_build_blueprint_body_parts`` is the extracted, directly
    testable form of the inline body-part renderer in _run_gen_missions."""

    def test_single_pool_no_header(self, gen_module):
        """An ordinary single-pool mission still renders as a bare bullet
        list with no header -- the #360 fix must not add headers where
        there was never more than one pool to begin with."""
        unique_fps = {
            ("Item A", "Item B"): [("Stanton", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert parts == ["- Item A\\n- Item B"]

    def test_single_pool_with_rank_label_still_headers(self, gen_module):
        """A single rank-tiered pool keeps its header (pre-#360 shape)."""
        unique_fps = {
            ("Item A",): [("Stanton", "Rank 0–1")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert parts == ["<EM4>[Stanton, Rank 0–1]</EM4>\\n- Item A"]

    def test_distinct_rank_labels_get_their_own_untouched_headers(self, gen_module):
        """Rank-tiered pools already have a distinguishing label, so the
        collision-numbering must NOT kick in (Shubin case, TestPoolRankLabels)."""
        unique_fps = {
            ("Surveyor-Go",): [("Stanton", "Rank 0–1")],
            ("FullSpec",):    [("Stanton", "Rank 4")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert parts == [
            "<EM4>[Stanton, Rank 0–1]</EM4>\\n- Surveyor-Go",
            "<EM4>[Stanton, Rank 4]</EM4>\\n- FullSpec",
        ]

    @pytest.mark.regression
    def test_colliding_headers_named_after_first_item(self, gen_module):
        """The exact live-reported shape: two unlabeled pools in the same
        system produce the same base header. A follow-up live report noted
        that numbering them "Reward Set 1" / "Reward Set 2" fixed the
        duplicate-header confusion but didn't tell a player what each set
        actually contained -- so each collision is now named after its own
        first item instead."""
        unique_fps = {
            ("P8-AR Rifle", "Palatino Arms"): [("Rayari_ResourceGathering", "")],
            ('Prism "Bonedust" Laser Shotgun', "Siebe Helmet"): [("Rayari_ResourceGathering", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert len(parts) == 2
        headers = [p.split("\\n", 1)[0] for p in parts]
        assert headers == [
            "<EM4>[Rayari_ResourceGathering, P8-AR Rifle Set]</EM4>",
            '<EM4>[Rayari_ResourceGathering, Prism "Bonedust" Laser Shotgun Set]</EM4>',
        ]
        assert headers[0] != headers[1], "colliding headers must be distinguishable"
        # Each item list stays attached to its own header, in order.
        assert "- P8-AR Rifle" in parts[0] and "- Palatino Arms" in parts[0]
        assert '- Prism "Bonedust" Laser Shotgun' in parts[1] and "- Siebe Helmet" in parts[1]

    def test_non_colliding_headers_get_no_extra_naming(self, gen_module):
        """Two pools in DIFFERENT systems produce naturally distinct headers
        -- no item-based suffix should be added since there's no collision."""
        unique_fps = {
            ("Item A",): [("Stanton", "")],
            ("Item B",): [("Pyro", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        headers = [p.split("\\n", 1)[0] for p in parts]
        assert headers == ["<EM4>[Pyro]</EM4>", "<EM4>[Stanton]</EM4>"]

    def test_three_way_collision_all_named(self, gen_module):
        """Three colliding headers all get named after their first item,
        not just the first repeat."""
        unique_fps = {
            ("A",): [("Stanton", "")],
            ("B",): [("Stanton", "")],
            ("C",): [("Stanton", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        headers = [p.split("\\n", 1)[0] for p in parts]
        assert headers == [
            "<EM4>[Stanton, A Set]</EM4>",
            "<EM4>[Stanton, B Set]</EM4>",
            "<EM4>[Stanton, C Set]</EM4>",
        ]

    @pytest.mark.regression
    def test_double_collision_falls_back_to_numeric_tiebreaker(self, gen_module):
        """Edge case: two colliding pools that ALSO happen to share the same
        first item name -- the item-based naming would collide right back
        into the original bug, so a numeric suffix is the last-resort
        tiebreaker to guarantee headers are always visually distinct."""
        unique_fps = {
            ("Shared Item", "Unique A"): [("Stanton", "")],
            ("Shared Item", "Unique B"): [("Stanton", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        headers = [p.split("\\n", 1)[0] for p in parts]
        assert headers == [
            "<EM4>[Stanton, Shared Item Set (1)]</EM4>",
            "<EM4>[Stanton, Shared Item Set (2)]</EM4>",
        ]
        assert headers[0] != headers[1]

    @pytest.mark.regression
    def test_known_rayari_pools_use_manual_override_labels(self, gen_module):
        """Final iteration on the #360 follow-up: per-mission scoping isn't
        possible (CIG reuses one description across every "Additional
        Resources For Research" variant, confirmed via SCMDB), so a manual
        override table names each known pool after what it's actually for,
        instead of an auto-derived "first item" label. Every instance of
        this mission shows both sets regardless -- the point is a player
        can recognize "this is the Yormandi Eye set" wherever it appears."""
        unique_fps = {
            (
                "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
                "Palatino Arms", "Palatino Arms Moonfall",
                "Palatino Core", "Palatino Core Moonfall",
                "Palatino Helmet", "Palatino Helmet Moonfall",
                "Palatino Legs", "Palatino Legs Moonfall",
            ): [("Rayari_ResourceGathering", "")],
            (
                'Prism "Bonedust" Laser Shotgun', 'Prism "Deep Sea" Laser Shotgun',
                'Prism "Firesteel" Laser Shotgun', "Prism Laser Shotgun",
                "Prism Laser Shotgun Battery (20 cap)", "Siebe Helmet",
                "Stirling Exploration Suit",
            ): [("Rayari_ResourceGathering", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        headers = [p.split("\\n", 1)[0] for p in parts]
        # Alphabetical by label text ("Irradiated..." < "Yormandi...") --
        # see test_override_order_is_independent_of_insertion_order below
        # for why this must not depend on dict/scan order.
        assert headers == [
            "<EM4>[Irradiated Valakkar Pearls]</EM4>",
            "<EM4>[Yormandi Eyes]</EM4>",
        ]
        # The system-name prefix and item-based naming are fully replaced,
        # not appended to.
        assert "Rayari_ResourceGathering" not in "".join(headers)
        assert "Set" not in "".join(headers)

    def test_overrides_are_skipped_on_a_non_english_run(self, gen_module):
        """The table is keyed on English display names, so a run resolving
        names in another language can never match it. It used to be consulted
        anyway: every lookup missed, the labels silently reverted to automatic
        naming, and the drift tripwire could not report it either, because
        fully translated names share zero items with the English set and never
        reach the overlap threshold. The one signal meant to catch a stale
        table stayed quiet for exactly the case it never had a chance at.

        Skipping explicitly is what makes that visible in the log instead.
        """
        unique_fps = {
            (
                "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
                "Palatino Arms", "Palatino Arms Moonfall",
                "Palatino Core", "Palatino Core Moonfall",
                "Palatino Helmet", "Palatino Helmet Moonfall",
                "Palatino Legs", "Palatino Legs Moonfall",
            ): [("Rayari_ResourceGathering", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps, False)
        assert "Yormandi Eyes" not in "".join(parts)
        # ...and the items still render, just under automatic naming.
        assert "P8-AR Rifle" in "".join(parts)

        # Same input on an English run keeps the manual label.
        parts_en = gen_module._build_blueprint_body_parts(unique_fps, True)
        assert "Yormandi Eyes" in "".join(parts_en)

    def test_non_english_run_does_not_log_a_drift_warning(self, gen_module, caplog):
        """A translated pool is not drift, and reporting it as such would
        train a maintainer to ignore the one warning that matters. The gate
        has to skip the tripwire too, not just the lookup."""
        import logging
        translated = {
            ("P8-AR Gewehr", "Palatino Arme", "Palatino Kern"): [("Rayari", "")],
        }
        with caplog.at_level(logging.WARNING):
            gen_module._build_blueprint_body_parts(translated, False)
        assert not [r for r in caplog.records if "override" in r.message.lower()]

    @pytest.mark.regression
    def test_override_order_is_independent_of_insertion_order(self, gen_module):
        """Both override pools share the identical (system, label) key
        ("Rayari_ResourceGathering", ""), so before this fix their relative
        order in the rendered body was decided by dict/insertion order --
        which traces back to whichever contract XML the scanner happened to
        reach first, making the section order non-deterministic across
        regenerations. Sorting by header text as the tiebreak fixes that:
        feeding the pools in the OPPOSITE insertion order must still
        produce the same output order."""
        yormandi_fp = (
            "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
            "Palatino Arms", "Palatino Arms Moonfall",
            "Palatino Core", "Palatino Core Moonfall",
            "Palatino Helmet", "Palatino Helmet Moonfall",
            "Palatino Legs", "Palatino Legs Moonfall",
        )
        irradiated_fp = (
            'Prism "Bonedust" Laser Shotgun', 'Prism "Deep Sea" Laser Shotgun',
            'Prism "Firesteel" Laser Shotgun', "Prism Laser Shotgun",
            "Prism Laser Shotgun Battery (20 cap)", "Siebe Helmet",
            "Stirling Exploration Suit",
        )
        keys = [("Rayari_ResourceGathering", "")]

        forward = {yormandi_fp: keys, irradiated_fp: keys}
        reversed_ = {irradiated_fp: keys, yormandi_fp: keys}

        forward_headers = [p.split("\\n", 1)[0] for p in gen_module._build_blueprint_body_parts(forward)]
        reversed_headers = [p.split("\\n", 1)[0] for p in gen_module._build_blueprint_body_parts(reversed_)]
        assert forward_headers == reversed_headers == [
            "<EM4>[Irradiated Valakkar Pearls]</EM4>",
            "<EM4>[Yormandi Eyes]</EM4>",
        ]

    def test_override_applies_even_as_the_only_pool(self, gen_module):
        """The override is keyed by item content, not by "is this
        colliding with another pool" -- a mission where this exact set is
        the ONLY pool should still get the override label, not render as a
        bare unheaded list."""
        unique_fps = {
            (
                "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
                "Palatino Arms", "Palatino Arms Moonfall",
                "Palatino Core", "Palatino Core Moonfall",
                "Palatino Helmet", "Palatino Helmet Moonfall",
                "Palatino Legs", "Palatino Legs Moonfall",
            ): [("Rayari_ResourceGathering", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert parts == [
            "<EM4>[Yormandi Eyes]</EM4>\\n"
            "- P8-AR Rifle\\n- P8-AR Rifle Magazine (15 Cap)\\n"
            "- Palatino Arms\\n- Palatino Arms Moonfall\\n"
            "- Palatino Core\\n- Palatino Core Moonfall\\n"
            "- Palatino Helmet\\n- Palatino Helmet Moonfall\\n"
            "- Palatino Legs\\n- Palatino Legs Moonfall"
        ]

    def test_unrelated_pools_are_unaffected_by_overrides(self, gen_module):
        """A pool whose item set doesn't match any override entry keeps the
        existing automatic naming -- the override table is additive, not a
        behavior change for everything else."""
        unique_fps = {
            ("Totally Unrelated Item",): [("Stanton", "")],
        }
        parts = gen_module._build_blueprint_body_parts(unique_fps)
        assert parts == ["- Totally Unrelated Item"]

    @pytest.mark.regression
    def test_near_miss_pool_logs_drift_warning(self, gen_module, caplog):
        """A pool missing just one item from a known override (e.g. CIG
        dropped "Palatino Legs Moonfall" from the Yormandi Eyes set in a
        patch) no longer matches exactly and silently reverts to
        auto-generated naming -- but it should log a warning so a
        maintainer notices the override table needs updating, instead of
        the drift going unnoticed forever."""
        drifted_items = (
            "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
            "Palatino Arms", "Palatino Arms Moonfall",
            "Palatino Core", "Palatino Core Moonfall",
            "Palatino Helmet", "Palatino Helmet Moonfall",
            "Palatino Legs",
            # "Palatino Legs Moonfall" missing -- simulates CIG drift.
        )
        unique_fps = {drifted_items: [("Stanton", "")]}
        with caplog.at_level(logging.WARNING, logger="generate_enhancements_ini_blueprint_test"):
            parts = gen_module._build_blueprint_body_parts(unique_fps)
        # Falls back to the ordinary bare-list rendering (no override match).
        assert parts == ["- " + "\\n- ".join(drifted_items)]
        assert any("Yormandi Eyes" in r.message for r in caplog.records), (
            f"expected a drift warning mentioning the near-matched override, got: "
            f"{[r.message for r in caplog.records]}"
        )

    def test_exact_match_does_not_log_drift_warning(self, gen_module, caplog):
        """An exact override match takes the normal override path and must
        not ALSO trigger the drift warning against itself."""
        unique_fps = {
            (
                "P8-AR Rifle", "P8-AR Rifle Magazine (15 Cap)",
                "Palatino Arms", "Palatino Arms Moonfall",
                "Palatino Core", "Palatino Core Moonfall",
                "Palatino Helmet", "Palatino Helmet Moonfall",
                "Palatino Legs", "Palatino Legs Moonfall",
            ): [("Stanton", "")],
        }
        with caplog.at_level(logging.WARNING, logger="generate_enhancements_ini_blueprint_test"):
            gen_module._build_blueprint_body_parts(unique_fps)
        assert caplog.records == []

    def test_unrelated_pool_does_not_log_drift_warning(self, gen_module, caplog):
        """A pool with low/no item overlap with any override must not warn
        -- the threshold exists specifically to avoid noise on genuinely
        unrelated pools."""
        unique_fps = {
            ("Totally Unrelated Item", "Another Unrelated Item"): [("Stanton", "")],
        }
        with caplog.at_level(logging.WARNING, logger="generate_enhancements_ini_blueprint_test"):
            gen_module._build_blueprint_body_parts(unique_fps)
        assert caplog.records == []


class TestBlueprintNameTags:
    """1.4.0 annotation: components in blueprint pools get the inline
    ``[CLASS-Sx-grade]`` tag the components pipeline writes onto stock
    component titles."""

    def test_scitem_lookup_emits_tag_for_component(self, gen_module, tmp_path):
        """A component XML with Size:/Grade:/Class: description should
        produce an entry in ``entity_name_tags``."""
        scitem_dir = tmp_path / "scitem"
        scitem_dir.mkdir()
        comp_xml = scitem_dir / "norfield_pp_s1.xml"
        comp_xml.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<EntityClassDefinition __ref="ent-norfield-uuid">\n'
            '  <Components>\n'
            '    <SAttachableComponentParams>\n'
            '      <AttachDef>\n'
            '        <Localization Name="@item_NameNorfield" Description="@item_DescNorfield"/>\n'
            '      </AttachDef>\n'
            '    </SAttachableComponentParams>\n'
            '  </Components>\n'
            '</EntityClassDefinition>\n',
            encoding="utf-8",
        )
        loc = {
            "item_NameNorfield": "Norfield",
            "item_DescNorfield": "Size: 1\\nGrade: A\\nClass: Military\\n\\nDescription text.",
        }

        _, entity_names, _, entity_name_tags = gen_module.build_scitem_lookups(scitem_dir, loc=loc)

        assert entity_names["ent-norfield-uuid"] == "Norfield"
        assert entity_name_tags["ent-norfield-uuid"] == "[MIL-S1-A]"

    @pytest.mark.regression
    def test_scitem_lookup_respects_user_tag_config(self, gen_module, tmp_path):
        """1.4.0 bug: ``build_scitem_lookups`` always used the default
        components TagConfig when rendering the entity_name_tags map.
        That map gets baked into ``blueprint_pools`` cache and drives the
        POTENTIAL BLUEPRINTS list inside mission descriptions — so a user
        who customised their Tag Builder saw their components pipeline
        emit the new style but mission descriptions still showed
        ``[MIL-S3-B]``. Verify a custom config flows through."""
        from src.utils.tag_builder import (
            DEFAULT_COMPONENT_CLASS_MAPPING, ElementSpec, TagConfig,
        )

        scitem_dir = tmp_path / "scitem"
        scitem_dir.mkdir()
        (scitem_dir / "norfield.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<EntityClassDefinition __ref="ent-norfield-uuid">\n'
            '  <Components>\n'
            '    <SAttachableComponentParams>\n'
            '      <AttachDef>\n'
            '        <Localization Name="@item_NameNorfield" Description="@item_DescNorfield"/>\n'
            '      </AttachDef>\n'
            '    </SAttachableComponentParams>\n'
            '  </Components>\n'
            '</EntityClassDefinition>\n',
            encoding="utf-8",
        )
        loc = {
            "item_NameNorfield": "Norfield",
            "item_DescNorfield": "Size: 1\\nGrade: A\\nClass: Military\\n\\n.",
        }

        # User config: round brackets, dot separator, long-form class label.
        # Expected render: "(Military.S1.A)".
        cfg = TagConfig(
            elements=[
                ElementSpec("class", True, "long"),
                ElementSpec("size",  True, "sn"),
                ElementSpec("grade", True, "letter"),
            ],
            separator="dot",
            enclosing="round",
            class_mapping=dict(DEFAULT_COMPONENT_CLASS_MAPPING),
        )

        _, _, _, entity_name_tags = gen_module.build_scitem_lookups(
            scitem_dir, loc=loc, tag_config=cfg,
        )
        assert entity_name_tags["ent-norfield-uuid"] == "(Military.S1.A)"

    def test_scitem_lookup_skips_tag_for_non_component(self, gen_module, tmp_path):
        """FPS gear / weapons whose description has no Size:/Grade:/Class:
        header should NOT produce a tag entry."""
        scitem_dir = tmp_path / "scitem"
        scitem_dir.mkdir()
        fps_xml = scitem_dir / "pickaxe.xml"
        fps_xml.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<EntityClassDefinition __ref="ent-pickaxe-uuid">\n'
            '  <Components>\n'
            '    <SAttachableComponentParams>\n'
            '      <AttachDef>\n'
            '        <Localization Name="@item_NamePickaxe" Description="@item_DescPickaxe"/>\n'
            '      </AttachDef>\n'
            '    </SAttachableComponentParams>\n'
            '  </Components>\n'
            '</EntityClassDefinition>\n',
            encoding="utf-8",
        )
        loc = {
            "item_NamePickaxe": "Pyro Pickaxe",
            "item_DescPickaxe": "A heavy-duty mining pickaxe with no component header.",
        }

        _, entity_names, _, entity_name_tags = gen_module.build_scitem_lookups(scitem_dir, loc=loc)

        assert entity_names["ent-pickaxe-uuid"] == "Pyro Pickaxe"
        assert "ent-pickaxe-uuid" not in entity_name_tags

    def test_blueprint_pool_prepends_tag_on_uuid_hit(self, gen_module, tmp_path):
        """``build_blueprint_pool_lookup`` should weave the tag into the
        display name when the entityClass UUID resolves AND has a tag entry.
        Default placement is "prepend" so the tag lands in front of the name,
        matching the components Tag Builder's default placement."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        # One blueprint pool with two BlueprintReward entries — one for
        # a tagged component, one for an FPS item.
        (pool_dir / "pool_adagio.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-adagio-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-norfield-uuid"/>\n'
            '  <BlueprintReward blueprintRecord="bp-pickaxe-uuid"/>\n'
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
        (bp_dir / "bp_craft_pickaxe.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-pickaxe-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-pickaxe-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        entity_names = {
            "ent-norfield-uuid": "Norfield",
            "ent-pickaxe-uuid": "Pyro Pickaxe",
        }
        entity_name_tags = {
            "ent-norfield-uuid": "[MIL-S1-A]",
            # No entry for pickaxe — FPS gear has no component tag.
        }

        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names,
            entity_name_tags=entity_name_tags,
        )

        items = pools["pool-adagio-uuid"]
        # Order: blueprint-pool resolution order, not alphabetical.
        assert "[MIL-S1-A] Norfield" in items, f"tagged name missing: {items}"
        assert "Pyro Pickaxe" in items, f"bare FPS name missing: {items}"
        # Critically, the FPS item is NOT tagged.
        assert not any(name.endswith(" Pyro Pickaxe") or name.startswith("Pyro Pickaxe ")
                       for name in items), (
            f"FPS gear should not get a [CLASS-Sx-grade] tag: {items}"
        )

    @pytest.mark.regression
    def test_blueprint_pool_respects_append_placement(self, gen_module, tmp_path):
        """Pre-1.4.1 bug (issue #31 follow-up): the BP-pool weave always
        appended the tag regardless of the components Tag Builder's
        ``placement`` setting, so a user who picked "append" still saw
        the (then-incorrect) appended form — but a user who picked
        "prepend" saw the components on the strings tab as
        ``[MIL-S1-A] Norfield`` and the same component in a mission's
        POTENTIAL BLUEPRINTS list as ``Norfield [MIL-S1-A]``. The fix
        threads ``name_tag_placement`` down so both paths agree."""
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

        pools_append, _ = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir,
            {"ent-norfield-uuid": "Norfield"},
            entity_name_tags={"ent-norfield-uuid": "[MIL-S1-A]"},
            name_tag_placement="append",
        )
        assert pools_append["pool-uuid"] == ["Norfield [MIL-S1-A]"]

        pools_prepend, _ = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir,
            {"ent-norfield-uuid": "Norfield"},
            entity_name_tags={"ent-norfield-uuid": "[MIL-S1-A]"},
            name_tag_placement="prepend",
        )
        assert pools_prepend["pool-uuid"] == ["[MIL-S1-A] Norfield"]

    def test_tagger_strict_path_unchanged(self, gen_module):
        """Full Size:/Grade:/Class: trio still produces the legacy
        '[CLASS-Sx-grade]' shape — the new fallback must not perturb
        this output for any ship component the strict path already handled."""
        tag = gen_module._component_name_tag
        assert tag("Size: 1\\nGrade: A\\nClass: Military") == "[MIL-S1-A]"
        assert tag("Item Type: Radar\\nSize: 2\\nGrade: C\\nClass: Industrial") == "[IND-S2-C]"
        assert tag("Size: 0\\nGrade: B\\nClass: Stealth") == "[STH-S0-B]"

    def test_tagger_fallback_mining_head_full(self, gen_module):
        """Helix / Hofstede / Lawson — Size: S0 + Grade: + Item Type:
        Mining Laser, no Class:. Should emit [MIN-S0-{grade}]."""
        tag = gen_module._component_name_tag
        helix_desc = (
            "Manufacturer: Thermyte Concern\\n"
            "Item Type: Mining Laser\\n"
            "Size: S0\\n"
            "Grade: B\\n"
            " \\nOptimal Range: 30 m"
        )
        assert tag(helix_desc) == "[MIN-S0-B]"

        lawson_desc = (
            "Manufacturer: Argo Astronautics\\n"
            "Item Type: Mining Laser\\n"
            "Size: S0\\n"
            "Grade: C\\n"
        )
        assert tag(lawson_desc) == "[MIN-S0-C]"

    def test_tagger_fallback_mining_head_size_double_zero(self, gen_module):
        """S00 (sub-size-0) preserves both zeros in the tag."""
        tag = gen_module._component_name_tag
        desc = "Item Type: Mining Laser\\nSize: S00\\nGrade: A\\n"
        assert tag(desc) == "[MIN-S00-A]"

    def test_tagger_fallback_mining_laser_size_only(self, gen_module):
        """Arbor MHV — bare 'Size: 0' + 'Item Type: Mining Laser ' (note
        the trailing space CIG writes), no Grade, no Class. Emits the
        type+size shape with no trailing grade."""
        tag = gen_module._component_name_tag
        arbor_desc = (
            "Manufacturer: Greycat Industrial\\n"
            "Item Type: Mining Laser \\n"
            "Size: 0\\n\\nOptimal Range: 15m"
        )
        assert tag(arbor_desc) == "[MIN-S0]"

    def test_tagger_fallback_grade_only_no_known_item_type(self, gen_module):
        """#160: An item with Size + Grade but an Item Type not in the
        abbreviation map returns None on the fallback path. A grade-only
        [Sx-grade] tag conveys nothing useful without a type and was
        incorrectly appearing on FPS gear / salvage heads in blueprint lists."""
        tag = gen_module._component_name_tag
        desc = "Item Type: Unrecognised Widget\\nSize: 2\\nGrade: A\\n"
        assert tag(desc) is None

    def test_tagger_ship_weapons_tag_with_damage_type(self, gen_module):
        """1.4.1 regression: ship weapons in POTENTIAL BLUEPRINTS lists
        were rendering bare ('- Tarantula GT-870 Mark 2 Cannon') because
        _ITEM_TYPE_ABBREV only had 'Mining Laser'. Expanding the map to
        cover every Ship-weapon Item Type makes the BP-list tag match the
        single-letter damage code the strings-tab tagger emits — so a
        Tarantula reads ``[B-S2] Tarantula …`` in both places."""
        tag = gen_module._component_name_tag
        # Ballistic family
        assert tag("Item Type: Ballistic Cannon\\nSize: 2\\n") == "[B-S2]"
        assert tag("Item Type: Ballistic Gatling\\nSize: 1\\n") == "[B-S1]"
        assert tag("Item Type: Ballistic Repeater\\nSize: 3\\n") == "[B-S3]"
        assert tag("Item Type: Mass Driver Cannon\\nSize: 4\\n") == "[B-S4]"
        assert tag("Item Type: Railgun\\nSize: 2\\n") == "[B-S2]"
        # Energy family (laser / plasma / neutron / tachyon)
        assert tag("Item Type: Laser Cannon\\nSize: 1\\n") == "[E-S1]"
        assert tag("Item Type: Laser Repeater\\nSize: 2\\n") == "[E-S2]"
        assert tag("Item Type: Plasma Cannon\\nSize: 5\\n") == "[E-S5]"
        assert tag("Item Type: Neutron Repeater\\nSize: 3\\n") == "[E-S3]"
        assert tag("Item Type: Tachyon Cannon\\nSize: 7\\n") == "[E-S7]"
        # Distortion family
        assert tag("Item Type: Distortion Cannon\\nSize: 2\\n") == "[D-S2]"
        assert tag("Item Type: Distortion Repeater\\nSize: 1\\n") == "[D-S1]"
        # EMP
        assert tag("Item Type: EMP Generator\\nSize: 3\\n") == "[EMP-S3]"

    def test_tagger_ship_weapons_trailing_space_variant(self, gen_module):
        """CIG occasionally writes ``Item Type: Laser Cannon ``\\n
        (trailing space before the literal ``\\n``). The regex strips it
        via ``.strip()`` before lookup, so both forms produce the same
        tag — locking the parity so a future CIG cleanup doesn't break
        the previously-working trailing-space variant or vice versa."""
        tag = gen_module._component_name_tag
        assert tag("Item Type: Laser Cannon \\nSize: 1\\n") == "[E-S1]"
        assert tag("Item Type: Ballistic Cannon \\nSize: 3\\n") == "[B-S3]"

    def test_tagger_salvage_head(self, gen_module):
        """1.4.1 regression: salvage heads (Baler, Salvation) were
        rendering bare in BP lists. Salvage Head → ``[SAL-Sx]``."""
        tag = gen_module._component_name_tag
        baler_desc = (
            "Manufacturer: Greycat Industrial\\n"
            "Item Type: Salvage Head\\n"
            "Size: 2\\n"
        )
        assert tag(baler_desc) == "[SAL-S2]"
        salvation_desc = (
            "Manufacturer: Roberts Space Industries\\n"
            "Item Type: Salvage Head\\n"
            "Size: 1\\n"
        )
        assert tag(salvation_desc) == "[SAL-S1]"

    def test_tagger_fallback_rejects_size_only(self, gen_module):
        """A description with ONLY Size: (no Grade, no recognised Item
        Type) returns None — bare [Sx] is too weak to be informative and
        would leak onto consumables / ammo containers that happen to have
        a Size: line. The bar is: at least one of {known item type, grade}
        must accompany the size."""
        tag = gen_module._component_name_tag
        assert tag("Size: 0") is None
        assert tag("Item Type: Random Thing\\nSize: 0\\n") is None

    def test_tagger_no_size_returns_none(self, gen_module):
        """No Size: anywhere → no tag. FPS gear, pistols, helmets fall
        through here unchanged."""
        tag = gen_module._component_name_tag
        assert tag("A heavy-duty mining pickaxe with no component header.") is None
        assert tag("Manufacturer: Klaus & Werner\\nItem Type: Pistol\\n") is None

    def test_strip_cig_size_prefix_helper(self, gen_module):
        """The strip helper removes ``S0 `` / ``S00 `` / ``S1 ``… prefixes
        but leaves names that start with ``S`` + letters (Sasquatch, etc.)."""
        f = gen_module._strip_cig_size_prefix
        assert f("S0 Helix") == "Helix"
        assert f("S00 Hofstede") == "Hofstede"
        assert f("S1 ExampleHead") == "ExampleHead"
        assert f("S15 BiggerHead") == "BiggerHead"
        # Names that begin with 'S' but not 'S{digit}' are untouched.
        assert f("Sasquatch") == "Sasquatch"
        assert f("Slicer Pistol") == "Slicer Pistol"
        assert f("Surveyor-Go") == "Surveyor-Go"
        # No prefix → unchanged.
        assert f("Norfield") == "Norfield"
        # Strip only the LEADING occurrence — a literal "S0" elsewhere stays.
        assert f("Foo S0 Bar") == "Foo S0 Bar"
        # Sanity: a name that's only the prefix collapses to empty (edge case;
        # unlikely in real data but worth pinning behavior).
        assert f("S0 ") == ""

    def test_blueprint_pool_strips_cig_size_prefix_on_uuid_hit(self, gen_module, tmp_path):
        """Tier-1 (UUID-resolved) names should have the CIG-baked size
        prefix stripped before reaching the blueprint list — eliminates
        the visual inconsistency of "S0 Helix" sitting next to
        "Surveyor [IND-S2-C]" in the same rendered list."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-helix-uuid"/>\n'
            '  <BlueprintReward blueprintRecord="bp-norfield-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_helix.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-helix-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-helix-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_norfield.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-norfield-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-norfield-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        entity_names = {
            "ent-helix-uuid": "S0 Helix",
            "ent-norfield-uuid": "Norfield",
        }
        entity_name_tags = {
            "ent-norfield-uuid": "[MIL-S1-A]",
            # Helix doesn't get a tag (its description lacks Class:) — but
            # the CIG-baked "S0 " prefix should still come off.
        }

        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names,
            entity_name_tags=entity_name_tags,
        )
        items = pools["pool-uuid"]
        assert "Helix" in items, f"prefix should be stripped: {items}"
        assert "S0 Helix" not in items, f"unstripped name should not appear: {items}"
        # Default placement is "prepend" — locked by the prepend test above.
        assert "[MIL-S1-A] Norfield" in items, f"tagged name should still work: {items}"

    def test_blueprint_pool_omits_tag_when_dict_unset(self, gen_module, tmp_path):
        """Back-compat: callers that don't pass entity_name_tags get
        un-annotated names (pre-1.4.0 behavior)."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_thing.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        # No entity_name_tags argument → no tag, even though we could've matched.
        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, {"ent-uuid": "Thing"},
        )
        assert pools["pool-uuid"] == ["Thing"]

    @pytest.mark.regression
    def test_blueprint_pool_tags_tier3_fallback_name(self, gen_module, tmp_path):
        """A live in-game mission body reported fuel nozzle names correctly
        resolved (#281 fix) but missing their [FN] tag, even though the tag
        shows correctly in Smart Citizen's own String Editor. Root cause:
        entity_name_tags is built from an entity's __ref + Description alone
        (independent of whether its Name attribute ever resolved), so a fuel
        nozzle can miss BOTH tier 1 (UUID) and tier 2 (filename) name
        resolution -- landing on the tier-3 fallback -- while still having a
        valid tag entry. The old code only ever checked entity_name_tags
        inside the tier-1 branch, so the tag data sat unused. The tag must
        now apply regardless of which tier supplied the name."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-nozzle-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_nozzle_fuelgiver_grin_nozzlefast.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-nozzle-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-nozzle-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        # entity_names and entity_names_by_filename are both EMPTY for this
        # entity ref -- reproducing tiers 1 and 2 both missing, exactly like
        # the real fuel nozzle bug. entity_name_tags DOES have an entry,
        # since that dict never depended on Name resolution succeeding.
        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names={},
            entity_names_by_filename={},
            entity_name_tags={"ent-nozzle-uuid": "[FN]"},
        )

        # Falls to tier 3's filename fallback, alias-corrected to "Norfield"
        # (#281), and now carries the tag tier 3 previously dropped.
        assert pools["pool-uuid"] == ["[FN] Norfield"]

    @pytest.mark.regression
    def test_blueprint_pool_name_fallback_tags_apply_without_any_entity_linkage(
        self, gen_module, tmp_path
    ):
        """The real 2.3.0 live-report shape: the fuel nozzle's entity XML
        isn't UUID-linked to its blueprint AT ALL (same broken linkage
        behind #281's garbled names), so entity_name_tags -- keyed by
        entity __ref -- can never supply the tag no matter which tier the
        name came from. name_fallback_tags is keyed by display name and
        derived purely from base.ini loc pairs (bare_type_name_tag_lookup),
        so it covers exactly this hole: tier-3 alias gives "Norfield", the
        name-keyed dict tags it."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-nozzle-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_nozzle_fuelgiver_grin_nozzlefast.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-nozzle-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-nozzle-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        # ALL entity-XML-derived dicts empty -- no UUID hit, no filename
        # hit, no UUID-keyed tag. Only the loc-derived name-keyed dict.
        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names={},
            entity_names_by_filename={},
            entity_name_tags={},
            name_fallback_tags={"Norfield": "[FN]"},
        )
        assert pools["pool-uuid"] == ["[FN] Norfield"]

    def test_blueprint_pool_entity_tag_wins_over_name_fallback(self, gen_module, tmp_path):
        """When the entity-XML route DOES have a tag (normal components),
        the name-keyed fallback must not double-weave or override it."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "pool.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-uuid">\n'
            '  <BlueprintReward blueprintRecord="bp-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_shield.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        pools, _pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names={"ent-uuid": "Aspirum"},
            entity_name_tags={"ent-uuid": "[MIL-S1-A]"},
            name_fallback_tags={"Aspirum": "[WRONG]"},
        )
        assert pools["pool-uuid"] == ["[MIL-S1-A] Aspirum"]


class TestPoolRankLabels:
    """1.4.0 sub-section labels: progression-gated pool filenames
    (Shubin / Headhunters style with ``RankN`` or ``RankNtoM`` suffixes)
    surface in the POTENTIAL BLUEPRINTS sub-section headers via
    ``_pool_rank_label``. Pools whose names don't carry a rank token
    return empty string and render with the bare system-only header
    they had before."""

    def test_rank_label_helper(self, gen_module):
        f = gen_module._pool_rank_label
        # Range patterns
        assert f("shubinrank0to1") == "Rank 0–1"
        assert f("shubinrank2to3") == "Rank 2–3"
        # Single-rank patterns
        assert f("shubinrank4") == "Rank 4"
        assert f("shubinrank0") == "Rank 0"
        # Case insensitivity (filenames are lowercased but __ref names may not be)
        assert f("ShubinRank4") == "Rank 4"
        assert f("SHUBINRANK0TO1") == "Rank 0–1"
        # No rank token → empty string (region pools, one-off pools)
        assert f("headhuntersmercenaryshipregionc") == ""
        assert f("collectorwikelo") == ""
        assert f("") == ""
        # Range takes precedence — "rank2to3" is a range, not "rank2" alone
        assert f("shubinrank2to3") == "Rank 2–3"

    def test_pool_lookup_exposes_filename_stem(self, gen_module, tmp_path):
        """``build_blueprint_pool_lookup`` returns a second dict mapping
        pool UUID → filename stem, with the ``bp_rewards_`` prefix stripped."""
        pool_dir = tmp_path / "blueprintrewards"
        bp_dir = tmp_path / "blueprints" / "crafting"
        pool_dir.mkdir(parents=True)
        bp_dir.mkdir(parents=True)

        (pool_dir / "bp_rewards_shubinrank4.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<BlueprintPoolRecord __ref="pool-rank4">\n'
            '  <BlueprintReward blueprintRecord="bp-uuid"/>\n'
            '</BlueprintPoolRecord>\n',
            encoding="utf-8",
        )
        (bp_dir / "bp_craft_thing.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<CraftingBlueprintRecord __ref="bp-uuid">\n'
            '  <CraftingProcess_Creation entityClass="ent-uuid"/>\n'
            '</CraftingBlueprintRecord>\n',
            encoding="utf-8",
        )

        pools, pool_names = gen_module.build_blueprint_pool_lookup(
            pool_dir, bp_dir, {"ent-uuid": "Thing"},
        )
        assert pools["pool-rank4"] == ["Thing"]
        # Stem stored with bp_rewards_ stripped, lowercased.
        assert pool_names["pool-rank4"] == "shubinrank4"
        # Round-trip through the label helper.
        assert gen_module._pool_rank_label(pool_names["pool-rank4"]) == "Rank 4"

    def test_scan_groups_items_by_rank_label(self, gen_module, tmp_path):
        """``scan_contract_generators`` groups per-pool items under a
        rank-label sub-key when ``pool_names`` is supplied, so distinct
        rank tiers don't get blended into one merged blob."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="ShubinTest_Stanton">
    <Contract debugName="ShubinTest_Stanton_T1">
        <Title>
            <ContractStringParam param="Title" value="@shubin_title"/>
            <ContractStringParam param="Description" value="@shubin_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-rank0to1" chance="1.0"/>
        <BlueprintRewards blueprintPool="pool-rank4" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "shubin.xml", contract_xml)

        _, mission_blueprints, _, _ = gen_module.scan_contract_generators(
            contractgen_dir,
            reputation_lookup={},
            blueprint_pools={
                "pool-rank0to1": ["Surveyor-Go [IND-S0-C]", "Lawson Mining Laser"],
                "pool-rank4":    ["FullSpec [IND-S2-A]", "Arbor MH2 Mining Laser"],
            },
            entity_names={},
            pool_names={
                "pool-rank0to1": "shubinrank0to1",
                "pool-rank4":    "shubinrank4",
            },
        )

        per_system = mission_blueprints["shubin_title"]["Stanton"]
        # Two distinct rank-label entries, NOT merged into one (each pool's
        # own label differs, so the per-contract grouping keeps them apart
        # even though both come from the same contract).
        by_label = {label: items for label, items in per_system.values()}
        assert "Rank 0–1" in by_label
        assert "Rank 4" in by_label
        assert by_label["Rank 0–1"] == ["Surveyor-Go [IND-S0-C]", "Lawson Mining Laser"]
        assert by_label["Rank 4"] == ["FullSpec [IND-S2-A]", "Arbor MH2 Mining Laser"]

    def test_scan_falls_back_to_empty_label_when_pool_names_missing(self, gen_module, tmp_path):
        """When pool_names isn't supplied (or doesn't cover a pool UUID),
        items land under the empty-label bucket — preserving the pre-1.4.0
        rendering shape for non-rank pools."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        contract_xml = '''
<ContractGeneratorHandler_List debugName="NoLabelTest_Stanton">
    <Contract debugName="NoLabelTest_Stanton_T1">
        <Title>
            <ContractStringParam param="Title" value="@nolabel_title"/>
            <ContractStringParam param="Description" value="@nolabel_desc"/>
        </Title>
        <BlueprintRewards blueprintPool="pool-x" chance="1.0"/>
    </Contract>
</ContractGeneratorHandler_List>
'''
        _write_contractgen_xml(contractgen_dir, "nolabel.xml", contract_xml)

        _, mission_blueprints, _, _ = gen_module.scan_contract_generators(
            contractgen_dir, reputation_lookup={},
            blueprint_pools={"pool-x": ["Item A", "Item B"]},
            entity_names={},
            # pool_names omitted → all pools resolve to empty label
        )
        per_system = mission_blueprints["nolabel_title"]["Stanton"]
        assert len(per_system) == 1, f"expected one entry, got {per_system}"
        label, items = next(iter(per_system.values()))
        assert label == "", f"expected empty label, got {per_system}"
        assert items == ["Item A", "Item B"]


class TestOrphanPuDescCleanup:
    """1.4.0 regression: when a single mission title is spawned by both modern
    ``CareerContract`` blocks (which carry BlueprintRewards) and older
    ``ContractLegacy`` blocks (which don't), the pu_missions enhancement
    scan emits desc entries for the ContractLegacy-fronted pu_missions
    XMLs. Those orphan descs end up sharing a [BP]-tagged title without
    a POTENTIAL BLUEPRINTS body, which reads as a bug to the user (issue
    #31 Covalex repro: ``Covalex_HaulCargo_SingleToMulti_RefinedOre`` had
    no BP list under the BP-tagged ``Covalex_HaulCargo_SingleToMulti_title``).
    The cleanup pass removes those orphan desc entries entirely so the
    title's BP claim only attaches to bodies that back it up.

    The pieces of the cleanup are exercised by smaller-grained unit
    coverage; this class drives the end-to-end shape of the orphan-drop
    rule directly via a synthetic ``out`` dict and the two indexes the
    cleanup loop reads.
    """

    @pytest.mark.regression
    def test_orphan_pu_desc_dropped_under_bp_title(self, gen_module):
        """Title T has 1 contractgen variant (desc D_CG, awards BP) and 1
        pu_missions-only variant (desc D_PU, ContractLegacy, no BP). The
        cleanup pass should drop D_PU but keep D_CG."""
        # The cleanup logic is inlined in main(), but its shape mirrors:
        out = {
            "T": "<some title text> <EM4>[BP]</EM4>",
            "D_CG": "<contractgen rendered body with POTENTIAL BLUEPRINTS>",
            "D_PU": "<pu_missions bare MISSION DETAILS body>",
        }
        contractgen_missions = {
            "T": [("Stanton", 100, 0, "D_CG", [], 0, 0, "", True, 1.0, "")],
        }
        mission_blueprints = {"T": {"Stanton": {"": ["Item A"]}}}
        pu_title_to_descs = {"T": {"D_CG", "D_PU"}}

        for _tk, _vs in contractgen_missions.items():
            if _tk not in mission_blueprints:
                continue
            _cg = {v[3] for v in _vs if v[3]}
            for _o in pu_title_to_descs.get(_tk, set()) - _cg:
                out.pop(_o, None)

        assert "T" in out, "title text must stay"
        assert "D_CG" in out, "contractgen-backed desc must stay"
        assert "D_PU" not in out, "pu-only orphan desc must be dropped"

    @pytest.mark.regression
    def test_orphan_pu_desc_preserved_when_title_has_no_bp(self, gen_module):
        """Title T has no BP info (not in mission_blueprints). The pu-only
        desc is NOT an orphan in the bug's sense — body and title are
        internally consistent (both BP-silent) — and must be preserved."""
        out = {
            "T": "<title text, no BP tag>",
            "D_CG": "<contractgen body, no BP section>",
            "D_PU": "<pu_missions body, no BP section>",
        }
        contractgen_missions = {
            "T": [("Stanton", 100, 0, "D_CG", [], 0, 0, "", False, 0.0, "")],
        }
        mission_blueprints: dict = {}  # T not present
        pu_title_to_descs = {"T": {"D_CG", "D_PU"}}

        for _tk, _vs in contractgen_missions.items():
            if _tk not in mission_blueprints:
                continue
            _cg = {v[3] for v in _vs if v[3]}
            for _o in pu_title_to_descs.get(_tk, set()) - _cg:
                out.pop(_o, None)

        assert "D_PU" in out, "non-BP title's pu desc must stay"
        assert "D_CG" in out


class TestCargoBpTitleDemotion:
    """#102: a haul title whose contractgenerator variants all carry
    BlueprintRewards can still be fronted by ContractLegacy blocks that spawn
    blueprint-less pu_missions cargo / delivery hauls (Covalex: 16 BP-bearing
    career variants vs 419 BP-less legacy hauls). Those haul descs survive the
    orphan-drop (kept so the haul shows mission info), so a flat ``[BP]`` would
    sit over blueprint-less bodies and read as wrong in-game. The title-augment
    loop demotes such titles to the honest ``[BP?]``.

    The decision is inlined in ``_run_gen_missions``; these tests drive its
    shape directly (mirroring ``TestOrphanPuDescCleanup`` above), since the
    augment loop isn't separately callable.
    """

    @staticmethod
    def _tag(variants, has_blueprints, pu_cargo_delivery_descs, pu_title_descs):
        """Replica of the augment-loop BP-tag branch (generate_enhancements_ini)."""
        _bp_variants = [v[7] for v in variants]
        _all_have_bp = has_blueprints and all(_bp_variants)
        # #341 follow-up: _all_have_bp only means every variant HAS a
        # BlueprintRewards pool, not that its own chance (v[8]) is 1.0 -- a
        # 100%-coverage-but-partial-chance mission must not read as
        # guaranteed. Live repro: Rayari's chance="0.25" missions.
        _all_bp_guaranteed = _all_have_bp and all(
            v[8] >= 1.0 for v in variants if v[7]
        )
        _any_variant_has_bp = any(_bp_variants)
        # Simplified partial detector: no dominant no-BP desc bucket. The real
        # loop weighs bucket share; for these single-bucket fixtures the result
        # matches, and the demotion path under test is independent of it.
        _bp_partial = has_blueprints and _any_variant_has_bp and not _all_have_bp
        _cg_desc_keys = {v[3] for v in variants if v[3]}
        _surviving_no_bp_cargo = bool(
            (pu_cargo_delivery_descs & pu_title_descs) - _cg_desc_keys
        )
        if _all_have_bp and _all_bp_guaranteed and not _surviving_no_bp_cargo:
            return "[BP]"
        if _bp_partial or (
            _all_have_bp and (_surviving_no_bp_cargo or not _all_bp_guaranteed)
        ):
            return "[BP?]"
        return ""

    @pytest.mark.regression
    def test_all_bp_variants_with_surviving_cargo_demotes(self, gen_module):
        """All career variants award BP, but a legacy cargo haul desc survives
        under the same title → demote ``[BP]`` to ``[BP?]`` (Covalex repro)."""
        # tuple: (system, sxp, fxp, desc_key, flags, spawns, difficulty,
        #         contract_has_bp[7], bp_chance, bp_variant, rank)
        variants = [("Stanton", 500, 0, "D_CG", [], 0, 0, True, 1.0, "", "")]
        tag = self._tag(
            variants,
            has_blueprints=True,
            pu_cargo_delivery_descs={"HaulCargo_AtoB_desc"},
            pu_title_descs={"D_CG", "HaulCargo_AtoB_desc"},
        )
        assert tag == "[BP?]"

    @pytest.mark.regression
    def test_all_bp_variants_no_cargo_stays_full_bp(self, gen_module):
        """All variants award BP and no legacy cargo haul desc survives (pure
        career / combat contract) → keep the unqualified ``[BP]``."""
        variants = [("Stanton", 500, 0, "D_CG", [], 0, 0, True, 1.0, "", "")]
        tag = self._tag(
            variants,
            has_blueprints=True,
            pu_cargo_delivery_descs=set(),
            pu_title_descs={"D_CG"},
        )
        assert tag == "[BP]"

    @pytest.mark.regression
    def test_zero_bp_cargo_title_gets_no_tag(self, gen_module):
        """A title whose variants award no BP must stay untagged even when it
        has surviving cargo descs (the demotion must not invent a ``[BP?]``)."""
        variants = [("Stanton", 500, 0, "D_CG", [], 0, 0, False, 0.0, "", "")]
        tag = self._tag(
            variants,
            has_blueprints=False,
            pu_cargo_delivery_descs={"HaulCargo_AtoB_desc"},
            pu_title_descs={"D_CG", "HaulCargo_AtoB_desc"},
        )
        assert tag == ""

    @pytest.mark.regression
    def test_full_coverage_with_partial_chance_demotes(self, gen_module):
        """#341 follow-up: every variant has a BlueprintRewards pool
        (_all_have_bp is True) but its own chance is under 1.0 -- the
        mission won't ALWAYS pay out, so the title must not read as the
        guaranteed [BP]. Before the fix, _all_have_bp alone drove the tag
        and this produced [BP] even though the mission DETAILS body (a
        separate code path keying off the same v.bp_chance field) already
        correctly said "25% chance", not "Guaranteed" -- the title and
        body disagreed about the same mission. Live repro: Rayari's
        RAIN_collectresources missions (chance="0.25"); verified against
        the LIVE DataForge cache that exactly those two titles flip to
        [BP?] and everything else, Battaglia included (chance="1"), keeps
        its tag."""
        variants = [("Pyro", 500, 0, "D_CG", [], 0, 0, True, 0.3, "", "")]
        tag = self._tag(
            variants,
            has_blueprints=True,
            pu_cargo_delivery_descs=set(),
            pu_title_descs={"D_CG"},
        )
        assert tag == "[BP?]"

    @pytest.mark.regression
    def test_full_coverage_full_chance_stays_full_bp(self, gen_module):
        """Every variant has a pool AND every one is chance=1.0 -- genuinely
        guaranteed, keep the unqualified [BP] (control case for the fix
        above, confirms it didn't just always demote to [BP?])."""
        variants = [("Pyro", 500, 0, "D_CG", [], 0, 0, True, 1.0, "", "")]
        tag = self._tag(
            variants,
            has_blueprints=True,
            pu_cargo_delivery_descs=set(),
            pu_title_descs={"D_CG"},
        )
        assert tag == "[BP]"

    @pytest.mark.regression
    def test_mixed_chance_across_variants_demotes(self, gen_module):
        """One variant is guaranteed (chance=1.0), another sharing the same
        title is only 50/50 -- the title as a whole is still not a sure
        thing, so it must demote to [BP?] rather than let the guaranteed
        variant win."""
        variants = [
            ("Stanton", 500, 0, "D_CG_A", [], 0, 0, True, 1.0, "", ""),
            ("Pyro", 500, 0, "D_CG_B", [], 0, 0, True, 0.5, "", ""),
        ]
        tag = self._tag(
            variants,
            has_blueprints=True,
            pu_cargo_delivery_descs=set(),
            pu_title_descs={"D_CG_A", "D_CG_B"},
        )
        assert tag == "[BP?]"


class TestTypelessTagFilter:
    """#160: typeless component tags ("[S1-A]" — size+grade, no class/type)
    are dropped before being woven into POTENTIAL BLUEPRINTS, so armour /
    magazines / salvage-mining heads show bare. Class/type-qualified tags
    survive."""

    def test_typeless_tags_match_the_filter(self, gen_module):
        for tag in ("[S1-A]", "[S2]", "[S3-B]", "[S0-D]"):
            assert gen_module._TYPELESS_COMPONENT_TAG_RE.search(tag), tag

    def test_class_or_type_tags_do_not_match(self, gen_module):
        for tag in ("[Mil-S1-A]", "[SAL-S2]", "[MIN-S0-B]", "[CIV-S3-C]"):
            assert not gen_module._TYPELESS_COMPONENT_TAG_RE.search(tag), tag
