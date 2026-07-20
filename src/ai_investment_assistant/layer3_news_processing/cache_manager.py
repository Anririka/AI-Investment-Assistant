"""処理済み記事のキャッシュ管理（layer3_news_processing_design.md §5）。

同一記事を複数日にわたって重複構造化しないためのキャッシュ。Layer1の`CacheStore`
インターフェース（`InMemoryCacheStore`／`GoogleDriveCacheStore`、Layer1詳細設計書§7）を
そのまま再利用する。構造化結果自体にはTTLを設けない（一度確定した分類は変化しないため）。
`age_hours`だけはキャッシュから読み出す都度、現在時刻基準で再計算する（§5、main.py側の責務）。
"""

from __future__ import annotations

from typing import Optional

from ..layer1_data_acquisition.caching import CacheStore

CACHE_KEY_PREFIX = "news_structured"


def get_cached(cache_store: CacheStore, item_id: str) -> Optional[dict]:
    return cache_store.get(f"{CACHE_KEY_PREFIX}:{item_id}")


def store_cached(cache_store: CacheStore, item_id: str, structured_item: dict) -> None:
    cache_store.set(f"{CACHE_KEY_PREFIX}:{item_id}", structured_item)  # TTLなし（§5）
