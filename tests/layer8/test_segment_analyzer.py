"""segment_analyzer.pyのテスト（layer8_self_evaluation_design.md §7-1-2〜§7-6、§11テスト方針）。"""

import pytest

from ai_investment_assistant.layer8_self_evaluation.segment_analyzer import (
    aggregate_by_asset_class,
    aggregate_by_holding_period,
    aggregate_by_reason_code,
    aggregate_by_score_band,
    confidence_label,
    holding_period_band,
    score_band,
)

THRESHOLDS = {
    "low_sample": {"max_count": 9},
    "medium_sample": {"min_count": 10, "max_count": 29},
    "normal": {"min_count": 30},
}


@pytest.mark.parametrize("score,expected", [
    (0, "0-59"), (59, "0-59"), (60, "60-69"), (69, "60-69"),
    (70, "70-79"), (79, "70-79"), (80, "80-89"), (89, "80-89"),
    (90, "90-100"), (100, "90-100"),
])
def test_score_band_boundaries(score, expected):
    assert score_band(score) == expected


@pytest.mark.parametrize("days,expected", [
    (1, "〜7日"), (7, "〜7日"), (8, "8〜14日"), (14, "8〜14日"),
    (15, "15〜30日"), (30, "15〜30日"), (31, "31日超"),
])
def test_holding_period_band_boundaries(days, expected):
    assert holding_period_band(days) == expected


@pytest.mark.parametrize("count,expected", [
    (0, "low_sample"), (9, "low_sample"), (10, "medium_sample"),
    (29, "medium_sample"), (30, "normal"), (100, "normal"),
])
def test_confidence_label_boundaries(count, expected):
    assert confidence_label(count, THRESHOLDS) == expected


def _win(reason_codes=None, composite=79, asset_class="us_equity", holding_days=18, return_pct=15.0):
    return {
        "outcome": "win", "final_return_pct": return_pct,
        "extracted_reason_codes": reason_codes or [], "reason_code_extraction_status": "success" if reason_codes else "no_match",
        "score_summary": {"composite": composite}, "score_context_available": True,
        "asset_class": asset_class, "holding_days": holding_days,
    }


def _loss(reason_codes=None, composite=50, asset_class="japan_equity", holding_days=5, return_pct=-8.0):
    return {
        "outcome": "loss", "final_return_pct": return_pct,
        "extracted_reason_codes": reason_codes or [], "reason_code_extraction_status": "success" if reason_codes else "no_match",
        "score_summary": {"composite": composite}, "score_context_available": True,
        "asset_class": asset_class, "holding_days": holding_days,
    }


def test_aggregate_by_reason_code_counts_win_rate_and_avg_return():
    evaluations = [_win(["TECH_RSI_HEALTHY"]), _win(["TECH_RSI_HEALTHY"]), _loss(["TECH_RSI_HEALTHY"])]
    result = aggregate_by_reason_code(evaluations, THRESHOLDS)
    entry = next(e for e in result if e["reason_code"] == "TECH_RSI_HEALTHY")
    assert entry["count"] == 3
    assert entry["win_rate"] == pytest.approx(2 / 3)
    assert entry["confidence"] == "low_sample"


def test_aggregate_by_reason_code_multi_counts_positions_with_multiple_codes():
    evaluations = [_win(["TECH_A", "FUND_B"])]
    result = aggregate_by_reason_code(evaluations, THRESHOLDS)
    codes = {e["reason_code"] for e in result}
    assert codes == {"TECH_A", "FUND_B"}
    assert all(e["count"] == 1 for e in result)


def test_aggregate_by_reason_code_excludes_no_match_evaluations():
    evaluations = [_win(reason_codes=None)]  # reason_code_extraction_status="no_match"
    result = aggregate_by_reason_code(evaluations, THRESHOLDS)
    assert result == []


def test_aggregate_by_score_band_groups_by_axis_and_band():
    evaluations = [_win(composite=79), _loss(composite=55)]
    result = aggregate_by_score_band(evaluations, THRESHOLDS)
    composite_bands = {e["band"] for e in result if e["axis"] == "composite"}
    assert composite_bands == {"70-79", "0-59"}


def test_aggregate_by_score_band_skips_positions_without_score_context():
    no_context = {"outcome": "win", "final_return_pct": 5.0, "score_context_available": False, "score_summary": None}
    result = aggregate_by_score_band([no_context], THRESHOLDS)
    assert result == []


def test_aggregate_by_asset_class_groups_correctly():
    evaluations = [_win(asset_class="us_equity"), _loss(asset_class="japan_equity"), _win(asset_class="us_equity")]
    result = aggregate_by_asset_class(evaluations)
    us = next(e for e in result if e["asset_class"] == "us_equity")
    jp = next(e for e in result if e["asset_class"] == "japan_equity")
    assert us["count"] == 2
    assert jp["count"] == 1
    assert "confidence" not in us  # §8の例に合わせ、asset_class別にはconfidenceを付与しない


def test_aggregate_by_holding_period_groups_correctly():
    evaluations = [_win(holding_days=5), _win(holding_days=20), _loss(holding_days=20)]
    result = aggregate_by_holding_period(evaluations)
    band_15_30 = next(e for e in result if e["band"] == "15〜30日")
    assert band_15_30["count"] == 2
    assert "confidence" not in band_15_30
