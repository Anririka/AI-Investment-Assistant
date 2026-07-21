"""score_context_loader.pyのテスト（layer8_self_evaluation_design.md §5-2、§11テスト方針）。"""

from ai_investment_assistant.layer8_self_evaluation.score_context_loader import (
    derive_sheet_date,
    find_score_context,
)


def test_derive_sheet_date_takes_first_8_chars_of_run_id():
    assert derive_sheet_date("20260718-0630") == "20260718"


def _sheet_row(**overrides):
    base = {
        "証券コード": "NVDA", "資産クラス": "us_equity",
        "テクニカルスコア": 84, "ファンダメンタルスコア": 71, "需給スコア": 78,
        "マクロスコア": 65, "ニューススコア": 63, "ニュース不確実性": 35,
        "レジーム適合スコア": 90, "総合スコア": 79,
        "投資理由": "テクニカル良好 (TECH_MA_PERFECT_ORDER_UP)", "リスク要因": "競合激化",
    }
    base.update(overrides)
    return base


def test_find_score_context_returns_matching_row_fields():
    context = find_score_context([_sheet_row()], "NVDA")
    assert context["score_summary"]["composite"] == 79
    assert context["score_summary"]["news_score"] == 63
    assert context["score_summary"]["news_uncertainty"] == 35
    assert context["asset_class"] == "us_equity"
    assert context["investment_reason"] == "テクニカル良好 (TECH_MA_PERFECT_ORDER_UP)"


def test_find_score_context_returns_none_when_ticker_not_found():
    assert find_score_context([_sheet_row()], "AMD") is None


def test_find_score_context_returns_none_when_sheet_rows_is_none():
    assert find_score_context(None, "NVDA") is None


def test_find_score_context_returns_none_when_sheet_rows_empty():
    assert find_score_context([], "NVDA") is None
