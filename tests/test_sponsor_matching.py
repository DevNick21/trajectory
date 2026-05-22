"""Unit tests for sponsor-register multi-signal matching.

Covers the six optimisations layered onto the legacy WRatio-only path:
  1. query-side alias expansion
  2. block-then-score (covered via the end-to-end lookup hitting an
     injected index)
  3. discriminator-token veto
  4. multi-scorer ensemble
  5. (Splink rescoring exercised only through its disabled-path fallback —
     enabling it requires the trained artifact, which is an offline output)
  6. top-K alternatives surfaced on SponsorStatus

Uses a synthetic DataFrame injected via `_reset_index_for_tests` so the
test suite stays parquet-free and deterministic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from askpicky.sub_agents import sponsor_register as sr


@pytest.fixture
def synthetic_index():
    """A 10-row register slice covering the failure modes we care about."""
    df = pd.DataFrame(
        {
            "Organisation Name": [
                "Octopus Energy Limited",
                "New Wave Capital Ltd t/a Capital on Tap",
                "Aaron Wise Limited",
                "Wise Payments Ltd",
                "Solar Park 4 Ltd",
                "Solar Park 18 Ltd",
                "EDF Energy Renewables Limited",
                "ABC International Holdings Plc",
                "Monzo Bank Ltd",
                "North Thames Water Plc",
            ],
            "Type & Rating": [
                "Worker (A rating)",
                "Worker (A rating)",
                "Worker (B rating)",
                "Worker (A rating)",
                "Worker (A rating)",
                "Worker (A rating)",
                "Worker (A (Premium))",
                "Worker (A rating)",
                "Worker (A rating)",
                "Worker (A rating)",
            ],
            "Route": ["Skilled Worker"] * 10,
        }
    )
    idx = sr._build_index_from_df(df)
    sr._reset_index_for_tests(idx)
    yield idx
    sr._reset_index_for_tests(None)


# ---------------------------------------------------------------------------
# Step 1 — query-side alias expansion
# ---------------------------------------------------------------------------


def test_expand_aliases_strips_legal_suffix():
    aliases = sr._expand_query_aliases("Octopus Energy Limited")
    assert "octopus energy limited" in aliases
    assert "octopus energy" in aliases


def test_expand_aliases_handles_trading_as_split():
    aliases = sr._expand_query_aliases("New Wave Capital Ltd t/a Capital on Tap")
    assert any("capital on tap" in a for a in aliases)


def test_expand_aliases_swaps_abbreviation_both_directions():
    aliases = sr._expand_query_aliases("ABC Intl Holdings")
    assert any("international" in a for a in aliases)

    aliases2 = sr._expand_query_aliases("ABC International Holdings")
    assert any("intl" in a.split() for a in aliases2)


def test_expand_aliases_swaps_ampersand_and_word():
    aliases = sr._expand_query_aliases("B & Q")
    assert any(" and " in a for a in aliases)


def test_expand_aliases_empty_input():
    assert sr._expand_query_aliases("") == []
    assert sr._expand_query_aliases("   ") == []


# ---------------------------------------------------------------------------
# Step 3 — discriminator-token veto
# ---------------------------------------------------------------------------


def test_discriminator_blocks_sibling_numeric_spvs():
    assert sr._discriminator_blocks_match("Solar Park 4", "Solar Park 18") is True


def test_discriminator_blocks_cardinal_directions():
    assert sr._discriminator_blocks_match("North Thames Water", "South Thames Water") is True


def test_discriminator_allows_legal_suffix_difference():
    assert (
        sr._discriminator_blocks_match("Octopus Energy", "Octopus Energy Limited")
        is False
    )


def test_discriminator_allows_word_token_difference():
    assert (
        sr._discriminator_blocks_match("EDF Renewables", "EDF Energy Renewables")
        is False
    )


def test_discriminator_allows_identical_after_normalisation():
    assert sr._discriminator_blocks_match("Monzo Bank", "monzo bank ltd") is False


# ---------------------------------------------------------------------------
# Step 4 — multi-scorer ensemble
# ---------------------------------------------------------------------------


def test_ensemble_high_for_suffix_only_difference():
    score, _ = sr._ensemble_score("octopus energy", "octopus energy limited")
    assert score >= 92


def test_ensemble_rejects_substring_only_short_query():
    """The failure mode the existing docstring flags: 'Wise' inside
    'Aaron Wise Limited' is a high partial_ratio false positive.
    token_sort_ratio drags the combined score below threshold."""
    score, breakdown = sr._ensemble_score("wise", "aaron wise limited")
    assert breakdown["partial"] >= 90  # confirms the failure mode exists
    assert score < 92


def test_ensemble_breakdown_keys():
    _, breakdown = sr._ensemble_score("foo ltd", "foo limited")
    assert set(breakdown) == {"wratio", "token_sort", "partial"}


# ---------------------------------------------------------------------------
# End-to-end — lookup with the synthetic index (covers steps 1, 2, 4, 6)
# ---------------------------------------------------------------------------


def test_lookup_finds_exact_match(synthetic_index):
    status = sr._lookup_sync("Octopus Energy Limited")
    assert status.status == "LISTED"
    assert status.matched_name == "Octopus Energy Limited"


def test_lookup_finds_suffix_stripped_match(synthetic_index):
    status = sr._lookup_sync("Octopus Energy")
    assert status.status == "LISTED"
    assert status.matched_name == "Octopus Energy Limited"


def test_lookup_finds_trade_name_inside_legal_entity(synthetic_index):
    status = sr._lookup_sync("Capital on Tap")
    assert status.status == "LISTED"
    assert "Capital on Tap" in status.matched_name


def test_lookup_returns_not_listed_for_unknown_company(synthetic_index):
    status = sr._lookup_sync("Some Company That Does Not Exist 9999")
    assert status.status == "NOT_LISTED"
    assert status.matched_name is None


def test_lookup_rejects_short_substring_false_positive(synthetic_index):
    """'Wise' should not resolve to 'Aaron Wise Limited' even though
    partial_ratio is 100. The ensemble + discriminator combination
    catches this."""
    status = sr._lookup_sync("Wise")
    # The match must not be 'Aaron Wise Limited' — either NOT_LISTED
    # or a different higher-scoring row (Wise Payments Ltd).
    assert status.matched_name != "Aaron Wise Limited"


def test_lookup_blocks_sibling_spvs_via_discriminator(synthetic_index):
    """A query for 'Solar Park 18' must not resolve to 'Solar Park 4'
    even if both have very high WRatio. The veto protects siblings."""
    status = sr._lookup_sync("Solar Park 18")
    assert status.matched_name == "Solar Park 18 Ltd"


def test_lookup_maps_b_rated(synthetic_index):
    status = sr._lookup_sync("Aaron Wise Limited")
    assert status.status == "B_RATED"


# ---------------------------------------------------------------------------
# Step 6 — top-K alternatives
# ---------------------------------------------------------------------------


def test_lookup_populates_alternative_matches_when_scores_cluster():
    """Two register rows that reduce to the same suffix-stripped form
    both score above threshold for the bare-brand query. Primary on
    `matched_name`, runner-up on `alternative_matches`.

    Real-world shape: a brand registered as both a Limited and a Plc
    (or trading entity + holding company), both legitimate sponsors,
    both equally plausible matches for the careers-page name.
    """
    df = pd.DataFrame(
        {
            "Organisation Name": [
                "Acme Group Limited",
                "Acme Group Plc",
                "Unrelated Company Ltd",
            ],
            "Type & Rating": ["Worker (A rating)"] * 3,
            "Route": ["Skilled Worker"] * 3,
        }
    )
    sr._reset_index_for_tests(sr._build_index_from_df(df))
    try:
        status = sr._lookup_sync("Acme Group")
        assert status.status == "LISTED"
        assert status.matched_name.startswith("Acme Group")
        assert len(status.alternative_matches) >= 1
        # Primary and alternatives must be distinct rows.
        assert all(
            alt.matched_name != status.matched_name
            for alt in status.alternative_matches
        )
        # Both surviving matches are real Acme Group rows, not the unrelated one.
        all_names = [status.matched_name] + [
            alt.matched_name for alt in status.alternative_matches
        ]
        assert all("Acme Group" in n for n in all_names)
    finally:
        sr._reset_index_for_tests(None)


def test_lookup_no_alternatives_when_only_one_match(synthetic_index):
    status = sr._lookup_sync("Monzo Bank Ltd")
    assert status.status == "LISTED"
    assert status.alternative_matches == []


# ---------------------------------------------------------------------------
# Step 5 — Splink path falls back cleanly when disabled
# ---------------------------------------------------------------------------


def test_splink_rescore_returns_empty_when_flag_off(synthetic_index, monkeypatch):
    monkeypatch.setattr(sr.settings, "enable_splink_sponsor_match", False, raising=False)
    out = sr._splink_rescore("octopus energy", [0, 1], synthetic_index)
    assert out == {}


def test_splink_rescore_returns_empty_when_artifact_missing(
    synthetic_index, monkeypatch, tmp_path
):
    monkeypatch.setattr(sr.settings, "enable_splink_sponsor_match", True, raising=False)
    monkeypatch.setattr(sr, "_splink_model_path", lambda: tmp_path / "missing.json")
    sr._splink_linker = None
    out = sr._splink_rescore("octopus energy", [0, 1], synthetic_index)
    assert out == {}
