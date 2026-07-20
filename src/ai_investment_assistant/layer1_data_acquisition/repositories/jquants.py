"""JQuantsRepository（layer1_data_acquisition_design.md 3-2 MarketDataRepository実装）。

J-Quants V2 API（APIキー方式、`x-api-key`ヘッダー）を使用する。V1のメールアドレス・
パスワードによるリフレッシュトークン認証は使用しない。

注意：get_daily_pricesのフィールド名は、GitHub Actions上でのライブ疎通確認
（scripts/layer1_live_check.pyのデバッグ出力）で得られた実際のV2レスポンスに
合わせて修正済み（トップレベルキーは`bars`ではなく`data`、各項目は
`Date`/`O`/`H`/`L`/`C`/`Vo`という短縮フィールド名で、分割調整後の
`AdjO`/`AdjH`/`AdjL`/`AdjC`/`AdjVo`も含まれる。株式分割時の連続性を優先し、
調整後値（Adj*）を正規化後のPriceBarとして採用している）。
get_fundamentals・get_listed_universe・get_trading_calendar・
get_earnings_calendarは、get_daily_pricesと異なりまだライブ検証できていない
ため、フィールド名は引き続き二次情報ベースの想定であることに注意。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Optional

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import MarketDataRepository
from ..models import DataFetchMeta, EarningsEvent, FundamentalSnapshot, PriceBar, PriceSeries, TickerInfo

BASE_URL = "https://api.jquants.com/v2"
TIMEOUT_SECONDS = 30


class JQuantsRepository(MarketDataRepository):
    """J-Quants V2 API（APIキー方式）による日本株データ取得。"""

    def __init__(self, api_key: str, plan: str = "free", price_delay_weeks: int = 12) -> None:
        if not api_key:
            raise AuthError("JQUANTS_API_KEY is not set")
        self._api_key = api_key
        self.plan = plan
        self.price_delay_weeks = price_delay_weeks
        # 8章の移行方針：Lightプラン以上ではprice_delay_weeks=0となり、
        # 「Web検索フォールバックに落ちた日本個別株は除外」ゲートは自然に無効化される。
        self.is_delayed = price_delay_weeks > 0
        self.delay_reason = (
            f"{plan} plan: price data delayed by {price_delay_weeks} weeks"
            if self.is_delayed
            else None
        )

    @classmethod
    def from_config(cls, entry: dict) -> "JQuantsRepository":
        api_key = os.environ.get("JQUANTS_API_KEY", "")
        return cls(
            api_key=api_key,
            plan=entry.get("plan", "free"),
            price_delay_weeks=entry.get("price_delay_weeks", 12),
        )

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        """HTTPリクエストを行い、ステータスコードを5-1のエラー分類に変換する。"""
        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                headers={"x-api-key": self._api_key},
                params=params or {},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"J-Quants rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"J-Quants auth error {response.status_code}: {response.text}")
        if response.status_code == 404:
            raise NotFoundError(f"J-Quants not found: {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"J-Quants server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(
                f"J-Quants unexpected status {response.status_code}: {response.text}"
            )
        return response.json()

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> PriceSeries:
        payload = self._request(
            "/equities/bars/daily",
            params={"code": ticker, "from": start_date.isoformat(), "to": end_date.isoformat()},
        )
        bars = tuple(
            PriceBar(
                date=datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                # 株式分割等をまたいだ連続性のため、調整後値（Adj*）を採用する
                open=float(row["AdjO"]),
                high=float(row["AdjH"]),
                low=float(row["AdjL"]),
                close=float(row["AdjC"]),
                volume=int(row["AdjVo"]),
            )
            for row in payload.get("data", [])
        )
        meta = DataFetchMeta(
            source_used="jquants",
            fetched_at=datetime.utcnow(),
            is_delayed=self.is_delayed,
            delay_reason=self.delay_reason,
            success=True,
        )
        return PriceSeries(ticker=ticker, currency="JPY", bars=bars, meta=meta)

    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        payload = self._request("/equities/financials", params={"code": ticker})
        rows = payload.get("financials", [])
        row = rows[0] if rows else {}
        meta = DataFetchMeta(source_used="jquants", fetched_at=datetime.utcnow())
        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=row.get("fiscal_period", ""),
            eps=row.get("eps"),
            net_assets=row.get("net_assets"),
            net_income=row.get("net_income"),
            revenue=row.get("revenue"),
            operating_income=row.get("operating_income"),
            operating_cash_flow=row.get("operating_cash_flow"),
            capital_expenditure=row.get("capital_expenditure"),
            interest_bearing_debt=row.get("interest_bearing_debt"),
            total_assets=row.get("total_assets"),
            dividend=row.get("dividend"),
            meta=meta,
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        payload = self._request("/equities/master")
        return [
            TickerInfo(
                ticker=row["code"],
                name=row.get("name", ""),
                sector_code=row.get("sector_code"),
                market=row.get("market"),
                market_cap=row.get("market_cap"),
            )
            for row in payload.get("equities", [])
        ]

    def get_trading_calendar(self) -> list[date]:
        payload = self._request("/markets/trading_calendar")
        return [
            datetime.strptime(row["date"], "%Y-%m-%d").date()
            for row in payload.get("calendar", [])
            if row.get("is_trading_day")
        ]

    def get_earnings_calendar(self) -> list[EarningsEvent]:
        payload = self._request("/equities/earnings_calendar")
        return [
            EarningsEvent(
                ticker=row["code"],
                announcement_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                is_confirmed=row.get("is_confirmed", False),
            )
            for row in payload.get("events", [])
        ]
