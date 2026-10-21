"""The generator parses every DataForge XML through one helper,
``_parse_xml_root``, which reads the bytes and parses them from memory: a
third faster than ``ET.parse`` on the path over the 24k scitem files (6.5 s
against 8.75 s on an NVMe machine), with the parse itself unchanged. This
locks that the helper behaves like the path form where the call sites care
(the same tree, lxml's ``ET.ParseError`` on malformed XML, ``OSError`` on a
missing file) and that no parse site has gone back to ``ET.parse``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "generate_enhancements_ini.py"
sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_parse_xml_root_test", _SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_returns_the_same_tree_as_parsing_the_path(gen, tmp_path):
    xml = tmp_path / "entity.xml"
    xml.write_bytes(
        b"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        b"<EntityClassDefinition.x __ref=\"u-1\" displayName=\"@item_Name_x\">\n"
        b"  <Components><SAttachableComponentParams size=\"2\"/></Components>\n"
        b"</EntityClassDefinition.x>\n"
    )
    root = gen._parse_xml_root(xml)
    assert ET.tostring(root) == ET.tostring(ET.parse(str(xml)).getroot())
    assert root.get("__ref") == "u-1"
    assert root.find(".//SAttachableComponentParams").get("size") == "2"


def test_malformed_xml_raises_the_parse_error_the_call_sites_catch(gen, tmp_path):
    xml = tmp_path / "bad.xml"
    xml.write_bytes(b"<Root><Child></Root>")
    with pytest.raises(ET.ParseError):
        gen._parse_xml_root(xml)


def test_a_missing_file_raises_oserror(gen, tmp_path):
    with pytest.raises(OSError):
        gen._parse_xml_root(tmp_path / "missing.xml")


def test_no_parse_site_calls_et_parse_on_a_path():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "ET.parse(" not in text, "parse DataForge XML through _parse_xml_root"
    assert text.count("_parse_xml_root(") >= 20
