"""Smart Citizen Overlay (SCO): mining scan signature decoding.

Locks the shared RS table in ``src/utils/mining_signatures.py`` and the
``decode_signature`` contract the overlay uses to turn a scanned number into
a deposit type and cluster size.
"""
import pytest

from src.utils.mining_signatures import (
    MINEABLE_RS_VALUES,
    ORE_SIGNATURES,
    OTHER_SIGNATURES,
    SignatureMatch,
    decode_signature,
    parse_signature_text,
)


class TestTable:
    def test_generator_view_matches_ore_bases(self):
        assert MINEABLE_RS_VALUES == {o: b for o, (b, _) in ORE_SIGNATURES.items()}

    def test_generator_imports_the_shared_table(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).parent.parent / "scripts" / "generate_enhancements_ini.py"
        spec = importlib.util.spec_from_file_location("gen_for_rs_check", path)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        assert gen.MINEABLE_RS_VALUES is MINEABLE_RS_VALUES

    def test_ship_ores_never_collide_within_their_caps(self):
        seen = {}
        for ore, (base, max_count) in ORE_SIGNATURES.items():
            for n in range(1, max_count + 1):
                assert base * n not in seen, (ore, n, seen.get(base * n))
                seen[base * n] = (ore, n)


class TestDecode:
    @pytest.mark.parametrize("value, expected", [
        (7200, [SignatureMatch("bexalite", 2)]),     # Amr's first screenshot
        (10200, [SignatureMatch("lindinium", 3)]),   # Amr's second screenshot
        (3170, [SignatureMatch("quantainium", 1)]),
        (25800, [SignatureMatch("ice", 6)]),
    ])
    def test_single_reading(self, value, expected):
        assert decode_signature(value) == expected

    def test_round_numbers_return_every_reading(self):
        assert decode_signature(12000) == [
            SignatureMatch("roc", 3),
            SignatureMatch("fps", 4),
            SignatureMatch("salvage", 6),
        ]

    def test_cap_rules_out_oversized_clusters(self):
        # 19200 is 6 x Savrillium on paper, but Savrillium tops out at 2.
        assert decode_signature(19200) == [SignatureMatch("aslarite", 5)]

    @pytest.mark.parametrize("value", [0, -3600, 1234, 3171])
    def test_no_match(self, value):
        assert decode_signature(value) == []

    def test_every_table_entry_decodes_at_every_count(self):
        for kind, (base, max_count) in {**ORE_SIGNATURES, **OTHER_SIGNATURES}.items():
            for n in range(1, max_count + 1):
                assert SignatureMatch(kind, n) in decode_signature(base * n)


class TestParseText:
    @pytest.mark.parametrize("text, expected", [
        ("7,200", 7200), ("10,200", 10200), (" 3170 ", 3170), ("10.200", 10200),
        ("", None), ("7,2O0", None), ("UNKNOWN", None),
    ])
    def test_parse(self, text, expected):
        assert parse_signature_text(text) == expected
