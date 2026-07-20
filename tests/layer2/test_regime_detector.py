"""regime_detector.pyのテスト（layer2_analysis_design.md §3-5、scoring_specification.md §3-6）。

人工的な「明確な上昇トレンド」「明確な下降トレンド」「レンジ」のダミー指数データで検証する
（layer2_analysis_design.md §6のテスト方針）。
"""

from datetime import date, datetime, timedelta

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer2_analysis.regime_detector import detect_regime, score_fit


def _make_series(closes, base_date=date(2024, 1, 1)):
    bars = tuple(
        PriceBar(date=base_date + timedelta(days=i), open=c, high=c * 1.005, low=c * 0.995, close=c, volume=1_000_000)
        for i, c in enumerate(closes)
    )
    meta = DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 20))
    return PriceSeries(ticker="INDEX", currency="JPY", bars=bars, meta=meta)


def test_clear_uptrend_is_detected():
    # 300日、単調増加で強いトレンド
    closes = [100 + i * 1.0 for i in range(300)]
    series = _make_series(closes)
    result = detect_regime(series)
    assert result["regime"] == "uptrend"
    assert result["reason_code"] == "REGIME_UPTREND"


def test_clear_downtrend_is_detected():
    closes = [1000 - i * 1.0 for i in range(300)]
    series = _make_series(closes)
    result = detect_regime(series)
    assert result["regime"] == "downtrend"
    assert result["reason_code"] == "REGIME_DOWNTREND"


def test_range_bound_market_is_detected():
    # 日々小幅にジグザグし、方向感の無い値動き（明確なトレンドを持たない）。
    # 正弦波のような滑らかな周期パターンは、局所的には単調な半周期区間を含みトレンドと
    # 誤判定されうるため、ADXが低く保たれる高頻度ジグザグを用いる。
    closes = [100 + (0.5 if i % 2 == 0 else -0.5) for i in range(300)]
    series = _make_series(closes)
    result = detect_regime(series)
    assert result["regime"] == "range"
    assert result["reason_code"] == "REGIME_RANGE"


def test_growth_style_fits_uptrend():
    fit = score_fit("uptrend", ["growth", "semiconductor"])
    assert fit["score"] == 90
    assert fit["reason_code"] == "REGIME_FIT_UPTREND_GROWTH"


def test_defensive_style_mismatches_uptrend():
    fit = score_fit("uptrend", ["defensive"])
    assert fit["score"] == 40
    assert fit["reason_code"] == "REGIME_FIT_UPTREND_DEFENSIVE_MISMATCH"


def test_defensive_style_fits_downtrend():
    fit = score_fit("downtrend", ["high_dividend"])
    assert fit["score"] == 90
    assert fit["reason_code"] == "REGIME_FIT_DOWNTREND_DEFENSIVE"


def test_range_is_neutral_regardless_of_style():
    fit = score_fit("range", ["growth"])
    assert fit["score"] == 60
    assert fit["reason_code"] == "REGIME_FIT_RANGE_NEUTRAL"
