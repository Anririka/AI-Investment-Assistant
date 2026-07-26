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


def test_find_score_context_coerces_string_scores_from_real_sheets_api_shape():
    """2026-07-26追加、回帰テスト：Google Sheets APIの`spreadsheets.values.get`は
    デフォルト（valueRenderOption=FORMATTED_VALUE）で数値セルも表示用の文字列
    （例："79"）として返す。実データ初回検証で、segment_analyzer.score_band()の
    比較演算が`'<' not supported between instances of 'str' and 'int'`で失敗する
    実例が発生した。既存の`_sheet_row()`（Pythonの数値型を直接使っており実物のAPI
    形状と異なっていた）とは異なり、実際のAPIが返す文字列型のまま値を渡し、
    score_summaryの各軸が正しくfloatへ変換されることを検証する。
    """
    row = _sheet_row(
        テクニカルスコア="84", ファンダメンタルスコア="71", 需給スコア="78",
        マクロスコア="65", ニューススコア="63", ニュース不確実性="35",
        レジーム適合スコア="90", 総合スコア="79.5",
    )
    context = find_score_context([row], "NVDA")
    score_summary = context["score_summary"]
    assert score_summary["composite"] == 79.5
    assert isinstance(score_summary["composite"], float)
    assert score_summary["technical"] == 84.0
    assert isinstance(score_summary["technical"], float)
