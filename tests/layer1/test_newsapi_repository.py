"""NewsApiRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import AuthError, RateLimitError
from ai_investment_assistant.layer1_data_acquisition.repositories.newsapi import NewsApiRepository


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        NewsApiRepository(api_key="")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.newsapi.requests.get")
def test_fetch_news_parses_articles(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "status": "ok",
            "articles": [
                {
                    "title": "Sample headline",
                    "content": "Some content [+120 chars]",
                    "publishedAt": "2026-07-17T09:00:00Z",
                    "url": "https://example.com/a",
                    "source": {"name": "Example News"},
                }
            ],
        },
    )
    repo = NewsApiRepository(api_key="k")

    items = repo.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))

    assert len(items) == 1
    assert items[0].title == "Sample headline"
    assert items[0].source_name == "Example News"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.newsapi.requests.get")
def test_rate_limit_status_raises(mock_get):
    mock_get.return_value = FakeResponse(429, text="rate limited")
    repo = NewsApiRepository(api_key="k")

    with pytest.raises(RateLimitError):
        repo.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.newsapi.requests.get")
def test_joins_multiple_tickers_with_or(mock_get):
    mock_get.return_value = FakeResponse(200, {"status": "ok", "articles": []})
    repo = NewsApiRepository(api_key="k")

    repo.fetch_news(["7203", "6758"], date(2026, 7, 1), date(2026, 7, 17))

    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["q"] == "7203 OR 6758"
