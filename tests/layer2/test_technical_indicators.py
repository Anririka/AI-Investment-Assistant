"""technical_indicators.pyのテスト（layer2_analysis_design.md §3-1、scoring_specification.md §3-1）。"""

from datetime import date, datetime, timedelta

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer2_analysis.technical_indicators import (
    ADX_BUCKETS,
    RSI_BUCKETS,
    _classify_ma_alignment,
    score_axis,
)
from ai_investment_assistant.layer2_analysis.bucket import score_from_buckets


def _make_series(closes, base_date=date(2025, 1, 1)):
    bars = tuple(
        PriceBar(
            date=base_date + timedelta(days=i),
            open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1_000_000,
        )
        for i, c in enumerate(closes)
    )
    meta = DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 20))
    return PriceSeries(ticker="TEST", currency="JPY", bars=bars, meta=meta)


def test_rsi_bucket_boundaries_match_spec():
    # scoring_specification.md §3-1のRSIバケット境界値テスト
    assert score_from_buckets(29.99, RSI_BUCKETS).reason_code == "TECH_RSI_OVERSOLD"
    assert score_from_buckets(30.00, RSI_BUCKETS).reason_code == "TECH_RSI_PULLBACK"
    assert score_from_buckets(44.99, RSI_BUCKETS).reason_code == "TECH_RSI_PULLBACK"
    assert score_from_buckets(45.00, RSI_BUCKETS).reason_code == "TECH_RSI_HEALTHY"
    assert score_from_buckets(59.99, RSI_BUCKETS).reason_code == "TECH_RSI_HEALTHY"
    assert score_from_buckets(60.00, RSI_BUCKETS).reason_code == "TECH_RSI_WARM"


def test_adx_bucket_boundaries_match_spec():
    assert score_from_buckets(19.99, ADX_BUCKETS).reason_code == "TECH_ADX_NO_TREND"
    assert score_from_buckets(20.00, ADX_BUCKETS).reason_code == "TECH_ADX_WEAK_TREND"
    assert score_from_buckets(24.99, ADX_BUCKETS).reason_code == "TECH_ADX_WEAK_TREND"
    assert score_from_buckets(25.00, ADX_BUCKETS).reason_code == "TECH_ADX_STRONG_TREND"


def test_ma_alignment_perfect_up_when_strictly_increasing():
    alignment = _classify_ma_alignment(ma5=110, ma25=105, ma75=100, ma200=90, close=112)
    assert alignment == "perfect_up"


def test_ma_alignment_perfect_down_when_strictly_decreasing():
    alignment = _classify_ma_alignment(ma5=90, ma25=100, ma75=105, ma200=110, close=88)
    assert alignment == "perfect_down"


def test_ma_alignment_converging_when_close_together():
    alignment = _classify_ma_alignment(ma5=100.1, ma25=100.05, ma75=100.0, ma200=99.98, close=100.1)
    assert alignment == "converging"


def test_score_axis_returns_valid_range_for_uptrend_series():
    # 300日分の緩やかな上昇トレンド（200MA計算可能）
    closes = [100 + i * 0.5 for i in range(300)]
    series = _make_series(closes)

    result = score_axis(series)

    assert 0 <= result["axis_score"] <= 100
    assert result["raw"]["ma200_available"] is True
    assert "MA" not in result["missing_indicators"]
    indicators = {s["indicator"] for s in result["sub_scores"]}
    assert {"RSI", "MACD", "MA", "ADX", "ATR", "BollingerBands", "VWAP", "Week52HighLow"} <= indicators


def test_score_axis_reallocates_when_200ma_unavailable():
    # 50日分のみ -> 200MAは計算不能、欠損としてMAを再配分する
    closes = [100 + i * 0.3 for i in range(50)]
    series = _make_series(closes)

    result = score_axis(series)

    assert result["raw"]["ma200_available"] is False
    assert "MA" in result["missing_indicators"]
    indicators = {s["indicator"] for s in result["sub_scores"]}
    assert "MA" not in indicators
    assert 0 <= result["axis_score"] <= 100
