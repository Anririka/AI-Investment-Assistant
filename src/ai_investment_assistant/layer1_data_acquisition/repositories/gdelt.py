"""GdeltRepository（NewsRepository実装）。

layer1_data_acquisition_design.md 10章確定事項1のとおり、本番運用の主力ニュース
ソース（`role: production_primary`）。GDELT 2.0 DOC APIはAPIキー不要。

注意（重要な制約）：GDELT DOC APIは記事の**メタデータのみ**（タイトル・URL・
掲載日・ドメイン）を返し、本文全文は提供しない。9章のPhase1完了基準7「本文・日時・
URLが取得できること」との整合は、`body`にタイトルを暫定的に流用する形とし、
実際に本文が必要になった時点（Layer3設計）で、`source_url`からの追加取得
（要ToS確認）や他ソースとの併用を検討する。この制約は本Repositoryの実装方針の
問題ではなく、GDELT DOC API自体の仕様である。
"""

from __future__ import annotations

from datetime import date, datetime

import requests

from ..exceptions import NotFoundError, RateLimitError, TransientError
from ..interfaces import NewsRepository
from ..models import RawNewsItem

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT_SECONDS = 30


class GdeltRepository(NewsRepository):
    """GDELT 2.0 DOC API（本番の主力ニュースソース、APIキー不要）。"""

    @classmethod
    def from_config(cls, entry: dict) -> "GdeltRepository":
        return cls()

    def fetch_news(self, query_or_tickers, since: date, until: date) -> list[RawNewsItem]:
        if isinstance(query_or_tickers, str):
            query = query_or_tickers
        else:
            query = " OR ".join(query_or_tickers)

        try:
            response = requests.get(
                BASE_URL,
                params={
                    "query": query,
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": 250,
                    "startdatetime": since.strftime("%Y%m%d%H%M%S"),
                    "enddatetime": until.strftime("%Y%m%d%H%M%S"),
                },
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"GDELT rate limit: {response.text}")
        if response.status_code == 400:
            raise NotFoundError(f"GDELT bad query (likely no results): {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"GDELT server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(f"GDELT unexpected status {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            # GDELTは結果0件のとき空文字列を返すことがある
            if not response.text.strip():
                return []
            raise TransientError(f"GDELT returned non-JSON response: {exc}") from exc

        items = []
        for article in payload.get("articles", []):
            seen_date_str = article.get("seendate", "")
            published_at = (
                datetime.strptime(seen_date_str, "%Y%m%dT%H%M%SZ")
                if seen_date_str
                else datetime.utcnow()
            )
            title = article.get("title", "")
            items.append(
                RawNewsItem(
                    title=title,
                    body=title,  # GDELT DOC APIは本文を提供しないため、暫定的にタイトルで代用
                    published_at=published_at,
                    source_url=article.get("url", ""),
                    source_name=article.get("domain", "gdelt"),
                )
            )
        return items
