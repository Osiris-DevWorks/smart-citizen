"""#485: the ship component generators in ``generate_enhancements_ini.py``.

``enhancements_shield``, ``enhancements_radar``, ``enhancements_cooler``,
``enhancements_powerplant``, ``enhancements_quantum_drive`` and
``enhancements_bomb_rack``, and ``_run_gen_components``, which runs them over
the component folders, had no test: the only one that named them checked four
strings it wrote itself (#481 removes it). A renamed XML field, a wrong unit
or a dropped line passed the whole suite.

The fixtures follow real entity XMLs from an extracted LIVE DataForge cache
(the Asas Veil shield, the Behring Hunter radar, the ACOM IcePlunge cooler,
the ACOM LumaCore power plant, the ACAS FoxFire quantum drive and the Aegis
Eclipse bomb rack): the same element paths and the same values, cut down to
what each generator reads. Each test asserts the exact text written. Where a
field is missing, the tests pin what the generator does today: a line left
out, or a "?" where a line shows two values and only one is there. A quantum
drive's spool time shows tenths, as its cooldown does: whole seconds showed
the FoxFire's 4.8 s as "5s" (#485).

The item name tags and the sibling loc keys ``_run_gen_components`` also
writes have their own tests (``test_scitem_sibling_mirror.py``,
``test_bare_type_tags.py`` and others), so the folder fixtures here carry only
a description key, except in the one test of what the run alone adds to a
name tag: the component type of the folder the item was found in.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_component_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Real-shape XML, cut down to what the generators read ─────────────────────

def _entity(name: str, *components: str) -> str:
    return (f"<EntityClassDefinition.{name}><Components>"
            + "".join(components)
            + f"</Components></EntityClassDefinition.{name}>")


def _attach(desc_key: str = "", name_key: str = "", **attrs: str) -> str:
    """``SAttachableComponentParams/AttachDef``, with its ``Localization``
    when *desc_key* is given (and the name key when *name_key* is, see the
    module docstring)."""
    attr_text = "".join(f' {k}="{v}"' for k, v in attrs.items())
    name = f'Name="@{name_key}" ' if name_key else ""
    loc = f'<Localization {name}Description="@{desc_key}"/>' if desc_key else ""
    return ("<SAttachableComponentParams>"
            f"<AttachDef{attr_text}>{loc}</AttachDef>"
            "</SAttachableComponentParams>")


def _amount(unit: str, value: str) -> str:
    attr = {"SPowerSegmentResourceUnit": "units",
            "SStandardResourceUnit": "standardResourceUnits",
            "SMicroResourceUnit": "microResourceUnits"}[unit]
    return f'<resourceAmountPerSecond><{unit} {attr}="{value}"/></resourceAmountPerSecond>'


def _uses(resource: str, unit: str, value: str) -> str:
    return f'<consumption resource="{resource}">{_amount(unit, value)}</consumption>'


def _makes(resource: str, unit: str, value: str) -> str:
    return f'<generation resource="{resource}">{_amount(unit, value)}</generation>'


def _resources(deltas: str = "", em: str | None = None, ir: str | None = None) -> str:
    """``ItemResourceComponentParams/states/ItemResourceState``: its deltas
    and its ``signatureParams``, as every real component carries them."""
    sigs = ""
    if em is not None:
        sigs += f'<EMSignature nominalSignature="{em}" decayRate="0.15"/>'
    if ir is not None:
        sigs += f'<IRSignature nominalSignature="{ir}" decayRate="0.15"/>'
    if sigs:
        sigs = f"<signatureParams>{sigs}</signatureParams>"
    return ("<ItemResourceComponentParams><states><ItemResourceState>"
            f"<deltas>{deltas}</deltas>{sigs}"
            "</ItemResourceState></states></ItemResourceComponentParams>")


def _overheat(kelvin: str) -> str:
    return ("<SEntityPhysicsControllerParams><PhysType>"
            "<SEntityRigidPhysicsControllerParams><temperature>"
            f'<itemResourceParams enableOverheat="1" overheatTemperature="{kelvin}"/>'
            "</temperature></SEntityRigidPhysicsControllerParams>"
            "</PhysType></SEntityPhysicsControllerParams>")


def _health(hp: str) -> str:
    return f'<SHealthComponentParams Health="{hp}"/>'


def _distortion(maximum: str) -> str:
    return f'<SDistortionParams DecayDelay="1.5" Maximum="{maximum}"/>'


def _resists(*pairs: tuple[str, str]) -> str:
    return "<ShieldResistance>" + "".join(
        f'<SShieldResistance Max="{mx}" Min="{mn}"/>' for mn, mx in pairs) + "</ShieldResistance>"


def _lines(*lines: str) -> str:
    """The generators join lines with a literal backslash-n (the loc-string
    line break), not a newline."""
    return "\\n".join(lines)


def _root(xml: str):
    return ET.fromstring(xml)


# The Veil's six resistances: physical, energy, then four the shield line
# does not show.
_VEIL_RESISTS = (("0", "0.25"), ("0", "0"), ("0.75", "0.95"), ("0", "0"), ("0", "0"), ("0", "0"))


def _veil(desc_key: str = "", name_key: str = "", resists=_VEIL_RESISTS,
          shield_attrs: str | None = None) -> str:
    if shield_attrs is None:
        shield_attrs = ('MaxShieldHealth="2244" MaxShieldRegen="449" '
                        'DownedRegenDelay="6.36" DamagedRegenDelay="3.18"')
    return _entity(
        "SHLD_ASAS_S01_Veil_SCItem",
        _attach(desc_key, name_key, Type="Shield", Size="1", Grade="2"),
        _overheat("383"),
        _health("150"),
        _resources(
            "<ItemResourceDeltaConversion>"
            + _uses("Power", "SPowerSegmentResourceUnit", "1")
            + _makes("Shield", "SStandardResourceUnit", "449")
            + "</ItemResourceDeltaConversion>"
            "<ItemResourceDeltaConsumption>"
            + _uses("Coolant", "SStandardResourceUnit", "0")
            + "</ItemResourceDeltaConsumption>",
            em="250", ir="0"),
        _distortion("2200"),
        f"<SCItemShieldGeneratorParams {shield_attrs}>{_resists(*resists)}"
        "</SCItemShieldGeneratorParams>",
    )


VEIL = _lines(
    "Max HP: 2,244  |  Regen: 449 HP/s",
    "Downed Delay: 6.4s  |  Damaged Delay: 3.2s",
    "Resist:  Phys: +0% – +25%",
    "Signatures:  EM: 250  |  IR: 0",
    "Power Draw: 1 PU/s",
    "Component HP: 150",
)


def _hunter(desc_key: str = "", name_key: str = "", aim: tuple[str, str] = ("780", "1028.5"),
            cooldown: str = "2.5",
            modes: tuple[tuple[str, str], ...] = (("1", "1"), ("0", "1"), ("0", "0"))) -> str:
    detections = "".join(
        f'<SCItemRadarSignatureDetection sensitivity="0.8" permitPassiveDetection="{p}" '
        f'permitActiveDetection="{a}"/>' for p, a in modes)
    return _entity(
        "RADR_BLTR_S01_Hunter",
        _attach(desc_key, name_key, Type="Radar", SubType="MidRangeRadar", Size="1", Grade="2"),
        _overheat("393"),
        _health("420"),
        _resources(
            "<ItemResourceDeltaConsumption>"
            + _uses("Power", "SPowerSegmentResourceUnit", "5")
            + "</ItemResourceDeltaConsumption>"
            "<ItemResourceDeltaConsumption>"
            + _uses("Coolant", "SStandardResourceUnit", "0")
            + "</ItemResourceDeltaConsumption>",
            em="1170", ir="0"),
        _distortion("3240"),
        "<SCItemRadarComponentParams>"
        f"<signatureDetection>{detections}</signatureDetection>"
        f'<pingProperties cooldownTime="{cooldown}"/>'
        f'<aimAssist distanceMinAssignment="{aim[0]}" distanceMaxAssignment="{aim[1]}" '
        'outsideRangeBufferDistance="60"/>'
        "</SCItemRadarComponentParams>",
    )


HUNTER = _lines(
    "Aim Assist Range: 780–1,028 m",
    "Ping Cooldown: 2.5s",
    "Detection Mode: Passive / Active",
    "Power Draw: 5 PU/s",
    "Component HP: 420",
)


def _iceplunge(desc_key: str = "", name_key: str = "", overheat: str = "675",
               em: str | None = "818", ir: str | None = "5890", hp: bool = True) -> str:
    return _entity(
        "COOL_ACOM_S01_IcePlunge_SCItem",
        _attach(desc_key, name_key, Type="Cooler", Size="1", Grade="3"),
        _overheat(overheat) if overheat else "",
        _health("69") if hp else "",
        _resources(
            "<ItemResourceDeltaConversion>"
            + _uses("Power", "SPowerSegmentResourceUnit", "2")
            + _makes("Coolant", "SStandardResourceUnit", "34")
            + "</ItemResourceDeltaConversion>",
            em=em, ir=ir),
        _distortion("1050"),
    )


ICEPLUNGE = _lines(
    "Cooling Rate: 34 CR/s",
    "Power Draw: 2 PU/s",
    "Component HP: 69",
    "Signatures:  EM: 818  |  IR: 5,890",
    "Overheat Temp: 675K",
)


def _lumacore(desc_key: str = "", name_key: str = "", overheat: str = "381") -> str:
    return _entity(
        "POWR_ACOM_S01_LumaCore_SCItem",
        _attach(desc_key, name_key, Type="PowerPlant", SubType="Power", Size="1", Grade="1"),
        _overheat(overheat),
        _health("140"),
        _resources(
            "<ItemResourceDeltaGeneration>"
            + _makes("Power", "SPowerSegmentResourceUnit", "16")
            + "</ItemResourceDeltaGeneration>"
            "<ItemResourceDeltaConsumption>"
            + _uses("Coolant", "SStandardResourceUnit", "0")
            + "</ItemResourceDeltaConsumption>",
            em="6550", ir="0"),
        _distortion("2050"),
    )


LUMACORE = _lines(
    "Power Output: 16 PU/s",
    "Component HP: 140",
    "Signatures:  EM: 6,550  |  IR: 0",
    "Overheat Temp: 381K",
    "Max Distortion: 2,050",
)

_FOXFIRE_PARAMS = {
    "driveSpeed": "263040000", "spoolUpTime": "4.8", "cooldownTime": "11.9",
    "calibrationRate": "1000", "minCalibrationRequirement": "5000",
    "maxCalibrationRequirement": "10000",
    "stageOneAccelRate": "10848920", "stageTwoAccelRate": "28291720",
}


def _foxfire(desc_key: str = "", name_key: str = "", form: str = "params",
             **params: str | None) -> str:
    """The FoxFire. *params* replace its drive parameters (None leaves one
    out). *form* is how they are written: ``params`` as on LIVE today, or one
    of the two older forms ``_find_by_type`` reads, ``__type`` (a ``params``
    element marked with it) or ``tag`` (the type name as the element)."""
    values = {**_FOXFIRE_PARAMS, **params}
    attr_text = "".join(f' {k}="{v}"' for k, v in values.items() if v is not None)
    element = {"params": "params", "__type": 'params __type="SQuantumDriveParams"',
               "tag": "SQuantumDriveParams"}[form]
    return _entity(
        "QDRV_ACAS_S01_FoxFire_SCItem",
        _attach(desc_key, name_key, Type="QuantumDrive", Size="1", Grade="2"),
        _overheat("372"),
        _health("120"),
        _resources(
            "<ItemResourceDeltaConsumption>"
            + _uses("Power", "SStandardResourceUnit", "2")
            + "</ItemResourceDeltaConsumption>"
            "<ItemResourceDeltaConsumption>"
            + _uses("QuantumFuel", "SMicroResourceUnit", "5")
            + "</ItemResourceDeltaConsumption>",
            em="21600", ir="0"),
        _distortion("1800"),
        '<SCItemQuantumDriveParams quantumFuelRequirement="0.00588" disconnectRange="20001">'
        f"<{element}{attr_text}/>"
        "</SCItemQuantumDriveParams>",
    )


FOXFIRE = _lines(
    "QT Speed: 263 Mm/s  |  Spool: 4.8s",
    "Cooldown: 11.9s",
    "Fuel/Gm: 0.0059",
    "QT Fuel Use: 5 μ/s",
    "Accel:  S1: 10,848,920  |  S2: 28,291,720",
    "Cal Rate: 1,000  |  Required: 5,000–10,000",
    "Power Draw: 2 PU/s",
    "Component HP: 120",
    "Signatures:  EM: 21,600  |  IR: 0",
    "Overheat Temp: 372K",
    "Max Distortion: 1,800",
)


def _eclipse(desc_key: str = "", name_key: str = "", slots: int = 10) -> str:
    tags = "".join(f'<String value="Eclipse_Bomb_{i}"/>' for i in range(slots))
    return _entity(
        "BMBRCK_S03_AEGS_Eclipse",
        _attach(desc_key, name_key, Type="BombLauncher", SubType="BombRack", Size="3", Grade="1"),
        _health("1500"),
        _resources(em="0", ir="0"),
        '<SCItemMissileRackParams launchDelay="0.125">'
        f"<slotTags>{tags}</slotTags></SCItemMissileRackParams>",
    )


ECLIPSE = _lines("Size: S3", "Grade: 1", "Bomb Slots: 10", "Component HP: 1,500")


# ── The generators ───────────────────────────────────────────────────────────

class TestShield:
    def test_every_stat_line(self, gen):
        assert gen.enhancements_shield(_root(_veil())) == VEIL

    def test_an_energy_resistance_is_shown_beside_physical(self, gen):
        """No shield has one on LIVE today, but the line reads it: the
        lower bound first, both signed."""
        resists = (("0", "0.25"), ("-0.77", "-0.26")) + (("0", "0"),) * 4
        xml = _veil(resists=resists)
        lines = gen.enhancements_shield(_root(xml)).split("\\n")
        assert lines[2] == "Resist:  Phys: +0% – +25%  |  Energy: -77% – -26%"

    def test_resistances_of_zero_leave_the_line_out(self, gen):
        xml = _veil(resists=(("0", "0"),) * 6)
        assert "Resist" not in gen.enhancements_shield(_root(xml))

    def test_regen_without_max_hp_shows_a_question_mark(self, gen):
        xml = _veil(shield_attrs='MaxShieldRegen="449"')
        first = gen.enhancements_shield(_root(xml)).split("\\n")[0]
        assert first == "Max HP: ?  |  Regen: 449 HP/s"

    def test_one_delay_alone(self, gen):
        attrs = 'MaxShieldHealth="2244" MaxShieldRegen="449" DamagedRegenDelay="3.18"'
        xml = _veil(shield_attrs=attrs)
        assert gen.enhancements_shield(_root(xml)).split("\\n")[1] == "Damaged Delay: 3.2s"

    def test_without_shield_params_it_writes_nothing(self, gen):
        """The power, health and signatures are not enough on their own."""
        xml = _veil().replace("SCItemShieldGeneratorParams", "SCItemSomethingElseParams")
        assert gen.enhancements_shield(_root(xml)) == ""


class TestRadar:
    def test_every_stat_line(self, gen):
        """The Hunter's 1028.5 m maximum shows as 1,028 (rounded half to
        even). Its distortion, signatures and overheat are not shown."""
        assert gen.enhancements_radar(_root(_hunter())) == HUNTER

    def test_a_passive_only_radar(self, gen):
        xml = _hunter(modes=(("1", "0"), ("0", "0")))
        assert "Detection Mode: Passive\\n" in gen.enhancements_radar(_root(xml))

    def test_no_detection_mode_leaves_the_line_out(self, gen):
        xml = _hunter(modes=(("0", "0"),))
        assert "Detection Mode" not in gen.enhancements_radar(_root(xml))

    def test_a_zero_range_and_an_empty_cooldown_leave_their_lines_out(self, gen):
        xml = _hunter(aim=("0", "0"), cooldown="")
        assert gen.enhancements_radar(_root(xml)) == _lines(
            "Detection Mode: Passive / Active", "Power Draw: 5 PU/s", "Component HP: 420")

    def test_nothing_it_reads_writes_nothing(self, gen):
        assert gen.enhancements_radar(_root(_entity("RADR_Empty", _attach()))) == ""


class TestCooler:
    def test_every_stat_line(self, gen):
        assert gen.enhancements_cooler(_root(_iceplunge())) == ICEPLUNGE

    def test_the_overheat_placeholder_leaves_the_line_out(self, gen):
        """450,000 K marks an item with no real overheat temperature."""
        assert "Overheat" not in gen.enhancements_cooler(_root(_iceplunge(overheat="450000")))
        below = gen.enhancements_cooler(_root(_iceplunge(overheat="449999")))
        assert "Overheat Temp: 449,999K" in below

    def test_one_signature_alone(self, gen):
        assert "\\nSignatures:  IR: 5,890\\n" in gen.enhancements_cooler(_root(_iceplunge(em=None)))

    def test_without_health_signatures_or_overheat(self, gen):
        xml = _iceplunge(overheat="", em=None, ir=None, hp=False)
        assert gen.enhancements_cooler(_root(xml)) == _lines(
            "Cooling Rate: 34 CR/s", "Power Draw: 2 PU/s")

    def test_nothing_it_reads_writes_nothing(self, gen):
        assert gen.enhancements_cooler(_root(_entity("COOL_Empty", _attach()))) == ""


class TestPowerPlant:
    def test_every_stat_line(self, gen):
        """Its output is the Power it generates, not the Coolant it uses."""
        assert gen.enhancements_powerplant(_root(_lumacore())) == LUMACORE

    def test_the_overheat_placeholder_leaves_the_line_out(self, gen):
        assert "Overheat" not in gen.enhancements_powerplant(_root(_lumacore(overheat="450000")))

    def test_nothing_it_reads_writes_nothing(self, gen):
        assert gen.enhancements_powerplant(_root(_entity("POWR_Empty", _attach()))) == ""


class TestQuantumDrive:
    def test_every_stat_line(self, gen):
        assert gen.enhancements_quantum_drive(_root(_foxfire())) == FOXFIRE

    @pytest.mark.parametrize("spool, shown",
                             [("4.8", "4.8s"), ("5.3", "5.3s"), ("8.5", "8.5s"), ("4", "4.0s")])
    def test_spool_shows_tenths(self, gen, spool, shown):
        """Whole seconds showed 4.8 and 5.3 both as "5s", and 8.5 as "8s"
        (#485); spool times on LIVE run 3.6 to 10.1 in tenths."""
        first = gen.enhancements_quantum_drive(_root(_foxfire(spoolUpTime=spool))).split("\\n")[0]
        assert first == f"QT Speed: 263 Mm/s  |  Spool: {shown}"

    @pytest.mark.parametrize("form", ["__type", "tag"])
    def test_the_older_typed_params_are_read(self, gen, form):
        """Before the 4.x rework the drive parameters were typed: a
        ``__type`` marker, or in some unforge builds the type name as the
        element. Only the typed lookup finds the second."""
        assert gen.enhancements_quantum_drive(_root(_foxfire(form=form))) == FOXFIRE

    def test_without_spool_shows_a_question_mark(self, gen):
        first = gen.enhancements_quantum_drive(_root(_foxfire(spoolUpTime=None))).split("\\n")[0]
        assert first == "QT Speed: 263 Mm/s  |  Spool: ?"

    def test_calibration_without_its_range_shows_question_marks(self, gen):
        xml = _foxfire(minCalibrationRequirement=None, maxCalibrationRequirement=None)
        text = gen.enhancements_quantum_drive(_root(xml))
        assert "\\nCal Rate: 1,000  |  Required: ?–?\\n" in text

    def test_one_acceleration_alone(self, gen):
        xml = _foxfire(stageTwoAccelRate=None)
        assert "\\nAccel:  S1: 10,848,920\\n" in gen.enhancements_quantum_drive(_root(xml))

    def test_without_drive_parameters_only_the_rest_is_written(self, gen):
        """No speed, spool, cooldown, acceleration or calibration lines."""
        xml = _foxfire(**{k: None for k in _FOXFIRE_PARAMS})
        lines = FOXFIRE.split("\\n")
        assert gen.enhancements_quantum_drive(_root(xml)) == _lines(*lines[2:4], *lines[6:])

    def test_without_quantum_drive_params_it_writes_nothing(self, gen):
        xml = _foxfire().replace("SCItemQuantumDriveParams", "SCItemSomethingElseParams")
        assert gen.enhancements_quantum_drive(_root(xml)) == ""


class TestBombRack:
    def test_every_stat_line(self, gen):
        assert gen.enhancements_bomb_rack(_root(_eclipse())) == ECLIPSE

    def test_no_slots_leaves_the_line_out(self, gen):
        assert gen.enhancements_bomb_rack(_root(_eclipse(slots=0))) == _lines(
            "Size: S3", "Grade: 1", "Component HP: 1,500")

    def test_without_attach_def_it_writes_nothing(self, gen):
        xml = _eclipse().replace("AttachDef", "AttachSomethingElse")
        assert gen.enhancements_bomb_rack(_root(xml)) == ""


# ── The components run ───────────────────────────────────────────────────────

# Each folder _run_gen_components reads, the XML put there, the description
# key it carries, its stock text in base.ini and the stats it should get.
_FOLDERS = {
    "shieldgenerator":  (_veil, "item_Desc_SHLD_ASAS_S01_Veil", "Veil shield.", VEIL),
    "radar":            (_hunter, "item_Desc_RADR_BLTR_S01_Hunter", "Hunter radar.", HUNTER),
    "cooler":           (_iceplunge, "item_DescCOOL_ACOM_S01_IcePlunge", "IcePlunge cooler.",
                         ICEPLUNGE),
    "powerplant":       (_lumacore, "item_Desc_POWR_ACOM_S01_LumaCore", "LumaCore power plant.",
                         LUMACORE),
    "quantumdrive":     (_foxfire, "item_Desc_QRDV_ACAS_S01_Foxfire", "FoxFire quantum drive.",
                         FOXFIRE),
    "bombcompartments": (_eclipse, "item_DescAEGS_Eclipse_BombRack_S03", "Eclipse bomb rack.",
                         ECLIPSE),
}


def _components_ctx(tmp_path: Path, folders=_FOLDERS, prepend: bool = False,
                    names: dict | None = None) -> dict:
    """The part of ``main()``'s context ``_run_gen_components`` reads, with
    one real-shape XML in each component folder of a records tree. *names*
    (folder: name key, name, description) adds each item's name key and
    replaces its description."""
    records = tmp_path / "raw" / "libs" / "foundry" / "records"
    ships = records / "entities" / "scitem" / "ships"
    loc = {}
    for folder, (make, key, stock, _stats) in folders.items():
        name_key, name, desc = (names or {}).get(folder, ("", "", stock))
        (ships / folder).mkdir(parents=True)
        xml_file = ships / folder / f"{key.lower()}.xml"
        xml_file.write_text(make(key, name_key=name_key), encoding="utf-8")
        loc[key] = desc
        if name_key:
            loc[name_key] = name
    return {"loc": loc, "tag_loc": loc, "ships_scitem": ships, "records": records,
            "xml_path_index": None, "tag_configs": {}, "stats_prepend": prepend}


class TestTheComponentsRun:
    def test_each_folder_goes_through_its_own_generator(self, gen, tmp_path):
        out = gen._run_gen_components(_components_ctx(tmp_path))
        assert out == {key: stock + gen.ENHANCEMENT_SEPARATOR + stats
                       for _make, key, stock, stats in _FOLDERS.values()}

    def test_stats_go_first_when_asked(self, gen, tmp_path):
        """#153's stats-first option reaches the components too."""
        out = gen._run_gen_components(_components_ctx(tmp_path, prepend=True))
        _make, key, stock, stats = _FOLDERS["cooler"]
        assert out[key] == stats + gen.STATS_PREPEND_SEPARATOR + stock

    def test_each_folders_items_are_tagged_with_its_own_type(self, gen, tmp_path):
        """With the Tag Builder's Type element on, an item's name tag ends in
        the type of the folder it was found in (``_SUBDIR_TO_TYPE``), and a
        bomb rack, which has none, gets no type. The descriptions carry no
        Item Type line, so the type can only come from the folder. The name
        keys are the real ones, CIG's spellings included."""
        from src.utils.tag_builder import (
            DEFAULT_COMPONENT_CLASS_MAPPING, DEFAULT_COMPONENT_TYPE_MAPPING, ElementSpec, TagConfig,
        )
        config = TagConfig(
            elements=[ElementSpec("class", True, "med"), ElementSpec("size", True, "sn"),
                      ElementSpec("grade", True, "letter"), ElementSpec("type", True, "short")],
            separator="hyphen", enclosing="square",
            class_mapping={**DEFAULT_COMPONENT_CLASS_MAPPING, **DEFAULT_COMPONENT_TYPE_MAPPING},
        )

        def desc(size: str, grade: str) -> str:
            return f"Size: {size}\\nGrade: {grade}\\nClass: Military\\n\\nStock text."

        names = {
            "shieldgenerator":  ("item_NameSHLD_ASAS_S01_Veil", "Veil", desc("1", "B")),
            "radar":            ("item_Name_RADR_BLTR_S01_Hunter", "Hunter", desc("1", "B")),
            "cooler":           ("item_NameCOOL_ACOM_S01_IcePlunge", "IcePlunge", desc("1", "C")),
            "powerplant":       ("item_Name_POWR_ACOM_S01_LumaCore", "LumaCore", desc("1", "A")),
            "quantumdrive":     ("item_Name_QRDV_ACAS_S01_Foxfire", "FoxFire", desc("1", "B")),
            "bombcompartments": ("item_NameAEGS_Eclipse_BombRack_S03", "Eclipse Bomb Rack",
                                 desc("3", "A")),
        }
        ctx = _components_ctx(tmp_path, names=names)
        ctx["tag_configs"] = {"components": config}

        out = gen._run_gen_components(ctx)

        assert {k: v for k, v in out.items() if k.startswith("item_Name")} == {
            "item_NameSHLD_ASAS_S01_Veil": "[MIL-S1-B-SH] Veil",
            "item_Name_RADR_BLTR_S01_Hunter": "[MIL-S1-B-RD] Hunter",
            "item_NameCOOL_ACOM_S01_IcePlunge": "[MIL-S1-C-CL] IcePlunge",
            "item_Name_POWR_ACOM_S01_LumaCore": "[MIL-S1-A-PW] LumaCore",
            "item_Name_QRDV_ACAS_S01_Foxfire": "[MIL-S1-B-QD] FoxFire",
            "item_NameAEGS_Eclipse_BombRack_S03": "[MIL-S3-A] Eclipse Bomb Rack",
        }

    def test_without_a_radar_folder_the_rest_is_written(self, gen, tmp_path):
        folders = {k: v for k, v in _FOLDERS.items() if k != "radar"}
        out = gen._run_gen_components(_components_ctx(tmp_path, folders))
        assert set(out) == {key for _make, key, _stock, _stats in folders.values()}

    def test_a_drive_it_cannot_read_is_left_out_with_a_warning(self, gen, tmp_path, caplog):
        """A drive speed that is not a number stops that drive's stats, not
        the run: the drive keeps its stock text (it is not written) and the
        other components are."""
        folders = dict(_FOLDERS)
        _make, key, stock, stats = folders["quantumdrive"]

        def unreadable(k, **kw):
            return _foxfire(k, driveSpeed="fast", **kw)

        folders["quantumdrive"] = (unreadable, key, stock, stats)
        with caplog.at_level(logging.WARNING):
            out = gen._run_gen_components(_components_ctx(tmp_path, folders))
        assert key not in out
        assert set(out) == {k for f, (_m, k, _s, _st) in _FOLDERS.items() if f != "quantumdrive"}
        assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
            f"Enhancements failed for {key.lower()}.xml: could not convert string to float: 'fast'"]
