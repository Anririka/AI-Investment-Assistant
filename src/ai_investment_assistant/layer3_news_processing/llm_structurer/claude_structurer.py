"""ClaudeStructurer（layer3_news_processing_design.md §6・§7・§14確定事項1、初期採用LLM）。

Claudeの小型モデルを用いて記事を構造化する。Structured output（Tool呼び出し）機能で
スキーマ準拠出力を強制し、自由文パースには依存しない（§6）。

注意（重要）：このファイル作成時点では、実際のAnthropic APIキーでのライブ疎通確認は
行えていない（このクラウド作業環境には専用のANTHROPIC_API_KEYが共有されていないため）。
GitHub Secretsに`ANTHROPIC_API_KEY`を新規登録し、実際にこのクラスを実行した結果（レスポンス
内容、またはエラーメッセージ）を共有いただければ、必要に応じて調整する。

Anthropic API呼び出し本体は`_create_message`に切り出しており、テストではこのメソッドを
差し替えることで、実際のAPI・`anthropic`パッケージ無しにプロンプト組み立て・結果組み立て
ロジックを検証できるようにしている。
"""

from __future__ import annotations

import os
from typing import Optional

from .base import NewsStructurer

DEFAULT_MODEL = "claude-haiku-4-5"

STRUCTURE_TOOL_SCHEMA = {
    "name": "submit_structured_news",
    "description": "ニュース記事を構造化した結果を送信する",
    "input_schema": {
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
    },
}


def build_prompt(article: dict, universe_tickers: list, sector_master: list) -> str:
    """プロンプトテンプレート（prompts/news_structuring_prompt_template.md、§7の要素）を組み立てる。"""
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
        "submit_structured_newsツールを使って結果を送信してください。"
    )


class ClaudeStructurer(NewsStructurer):
    """Claude小型モデルによるニュース構造化（Ver1初期採用、§14確定事項1）。"""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_config(cls, config: dict) -> "ClaudeStructurer":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = config.get("model", DEFAULT_MODEL)
        return cls(api_key=api_key, model=model)

    def _create_message(self, prompt: str) -> dict:
        """実際のAnthropic API呼び出し（テストではこのメソッドをオーバーライドする）。"""
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=[STRUCTURE_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_structured_news"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        return dict(tool_use_block.input)

    def structure(self, article: dict, universe_tickers: list = None, sector_master: list = None) -> dict:
        universe_tickers = universe_tickers or []
        sector_master = sector_master or []
        prompt = build_prompt(article, universe_tickers, sector_master)

        result = self._create_message(prompt)
        result["llm_provider"] = "claude"
        result["llm_model"] = self._model
        result["structuring_status"] = "success"
        return result
