"""JQuantsRepositoryのテスト（requests.getをモックし、V2 APIキー方式を検証する）。

注意：ここでのレスポンスJSONの形は実装時点の想定であり、実際のV2 APIレスポンスとの
突合はまだ行えていない（jquants.pyのモジュールdocstring参照）。本テストは、想定した
形のレスポンスに対して本Repositoryのパース・正規化・エラー分類ロジックが正しく動作
することを保証するものである。
"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    TransientError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.jquants import JQuantsRepository


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        JQuantsRepository(api_key="")


def test_from_config_reads_env_var(monkeypatch):
    monkeypatch.setenv("JQUANTS_API_KEY", "test-key")
    repo = JQuantsRepository.from_config({"plan": "light", "price_delay_weeks": 0})
    assert repo.plan == "light"
    assert repo.is_delayed is False
    assert repo.delay_reason is None


def test_free_plan_sets_delay_flag():
    repo = JQuantsRepository(api_key="k", plan="free", price_delay_weeks=12)
    assert repo.is_delayed is True
    assert "12" in repo.delay_reason


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_daily_prices_parses_normalized_series(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "bars": [
                {"date": "2026-07-16", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 1_000_000},
                {"date": "2026-07-17", "open": 103.0, "high": 108.0, "low": 101.0, "close": 106.0, "volume": 1_200_000},
            ]
        },
    )
    repo = JQuantsRepository(api_key="k", plan="light", price_delay_weeks=0)

    series = repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))

    assert series.ticker == "7203"
    assert series.currency == "JPY"
    assert len(series.bars) == 2
    assert series.bars[0].close == 103.0
    assert series.meta.source_used == "jquants"
    assert series.meta.is_delayed is False

    called_headers = mock_get.call_args.kwargs["headers"]
    assert called_headers == {"x-api-key": "k"}


@pytest.mark.parametrize(
    "status_code,expected_exception",
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, TransientError),
        (503, TransientError),
    ],
)
@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_error_status_codes_map_to_expected_exceptions(mock_get, status_code, expected_exception):
    mock_get.return_value = FakeResponse(status_code, text="error detail")
    repo = JQuantsRepository(api_key="k")

    with pytest.raises(expected_exception):
        repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_listed_universe_parses_ticker_info(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "equities": [
                {"code": "7203", "name": "トヨタ自動車", "sector_code": "3700", "market": "プライム", "market_cap": 4.0e13}
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    universe = repo.get_listed_universe()

    assert len(universe) == 1
    assert universe[0].ticker == "7203"
    assert universe[0].name == "トヨタ自動車"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_trading_calendar_filters_non_trading_days(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "calendar": [
                {"date": "2026-07-17", "is_trading_day": True},
                {"date": "2026-07-18", "is_trading_day": False},
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    calendar = repo.get_trading_calendar()

    assert calendar == [date(2026, 7, 17)]


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_earnings_calendar_parses_events(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {"events": [{"code": "7203", "date": "2026-08-05", "is_confirmed": True}]},
    )
    repo = JQuantsRepository(api_key="k")

    events = repo.get_earnings_calendar()

    assert len(events) == 1
    assert events[0].ticker == "7203"
    assert events[0].is_confirmed is True


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_connection_error_raises_transient_error(mock_get):
    import requests

    mock_get.side_effect = requests.ConnectionError("boom")
    repo = JQuantsRepository(api_key="k")

    with pytest.raises(TransientError):
        repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))
