"""schema.pyのテスト（layer3_news_processing_design.md §8）。"""

import pytest

from ai_investment_assistant.layer3_news_processing.schema import (
    CURRENT_SCHEMA_VERSION,
    SUMMARY_MAX_CHARS,
    compute_item_id,
    truncate_summary,
    validate,
)


def _valid_item(**overrides):
    item = {
        "news_schema_version": CURRENT_SCHEMA_VERSION,
        "item_id": "sha256:abc",
        "headline": "キオクシアHD、特許訴訟で株価急落",
        "source_name": "株探",
        "source_url": "https://s.kabutan.jp/news/1",
        "source_data_origin": "gdelt",
        "published_at": "2026-07-17T06:10:00Z",
        "fetched_at": "2026-07-18T06:02:11Z",
        "age_hours": 23.9,
        "category": "corporate_legal",
        "affected_companies": [{"ticker": "285A", "name": "キオクシアホールディングス", "relevance": "primary"}],
        "affected_sectors": ["semiconductor"],
        "impact_direction": "negative",
        "impact_horizon": "short_term",
        "importance": 82,
        "importance_llm_raw": 82,
        "importance_source": "llm",
        "confidence": 0.85,
        "confidence_reason": "大手報道機関複数で確認",
        "summary": "特許訴訟の観測からストップ安。",
        "llm_provider": "claude",
        "llm_model": "claude-haiku-4-5",
        "structuring_status": "success",
    }
    item.update(overrides)
    return item


def test_valid_item_passes_validation():
    validate(_valid_item())  # 例外が出なければOK


def test_invalid_impact_direction_fails_validation():
    with pytest.raises(Exception):
        validate(_valid_item(impact_direction="very_positive"))


def test_summary_too_long_fails_validation():
    with pytest.raises(Exception):
        validate(_valid_item(summary="あ" * 81))


def test_compute_item_id_is_deterministic():
    id1 = compute_item_id("https://example.com/a", "見出し")
    id2 = compute_item_id("https://example.com/a", "見出し")
    assert id1 == id2
    assert id1.startswith("sha256:")


def test_compute_item_id_differs_for_different_inputs():
    id1 = compute_item_id("https://example.com/a", "見出しA")
    id2 = compute_item_id("https://example.com/a", "見出しB")
    assert id1 != id2


def test_truncate_summary_leaves_short_text_untouched():
    text = "短い要約"
    assert truncate_summary(text) == text


def test_truncate_summary_cuts_at_80_chars():
    text = "あ" * 100
    result = truncate_summary(text)
    assert len(result) == SUMMARY_MAX_CHARS
