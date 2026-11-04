"""Tests for the status classifier in src.parser.ini_parser.

Status semantics:
- "Modified" — user explicitly set a custom_value
- "Enhanced" — value came from Smart Citizen's enhancements pipeline
- "Unmodified" — value is the stock base.ini text, unchanged
- "New" — key only exists in user / enhancements (not in base merged)

The "Enhanced" bucket is the new one — pre-1.3.0 these entries showed
as "Modified" because the source-origin-based path returned "Modified"
for any non-base, non-user source. Distinguishing them lets users see
at a glance what they changed vs. what the app generated.
"""
from __future__ import annotations

import pytest

from src.parser.ini_parser import _determine_status_from_source

pytestmark = pytest.mark.unit


class TestDetermineStatusFromSource:
    # ── key in base (key_in_base=True) ────────────────────────────────────

    def test_user_source_is_modified(self):
        assert _determine_status_from_source("user", "global", key_in_base=True) == "Modified"

    def test_enhancements_source_is_enhanced(self):
        """The new branch — enhancements pipeline output gets its own
        bucket so users can distinguish their own edits from generated
        content in the Status column."""
        assert _determine_status_from_source("enhancements", "global", key_in_base=True) == "Enhanced"

    def test_base_source_is_unmodified(self):
        assert _determine_status_from_source("global", "global", key_in_base=True) == "Unmodified"

    def test_base_source_with_custom_base_name(self):
        """``base_source`` is parameterised — confirm the rule is "source
        equals base_source", not "source is literally global"."""
        assert _determine_status_from_source("custom_base", "custom_base", key_in_base=True) == "Unmodified"

    def test_other_higher_priority_source_is_modified(self):
        """Generic fallback: any non-base, non-user, non-enhancements
        source still returns Modified. Rare post-1.0 (the four URL-based
        sources retired in 0.7.0) but kept as the safe default for any
        future custom source name."""
        assert _determine_status_from_source("contracts", "global", key_in_base=True) == "Modified"
        assert _determine_status_from_source("ships", "global", key_in_base=True) == "Modified"

    def test_enhancements_takes_precedence_over_modified_fallback(self):
        """Regression guard: if the function order changes so the generic
        Modified-fallback runs before the enhancements check, this
        catches it."""
        result = _determine_status_from_source("enhancements", "global", key_in_base=True)
        assert result == "Enhanced", (
            "enhancements check must run before the catch-all 'Modified' "
            "branch, otherwise the new bucket silently empties out"
        )

    # ── key not in base (key_in_base=False) ───────────────────────────────

    def test_user_source_not_in_base_is_new(self):
        """User added a key that doesn't exist in any base source."""
        assert _determine_status_from_source("user", "global", key_in_base=False) == "New"

    def test_enhancements_source_not_in_base_is_new(self):
        """Enhancement pipeline discovered a key from XML that base.ini
        doesn't have — should show as 'New', not 'Enhanced'."""
        assert _determine_status_from_source("enhancements", "global", key_in_base=False) == "New"

    def test_base_source_not_in_base_is_new(self):
        """Edge case: base source claims it but the key isn't in the
        merged base (e.g. a filtered-out duplicate). Still 'New'."""
        assert _determine_status_from_source("global", "global", key_in_base=False) == "New"

    def test_other_source_not_in_base_is_new(self):
        """Any source when the key is absent from base is 'New'."""
        assert _determine_status_from_source("contracts", "global", key_in_base=False) == "New"

    # ── key in merged base but not in global source ──────────────────────

    def test_enhancements_only_in_global_source_false_is_new(self):
        """Key merged in from enhancements but absent from the stock
        base source (base.ini) — XML-discovered item."""
        assert _determine_status_from_source(
            "enhancements", "global",
            key_in_base=True, in_global_source=False,
        ) == "New"

    def test_enhancements_in_global_source_true_is_enhanced(self):
        """Key exists in both stock base and enhancements — the
        enhancement pipeline augmented an existing entry."""
        assert _determine_status_from_source(
            "enhancements", "global",
            key_in_base=True, in_global_source=True,
        ) == "Enhanced"
