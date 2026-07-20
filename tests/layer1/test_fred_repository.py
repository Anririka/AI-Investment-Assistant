"""FredRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.fred import FredRepository


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        FredRepository(api_key="")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fred.requests.get")
def test_get_series_skips_missing_values(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "observations": [
                {"date": "2026-05-01", "value": "310.1"},
                {"date": "2026-06-01", "value": "."},  # 欠測値
                {"date": "2026-07-01", "value": "311.4"},
            ]
        },
    )
    repo = FredRepository(api_key="k")

    series = repo.get_series("CPIAUCSL", date(2026, 5, 1), date(2026, 7, 1))

    assert len(series.points) == 2  # 欠測値は除外される
    assert series.points[0].value == 310.1


@pytest.mark.parametrize(
    "status_code,expected_exception",
    [(401, AuthError), (403, AuthError), (400, NotFoundError), (429, RateLimitError)],
)
@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fred.requests.get")
def test_error_status_codes_map_to_expected_exceptions(mock_get, status_code, expected_exception):
    mock_get.return_value = FakeResponse(status_code, text="error")
    repo = FredRepository(api_key="k")

    with pytest.raises(expected_exception):
        repo.get_series("CPIAUCSL", date(2026, 5, 1), date(2026, 7, 1))
