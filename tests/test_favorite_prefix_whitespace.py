"""Regression tests for the space favourite-prefix round-trip (issue #100).

A favourite is encoded by prepending a configurable prefix to the ship's
custom value, and the prefix may be a single space (the "invisible"
sort-to-top marker offered in the Enhancements tab). That value is stored
verbatim in user.ini, e.g. ``vehicle_NameARGO_Mole= Argo MOLE``.

The bug: parse_ini_file used to ``value.strip()`` on every load, so the
leading-space prefix was silently deleted when user.ini was read back,
and the ship showed as "modified" but not favourited. The fix gives
parse_ini_file a ``strip_values`` flag and reads user.ini with it False.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser.ini_parser import load_overrides, parse_ini_file  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

SPACE = " "


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_default_strips_values(tmp_path):
    p = _write(tmp_path / "base.ini", "k=  padded value  \n")
    assert parse_ini_file(p)["k"] == "padded value"


def test_strip_values_false_preserves_leading_space(tmp_path):
    p = _write(tmp_path / "user.ini", "vehicle_NameARGO_Mole= Argo MOLE\n")
    value = parse_ini_file(p, strip_values=False)["vehicle_NameARGO_Mole"]
    assert value == " Argo MOLE"
    assert value.startswith(SPACE)  # favourite detection would fire


def test_load_overrides_preserves_space_prefix(tmp_path):
    """load_overrides is the user.ini reader; it must keep the space prefix."""
    _write(
        tmp_path / "user.ini",
        "vehicle_NameARGO_Mole= Argo MOLE\n"
        "vehicle_NameRSI_Perseus= RSI Perseus\n",
    )
    overrides = load_overrides(tmp_path / "user.ini")
    assert overrides["vehicle_NameARGO_Mole"] == " Argo MOLE"
    # The whole point: a space-prefixed value is still recognised as a favourite.
    assert all(v.startswith(SPACE) for v in overrides.values())


def test_visible_prefix_unaffected(tmp_path):
    """A '*' prefix worked before and still works (no whitespace to strip)."""
    _write(tmp_path / "user.ini", "vehicle_NameARGO_Mole=*Argo MOLE\n")
    overrides = load_overrides(tmp_path / "user.ini")
    assert overrides["vehicle_NameARGO_Mole"] == "*Argo MOLE"
