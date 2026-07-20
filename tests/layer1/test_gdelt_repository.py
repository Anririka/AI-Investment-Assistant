"""GdeltRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import NotFoundError
from ai_investment_assistant.layer1_data_acquisition.repositories.gdelt import GdeltRepository


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def test_no_api_key_required():
    # GDELTはAPIキー不要（fromでインスタンス化できることのみ確認）
    repo = GdeltRepository()
    assert repo is not None


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.gdelt.requests.get")
def test_fetch_news_parses_articles(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "articles": [
                {
                    "title": "サンプル記事",
                    "seendate": "20260717T090000Z",
                    "url": "https://example.co.jp/a",
                    "domain": "example.co.jp",
                }
            ]
        },
    )
    repo = GdeltRepository()

    items = repo.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))

    assert len(items) == 1
    assert items[0].title == "サンプル記事"
    assert items[0].body == "サンプル記事"  # GDELTは本文非提供のためタイトルで代用
    assert items[0].source_name == "example.co.jp"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.gdelt.requests.get")
def test_empty_text_response_returns_empty_list(mock_get):
    mock_get.return_value = FakeResponse(200, json_data=None, text="")
    repo = GdeltRepository()

    items = repo.fetch_news(["NOMATCH"], date(2026, 7, 1), date(2026, 7, 17))

    assert items == []


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.gdelt.requests.get")
def test_bad_request_raises_not_found(mock_get):
    mock_get.return_value = FakeResponse(400, text="bad query")
    repo = GdeltRepository()

    with pytest.raises(NotFoundError):
        repo.fetch_news(["7203"], date(2026, 7, 1), date(2026, 7, 17))
