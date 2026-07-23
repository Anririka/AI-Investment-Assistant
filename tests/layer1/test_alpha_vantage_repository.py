"""AlphaVantageRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage import (
    AlphaVantageRepository,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        AlphaVantageRepository(api_key="")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_get_daily_prices_filters_by_date_range_and_sorts(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "Time Series (Daily)": {
                "2026-07-17": {"1. open": "103", "2. high": "108", "3. low": "101", "4. close": "106", "5. volume": "1200000"},
                "2026-07-16": {"1. open": "100", "2. high": "105", "3. low": "98", "4. close": "103", "5. volume": "1000000"},
                "2026-06-01": {"1. open": "90", "2. high": "95", "3. low": "88", "4. close": "92", "5. volume": "900000"},
            }
        },
    )
    repo = AlphaVantageRepository(api_key="k")

    series = repo.get_daily_prices("AAPL", date(2026, 7, 16), date(2026, 7, 17))

    assert series.currency == "USD"
    assert len(series.bars) == 2
    assert series.bars[0].date == date(2026, 7, 16)  # 日付順にソートされる
    assert series.bars[1].date == date(2026, 7, 17)


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_note_field_raises_rate_limit_error(mock_get):
    mock_get.return_value = FakeResponse(200, {"Note": "Thank you for using Alpha Vantage! ..."})
    repo = AlphaVantageRepository(api_key="k")

    with pytest.raises(RateLimitError):
        repo.get_daily_prices("AAPL", date(2026, 7, 16), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_error_message_field_raises_not_found_error(mock_get):
    mock_get.return_value = FakeResponse(200, {"Error Message": "Invalid API call"})
    repo = AlphaVantageRepository(api_key="k")

    with pytest.raises(NotFoundError):
        repo.get_daily_prices("BADTICKER", date(2026, 7, 16), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_get_fundamentals_parses_overview(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "LatestQuarter": "2026-06-30",
            "EPS": "6.5",
            "BookValue": "4.2",
            "RevenueTTM": "400000000000",
            "DividendPerShare": "1.0",
            "MarketCapitalization": "3000000000000",
        },
    )
    repo = AlphaVantageRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    assert snapshot.eps == 6.5
    assert snapshot.revenue == 400000000000.0
    assert snapshot.net_income is None  # OVERVIEWからは取得しない設計
    # 2026-07-23追加：net_incomeが常時取得不能なため、min_market_cap screeningの
    # ための時価総額はOVERVIEWが直接提供するMarketCapitalizationから取得する
    # （run_daily_pipeline.pyのnet_income/EPSベースの近似計算に頼らずに済む）。
    assert snapshot.market_cap == 3_000_000_000_000.0


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_get_fundamentals_market_cap_missing_defaults_to_none(mock_get):
    mock_get.return_value = FakeResponse(200, {"LatestQuarter": "2026-06-30"})
    repo = AlphaVantageRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    assert snapshot.market_cap is None


def test_get_trading_calendar_raises_not_implemented():
    repo = AlphaVantageRepository(api_key="k")
    with pytest.raises(NotImplementedError):
        repo.get_trading_calendar()


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_get_listed_universe_parses_csv(mock_get):
    mock_get.return_value = FakeResponse(
        200, text="symbol,name,exchange,assetType,ipoDate,delistingDate,status\n"
        "AAPL,Apple Inc,NASDAQ,Stock,1980-12-12,,Active\n"
    )
    repo = AlphaVantageRepository(api_key="k")

    universe = repo.get_listed_universe()

    assert len(universe) == 1
    assert universe[0].ticker == "AAPL"
    assert universe[0].market == "NASDAQ"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.alpha_vantage.requests.get")
def test_get_earnings_calendar_parses_csv(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        text="symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        "AAPL,Apple Inc,2026-08-05,2026-06-30,1.5,USD\n",
    )
    repo = AlphaVantageRepository(api_key="k")

    events = repo.get_earnings_calendar()

    assert len(events) == 1
    assert events[0].ticker == "AAPL"
    assert events[0].announcement_date == date(2026, 8, 5)
