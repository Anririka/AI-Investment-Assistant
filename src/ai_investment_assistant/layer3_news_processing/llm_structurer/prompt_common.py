"""LLM構造化プロンプトの共通部分（layer3_news_processing_design.md §7）。

プロンプトの実質的な指示内容をベンダー間で共有し、モデルを切り替えても抽出結果の
一貫性を保つ（§7）。抽出スキーマ（`EXTRACTION_SCHEMA`）も共有し、Claude（tool
input_schema）・Gemini（response_json_schema）のどちらでも同じ定義を使い回せるようにする。
"""

from __future__ import annotations

EXTRACTION_SCHEMA = {
    "type": "object",
    "required": [
        "category", "affected_companies", "affected_sectors", "impact_direction",
        "impact_horizon", "importance", "confidence", "confidence_reason", "summary",
    ],
    "properties": {
        "category": {"type": "string"},
        "affected_companies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["ticker", "name", "relevance"],
                "properties": {
                    "ticker": {"type": "string"},
                    "name": {"type": "string"},
                    "relevance": {"type": "string", "enum": ["primary", "secondary"]},
                },
            },
        },
        "affected_sectors": {"type": "array", "items": {"type": "string"}},
        "impact_direction": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "impact_horizon": {"type": "string", "enum": ["short_term", "mid_term", "long_term"]},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence_reason": {"type": "string"},
        "summary": {"type": "string", "maxLength": 80},
    },
}


def build_prompt(article: dict, universe_tickers: list, sector_master: list) -> str:
    """プロンプトテンプレート（prompts/news_structuring_prompt_template.md、§7の要素）を組み立てる。

    ベンダー非依存の文面とする（Claude/Geminiいずれも構造化出力はスキーマ強制機能側で
    保証するため、特定ベンダーのAPI呼び出し方法への言及は含めない）。
    """
    tickers_str = ", ".join(f"{t['ticker']}:{t['name']}" for t in universe_tickers) or "（なし）"
    sectors_str = ", ".join(sector_master) or "（なし）"
    return (
        "以下のニュース記事を構造化してください。\n\n"
        "【記事】\n"
        f"見出し: {article['headline']}\n"
        f"本文: {article['body']}\n\n"
        "【対象ユニバース制約】\n"
        "以下のリストに含まれる銘柄のみをaffected_companiesとして抽出してください。"
        "リストに無い銘柄・業種に言及する場合は、affected_companiesは空にし、"
        "affected_sectorsのみで表現してください。\n"
        f"銘柄リスト: {tickers_str}\n"
        f"業種リスト: {sectors_str}\n\n"
        "【採点基準】\n"
        "importance（重要度、0-100）：株価・市場への影響範囲の広さで判断してください。\n"
        "confidence（信頼度、0-1）：情報源の一次性・公式性"
        "（決算短信等の一次情報＞大手報道機関＞二次的なまとめ記事）で判断してください。\n\n"
        "指定されたスキーマの形式で構造化結果を出力してください。"
    )
