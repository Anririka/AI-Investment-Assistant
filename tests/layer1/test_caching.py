"""CachingRepositoryDecorator / InMemoryCacheStoreのテスト（6章・7章の挙動を検証）。"""

from datetime import date

from ai_investment_assistant.layer1_data_acquisition.caching import (
    CachingRepositoryDecorator,
    InMemoryCacheStore,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeRepo:
    def __init__(self):
        self.daily_prices_calls = 0
        self.fundamentals_calls = 0
        self.fetch_news_calls = 0

    def get_daily_prices(self, ticker, start_date, end_date):
        self.daily_prices_calls += 1
        return f"prices-for-{ticker}"

    def get_fundamentals(self, ticker):
        self.fundamentals_calls += 1
        return f"fundamentals-for-{ticker}"

    def fetch_news(self, query_or_tickers, since, until):
        self.fetch_news_calls += 1
        return ["news-item"]


def test_in_memory_cache_store_hit_and_miss():
    store = InMemoryCacheStore()
    assert store.get("k") is None

    store.set("k", "v")
    assert store.get("k") == "v"


def test_in_memory_cache_store_ttl_expiry():
    clock = FakeClock()
    store = InMemoryCacheStore(clock=clock)

    store.set("k", "v", ttl_seconds=10)
    clock.now = 5
    assert store.get("k") == "v"

    clock.now = 11
    assert store.get("k") is None


def test_daily_prices_are_cached_without_ttl_second_call_hits_cache():
    repo = FakeRepo()
    store = InMemoryCacheStore()
    decorated = CachingRepositoryDecorator(repo, store, source_name="jquants")

    first = decorated.get_daily_prices("7203", date(2026, 7, 1), date(2026, 7, 17))
    second = decorated.get_daily_prices("7203", date(2026, 7, 1), date(2026, 7, 17))

    assert first == second == "prices-for-7203"
    assert repo.daily_prices_calls == 1  # 2回目はキャッシュから返り、API呼び出しは発生しない


def test_fundamentals_are_cached_with_seven_day_ttl():
    repo = FakeRepo()
    clock = FakeClock()
    store = InMemoryCacheStore(clock=clock)
    decorated = CachingRepositoryDecorator(repo, store, source_name="jquants")

    decorated.get_fundamentals("7203")
    decorated.get_fundamentals("7203")
    assert repo.fundamentals_calls == 1

    clock.now = CachingRepositoryDecorator.FUNDAMENTALS_TTL_SECONDS + 1
    decorated.get_fundamentals("7203")
    assert repo.fundamentals_calls == 2  # TTL経過後は再取得される


def test_fetch_news_is_not_cached_delegates_every_call():
    repo = FakeRepo()
    store = InMemoryCacheStore()
    decorated = CachingRepositoryDecorator(repo, store, source_name="newsapi")

    decorated.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))
    decorated.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))

    assert repo.fetch_news_calls == 2  # 毎回委譲される（キャッシュ対象外）


def test_different_tickers_use_different_cache_keys():
    repo = FakeRepo()
    store = InMemoryCacheStore()
    decorated = CachingRepositoryDecorator(repo, store, source_name="jquants")

    decorated.get_daily_prices("7203", date(2026, 7, 1), date(2026, 7, 17))
    decorated.get_daily_prices("6758", date(2026, 7, 1), date(2026, 7, 17))

    assert repo.daily_prices_calls == 2
