"""TwelveDataRepository（MarketDataRepository実装、米国株の大量スクリーニング主力）。

layer1_data_acquisition_design.md 6-2確定方針の「まずTwelve Dataで広くスクリーニング」
の主力Repository。Alpha Vantageと異なりJSON APIで統一されている。

注意：レスポンスJSONのフィールド名は、Twelve Data公式ドキュメントの二次情報から
実装したものであり、実際のライブAPIレスポンスとは未照合。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Optional

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import MarketDataRepository
from ..models import DataFetchMeta, EarningsEvent, FundamentalSnapshot, PriceBar, PriceSeries, TickerInfo

BASE_URL = "https://api.twelvedata.com"
TIMEOUT_SECONDS = 30


class TwelveDataRepository(MarketDataRepository):
    """Twelve Data API（米国株、広範スクリーニングの主力）。"""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise AuthError("TWELVE_DATA_API_KEY is not set")
        self._api_key = api_key

    @classmethod
    def from_config(cls, entry: dict) -> "TwelveDataRepository":
        return cls(api_key=os.environ.get("TWELVE_DATA_API_KEY", ""))

    def _request(self, path: str, params: dict[str, Any]) -> dict:
        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                params={**params, "apikey": self._api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except (
            requests.ConnectionError,
            requests.Timeout,
            # 2026-08-26追加（実運用ログで発覚：SNAPSHOT_MISSING「Response ended
            # prematurely」が2日連続で発生し、us_equity_bulk_price stage1が丸ごと
            # blocked扱いになった件の根本対応）。ChunkedEncodingErrorは
            # urllib3のProtocolError（"Response ended prematurely"＝サーバー側が
            # レスポンス送信を完了する前に接続を切った場合）をrequestsが再送出する例外で、
            # requests.ConnectionErrorのサブクラスではないため、これまでの
            # except節では捕捉されずTransientErrorに変換されないまま素通りしていた。
            # 725銘柄規模・約63分のbulk scan中に1回でも発生すると、本来「1銘柄だけ
            # 静かに除外して継続する」設計（_fetch_bulk_prices docstring参照）が働かず、
            # 未捕捉のまま呼び出し元の一番外側まで伝播し、米国株スキャン全体が
            # critical（SNAPSHOT_MISSING）として扱われてしまっていた。
            # ContentDecodingErrorも同種（レスポンスボディの展開に失敗する一時的な
            # 通信起因のエラー）のため合わせて含める。
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        ) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"Twelve Data rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"Twelve Data auth error {response.status_code}: {response.text}")
        if response.status_code == 404:
            raise NotFoundError(f"Twelve Data not found: {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"Twelve Data server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(
                f"Twelve Data unexpected status {response.status_code}: {response.text}"
            )

        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            code = payload.get("code")
            message = payload.get("message", "")
            if code == 429:
                raise RateLimitError(message)
            if code in (401, 403):
                raise AuthError(message)
            if code == 404:
                raise NotFoundError(message)
            raise TransientError(f"Twelve Data error {code}: {message}")
        return payload

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> PriceSeries:
        payload = self._request(
            "/time_series",
            {
                "symbol": ticker,
                "interval": "1day",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        bars = tuple(
            PriceBar(
                date=datetime.strptime(row["datetime"], "%Y-%m-%d").date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(float(row.get("volume", 0) or 0)),
            )
            for row in payload.get("values", [])
        )
        meta = DataFetchMeta(source_used="twelve_data", fetched_at=datetime.utcnow())
        return PriceSeries(ticker=ticker, currency="USD", bars=bars, meta=meta)

    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        payload = self._request("/statistics", {"symbol": ticker})
        stats = payload.get("statistics", {})
        financials = stats.get("financials", {})
        valuations = stats.get("valuations_metrics", {})

        def _get(d: dict, *keys: str) -> Optional[Any]:
            for key in keys:
                if key in d and d[key] not in (None, ""):
                    return d[key]
            return None

        def _to_float(value: Optional[Any]) -> Optional[float]:
            # 2026-07-23追加：J-Quants側で数値項目が文字列で返り、そのまま演算に
            # 使ってTypeErrorになった実例があった（jquants.py参照）ため、こちらも
            # 同様に明示的なfloat変換で防御する（未ライブ検証のためTwelve Dataでも
            # 同じ形になる可能性を考慮）。
            if value in (None, "", "None", "-"):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        meta = DataFetchMeta(source_used="twelve_data", fetched_at=datetime.utcnow())
        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=_get(financials, "fiscal_period") or "",
            # Twelve Dataの/statisticsはベンダー固有の深いネスト構造のため、EPSは
            # valuations_metrics側の値で代用する（要ライブ検証、コメント参照）。
            eps=_to_float(_get(valuations, "eps", "trailing_eps")),
            net_assets=_to_float(_get(valuations, "book_value_per_share")),
            net_income=_to_float(_get(financials, "net_income")),
            revenue=_to_float(_get(financials, "revenue_ttm", "revenue")),
            operating_income=_to_float(_get(financials, "operating_income")),
            operating_cash_flow=_to_float(_get(financials, "operating_cash_flow")),
            capital_expenditure=_to_float(_get(financials, "capital_expenditures")),
            interest_bearing_debt=_to_float(_get(financials, "total_debt")),
            total_assets=_to_float(_get(financials, "total_assets")),
            dividend=_to_float(_get(valuations, "dividend_per_share")),
            meta=meta,
            # 2026-07-23追加：米国株のmarket_capが常時取得不能だった問題への対応
            # （Alpha Vantageと同じ理由、models.py FundamentalSnapshotのdocstring参照）。
            market_cap=_to_float(_get(valuations, "market_capitalization", "market_cap")),
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        payload = self._request("/stocks", {})
        return [
            TickerInfo(
                ticker=row["symbol"],
                name=row.get("name", ""),
                sector_code=None,
                market=row.get("exchange"),
                market_cap=None,
            )
            for row in payload.get("data", [])
        ]

    def get_trading_calendar(self) -> list[date]:
        raise NotImplementedError(
            "Twelve Dataの取引カレンダー相当エンドポイント(/market_state)は「現在の市場状態」"
            "を返すものであり、日付一覧としての取引カレンダーではないため未実装。"
            "必要になった時点でJ-Quantsの取引カレンダー（日本の休日等と重複しない範囲）や"
            "別途カレンダーデータソースの追加を検討する。"
        )

    def get_earnings_calendar(self) -> list[EarningsEvent]:
        payload = self._request("/earnings", {})
        events = []
        for row in payload.get("earnings", []):
            events.append(
                EarningsEvent(
                    ticker=payload.get("symbol", row.get("symbol", "")),
                    announcement_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    is_confirmed=row.get("eps_actual") is not None,
                )
            )
        return events
