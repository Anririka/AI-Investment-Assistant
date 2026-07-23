"""AlphaVantageRepository（MarketDataRepository実装、米国株）。

layer1_data_acquisition_design.md 6-2の確定方針により、Alpha Vantageは「広範な
スクリーニングの主力」ではなく、**Twelve Dataで絞り込んだ最終候補銘柄への決算・EPS・
サプライズ等の補完用途に限定**する（1日25件という制約のため）。そのため
`get_listed_universe`・`get_trading_calendar`はTwelve Data側が担う設計であり、
本Repositoryでは意図的に「未対応」として明示する（不正確な実装をするよりも、
呼び出された場合にわかりやすいエラーで失敗させる方針）。

注意：レスポンスJSONのフィールド名は、Alpha Vantage公式ドキュメントの二次情報から
実装したものであり、実際のライブAPIレスポンスとは未照合。
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime
from typing import Any, Optional

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import MarketDataRepository
from ..models import DataFetchMeta, EarningsEvent, FundamentalSnapshot, PriceBar, PriceSeries, TickerInfo

BASE_URL = "https://www.alphavantage.co/query"
TIMEOUT_SECONDS = 30


class AlphaVantageRepository(MarketDataRepository):
    """Alpha Vantage API（米国株、決算・EPS等の補完用途に限定）。"""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise AuthError("ALPHA_VANTAGE_API_KEY is not set")
        self._api_key = api_key

    @classmethod
    def from_config(cls, entry: dict) -> "AlphaVantageRepository":
        return cls(api_key=os.environ.get("ALPHA_VANTAGE_API_KEY", ""))

    def _request(self, params: dict[str, Any]) -> dict:
        try:
            response = requests.get(
                BASE_URL, params={**params, "apikey": self._api_key}, timeout=TIMEOUT_SECONDS
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"Alpha Vantage rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"Alpha Vantage auth error {response.status_code}: {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"Alpha Vantage server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(
                f"Alpha Vantage unexpected status {response.status_code}: {response.text}"
            )

        payload = response.json()
        # Alpha Vantageは制限超過時もHTTP 200でエラーメッセージを返すことがある。
        if "Note" in payload or "Information" in payload:
            raise RateLimitError(str(payload.get("Note") or payload.get("Information")))
        if "Error Message" in payload:
            raise NotFoundError(str(payload["Error Message"]))
        return payload

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> PriceSeries:
        payload = self._request(
            {"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "full"}
        )
        series = payload.get("Time Series (Daily)", {})
        bars = []
        for day_str, values in series.items():
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            if not (start_date <= day <= end_date):
                continue
            bars.append(
                PriceBar(
                    date=day,
                    open=float(values["1. open"]),
                    high=float(values["2. high"]),
                    low=float(values["3. low"]),
                    close=float(values["4. close"]),
                    volume=int(values["5. volume"]),
                )
            )
        bars.sort(key=lambda b: b.date)
        meta = DataFetchMeta(source_used="alpha_vantage", fetched_at=datetime.utcnow())
        return PriceSeries(ticker=ticker, currency="USD", bars=tuple(bars), meta=meta)

    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        payload = self._request({"function": "OVERVIEW", "symbol": ticker})
        meta = DataFetchMeta(source_used="alpha_vantage", fetched_at=datetime.utcnow())

        def _to_float(value: Optional[str]) -> Optional[float]:
            if value in (None, "", "None", "-"):
                return None
            try:
                return float(value)
            except ValueError:
                return None

        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=payload.get("LatestQuarter", ""),
            eps=_to_float(payload.get("EPS")),
            net_assets=_to_float(payload.get("BookValue")),
            net_income=None,  # OVERVIEWは比率中心のため、正確な純利益はINCOME_STATEMENTが必要（要検証）
            revenue=_to_float(payload.get("RevenueTTM")),
            operating_income=None,
            operating_cash_flow=None,
            capital_expenditure=None,
            interest_bearing_debt=None,
            total_assets=None,
            dividend=_to_float(payload.get("DividendPerShare")),
            meta=meta,
            # 2026-07-23追加：net_incomeを提供しないため、min_market_cap screeningの
            # ためのnet_income/EPSベースの近似計算（run_daily_pipeline.py側）が
            # 米国株では常に失敗していた。OVERVIEWが時価総額を直接提供する
            # `MarketCapitalization`フィールドを使う（未ライブ検証、本ファイル冒頭の
            # 注意書きどおり二次情報ベース）。
            market_cap=_to_float(payload.get("MarketCapitalization")),
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        """LISTING_STATUS（CSV形式）から銘柄マスタを取得する。"""
        try:
            response = requests.get(
                BASE_URL,
                params={"function": "LISTING_STATUS", "apikey": self._api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc
        if response.status_code != 200:
            raise TransientError(f"Alpha Vantage LISTING_STATUS status {response.status_code}")

        reader = csv.DictReader(io.StringIO(response.text))
        return [
            TickerInfo(
                ticker=row["symbol"],
                name=row.get("name", ""),
                sector_code=None,
                market=row.get("exchange"),
                market_cap=None,
            )
            for row in reader
        ]

    def get_trading_calendar(self) -> list[date]:
        raise NotImplementedError(
            "Alpha Vantageは決算・EPS等の補完用途に限定する設計のため、取引カレンダーは"
            "Twelve Dataリポジトリを使用すること（layer1_data_acquisition_design.md 6-2）。"
        )

    def get_earnings_calendar(self) -> list[EarningsEvent]:
        """EARNINGS_CALENDAR（CSV形式、銘柄指定なしで今後の決算発表予定を取得）を使用する。"""
        try:
            response = requests.get(
                BASE_URL,
                params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": self._api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc
        if response.status_code != 200:
            raise TransientError(f"Alpha Vantage EARNINGS_CALENDAR status {response.status_code}")

        reader = csv.DictReader(io.StringIO(response.text))
        events = []
        for row in reader:
            report_date = row.get("reportDate")
            if not report_date:
                continue
            events.append(
                EarningsEvent(
                    ticker=row.get("symbol", ""),
                    announcement_date=datetime.strptime(report_date, "%Y-%m-%d").date(),
                    is_confirmed=False,  # EARNINGS_CALENDARは予定日のため未確定扱い
                )
            )
        return events
