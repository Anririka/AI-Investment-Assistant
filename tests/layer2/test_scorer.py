"""scorer.pyのテスト（layer2_analysis_design.md §3-7、scoring_specification.md §5）。"""

from ai_investment_assistant.layer2_analysis.scorer import build_candidate, compute_composite_score

AXIS_WEIGHTS = {"technical": 25, "fundamental": 25, "supply_demand": 15, "macro": 15, "news": 10, "regime": 10}


def test_composite_score_matches_weighted_average():
    result = compute_composite_score(
        technical_score=84, fundamental_score=71, supply_demand_score=78,
        macro_score=65, news_score=63, regime_fit_score=90, axis_weights=AXIS_WEIGHTS,
    )
    expected = 84 * 0.25 + 71 * 0.25 + 78 * 0.15 + 65 * 0.15 + 63 * 0.10 + 90 * 0.10
    assert result["total"] == round(expected, 2)
    assert result["score_meta"]["scoring_version"] == "1.0.0"


def test_composite_score_all_zero_axes_is_zero():
    result = compute_composite_score(0, 0, 0, 0, 0, 0, AXIS_WEIGHTS)
    assert result["total"] == 0.0


def test_composite_score_all_hundred_axes_is_hundred():
    result = compute_composite_score(100, 100, 100, 100, 100, 100, AXIS_WEIGHTS)
    assert result["total"] == 100.0


def test_build_candidate_assembles_all_required_fields():
    technical = {"raw": {}, "sub_scores": [], "axis_score": 84, "axis_score_reason": "r"}
    fundamental = {"raw": {}, "sub_scores": [], "axis_score": 71, "axis_score_reason": "r"}
    supply_demand = {"raw": {}, "sub_scores": [], "axis_score": 78, "axis_score_reason": "r"}
    news = {"relevant_items": [], "score": 63, "uncertainty": 0, "axis_score_reason": "r"}
    regime_fit = {"score": 90, "reason_code": "REGIME_FIT_UPTREND_GROWTH", "reason": "r"}

    candidate = build_candidate(
        asset_class="us_equity", ticker="NVDA", name="NVIDIA Corporation",
        style_tags=["growth", "semiconductor"], data_quality={"is_delayed": False, "missing_fields": []},
        technical=technical, fundamental=fundamental, supply_demand=supply_demand, news=news,
        macro_axis_score=65, regime_fit=regime_fit, axis_weights=AXIS_WEIGHTS,
    )

    assert candidate["ticker"] == "NVDA"
    assert candidate["composite_score"]["total"] > 0
    assert candidate["macro_axis_score_ref"] == 65
