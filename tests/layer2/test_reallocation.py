"""reallocation.pyのテスト（scoring_specification.md §4の欠損時再配分仕様）。"""

from ai_investment_assistant.layer2_analysis.reallocation import (
    NEUTRAL_SCORE,
    WeightedItem,
    reallocate,
    weighted_axis_score,
)


def test_no_missing_items_effective_weights_equal_original():
    items = [WeightedItem("A", 45, 80), WeightedItem("B", 35, 70), WeightedItem("C", 20, 60)]
    result = reallocate(items)
    assert result.reallocated is False
    assert result.missing == ()
    assert round(result.effective_weights["A"], 4) == 45.0


def test_missing_item_is_proportionally_redistributed():
    # 需給軸の例：信用倍率(20)欠損 -> 残り45:35の比率を保ったまま100%に按分
    items = [WeightedItem("VolumeSurgeRatio", 45, 80), WeightedItem("VolumeMADeviation", 35, 70), WeightedItem("MarginRatio", 20, None)]
    result = reallocate(items)
    assert result.reallocated is True
    assert result.missing == ("MarginRatio",)
    # 45:35の比率を保って100に按分 -> 56.25, 43.75
    assert round(result.effective_weights["VolumeSurgeRatio"], 2) == 56.25
    assert round(result.effective_weights["VolumeMADeviation"], 2) == 43.75


def test_weighted_axis_score_matches_design_doc_example():
    # layer2_analysis_design.md §3-3の需給軸の例（出来高急増率80点、乖離率70点、信用倍率欠損）
    items = [WeightedItem("VolumeSurgeRatio", 45, 80), WeightedItem("VolumeMADeviation", 35, 70), WeightedItem("MarginRatio", 20, None)]
    score, result = weighted_axis_score(items)
    expected = 80 * 0.5625 + 70 * 0.4375
    assert round(score, 2) == round(expected, 2)


def test_all_missing_returns_neutral_score():
    items = [WeightedItem("A", 50, None), WeightedItem("B", 50, None)]
    score, result = weighted_axis_score(items)
    assert score == NEUTRAL_SCORE
    assert result.reallocated is True
    assert set(result.missing) == {"A", "B"}


def test_effective_weights_always_sum_to_100_when_available():
    items = [WeightedItem("A", 25, 90), WeightedItem("B", 20, None), WeightedItem("C", 15, 60), WeightedItem("D", 10, 70)]
    result = reallocate(items)
    assert round(sum(result.effective_weights.values()), 6) == 100.0
