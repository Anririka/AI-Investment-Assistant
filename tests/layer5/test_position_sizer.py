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
    # fx_rate_to_jpy=1.0で従来通りの整数株への切り下げ動作自体を確認する
    # （為替換算そのものは別のテストで検証する）。
    result = size_position(_candidate(), available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    # 33% cap = 990000; 990000/333.74 ≈ 2966.6 shares by cap; also limited by available_capital
    assert result["excluded"] is False
    assert isinstance(result["recommended_shares"], int)
    assert result["recommended_shares"] == int(990000 // 333.74)


def test_size_position_japan_equity_floors_to_100_share_lots():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["recommended_shares"] % 100 == 0


def test_size_position_stop_loss_and_take_profit_prices():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=15.0)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["stop_loss_price"] == pytest.approx(2500 * 0.9)
    assert result["take_profit_price"] == pytest.approx(2500 * 1.15)


def test_size_position_zero_shares_when_price_exceeds_available_capital():
    candidate = _candidate(entry_price_basis=1000000)
    result = size_position(candidate, available_capital=500000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["excluded"] is True
    assert result["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"


def test_size_position_zero_shares_when_per_position_cap_too_small_for_japan_lot():
    # total_capital=250000 (test phase) -> 33% cap = 82500円。2500円株で100株単位だと
    # 250000円必要になり上限を超えるため0株になる。
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500)
    result = size_position(candidate, available_capital=250000, total_capital=250000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["excluded"] is True
    assert result["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"


def test_size_position_applies_out_of_range_take_profit_and_logs_it():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=90)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["take_profit_target_pct"] == 50
    assert len(result["rule_enforcement_log_entries"]) == 1


# --- 為替換算（2026-07-24追加、重大バグ修正の回帰テスト） -----------------------------
#
# Layer5の初回実データ接続テストで、米国株の投資可能額判定に為替換算が一切
# 行われておらず、NVDA終値$208.76に対しtotal_capital=250,000円をそのまま適用し
# 「395株・82,460円」という、実際には1,200万円超（予算の約50倍）になる致命的な
# 提案が生成されていたことが判明した。以下はこの回帰を防ぐためのテスト。

def test_size_position_us_equity_applies_fx_conversion_for_budget_math():
    """1USD=150円のとき、$100の株を予算100,000円で買う場合、
    為替換算後の単価は15,000円になるため、上限株数は 100,000/15,000 ≈ 6株
    （fx_rate_to_jpy=1.0の場合の1000株とは全く異なる）。
    """
    candidate = _candidate(ticker="NVDA", asset_class="us_equity", entry_price_basis=100.0)
    result = size_position(
        candidate, available_capital=100_000, total_capital=100_000 / 0.33,
        take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0,
    )
    assert result["excluded"] is False
    assert result["recommended_shares"] == 6  # floor(100000 / (100*150)) = floor(6.67) = 6
    assert result["position_amount"] == pytest.approx(6 * 100.0 * 150.0)
    assert result["fx_rate_to_jpy"] == 150.0


def test_size_position_us_equity_stop_loss_and_take_profit_stay_in_native_currency():
    """損切/利確価格は円換算せず、実際の取引所の通貨（USD）のまま返すこと
    （注文は現地通貨建てで出すため）。
    """
    candidate = _candidate(ticker="NVDA", asset_class="us_equity", entry_price_basis=200.0, take_profit_target_pct=15.0)
    result = size_position(
        candidate, available_capital=10_000_000, total_capital=10_000_000,
        take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0,
    )
    assert result["stop_loss_price"] == pytest.approx(200.0 * 0.9)  # USD建てのまま、円換算しない
    assert result["take_profit_price"] == pytest.approx(200.0 * 1.15)  # USD建てのまま


def test_size_position_reproduces_and_fixes_reported_nvda_scale_bug():
    """2026-07-24に実際のLayer5実行で報告されたバグの再現・修正確認テスト：
    total_capital=250,000円（テスト運用額）・NVDA終値$208.76・33%上限のケースで、
    為替換算前は誤って「395株・82,460円」（実勢レートで1,200万円超）が算出されて
    いた。1USD=150円として正しく換算すると、円換算後の実質単価は31,314円になり、
    33%上限（82,500円）÷31,314円 ≈ 2株程度まで正しく絞り込まれること（395株には
    到底ならないこと）を確認する。
    """
    candidate = _candidate(ticker="NVDA", asset_class="us_equity", entry_price_basis=208.76)
    result = size_position(
        candidate, available_capital=250_000, total_capital=250_000,
        take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0,
    )
    assert result["excluded"] is False
    assert result["recommended_shares"] < 10  # 395株のような大きな誤りには絶対にならない
    assert result["position_amount"] <= 250_000  # 想定予算を超えない


def test_allocate_positions_applies_usd_jpy_rate_to_us_equity_only():
    """allocate_positionsは、japan_equityにはfx_rate_to_jpy=1.0、us_equityには
    usd_jpy_rateをそのまま適用すること。
    """
    candidates = [
        _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500),
        _candidate(ticker="NVDA", asset_class="us_equity", entry_price_basis=200.0),
    ]
    result = allocate_positions(
        candidates, available_capital=1_000_000, total_capital=1_000_000,
        take_profit_policy=TP_POLICY, usd_jpy_rate=150.0,
    )
    proposals_by_ticker = {p["ticker"]: p for p in result["proposals"]}
    assert proposals_by_ticker["7203"]["fx_rate_to_jpy"] == 1.0
    assert proposals_by_ticker["NVDA"]["fx_rate_to_jpy"] == 150.0
    # NVDAのposition_amountは円換算後の値（株数 × 200 × 150）になっていること
    nvda = proposals_by_ticker["NVDA"]
    assert nvda["position_amount"] == pytest.approx(nvda["recommended_shares"] * 200.0 * 150.0)


def test_allocate_positions_sequential_consumption_never_exceeds_total_capital():
    candidates = [
        _candidate(ticker="A", asset_class="us_equity", entry_price_basis=100),
        _candidate(ticker="B", asset_class="us_equity", entry_price_basis=200),
        _candidate(ticker="C", asset_class="us_equity", entry_price_basis=300),
    ]
    result = allocate_positions(candidates, available_capital=3000000, total_capital=3000000,
                                 take_profit_policy=TP_POLICY, usd_jpy_rate=1.0)
    total_spent = sum(p["position_amount"] for p in result["proposals"])
    assert total_spent <= 3000000
    assert len(result["proposals"]) == 3


def test_allocate_positions_zero_share_candidate_excluded_from_proposals_and_logged():
    candidates = [
        _candidate(ticker="EXPENSIVE", asset_class="us_equity", entry_price_basis=10_000_000),
        _candidate(ticker="CHEAP", asset_class="us_equity", entry_price_basis=100),
    ]
    result = allocate_positions(candidates, available_capital=3000000, total_capital=3000000,
                                 take_profit_policy=TP_POLICY, usd_jpy_rate=1.0)
    tickers_in_proposals = [p["ticker"] for p in result["proposals"]]
    assert "EXPENSIVE" not in tickers_in_proposals
    assert "CHEAP" in tickers_in_proposals
    not_selected = [d for d in result["decision_log_entries"] if d["ticker"] == "EXPENSIVE"]
    assert not_selected[0]["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"
    assert not_selected[0]["decision"] == "not_selected"
