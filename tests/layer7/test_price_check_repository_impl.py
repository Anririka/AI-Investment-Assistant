"""LookbackPriceCheckRepositoryのテスト（layer7_proposal_tracking_design.md §7-2・§7-3）。"""

from datetime import date

import pytest

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer7_proposal_tracking.repository.price_check_repository_impl import (
    LookbackPriceCheckRepository,
    infer_asset_class,
)


class FakeChain:
    def __init__(self, bars):
        self._bars = bars
        self.calls = []

    def get_daily_prices(self, ticker, start_date, end_date):
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
