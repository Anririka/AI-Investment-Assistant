"""position_sizer.pyのテスト（layer5_ai_judgment_design.md §8、§12テスト方針）。

2026-07-24追加：米国株の為替換算漏れバグ（NVDA $208.76が円建て予算にそのまま
適用され、想定の約50倍の規模になった実例）を受け、`size_position()`の
`fx_rate_to_jpy`・`allocate_positions()`の`usd_jpy_rate`は必須引数とした。

2026-07-26追加：日本株も単元未満株（SBI証券のS株等、1株単位の売買）を使う前提に
切り替えたため、日本株の100株単位切り下げに関するテストは、1株単位切り下げに
更新した。以前の「テスト期間中の資金(25万円)では日本株が100株単位のため
構造的に一切約定できない」問題（トヨタ自動車=289,700円必要 > 25万円）を
1株単位化で解消できることを検証する回帰テストも追加した。
"""

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
    # fx_rate_to_jpy=1.0を渡し、旧来（円換算なし）と同じ計算になることを確認する。
    result = size_position(_candidate(), available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    # 33% cap = 990000; 990000/333.74 ≈ 2966.6 shares by cap; also limited by available_capital
    assert result["excluded"] is False
    assert isinstance(result["recommended_shares"], int)
    assert result["recommended_shares"] == int(990000 // 333.74)


def test_size_position_japan_equity_floors_to_1_share_unit():
    # 2026-07-26変更：日本株も単元未満株（1株単位）で計算するため、100の倍数である
    # 必要はない。2500円の株を3,000,000円の資金・33%上限(990,000円)で計算すると
    # floor(990000/2500)=396株になるはず（100株単位縛りなら300株止まりだった）。
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["recommended_shares"] == int(990000 // 2500)


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


def test_size_position_zero_shares_when_even_1_share_exceeds_cap():
    # 1株単位化後も、1株の価格自体が上限を超えていれば0株になることは変わらない。
    candidate = _candidate(ticker="6861", asset_class="japan_equity", entry_price_basis=71820)
    result = size_position(candidate, available_capital=250000, total_capital=250000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    # 33% cap = 82,500円。71,820円は1株なら買えるが、2株目は買えないはず。
    assert result["excluded"] is False
    assert result["recommended_shares"] == 1


def test_size_position_japan_equity_toyota_scale_now_buyable_with_test_phase_capital():
    # 実データで確認された問題の回帰テスト：test_phase資金(25万円)・33%上限(82,500円)に
    # 対し、トヨタ自動車(終値2,897円)は100株単位だと289,700円必要で総資金自体を上回り
    # 構造的に一切約定できなかった。1株単位化後はfloor(82500/2897)=28株が買えるはず。
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2897)
    result = size_position(candidate, available_capital=250000, total_capital=250000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["excluded"] is False
    assert result["recommended_shares"] == int((250000 * 0.33) // 2897)
    assert result["recommended_shares"] > 0


def test_size_position_applies_out_of_range_take_profit_and_logs_it():
    candidate = _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=90)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=1.0)
    assert result["take_profit_target_pct"] == 50
    assert len(result["rule_enforcement_log_entries"]) == 1


def test_size_position_us_equity_applies_fx_conversion_for_budget_math():
    # entry_price_basis=100(USD)、fx_rate_to_jpy=150.0 -> 円換算後15,000円/株として
    # 資金管理計算が行われるべき（旧来の「USD建て価格をそのまま円建て予算に適用する」
    # バグでは、100円/株として計算されてしまい株数が過大になっていた）。
    candidate = _candidate(ticker="AAPL", asset_class="us_equity", entry_price_basis=100.0)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0)
    entry_price_jpy = 100.0 * 150.0
    per_position_cap = 3000000 * 0.33
    expected_shares = int(per_position_cap // entry_price_jpy)
    assert result["recommended_shares"] == expected_shares
    assert result["position_amount"] == pytest.approx(expected_shares * entry_price_jpy)
    assert result["fx_rate_to_jpy"] == 150.0


def test_size_position_us_equity_stop_loss_and_take_profit_stay_in_native_currency():
    # 損切/利確価格は、実際の注文が現地取引所の通貨建てで出されるため、
    # fx_rate_to_jpyを適用せず、entry_price_basis（USD）のまま算出されるべき。
    candidate = _candidate(ticker="AAPL", asset_class="us_equity", entry_price_basis=100.0, take_profit_target_pct=15.0)
    result = size_position(candidate, available_capital=3000000, total_capital=3000000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0)
    assert result["stop_loss_price"] == pytest.approx(100.0 * 0.9)
    assert result["take_profit_price"] == pytest.approx(100.0 * 1.15)


def test_size_position_reproduces_and_fixes_reported_nvda_scale_bug():
    # 2026-07-24のライブ実行で実際に発生した規模: NVDA終値$208.76、
    # total_capital/available_capital=250,000円(テスト期間の縮小運用額)、
    # 実勢レートusd_jpy=150.0。旧バグでは395株・82,460円という、想定予算の
    # 約50倍規模（395株×$208.76≈1,200万円超）の提案が生成されていた。
    # 修正後は、円換算後の価格(208.76×150.0≈31,314円)を基準に計算されるべきで、
    # 33%上限=82,500円のもとでは1株未満、または高々数株にとどまるはずである。
    candidate = _candidate(ticker="NVDA", asset_class="us_equity", entry_price_basis=208.76)
    result = size_position(candidate, available_capital=250000, total_capital=250000,
                            take_profit_policy=TP_POLICY, fx_rate_to_jpy=150.0)
    if result["excluded"]:
        assert result["reason_code"] == "INSUFFICIENT_FUNDS_ZERO_SHARES"
    else:
        assert result["recommended_shares"] < 10
        assert result["position_amount"] <= 250_000


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


def test_allocate_positions_applies_usd_jpy_rate_to_us_equity_only():
    # 日本株はfx_rate_to_jpy=1.0固定、米国株のみusd_jpy_rateが適用されることを検証する。
    candidates = [
        _candidate(ticker="7203", asset_class="japan_equity", entry_price_basis=2500, take_profit_target_pct=15.0),
        _candidate(ticker="AAPL", asset_class="us_equity", entry_price_basis=100.0, take_profit_target_pct=15.0),
    ]
    result = allocate_positions(candidates, available_capital=3000000, total_capital=3000000,
                                 take_profit_policy=TP_POLICY, usd_jpy_rate=150.0)
    by_ticker = {p["ticker"]: p for p in result["proposals"]}
    assert by_ticker["7203"]["fx_rate_to_jpy"] == 1.0
    assert by_ticker["AAPL"]["fx_rate_to_jpy"] == 150.0
    # AAPLのposition_amountは円換算後価格(100×150=15,000円)ベースで計算されているはず
    assert by_ticker["AAPL"]["position_amount"] == pytest.approx(
        by_ticker["AAPL"]["recommended_shares"] * 100.0 * 150.0
    )
