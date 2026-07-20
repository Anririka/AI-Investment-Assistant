"""RepositoryFactoryのテスト（layer1_data_acquisition_design.md 3-2・3-3の確定仕様）。"""

import pytest

from ai_investment_assistant.layer1_data_acquisition.caching import InMemoryCacheStore
from ai_investment_assistant.layer1_data_acquisition.factory import (
    RepositoryFactory,
    UnimplementedRepositoryError,
)
from ai_investment_assistant.layer1_data_acquisition.fallback import FallbackChainRepository


def test_build_chain_for_japan_equity_uses_jquants(monkeypatch):
    monkeypatch.setenv("JQUANTS_API_KEY", "test-key")
    config = {
        "japan_equity": {
            "chain": [
                {"name": "jquants", "plan": "light", "price_delay_weeks": 0, "rate_limit_per_minute": 60},
                {"name": "web_search_fallback"},  # 未実装なのでスキップされるはず
            ]
        }
    }
    factory = RepositoryFactory(config, cache_store=InMemoryCacheStore())

    chain = factory.build_chain("japan_equity")

    assert isinstance(chain, FallbackChainRepository)
    assert len(chain._candidates) == 1  # web_search_fallbackは未実装のため除外される
    assert chain._candidates[0].name == "jquants"


def test_build_chain_raises_for_unknown_data_type():
    factory = RepositoryFactory({}, cache_store=InMemoryCacheStore())

    with pytest.raises(KeyError):
        factory.build_chain("nonexistent_type")


def test_build_chain_raises_when_no_implemented_repository_in_chain():
    config = {"some_type": {"chain": [{"name": "web_search_fallback"}]}}
    factory = RepositoryFactory(config, cache_store=InMemoryCacheStore())

    with pytest.raises(UnimplementedRepositoryError):
        factory.build_chain("some_type")


def test_build_chain_for_us_equity_uses_alpha_vantage_and_twelve_data(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "av-key")
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "td-key")
    config = {
        "us_equity": {
            "chain": [
                {"name": "alpha_vantage", "rate_limit_per_minute": 5},
                {"name": "twelve_data"},
            ]
        }
    }
    factory = RepositoryFactory(config, cache_store=InMemoryCacheStore())

    chain = factory.build_chain("us_equity")

    names = [c.name for c in chain._candidates]
    assert names == ["alpha_vantage", "twelve_data"]


def test_build_chain_for_macro_uses_fred(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fred-key")
    config = {"macro": {"chain": [{"name": "fred"}]}}
    factory = RepositoryFactory(config, cache_store=InMemoryCacheStore())

    chain = factory.build_chain("macro")

    assert chain._candidates[0].name == "fred"


def test_build_chain_for_news_uses_newsapi_and_gdelt(monkeypatch):
    monkeypatch.setenv("NEWSAPI_API_KEY", "news-key")
    config = {
        "news": {
            "chain": [
                {"name": "newsapi", "environment": "development_only"},
                {"name": "gdelt"},
            ]
        }
    }
    factory = RepositoryFactory(config, cache_store=InMemoryCacheStore())

    chain = factory.build_chain("news")

    names = [c.name for c in chain._candidates]
    assert names == ["newsapi", "gdelt"]
