"""Layer6 Google Sheets「本日の提案」からscore_summary/investment_reason等を取得
（layer8_self_evaluation_design.md §5-2）。

`run_id`の先頭8桁（YYYYMMDD）から対象ファイル名`提案ログ_YYYYMMDD`を直接導出し、
そのファイルのみを名前指定で取得する（全シート横断検索は行わない、確定仕様）。
"""

from __future__ import annotations

from typing import Optional


def derive_sheet_date(run_id: str) -> str:
    """run_id（例："20260718-0630"）の先頭8桁からYYYYMMDDを導出する。"""
    return run_id[:8]


def find_score_context(sheet_rows: Optional[list], ticker: str) -> Optional[dict]:
    """`sheet_rows`（Layer6「本日の提案」シートの行、§6-3の列名のままの辞書リスト）から
    `ticker`に一致する行を検索し、Layer8が必要とするフィールドのみを抽出する。

    見つからない場合はNone（§5-3：score_context_available: falseとして扱う）。
    """
    if not sheet_rows:
        return None

    for row in sheet_rows:
        if row.get("証券コード") == ticker:
            return {
                "score_summary": {
                    "technical": row.get("テクニカルスコア"),
                    "fundamental": row.get("ファンダメンタルスコア"),
                    "supply_demand": row.get("需給スコア"),
                    "macro": row.get("マクロスコア"),
                    "news_score": row.get("ニューススコア"),
                    "news_uncertainty": row.get("ニュース不確実性"),
                    "regime_fit": row.get("レジーム適合スコア"),
                    "composite": row.get("総合スコア"),
                },
                "investment_reason": row.get("投資理由"),
                "risk_factors": row.get("リスク要因"),
                "asset_class": row.get("資産クラス"),
            }
    return None
