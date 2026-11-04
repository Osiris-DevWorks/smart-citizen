"""Tests for ship sort-order prefix helpers (issue #142).

The order number rides in custom_value, zero-padded to two digits and followed
by a ``-`` separator, inserted after any favorite prefix. So a ship can be "*",
"01-", or "*01-" and the tokens always compose as ``{favorite}{order}-{name}`` —
never ``01*name`` and never chopping digits off a numeric ship name.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.utils.ship_sort_prefix import get_order, set_order  # noqa: E402

pytestmark = pytest.mark.unit

FAV = "*"


# ── get_order ────────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_no_prefix(self):
        assert get_order("Avenger", FAV) == ""

    def test_order_only(self):
        assert get_order("01-Avenger", FAV) == "01"

    def test_favorite_only(self):
        assert get_order("*Avenger", FAV) == ""

    def test_favorite_and_order(self):
        assert get_order("*01-Avenger", FAV) == "01"

    def test_single_digit_is_not_an_order(self):
        assert get_order("1-Avenger", FAV) == ""

    def test_two_digits_without_separator_is_not_an_order(self):
        # The separator is required: without it, leading digits are part of the
        # name (this is what makes numeric ship names safe).
        assert get_order("05Avenger", FAV) == ""

    def test_empty(self):
        assert get_order("", FAV) == ""

    def test_high_number(self):
        assert get_order("*99-Reclaimer", FAV) == "99"


# ── get_order: numeric ship names must NOT read as an order (issue #142) ──────

class TestGetOrderNumericShipNames:
    """Star Citizen ships whose display name starts with two digits must report
    no sort order — otherwise the # column shows a phantom number and editing it
    corrupts the name."""

    @pytest.mark.parametrize(
        "name",
        ["300i", "315p", "325a", "350r", "100i", "125a", "135c",
         "400i", "600i", "890 Jump", "990", "85X"],
    )
    def test_numeric_name_has_no_order(self, name):
        assert get_order(name, FAV) == ""

    @pytest.mark.parametrize("name", ["300i", "890 Jump", "100i", "85X", "990"])
    def test_favorited_numeric_name_has_no_order(self, name):
        assert get_order(FAV + name, FAV) == ""


# ── set_order: add / replace / clear ─────────────────────────────────────────

class TestSetOrder:
    def test_add_to_plain(self):
        # No custom value yet → order prepends to the stock name.
        assert set_order("", "Avenger", FAV, "05") == "05-Avenger"

    def test_add_to_existing_custom(self):
        assert set_order("Avenger Titan", "Avenger", FAV, "02") == "02-Avenger Titan"

    def test_replace_order(self):
        assert set_order("03-Avenger", "Avenger", FAV, "07") == "07-Avenger"

    def test_clear_order_collapses_to_empty(self):
        # Removing the only thing distinguishing it from stock → "".
        assert set_order("03-Avenger", "Avenger", FAV, "") == ""

    def test_clear_order_keeps_custom_name(self):
        assert set_order("03-Avenger Titan", "Avenger", FAV, "") == "Avenger Titan"


# ── set_order: numeric ship names are never corrupted (issue #142) ───────────

class TestSetOrderNumericShipNames:
    def test_clear_on_favorited_numeric_name_is_noop(self):
        # The regression: this used to return "*0i" (digits chopped).
        assert set_order("*300i", "300i", FAV, "") == "*300i"

    def test_clear_on_numeric_name_collapses_to_stock(self):
        assert set_order("300i", "300i", FAV, "") == ""

    def test_order_a_numeric_ship(self):
        assert set_order("300i", "300i", FAV, "05") == "05-300i"

    def test_order_a_favorited_numeric_ship(self):
        assert set_order("*300i", "300i", FAV, "05") == "*05-300i"

    def test_order_a_numeric_ship_with_space(self):
        assert set_order("890 Jump", "890 Jump", FAV, "03") == "03-890 Jump"

    def test_clear_order_on_numeric_ship_restores_name(self):
        # Round-trip: set an order, then clear it, name comes back intact.
        ordered = set_order("*300i", "300i", FAV, "05")
        assert ordered == "*05-300i"
        assert get_order(ordered, FAV) == "05"
        assert set_order(ordered, "300i", FAV, "") == "*300i"


# ── set_order: composition with the favorite prefix ──────────────────────────

class TestSetOrderWithFavorite:
    def test_order_lands_behind_favorite(self):
        # Favorite stays first; we must never produce "01*Avenger".
        assert set_order("*Avenger", "Avenger", FAV, "01") == "*01-Avenger"

    def test_replace_order_preserves_favorite(self):
        assert set_order("*01-Avenger", "Avenger", FAV, "08") == "*08-Avenger"

    def test_clear_order_preserves_favorite(self):
        assert set_order("*01-Avenger", "Avenger", FAV, "") == "*Avenger"

    def test_favorite_only_then_clear_order_is_noop(self):
        assert set_order("*Avenger", "Avenger", FAV, "") == "*Avenger"


# ── set_order: zero-padding normalization ────────────────────────────────────

class TestSetOrderPadding:
    def test_single_digit_input_is_padded(self):
        assert set_order("Avenger", "Avenger", FAV, "5") == "05-Avenger"

    def test_two_digit_input_unchanged(self):
        assert set_order("Avenger", "Avenger", FAV, "10") == "10-Avenger"
