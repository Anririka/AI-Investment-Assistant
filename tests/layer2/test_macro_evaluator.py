"""macro_evaluator.pyのテスト（layer2_analysis_design.md §3-4、scoring_specification.md §3-4）。"""

from datetime import date, datetime

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, TimeSeries, TimeSeriesPoint
from ai_investment_assistant.layer2_analysis.macro_evaluator import (
    apply_sector_sensitivity,
    score_axis,
    score_indicator,
)


def _series(values, series_id="us_10y_yield"):
    meta = DataFetchMeta(source_used="fred", fetched_at=datetime(2026, 7, 20))
    points = tuple(TimeSeriesPoint(date=date(2026, m, 1), value=v) for m, v in enumerate(values, start=1))
    return TimeSeries(series_id=series_id, points=points, meta=meta)


def test_falling_us10y_yield_scores_high():
    series = _series([4.6, 4.5])  # 低下
    result = score_indicator("us_10y_yield", series)
    assert result["reason_code"] == "MACRO_US10Y_FALLING"
    assert result["score"] == 80


def test_rising_us10y_yield_scores_low():
    series = _series([4.4, 4.6])  # 上昇
    result = score_indicator("us_10y_yield", series)
    assert result["reason_code"] == "MACRO_US10Y_RISING"
    assert result["score"] == 35


def test_flat_scores_neutral():
    series = _series([4.5, 4.51])  # 誤差程度、横ばい扱い
    result = score_indicator("us_10y_yield", series)
    assert result["reason_code"] == "MACRO_US10Y_FLAT"
    assert result["score"] == 60


def test_gdp_beat_is_favorable_unlike_yield():
    series = _series([2.0, 2.5], series_id="gdp_growth")
    result = score_indicator("gdp_growth", series)
    assert result["reason_code"] == "MACRO_GDP_BEAT"


def test_no_data_returns_neutral():
    empty = TimeSeries(series_id="cpi_yoy", points=(), meta=DataFetchMeta(source_used="fred", fetched_at=datetime(2026, 7, 20)))
    result = score_indicator("cpi_yoy", empty)
    assert result["score"] == 50


def test_score_axis_weighted_average():
    series_map = {
        "us_10y_yield": _series([4.6, 4.5], "us_10y_yield"),
        "fed_funds_rate": _series([4.3, 4.2], "fed_funds_rate"),
    }
    result = score_axis(series_map)
    # 両方favorable(falling、閾値を明確に超える変化量)なので80点、重み20:20 -> 平均80
    assert result["axis_score"] == 80.0


def test_sector_sensitivity_default_is_noop():
    corrected = apply_sector_sensitivity(70.0, ["growth"], {"growth": 1.0, "default": 1.0})
    assert corrected == 70.0


def test_sector_sensitivity_applies_custom_factor():
    corrected = apply_sector_sensitivity(70.0, ["growth"], {"growth": 0.9, "default": 1.0})
    assert corrected == 63.0
