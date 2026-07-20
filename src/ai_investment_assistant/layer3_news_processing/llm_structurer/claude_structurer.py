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
from .prompt_common import EXTRACTION_SCHEMA, build_prompt  # noqa: F401 (re-export、既存importとの互換性維持)

DEFAULT_MODEL = "claude-haiku-4-5"

STRUCTURE_TOOL_SCHEMA = {
    "name": "submit_structured_news",
    "description": "ニュース記事を構造化した結果を送信する",
    "input_schema": EXTRACTION_SCHEMA,
}


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
