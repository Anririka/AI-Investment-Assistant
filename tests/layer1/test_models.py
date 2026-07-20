"""models.pyの正規化スキーマの基本的な構築テスト。"""

from datetime import date, datetime

from ai_investment_assistant.layer1_data_acquisition.models import (
    DataFetchMeta,
    EarningsEvent,
    FundamentalSnapshot,
    PriceBar,
    PriceSeries,
    RawNewsItem,
    TickerInfo,
    TimeSeries,
    TimeSeriesPoint,
)


def test_price_series_construction():
    meta = DataFetchMeta(source_used="jquants", fetched_at=datetime(2026, 7, 20, 9, 0, 0))
    bar = PriceBar(date=date(2026, 7, 17), open=100.0, high=110.0, low=95.0, close=105.0, volume=1000)
    series = PriceSeries(ticker="7203", currency="JPY", bars=(bar,), meta=meta)

    assert series.ticker == "7203"
    assert series.bars[0].close == 105.0
    assert series.meta.source_used == "jquants"


def test_data_fetch_meta_defaults():
    meta = DataFetchMeta(source_used="alpha_vantage", fetched_at=datetime(2026, 7, 20))
    assert meta.is_delayed is False
    assert meta.delay_reason is None
    assert meta.success is True


def test_fundamental_snapshot_allows_missing_values():
    meta = DataFetchMeta(source_used="jquants", fetched_at=datetime(2026, 7, 20))
    snapshot = FundamentalSnapshot(
        ticker="7203",
        fiscal_period="2026Q1",
        eps=120.5,
        net_assets=None,
        net_income=None,
        revenue=None,
        operating_income=None,
        operating_cash_flow=None,
        capital_expenditure=None,
        interest_bearing_debt=None,
        total_assets=None,
        dividend=None,
        meta=meta,
    )
    assert snapshot.eps == 120.5
    assert snapshot.net_assets is None


def test_ticker_info_and_earnings_event():
    info = TickerInfo(ticker="7203", name="トヨタ自動車", sector_code="3700", market="プライム", market_cap=1.0e13)
    assert info.name == "トヨタ自動車"

    event = EarningsEvent(ticker="7203", announcement_date=date(2026, 8, 1), is_confirmed=True)
    assert event.is_confirmed is True


def test_raw_news_item_and_time_series():
    news = RawNewsItem(
        title="サンプル記事",
        body="本文",
        published_at=datetime(2026, 7, 20, 8, 0, 0),
        source_url="https://example.com/1",
        source_name="GDELT",
    )
    assert news.source_name == "GDELT"

    meta = DataFetchMeta(source_used="fred", fetched_at=datetime(2026, 7, 20))
    series = TimeSeries(
        series_id="CPIAUCSL",
        points=(TimeSeriesPoint(date=date(2026, 6, 1), value=310.5),),
        meta=meta,
    )
    assert series.points[0].value == 310.5
