"""ClaudeStructurerのテスト（layer3_news_processing_design.md §6・§7）。

実際のAnthropic APIは呼び出さず、`_create_message`をオーバーライドしたサブクラスで
プロンプト組み立て・結果組み立てロジックを検証する（このサンドボックス環境には
anthropicパッケージも専用APIキーも無いため）。
"""

import pytest

from ai_investment_assistant.layer3_news_processing.llm_structurer.claude_structurer import (
    ClaudeStructurer,
    build_prompt,
)


class FakeClaudeStructurer(ClaudeStructurer):
    def __init__(self, fake_response):
        super().__init__(api_key="fake-key")
        self._fake_response = fake_response
        self.last_prompt = None

    def _create_message(self, prompt):
        self.last_prompt = prompt
        return self._fake_response


def test_missing_api_key_raises_value_error():
    with pytest.raises(ValueError):
        ClaudeStructurer(api_key="")


def test_build_prompt_includes_headline_body_and_universe():
    article = {"headline": "トヨタ決算", "body": "本文"}
    prompt = build_prompt(article, [{"ticker": "7203", "name": "トヨタ自動車"}], ["automobile"])
    assert "トヨタ決算" in prompt
    assert "7203:トヨタ自動車" in prompt
    assert "automobile" in prompt


def test_build_prompt_handles_empty_universe():
    article = {"headline": "h", "body": "b"}
    prompt = build_prompt(article, [], [])
    assert "（なし）" in prompt


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
    structurer = FakeClaudeStructurer(fake_response)
    article = {"headline": "トヨタ決算発表", "body": "本文"}

    result = structurer.structure(article, universe_tickers=[{"ticker": "7203", "name": "トヨタ自動車"}])

    assert result["llm_provider"] == "claude"
    assert result["llm_model"] == "claude-haiku-4-5"
    assert result["structuring_status"] == "success"
    assert result["category"] == "earnings"
    assert structurer.last_prompt is not None
