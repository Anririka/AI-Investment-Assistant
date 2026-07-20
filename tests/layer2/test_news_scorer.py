"""news_scorer.pyのテスト（layer2_analysis_design.md §3-6、scoring_specification.md §3-5）。

design書の主眼テストケース：「強いポジティブ1件＋強いネガティブ1件」でscore≈50かつ
uncertaintyが高い値になることを確認する。
"""

import pytest

from ai_investment_assistant.layer2_analysis.exceptions import SchemaVersionError
from ai_investment_assistant.layer2_analysis.news_scorer import score_axis

DECAY_CURVE = [
    {"within_hours": 24, "factor": 1.0, "reason_code": "NEWS_DECAY_FRESH"},
    {"within_hours": 72, "factor": 0.8, "reason_code": "NEWS_DECAY_RECENT"},
    {"within_hours": 168, "factor": 0.6, "reason_code": "NEWS_DECAY_WEEK_OLD"},
    {"within_hours": 336, "factor": 0.3, "reason_code": "NEWS_DECAY_TWO_WEEKS_OLD"},
    {"within_hours": None, "factor": 0.1, "reason_code": "NEWS_DECAY_STALE"},
]
COMPAT = {"news_schema": {"supported_schema_versions": ["1.0", "1.1"], "accept_major_version": 1}}


def _item(direction, importance=80, confidence=0.9, age_hours=5.0, category="product", schema="1.0"):
    return {
        "news_schema_version": schema,
        "category": category,
        "headline": f"{direction} headline",
        "source": "TestWire",
        "impact_direction": direction,
        "impact_horizon": "mid_term",
        "confidence": confidence,
        "importance": importance,
        "published_at": "2026-07-18T03:15:00Z",
        "age_hours": age_hours,
    }


def test_no_news_defaults_to_neutral():
    result = score_axis([], DECAY_CURVE, COMPAT)
    assert result["score"] == 50
    assert result["uncertainty"] == 0
    assert result["relevant_items"] == []


def test_single_positive_news_raises_score_above_50():
    result = score_axis([_item("positive")], DECAY_CURVE, COMPAT)
    assert result["score"] > 50
    assert result["uncertainty"] == 0  # 相殺なし


def test_single_negative_news_lowers_score_below_50():
    result = score_axis([_item("negative")], DECAY_CURVE, COMPAT)
    assert result["score"] < 50
    assert result["uncertainty"] == 0


def test_strong_positive_and_negative_cancel_to_near_50_with_high_uncertainty():
    # design書の主眼テストケース
    items = [_item("positive", importance=90, confidence=0.9), _item("negative", importance=90, confidence=0.9)]
    result = score_axis(items, DECAY_CURVE, COMPAT)

    assert result["score"] == pytest.approx(50, abs=1.0)
    assert result["uncertainty"] > 90  # ほぼ完全に拮抗しているため高いuncertainty


def test_old_news_is_decayed_more_than_fresh_news():
    fresh = score_axis([_item("positive", age_hours=1.0)], DECAY_CURVE, COMPAT)
    stale = score_axis([_item("positive", age_hours=400.0)], DECAY_CURVE, COMPAT)
    assert fresh["score"] > stale["score"]


def test_matching_major_version_is_accepted():
    result = score_axis([_item("positive", schema="1.1")], DECAY_CURVE, COMPAT)
    assert result["score"] > 50  # 例外を送出せず正常処理される


def test_mismatched_major_version_raises_schema_version_error():
    with pytest.raises(SchemaVersionError):
        score_axis([_item("positive", schema="2.0")], DECAY_CURVE, COMPAT)


def test_contribution_reason_code_uses_category():
    result = score_axis([_item("positive", category="earnings")], DECAY_CURVE, COMPAT)
    assert result["relevant_items"][0]["reason_code"] == "NEWS_EARNINGS"
