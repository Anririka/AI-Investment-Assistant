"""JSONスキーマ全体のvalidationテスト（layer2_analysis_design.md §6）。

Layer1のダミー出力一式（PriceSeries／FundamentalSnapshot／TimeSeries）を各モジュールに
通し、scorer.py→ranking.py→json_builder.pyのパイプラインを経て組み立てた最終JSONが、
§5のJSON Schemaに対してvalidationが通ることを確認する。
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from ai_investment_assistant.layer1_data_acquisition.models import (
    DataFetchMeta,
    FundamentalSnapshot,
    PriceBar,
    PriceSeries,
    TimeSeries,
    TimeSeriesPoint,
)
from ai_investment_assistant.layer2_analysis import (
    fundamental_metrics,
    json_builder,
    macro_evaluator,
    news_scorer,
    ranking,
    regime_detector,
    scorer,
    supply_demand,
    technical_indicators,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "ai_investment_assistant" / "layer2_analysis" / "schemas" / "layer2_output.schema.json"
)

AXIS_WEIGHTS = {"technical": 25, "fundamental": 25, "supply_demand": 15, "macro": 15, "news": 10, "regime": 10}
DECAY_CURVE = [
    {"within_hours": 24, "factor": 1.0, "reason_code": "NEWS_DECAY_FRESH"},
    {"within_hours": None, "factor": 0.1, "reason_code": "NEWS_DECAY_STALE"},
]
COMPAT = {"news_schema": {"supported_schema_versions": ["1.0"], "accept_major_version": 1}}


def _dummy_price_series(ticker, start_price=100.0, days=300):
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    bars = tuple(
        PriceBar(
            date=date(2025, 1, 1) + timedelta(days=i),
            open=start_price + i * 0.3, high=(start_price + i * 0.3) * 1.01,
            low=(start_price + i * 0.3) * 0.99, close=start_price + i * 0.3, volume=1_000_000 + i * 100,
        )
        for i in range(days)
    )
    return PriceSeries(ticker=ticker, currency="JPY", bars=bars, meta=meta)


def _dummy_fundamentals(ticker):
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    return FundamentalSnapshot(
        ticker=ticker, fiscal_period="2026Q1", eps=100.0, net_assets=5e8, net_income=5e7,
        revenue=1e9, operating_income=1e8, operating_cash_flow=1.2e8, capital_expenditure=2e7,
        interest_bearing_debt=2e8, total_assets=1e9, dividend=10.0, meta=meta,
    )


def _dummy_macro_series_map():
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    ids = ["us_10y_yield", "fed_funds_rate", "unemployment_rate", "cpi_yoy", "ppi_yoy", "gdp_growth", "leading_index"]
    return {
        sid: TimeSeries(
            series_id=sid,
            points=(TimeSeriesPoint(date=date(2026, 5, 1), value=2.0), TimeSeriesPoint(date=date(2026, 6, 1), value=1.9)),
            meta=meta,
        )
        for sid in ids
    }


@pytest.fixture(scope="module")
def schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_full_pipeline_output_validates_against_schema(schema):
    price_series = _dummy_price_series("7203")
    fundamentals = _dummy_fundamentals("7203")
    index_series = _dummy_price_series("NIKKEI225", start_price=30000, days=300)

    technical = technical_indicators.score_axis(price_series)
    fundamental = fundamental_metrics.score_axis(fundamentals, per=15.0, pbr=1.2, dividend_yield_percentile=0.6)
    supply = supply_demand.score_axis(price_series, margin_ratio=None)
    macro = macro_evaluator.score_axis(_dummy_macro_series_map())
    news = news_scorer.score_axis([], DECAY_CURVE, COMPAT)
    regime = regime_detector.detect_regime(index_series)
    fit = regime_detector.score_fit(regime["regime"], ["growth"])

    candidate = scorer.build_candidate(
        asset_class="japan_equity", ticker="7203", name="トヨタ自動車",
        style_tags=["growth"], data_quality={"is_delayed": False, "missing_fields": []},
        technical=technical, fundamental=fundamental, supply_demand=supply, news=news,
        macro_axis_score=macro["axis_score"], regime_fit=fit, axis_weights=AXIS_WEIGHTS,
    )

    ranked = ranking.rank_candidates([candidate])

    run_meta = scorer.build_run_meta(
        run_id="20260720-0900", analysis_started_at=datetime(2026, 7, 20, 9, 0, 0),
        analysis_completed_at=datetime(2026, 7, 20, 9, 5, 0), critical_errors=[], warning_errors=[],
        degraded_sources=[], excluded_candidates_count=0,
    )
    regime_output = {
        "current_regime": regime["regime"], "regime_reason": regime["reason"],
        "strategy_bias": {"japan_equity": "neutral"},
    }
    macro_output = {"series": macro["series"], "axis_score": macro["axis_score"], "axis_score_reason": macro["axis_score_reason"]}

    output, warnings = json_builder.build_output(
        run_meta=run_meta, regime=regime_output, macro=macro_output, ranked_candidates=ranked,
        excluded_summary=[], candidate_limits={"japan_equity": 10}, max_total_candidates=30,
    )

    jsonschema.validate(instance=output, schema=schema)
    assert warnings == []
    assert output["candidates"][0]["ticker"] == "7203"
