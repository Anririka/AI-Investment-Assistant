"""GeminiStructurer（layer3_news_processing_design.md §6のStrategyパターン実装その2）。

コスト最適化のため、Gemini API（Flash-Liteモデル）の無料枠を利用する構成に切り替える
際の実装。`response_json_schema`によるスキーマ強制出力機能を用い、Claudeのtool呼び出し
方式と同じ抽出スキーマ（`prompt_common.EXTRACTION_SCHEMA`）を共有する。

注意（重要）：このファイル作成時点では、実際のGemini APIキーでのライブ疎通確認は
行えていない（このクラウド作業環境には専用のGEMINI_API_KEYが共有されていないため）。
GitHub Secretsに`GEMINI_API_KEY`を新規登録し、実際にこのクラスを実行した結果（レスポンス
内容、またはエラーメッセージ）を共有いただければ、必要に応じて調整する。

Gemini API呼び出し本体は`_create_message`に切り出しており、テストではこのメソッドを
差し替えることで、実際のAPI・`google-genai`パッケージ無しにプロンプト組み立て・結果組み立て
ロジックを検証できるようにしている（claude_structurer.pyと同じテスト容易化パターン）。

無料枠に関する注意：Gemini APIの無料枠は、利用データがGoogleのサービス改善に使われる
（Googleの利用規約に基づく）。有料枠に切り替えるとこの扱いが変わる。レート制限も
公開ドキュメント上で流動的なため、実際の記事数に対して十分か、稼働開始前に
https://aistudio.google.com/rate-limit で確認することを推奨する。
"""

from __future__ import annotations

import os

from .base import NewsStructurer
from .prompt_common import EXTRACTION_SCHEMA, build_prompt  # noqa: F401 (re-export)

DEFAULT_MODEL = "gemini-2.5-flash-lite"


class GeminiStructurer(NewsStructurer):
    """Gemini Flash-Lite（無料枠）によるニュース構造化（コスト最適化のための代替実装）。"""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_config(cls, config: dict) -> "GeminiStructurer":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        model = config.get("model", DEFAULT_MODEL)
        return cls(api_key=api_key, model=model)

    def _create_message(self, prompt: str) -> dict:
        """実際のGemini API呼び出し（テストではこのメソッドをオーバーライドする）。"""
        import json

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=EXTRACTION_SCHEMA,
            ),
        )
        return json.loads(response.text)

    def structure(self, article: dict, universe_tickers: list = None, sector_master: list = None) -> dict:
        universe_tickers = universe_tickers or []
        sector_master = sector_master or []
        prompt = build_prompt(article, universe_tickers, sector_master)

        result = self._create_message(prompt)
        result["llm_provider"] = "gemini"
        result["llm_model"] = self._model
        result["structuring_status"] = "success"
        return result
