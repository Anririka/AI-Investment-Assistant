"""cache_manager.pyのテスト（layer3_news_processing_design.md §5）。

同一記事の2回目の処理でLLM呼び出しがスキップされること（§13）を、main.pyの
統合テスト（test_main.py）で確認する。ここではcache_manager単体のget/set動作を検証する。
"""

from ai_investment_assistant.layer1_data_acquisition.caching import InMemoryCacheStore
from ai_investment_assistant.layer3_news_processing.cache_manager import get_cached, store_cached


def test_get_cached_returns_none_when_not_stored():
    store = InMemoryCacheStore()
    assert get_cached(store, "sha256:abc") is None


def test_store_then_get_returns_the_same_item():
    store = InMemoryCacheStore()
    item = {"headline": "h", "category": "earnings"}
    store_cached(store, "sha256:abc", item)
    assert get_cached(store, "sha256:abc") == item


def test_different_item_ids_do_not_collide():
    store = InMemoryCacheStore()
    store_cached(store, "sha256:a", {"headline": "A"})
    store_cached(store, "sha256:b", {"headline": "B"})
    assert get_cached(store, "sha256:a")["headline"] == "A"
    assert get_cached(store, "sha256:b")["headline"] == "B"
