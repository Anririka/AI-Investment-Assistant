"""outcome_analyzer.pyのテスト（layer8_self_evaluation_design.md §7-1、§11テスト方針）。"""

import pytest

from ai_investment_assistant.layer8_self_evaluation.outcome_analyzer import (
    build_evaluation_entry,
    classify_outcome,
    compute_overall_stats,
    compute_pnl_amount,
    compute_profit_factor,
)


def test_classify_outcome_positive_return_is_win():
    assert classify_outcome(15.0) == "win"


def test_classify_outcome_zero_return_is_loss():
    # final_return_pct <= 0 は loss（境界値）
    assert classify_outcome(0.0) == "loss"


def test_classify_outcome_negative_return_is_loss():
    assert classify_outcome(-10.0) == "loss"


def test_compute_pnl_amount():
    assert compute_pnl_amount(entry_price=100.0, exit_price=115.0, recommended_shares=4) == 60.0


def _closed_position(**overrides):
    base = {
        "tracking_id": "TRK-1", "run_id": "20260718-0630", "ticker": "NVDA",
        "entry_price": 333.74, "exit_price": 383.80, "recommended_shares": 4,
        "holding_days": 18, "exit_reason": "take_profit", "final_return_pct": 15.0,
        "max_unrealized_gain_pct": 16.2, "max_unrealized_loss_pct": -1.1,
    }
    base.update(overrides)
    return base


def _sheet_row(**overrides):
    base = {
        "証券コード": "NVDA", "資産クラス": "us_equity",
        "テクニカルスコア": 84, "ファンダメンタルスコア": 71, "需給スコア": 78,
        "マクロスコア": 65, "ニューススコア": 63, "ニュース不確実性": 35,
        "レジーム適合スコア": 90, "総合スコア": 79,
        "投資理由": "TECH_MA_PERFECT_ORDER_UP による良好なテクニカル。", "リスク要因": "競合激化",
    }
    base.update(overrides)
    return base


def test_build_evaluation_entry_with_score_context_available():
    evaluation = build_evaluation_entry(_closed_position(), [_sheet_row()])
    assert evaluation["outcome"] == "win"
    assert evaluation["pnl_amount"] == pytest.approx((383.80 - 333.74) * 4)
    assert evaluation["score_context_available"] is True
    assert evaluation["score_summary"]["composite"] == 79
    assert evaluation["extracted_reason_codes"] == ["TECH_MA_PERFECT_ORDER_UP"]
    assert evaluation["asset_class"] == "us_equity"


def test_build_evaluation_entry_without_score_context():
    evaluation = build_evaluation_entry(_closed_position(), None)
    assert evaluation["score_context_available"] is False
    assert evaluation["score_summary"] is None
    assert evaluation["extracted_reason_codes"] == []
    assert evaluation["reason_code_extraction_status"] == "no_match"
    assert evaluation["asset_class"] is None


def test_build_evaluation_entry_score_context_ticker_mismatch_treated_as_unavailable():
    evaluation = build_evaluation_entry(_closed_position(ticker="AMD"), [_sheet_row()])
    assert evaluation["score_context_available"] is False


def test_compute_profit_factor_normal_case():
    evaluations = [{"pnl_amount": 100.0}, {"pnl_amount": -50.0}]
    value, note = compute_profit_factor(evaluations)
    assert value == 2.0
    assert note is None


def test_compute_profit_factor_all_wins_returns_null_with_note():
    evaluations = [{"pnl_amount": 100.0}, {"pnl_amount": 50.0}]
    value, note = compute_profit_factor(evaluations)
    assert value is None
    assert "全勝" in note


def test_compute_profit_factor_all_losses_returns_zero():
    evaluations = [{"pnl_amount": -100.0}, {"pnl_amount": -50.0}]
    value, note = compute_profit_factor(evaluations)
    assert value == 0.0
    assert note is None


def test_compute_profit_factor_no_closed_positions_returns_null_with_note():
    value, note = compute_profit_factor([])
    assert value is None
    assert "クローズ済みポジションが無い" in note


def test_compute_overall_stats_empty_list():
    stats = compute_overall_stats([])
    assert stats["win_rate"] is None
    assert stats["profit_factor"] is None


def test_compute_overall_stats_mixed_outcomes():
    evaluations = [
        {"outcome": "win", "final_return_pct": 15.0, "pnl_amount": 200.0, "exit_reason": "take_profit"},
        {"outcome": "loss", "final_return_pct": -10.0, "pnl_amount": -100.0, "exit_reason": "stop_loss"},
        {"outcome": "win", "final_return_pct": 5.0, "pnl_amount": 50.0, "exit_reason": "holding_period_expired"},
    ]
    stats = compute_overall_stats(evaluations)
    assert stats["win_rate"] == pytest.approx(2 / 3)
    assert stats["avg_win_pct"] == pytest.approx((15.0 + 5.0) / 2)
    assert stats["avg_loss_pct"] == -10.0
    assert stats["take_profit_rate"] == pytest.approx(1 / 3)
    assert stats["stop_loss_rate"] == pytest.approx(1 / 3)
    assert stats["profit_factor"] == pytest.approx(250.0 / 100.0)
