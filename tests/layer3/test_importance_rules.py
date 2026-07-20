"""importance_rules.pyのテスト（layer3_news_processing_design.md §4-2、§13）。"""

from ai_investment_assistant.layer3_news_processing.importance_rules import apply_importance_floor

CONFIG = {
    "category_importance_floor": {"earnings": 70, "fomc": 70},
    "default_floor": 0,
}


def test_llm_value_below_floor_is_corrected():
    result = apply_importance_floor(40, "earnings", CONFIG)
    assert result["importance"] == 70
    assert result["importance_llm_raw"] == 40
    assert result["importance_source"] == "rule_floor_applied"


def test_llm_value_above_floor_is_unchanged():
    result = apply_importance_floor(85, "earnings", CONFIG)
    assert result["importance"] == 85
    assert result["importance_llm_raw"] == 85
    assert result["importance_source"] == "llm"


def test_category_without_floor_uses_default():
    result = apply_importance_floor(30, "other", CONFIG)
    assert result["importance"] == 30
    assert result["importance_source"] == "llm"


def test_value_exactly_at_floor_is_not_marked_as_corrected():
    result = apply_importance_floor(70, "earnings", CONFIG)
    assert result["importance"] == 70
    assert result["importance_source"] == "llm"
