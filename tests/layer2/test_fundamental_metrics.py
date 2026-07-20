"""fundamental_metrics.pyのテスト（layer2_analysis_design.md §3-2、scoring_specification.md §3-2）。"""

import pytest

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, FundamentalSnapshot
from ai_investment_assistant.layer2_analysis.fundamental_metrics import (
    PER_BUCKETS,
    AbsoluteRangePERScorer,
    SectorRelativePERScorer,
    score_axis,
)
from ai_investment_assistant.layer2_analysis.bucket import score_from_buckets
from datetime import datetime


def _snapshot(**overrides):
    defaults = dict(
        ticker="TEST", fiscal_period="2026Q1", eps=100.0, net_assets=500_000_000.0,
        net_income=50_000_000.0, revenue=1_000_000_000.0, operating_income=100_000_000.0,
        operating_cash_flow=120_000_000.0, capital_expenditure=20_000_000.0,
        interest_bearing_debt=200_000_000.0, total_assets=1_000_000_000.0, dividend=10.0,
        meta=DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 20)),
    )
    defaults.update(overrides)
    return FundamentalSnapshot(**defaults)


def test_per_bucket_boundaries_match_spec():
    assert score_from_buckets(9.99, PER_BUCKETS).reason_code == "FUND_PER_CHEAP"
    assert score_from_buckets(10.00, PER_BUCKETS).reason_code == "FUND_PER_LOW"
    assert score_from_buckets(49.99, PER_BUCKETS).reason_code == "FUND_PER_HIGH"
    assert score_from_buckets(50.00, PER_BUCKETS).reason_code == "FUND_PER_EXTREME_OR_NA"


def test_absolute_range_per_scorer_handles_none_and_negative_as_extreme():
    scorer = AbsoluteRangePERScorer()
    assert scorer.score(None).reason_code == "FUND_PER_EXTREME_OR_NA"
    assert scorer.score(-5.0).reason_code == "FUND_PER_EXTREME_OR_NA"
    assert scorer.score(12.0).reason_code == "FUND_PER_LOW"


def test_sector_relative_per_scorer_is_not_implemented():
    scorer = SectorRelativePERScorer()
    with pytest.raises(NotImplementedError):
        scorer.score(15.0, sector_code="3700")


def test_score_axis_computes_roe_roa_from_snapshot():
    snapshot = _snapshot(net_income=75_000_000.0, net_assets=500_000_000.0, total_assets=1_000_000_000.0)
    result = score_axis(snapshot, per=12.0, pbr=1.2, dividend_yield_percentile=0.5)

    assert result["raw"]["roe"] == pytest.approx(15.0)  # 75M/500M*100
    assert result["raw"]["roa"] == pytest.approx(7.5)   # 75M/1000M*100


def test_score_axis_reallocates_when_growth_rates_missing():
    snapshot = _snapshot()
    result = score_axis(
        snapshot, per=12.0, pbr=1.2, dividend_yield_percentile=0.5,
        prior_year_eps=None, prior_year_revenue=None, prior_year_fcf=None,
    )
    assert "EPSGrowth" in result["missing_indicators"]
    assert "SalesGrowth" in result["missing_indicators"]
    assert 0 <= result["axis_score"] <= 100


def test_score_axis_computes_growth_rates_when_prior_year_given():
    snapshot = _snapshot(eps=115.0, revenue=1_100_000_000.0)
    result = score_axis(
        snapshot, per=12.0, pbr=1.2, dividend_yield_percentile=0.5,
        prior_year_eps=100.0, prior_year_revenue=1_000_000_000.0,
    )
    assert result["raw"]["eps_growth_yoy"] == pytest.approx(15.0)
    assert result["raw"]["sales_growth_yoy"] == pytest.approx(10.0)


def test_no_dividend_uses_none_bucket():
    snapshot = _snapshot(dividend=0.0)
    result = score_axis(snapshot, per=12.0, pbr=1.2, dividend_yield_percentile=None)
    div_sub = next(s for s in result["sub_scores"] if s["indicator"] == "DividendYieldRank")
    assert div_sub["reason_code"] == "FUND_DIV_YIELD_NONE"
