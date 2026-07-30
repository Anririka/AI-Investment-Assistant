"""LookbackPriceCheckRepositoryのテスト（layer7_proposal_tracking_design.md §7-2・§7-3）。"""

from datetime import date

import pytest

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer7_proposal_tracking.repository.price_check_repository_impl import (
    LookbackPriceCheckRepository,
    infer_asset_class,
)


class FakeChain:
    """実物の`FallbackChainRepository`と同じインターフェース（`call(method_name, *args)`
    のみを公開し、`get_daily_prices`等の直接メソッドは持たない）を模したフェイク。

    2026-07-26追加：以前のFakeChainは`get_daily_prices`を直接のメソッドとして持って
    いたため、`LookbackPriceCheckRepository`側の実装ミス（`chain.get_daily_prices(...)`
    という、実物には存在しない直接呼び出し）を単体テストで検知できなかった
    （実地検証で`AttributeError`として発覚。price_check_repository_impl.py参照）。
    """

    def __init__(self, bars):
        self._bars = bars
        self.calls = []

    def call(self, method_name, *args, **kwargs):
        assert method_name == "get_daily_prices"
        ticker, start_date, end_date = args
        self.calls.append((ticker, start_date, end_date))
        return PriceSeries(
            ticker=ticker, currency="USD", bars=tuple(self._bars),
            meta=DataFetchMeta(source_used="fake", fetched_at=None),
        )


def test_get_latest_price_returns_most_recent_bar():
    bars = [
        PriceBar(date=date(2026, 7, 16), open=1, high=2, low=0.5, close=1.5, volume=100),
        PriceBar(date=date(2026, 7, 18), open=1, high=3, low=0.8, close=2.5, volume=200),
        PriceBar(date=date(2026, 7, 17), open=1, high=2.5, low=0.6, close=2.0, volume=150),
    ]
    chain = FakeChain(bars)
    repo = LookbackPriceCheckRepository({"us_equity": chain}, clock=lambda: date(2026, 7, 18))
    snapshot = repo.get_latest_price("NVDA", "us_equity")
    assert snapshot.date == date(2026, 7, 18)
    assert snapshot.close == 2.5
    assert snapshot.high == 3
    assert snapshot.low == 0.8
    assert snapshot.volume == 200


def test_get_latest_price_raises_when_no_bars_returned():
    repo = LookbackPriceCheckRepository({"us_equity": FakeChain([])})
    with pytest.raises(ValueError):
        repo.get_latest_price("NVDA", "us_equity")


def test_get_latest_price_raises_when_asset_class_not_configured():
    repo = LookbackPriceCheckRepository({"us_equity": FakeChain([])})
    with pytest.raises(ValueError):
        repo.get_latest_price("7203", "japan_equity")


def test_infer_asset_class_numeric_ticker_is_japan_equity():
    assert infer_asset_class("7203") == "japan_equity"


def test_infer_asset_class_alpha_ticker_is_us_equity():
    assert infer_asset_class("NVDA") == "us_equity"


class FakeFactory:
    """`RepositoryFactory.build_chain(data_type)`呼び出しを記録するフェイク。"""

    def __init__(self):
        self.requested_data_types = []

    def build_chain(self, data_type):
        self.requested_data_types.append(data_type)
        return f"chain-for-{data_type}"


def test_from_repository_factory_uses_us_equity_bulk_price_not_us_equity():
    # 2026-07-31追加（実運用ログ調査で発覚）：Layer7は価格のみ必要でファンダメンタルズは
    # 取得しないにもかかわらず、以前はus_equityチェーン（先頭候補alpha_vantage、
    # Layer2第2段階用に予約された25回/日枠）を使っており、毎営業日15:30 JSTの保有銘柄
    # チェックのたびにこの枠を気づかないうちに消費していた。twelve_dataのみの
    # us_equity_bulk_priceチェーンを使うよう修正したことを検証する。
    factory = FakeFactory()

    repo = LookbackPriceCheckRepository.from_repository_factory(factory)

    assert factory.requested_data_types == ["japan_equity", "us_equity_bulk_price"]
    assert repo._chains["us_equity"] == "chain-for-us_equity_bulk_price"
    assert repo._chains["japan_equity"] == "chain-for-japan_equity"
