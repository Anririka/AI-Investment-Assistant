"""TwelveDataRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data import (
    TwelveDataRepository,
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
        TwelveDataRepository(api_key="")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_get_daily_prices_parses_values(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "values": [
                {"datetime": "2026-07-17", "open": "103", "high": "108", "low": "101", "close": "106", "volume": "1200000"},
                {"datetime": "2026-07-16", "open": "100", "high": "105", "low": "98", "close": "103", "volume": "1000000"},
            ],
            "status": "ok",
        },
    )
    repo = TwelveDataRepository(api_key="k")

    series = repo.get_daily_prices("AAPL", date(2026, 7, 16), date(2026, 7, 17))

    assert series.currency == "USD"
    assert len(series.bars) == 2


@pytest.mark.parametrize(
    "code,expected_exception",
    [(429, RateLimitError), (401, AuthError), (403, AuthError), (404, NotFoundError)],
)
@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_status_error_field_maps_to_exceptions(mock_get, code, expected_exception):
    mock_get.return_value = FakeResponse(200, {"status": "error", "code": code, "message": "boom"})
    repo = TwelveDataRepository(api_key="k")

    with pytest.raises(expected_exception):
        repo.get_daily_prices("AAPL", date(2026, 7, 16), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_get_listed_universe_parses_data(mock_get):
    mock_get.return_value = FakeResponse(
        200, {"data": [{"symbol": "AAPL", "name": "Apple Inc", "exchange": "NASDAQ"}]}
    )
    repo = TwelveDataRepository(api_key="k")

    universe = repo.get_listed_universe()

    assert universe[0].ticker == "AAPL"
    assert universe[0].market == "NASDAQ"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_get_fundamentals_parses_statistics_and_coerces_strings_to_float(mock_get):
    """2026-07-23追加：J-Quantsで数値項目が文字列で返り、そのまま演算してTypeErrorに
    なった実例（jquants.py参照）と同じ問題を防ぐため、Twelve Data側も文字列で来ても
    floatへ変換されることを確認する。あわせて、米国株のmarket_cap常時取得不能問題への
    対応として追加した`market_capitalization`のマッピングも検証する。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "statistics": {
                "financials": {
                    "fiscal_period": "2026Q2",
                    "net_income": "9.4e10",
                    "revenue_ttm": "3.8e11",
                    "operating_income": "1.2e11",
                    "operating_cash_flow": "1.1e11",
                    "capital_expenditures": "1.0e10",
                    "total_debt": "9.0e10",
                    "total_assets": "3.5e11",
                },
                "valuations_metrics": {
                    "eps": "6.5",
                    "book_value_per_share": "4.2",
                    "dividend_per_share": "1.0",
                    "market_capitalization": "3000000000000",
                },
            }
        },
    )
    repo = TwelveDataRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    assert snapshot.eps == 6.5
    assert isinstance(snapshot.eps, float)
    assert snapshot.net_income == 9.4e10
    assert isinstance(snapshot.net_income, float)
    assert snapshot.market_cap == 3_000_000_000_000.0


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_get_fundamentals_missing_statistics_returns_all_none(mock_get):
    mock_get.return_value = FakeResponse(200, {})
    repo = TwelveDataRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    assert snapshot.eps is None
    assert snapshot.market_cap is None


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.twelve_data.requests.get")
def test_get_earnings_calendar_parses_events(mock_get):
    mock_get.return_value = FakeResponse(
        200, {"symbol": "AAPL", "earnings": [{"date": "2026-08-05", "eps_actual": None}]}
    )
    repo = TwelveDataRepository(api_key="k")

    events = repo.get_earnings_calendar()

    assert events[0].ticker == "AAPL"
    assert events[0].is_confirmed is False


def test_get_trading_calendar_raises_not_implemented():
    repo = TwelveDataRepository(api_key="k")
    with pytest.raises(NotImplementedError):
        repo.get_trading_calendar()
