"""position_sizer.pyのテスト（layer5_ai_judgment_design.md §8、§12テスト方針）。"""

import pytest

from ai_investment_assistant.layer5_ai_judgment.scripts.position_sizer import (
    allocate_positions,
    resolve_take_profit_target_pct,
    size_position,
)

TP_POLICY = {"min_pct": 5, "max_pct": 50, "default_pct": 15}


def test_resolve_take_profit_within_range_is_unchanged():
    pct, log = resolve_take_profit_target_pct(15.0, TP_POLICY)
    assert pct == 15.0
    assert log is None


def test_resolve_take_profit_above_max_clamps_and_logs():
    pct, log = resolve_take_profit_target_pct(60, TP_POLICY)
    assert pct == 50
    assert log["applied"] is True
    assert log["rule"] == "take_profit_target_pct_out_of_range"


def test_resolve_take_profit_below_min_clamps_and_logs():
    pct, log = resolve_take_profit_target_pct(2, TP_POLICY)
    assert pct == 5


def test_resolve_take_profit_missing_uses_default_and_logs():
    pct, log = resolve_take_profit_target_pct(None, TP_POLICY)
    assert pct == 15
    assert log["rule"] == "take_profit_target_pct_missing_or_invalid"


def _candidate(**overrides):
    base = {
        "ticker": "NVDA", "asset_class": "us_equity", "entry_price_basis": 333.74,
        "take_profit_target_pct": 15.0,
    }
    base.update(overrides)
    return base


def test_size_position_us_equity_floors_to_integer_shares():
    result = size_position(_candidate(), available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY)
    # 33% cap = 990000; 990000/333.74 ≈ 2966.6 shares by cap; also limited by available_capital
    assert result["excluded"] is False
    assert isinstance(result["recommended_shares"], int)
    assert result["recommended_shares"] == int(990000 // 333.74)


def test_size_position_japan_equity_floors_to_100_share_lots():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY)
    assert result["recommended_shares"] % 100 == 0


def test_size_position_stop_loss_and_take_profit_prices():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=15.0)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY)
    assert result["stop_loss_price"] == pytest.approx(2500 * 0.9)
    assert result["take_profit_price"] == pytest.approx(2500 * 1.15)


def test_size_position_zero_shares_when_price_exceeds_available_capital():
    candidate = _candidate(entry_price_basis=1000000)
    result = size_position(candidate, available_capital=500000, total_capital=3000000,
                            take_profit_policy=TP_POLICY)
    assert result["excluded"] is True
    assert result["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"


def test_size_position_zero_shares_when_per_position_cap_too_small_for_japan_lot():
    # total_capital=250000 (test phase) -> 33% cap = 82500円。2500円株で100株単位だと
    # 250000円必要になり上限を超えるため0株になる。
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500)
    result = size_position(candidate, available_capital=250000, total_capital=250000,
                            take_profit_policy=TP_POLICY)
    assert result["excluded"] is True
    assert result["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"


def test_size_position_applies_out_of_range_take_profit_and_logs_it():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=90)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY)
    assert result["take_profit_target_pct"] == 50
    assert len(result["rule_enforcement_log_entries"]) == 1


def test_allocate_positions_sequential_consumption_never_exceeds_total_capital():
    candidates = [
        _candidate(ticker="A", asset_class="us_equity", entry_price_basis=100),
        _candidate(ticker="B", asset_class="us_equity", entry_price_basis=200),
        _candidate(ticker="C", asset_class="us_equity", entry_price_basis=300),
    ]
    result = allocate_positions(candidates, available_capital=3000000, total_capital=3000000,
                                 take_profit_policy=TP_POLICY)
    total_spent = sum(p["position_amount"] for p in result["proposals"])
    assert total_spent <= 3000000
    assert len(result["proposals"]) == 3


def test_allocate_positions_zero_share_candidate_excluded_from_proposals_and_logged():
    candidates = [
        _candidate(ticker="EXPENSIVE", asset_class="us_equity", entry_price_basis=10_000_000),
        _candidate(ticker="CHEAP", asset_class="us_equity", entry_price_basis=100),
    ]
    result = allocate_positions(candidates, available_capital=3000000, total_capital=3000000,
                                 take_profit_policy=TP_POLICY)
    tickers_in_proposals = [p["ticker"] for p in result["proposals"]]
    assert "EXPENSIVE" not in tickers_in_proposals
    assert "CHEAP" in tickers_in_proposals
    not_selected = [d for d in result["decision_log_entries"] if d["ticker"] == "EXPENSIVE"]
    assert not_selected[0]["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"
    assert not_selected[0]["decision"] == "not_selected"
