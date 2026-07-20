"""NewsApiRepository（NewsRepository実装）。

layer1_data_acquisition_design.md 10章確定事項1のとおり、NewsAPIは
「開発・検証用途、およびGDELT障害時の補助用途」に限定する
（config/api_sources.yamlの`environment: development_only`フラグで可視化済み）。
本番の主力はGDELT（gdelt.py）。

注意：NewsAPIの無料/Developerプランは記事の全文(content)ではなく、冒頭の抜粋
（約200文字、末尾に"[+N chars]"が付く）しか返さない制約がある。本文全文が必要な
場合は将来的に有料プランへの移行を検討する（現時点ではLayer1の責務である
「取得できた範囲のRawNewsItemを正規化して返す」を満たせば十分とする）。
"""

from __future__ import annotations

import os
from datetime import date, datetime

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import NewsRepository
from ..models import RawNewsItem

BASE_URL = "https://newsapi.org/v2/everything"
TIMEOUT_SECONDS = 30


class NewsApiRepository(NewsRepository):
    """NewsAPI（開発・検証用途限定、本番の主力はGDELT）。"""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise AuthError("NEWSAPI_API_KEY is not set")
        self._api_key = api_key

    @classmethod
    def from_config(cls, entry: dict) -> "NewsApiRepository":
        return cls(api_key=os.environ.get("NEWSAPI_API_KEY", ""))

    def fetch_news(self, query_or_tickers, since: date, until: date) -> list[RawNewsItem]:
        if isinstance(query_or_tickers, str):
            query = query_or_tickers
        else:
            query = " OR ".join(query_or_tickers)

        try:
            response = requests.get(
                BASE_URL,
                headers={"X-Api-Key": self._api_key},
                params={
                    "q": query,
                    "from": since.isoformat(),
                    "to": until.isoformat(),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 100,
                },
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"NewsAPI rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"NewsAPI auth error {response.status_code}: {response.text}")
        if response.status_code == 400:
            raise NotFoundError(f"NewsAPI bad request (no results likely): {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"NewsAPI server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(f"NewsAPI unexpected status {response.status_code}: {response.text}")

        payload = response.json()
        if payload.get("status") != "ok":
            raise TransientError(f"NewsAPI returned non-ok status: {payload}")

        items = []
        for article in payload.get("articles", []):
            published_at_str = article.get("publishedAt", "")
            published_at = (
                datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%SZ")
                if published_at_str
                else datetime.utcnow()
            )
            items.append(
                RawNewsItem(
                    title=article.get("title", ""),
                    body=article.get("content") or article.get("description") or "",
                    published_at=published_at,
                    source_url=article.get("url", ""),
                    source_name=(article.get("source") or {}).get("name", "newsapi"),
                )
            )
        return items
