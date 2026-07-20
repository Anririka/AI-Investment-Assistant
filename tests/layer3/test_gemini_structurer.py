"""GeminiStructurerのテスト（layer3_news_processing_design.md §6、コスト最適化のための代替実装）。

実際のGemini APIは呼び出さず、`_create_message`をオーバーライドしたサブクラスで
プロンプト組み立て・結果組み立てロジックを検証する（このサンドボックス環境には
google-genaiパッケージも専用APIキーも無いため）。
"""

import pytest

from ai_investment_assistant.layer3_news_processing.llm_structurer.gemini_structurer import (
    GeminiStructurer,
    build_prompt,
)


class FakeGeminiStructurer(GeminiStructurer):
    def __init__(self, fake_response):
        super().__init__(api_key="fake-key")
        self._fake_response = fake_response
        self.last_prompt = None

    def _create_message(self, prompt):
        self.last_prompt = prompt
        return self._fake_response


def test_missing_api_key_raises_value_error():
    with pytest.raises(ValueError):
        GeminiStructurer(api_key="")


def test_default_model_is_flash_lite():
    structurer = FakeGeminiStructurer({})
    assert structurer._model == "gemini-2.5-flash-lite"


def test_from_config_reads_env_var_and_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    structurer = GeminiStructurer.from_config({"model": "gemini-3.1-flash-lite"})
    assert structurer._model == "gemini-3.1-flash-lite"


def test_structure_assembles_llm_metadata_fields():
    fake_response = {
        "category": "earnings",
        "affected_companies": [{"ticker": "7203", "name": "トヨタ自動車", "relevance": "primary"}],
        "affected_sectors": ["automobile"],
        "impact_direction": "positive",
        "impact_horizon": "mid_term",
        "importance": 75,
        "confidence": 0.8,
        "confidence_reason": "決算短信から直接引用",
        "summary": "トヨタが増収増益の決算を発表。",
    }
    structurer = FakeGeminiStructurer(fake_response)
    article = {"headline": "トヨタ決算発表", "body": "本文"}

    result = structurer.structure(article, universe_tickers=[{"ticker": "7203", "name": "トヨタ自動車"}])

    assert result["llm_provider"] == "gemini"
    assert result["llm_model"] == "gemini-2.5-flash-lite"
    assert result["structuring_status"] == "success"
    assert result["category"] == "earnings"
    assert structurer.last_prompt is not None


def test_build_prompt_is_vendor_neutral_and_shared_with_claude():
    from ai_investment_assistant.layer3_news_processing.llm_structurer.claude_structurer import (
        build_prompt as claude_build_prompt,
    )

    article = {"headline": "h", "body": "b"}
    assert build_prompt is claude_build_prompt  # 同一の共有プロンプト関数を使っている
