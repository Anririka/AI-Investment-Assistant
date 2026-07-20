"""screener.pyのテスト（layer2_analysis_design.md §3-8）。"""

from ai_investment_assistant.layer2_analysis.screener import (
    compute_dividend_yield_percentiles,
    filter_universe,
)

UNIVERSE_CONFIG = {
    "japan_equity": {"min_market_cap": 100_000_000_000, "min_avg_volume": 500_000},
}


def test_delayed_candidate_is_excluded_with_correct_reason_code():
    candidates = [{"ticker": "6723", "asset_class": "japan_equity", "is_delayed": True, "market_cap": 1e12, "avg_volume": 1e6}]
    passed, excluded = filter_universe(candidates, UNIVERSE_CONFIG)
    assert passed == []
    assert excluded[0]["reason_code"] == "DATA_DELAYED_12W"


def test_market_cap_below_threshold_is_excluded():
    candidates = [{"ticker": "X", "asset_class": "japan_equity", "market_cap": 1e9, "avg_volume": 1e6}]
    passed, excluded = filter_universe(candidates, UNIVERSE_CONFIG)
    assert passed == []
    assert excluded[0]["reason_code"] == "MARKET_CAP_TOO_SMALL"


def test_volume_below_threshold_is_excluded():
    candidates = [{"ticker": "X", "asset_class": "japan_equity", "market_cap": 2e12, "avg_volume": 1000}]
    passed, excluded = filter_universe(candidates, UNIVERSE_CONFIG)
    assert passed == []
    assert excluded[0]["reason_code"] == "VOLUME_TOO_LOW"


def test_candidate_meeting_all_conditions_passes():
    candidates = [{"ticker": "7203", "asset_class": "japan_equity", "market_cap": 4e13, "avg_volume": 3e7}]
    passed, excluded = filter_universe(candidates, UNIVERSE_CONFIG)
    assert len(passed) == 1
    assert excluded == []


def test_dividend_yield_percentile_ranks_highest_near_one():
    candidates = [
        {"ticker": "A", "dividend_yield": 0.01},
        {"ticker": "B", "dividend_yield": 0.05},
        {"ticker": "C", "dividend_yield": 0.03},
    ]
    percentiles = compute_dividend_yield_percentiles(candidates)
    assert percentiles["B"] == 1.0
    assert percentiles["A"] < percentiles["C"] < percentiles["B"]


def test_zero_dividend_excluded_from_percentile_population():
    candidates = [{"ticker": "A", "dividend_yield": 0.0}, {"ticker": "B", "dividend_yield": 0.02}]
    percentiles = compute_dividend_yield_percentiles(candidates)
    assert "A" not in percentiles
    assert percentiles["B"] == 1.0
