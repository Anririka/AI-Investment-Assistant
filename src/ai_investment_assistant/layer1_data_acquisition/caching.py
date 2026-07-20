"""CachingRepositoryDecorator（layer1_data_acquisition_design.md 6章・7章の確定仕様）。

任意のRepositoryをラップし、呼び出し前にキャッシュを確認する。
永続化先はGoogle Driveに一本化する設計（7-2）のため、`CacheStore`を抽象化し、
本番はGoogle Drive実装、テスト・ローカル開発はインメモリ実装を使えるようにする。
"""

from __future__ import annotations

import abc
import time
from datetime import date
from typing import Any, Callable, Optional


class CacheStore(abc.ABC):
    """キャッシュの永続化先を抽象化するインターフェース。"""

    @abc.abstractmethod
    def get(self, key: str) -> Optional[Any]:
        ...

    @abc.abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        ...


class InMemoryCacheStore(CacheStore):
    """実行内メモリキャッシュ（7-1の1.）。テスト・単一run内の重複排除に使う。

    本番の永続キャッシュ（Google Drive、7-1の2.）は別途`GoogleDriveCacheStore`等として
    実装し、同じ`CacheStore`インターフェースでこのクラスと差し替える。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._store: dict[str, tuple[Any, Optional[float]]] = {}
        self._clock = clock

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._clock() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        expires_at = self._clock() + ttl_seconds if ttl_seconds is not None else None
        self._store[key] = (value, expires_at)


class CachingRepositoryDecorator:
    """Repositoryの主要メソッド呼び出しを`(source, ticker, ...)`をキーにキャッシュする。

      確定済み日次データ（get_daily_prices） : TTLなし（7-2、一度取得したら再取得しない）
      ファンダメンタルデータ（get_fundamentals）: TTL 7日（7-2）
      ニュース（fetch_news）                  : キャッシュ対象外（7-2）、そのまま委譲する
    """

    FUNDAMENTALS_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, repository: Any, cache_store: CacheStore, source_name: str) -> None:
        self._repository = repository
        self._cache_store = cache_store
        self._source_name = source_name

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> Any:
        key = f"{self._source_name}:daily_prices:{ticker}:{start_date}:{end_date}"
        cached = self._cache_store.get(key)
        if cached is not None:
            return cached
        result = self._repository.get_daily_prices(ticker, start_date, end_date)
        self._cache_store.set(key, result)
        return result

    def get_fundamentals(self, ticker: str) -> Any:
        key = f"{self._source_name}:fundamentals:{ticker}"
        cached = self._cache_store.get(key)
        if cached is not None:
            return cached
        result = self._repository.get_fundamentals(ticker)
        self._cache_store.set(key, result, ttl_seconds=self.FUNDAMENTALS_TTL_SECONDS)
        return result

    def __getattr__(self, item: str) -> Any:
        # キャッシュ対象外のメソッド（fetch_news等）はそのまま委譲する（7-2）
        return getattr(self._repository, item)
