"""structurer_factory.pyのテスト（layer3_news_processing_design.md §6のベンダー切り替え）。"""

import pytest

from ai_investment_assistant.layer3_news_processing.llm_structurer.claude_structurer import ClaudeStructurer
from ai_investment_assistant.layer3_news_processing.llm_structurer.gemini_structurer import GeminiStructurer
from ai_investment_assistant.layer3_news_processing.structurer_factory import build_structurer


def test_gemini_provider_builds_gemini_structurer(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config = {"news_structurer": {"provider": "gemini", "model": "gemini-2.5-flash-lite"}}
    structurer = build_structurer(config)
    assert isinstance(structurer, GeminiStructurer)


def test_claude_provider_builds_claude_structurer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    config = {"news_structurer": {"provider": "claude", "model": "claude-haiku-4-5"}}
    structurer = build_structurer(config)
    assert isinstance(structurer, ClaudeStructurer)


def test_unknown_provider_raises_value_error():
    config = {"news_structurer": {"provider": "unknown_vendor"}}
    with pytest.raises(ValueError):
        build_structurer(config)


def test_defaults_to_claude_when_provider_not_specified(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    structurer = build_structurer({"news_structurer": {}})
    assert isinstance(structurer, ClaudeStructurer)
