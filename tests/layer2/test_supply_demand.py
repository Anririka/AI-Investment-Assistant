"""supply_demand.pyのテスト（layer2_analysis_design.md §3-3、scoring_specification.md §3-3）。"""

from datetime import date, datetime, timedelta

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer2_analysis.supply_demand import score_axis


def _make_series(volumes, base_date=date(2025, 1, 1)):
    bars = tuple(
        PriceBar(date=base_date + timedelta(days=i), open=100, high=101, low=99, close=100, volume=v)
        for i, v in enumerate(volumes)
    )
    meta = DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 20))
    return PriceSeries(ticker="TEST", currency="JPY", bars=bars, meta=meta)


def test_margin_ratio_missing_reallocates_to_remaining_two():
    volumes = [1_000_000] * 25 + [3_500_000]  # 出来高急増
    series = _make_series(volumes)

    result = score_axis(series, margin_ratio=None)

    assert "MarginRatio" in result["missing_indicators"]
    indicators = {s["indicator"] for s in result["sub_scores"]}
    assert indicators == {"VolumeSurgeRatio", "VolumeMADeviation"}
    assert 0 <= result["axis_score"] <= 100


def test_margin_ratio_present_is_scored():
    volumes = [1_000_000] * 26
    series = _make_series(volumes)

    result = score_axis(series, margin_ratio=2.0)

    margin_sub = next(s for s in result["sub_scores"] if s["indicator"] == "MarginRatio")
    assert margin_sub["reason_code"] == "SUPD_MARGIN_RATIO_NEUTRAL"


def test_short_series_returns_none_for_ratios():
    series = _make_series([1_000_000])
    result = score_axis(series, margin_ratio=None)
    assert result["raw"]["volume_surge_ratio"] is None
