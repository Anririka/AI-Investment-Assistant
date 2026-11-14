"""FinancialModelingPrepRepository（MarketDataRepository実装、米国株）。

2026-10-07頃からAlpha Vantage（OVERVIEW）・Twelve Data（/statistics）の両方が
get_fundamentals用のエンドポイントを有料プラン専用に変更したため（実運用ログで確認、
`{"Information": "...This is a premium endpoint..."}` / `403 .../statistics is
available exclusively with pro or ultra or venture or enterprise plans`）、
us_equityチェーンのget_fundamentals用フォールバック候補としてFinancial Modeling Prep
（FMP）を追加する。layer1_data_acquisition_design.md 6-1の比較表で「不採用（参考記載）
... ファンダメンタル項目が不足した場合の予備候補として記録」と明記されていた候補。

無料枠は1日250件（2026-10時点、要最新確認）。本Repositoryはget_fundamentals専用に
限定し、他のメソッド（get_daily_prices等）はAlpha Vantageと同様に意図的に
「未対応」とする（layer1_data_acquisition_design.md 6-2の役割分担どおり、
広範スクリーニングはTwelve Data、米国株の日次株価もTwelve Data側が担う設計を維持する）。

注意：レスポンスJSONのフィールド名は、Financial Modeling Prep公式ドキュメントの
二次情報から実装したものであり、実際のライブAPIレスポンスとは未照合（Alpha Vantage・
Twelve Dataの既存実装と同じ注意書き）。FMPは2024年以降、新しい`/stable/`系エンドポイント
への移行を進めているため、無料キー取得後にまず本ファイルの`BASE_URL`配下の各エンドポイントを
1回ずつ手動で叩き、フィールド名（特に`netIncome`・`totalStockholdersEquity`・
`operatingCashFlow`・`capitalExpenditure`）がドキュメントと一致するか確認すること。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Optional

import requests

from ..exceptions import AuthError, NotFoundError, RateLimitError, TransientError
from ..interfaces import MarketDataRepository
from ..models import DataFetchMeta, EarningsEvent, FundamentalSnapshot, PriceSeries, TickerInfo

BASE_URL = "https://financialmodelingprep.com/api/v3"
TIMEOUT_SECONDS = 30


class FinancialModelingPrepRepository(MarketDataRepository):
    """Financial Modeling Prep API（米国株、get_fundamentals専用のフォールバック候補）。"""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise AuthError("FMP_API_KEY is not set")
        self._api_key = api_key

    @classmethod
    def from_config(cls, entry: dict) -> "FinancialModelingPrepRepository":
        return cls(api_key=os.environ.get("FMP_API_KEY", ""))

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        try:
            response = requests.get(
                f"{BASE_URL}/{path}",
                params={**(params or {}), "apikey": self._api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(f"FMP rate limit: {response.text}")
        if response.status_code in (401, 403):
            raise AuthError(f"FMP auth error {response.status_code}: {response.text}")
        if response.status_code >= 500:
            raise TransientError(f"FMP server error {response.status_code}")
        if response.status_code != 200:
            raise TransientError(f"FMP unexpected status {response.status_code}: {response.text}")

        payload = response.json()
        # FMPは上限超過・無効キー時もHTTP 200でエラーメッセージを返すことがある
        # （{"Error Message": "..."}、またはdictそのものが{"Error Message": ...}の形）。
        if isinstance(payload, dict) and "Error Message" in payload:
            message = str(payload["Error Message"])
            if "limit" in message.lower():
                raise RateLimitError(message)
            raise NotFoundError(message)
        return payload

    def _latest(self, path: str, ticker: str) -> Optional[dict]:
        payload = self._request(f"{path}/{ticker}", {"period": "quarter", "limit": 1})
        if not payload:
            return None
        return payload[0]

    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        meta = DataFetchMeta(source_used="fmp", fetched_at=datetime.utcnow())

        income = self._latest("income-statement", ticker) or {}
        balance = self._latest("balance-sheet-statement", ticker) or {}
        cashflow = self._latest("cash-flow-statement", ticker) or {}
        profile_list = self._request(f"profile/{ticker}")
        profile = profile_list[0] if profile_list else {}

        def _num(value: Any) -> Optional[float]:
            if value in (None, "", "None"):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        fiscal_period = income.get("date") or balance.get("date") or ""

        # FMPはcapitalExpenditureを負値（キャッシュアウト）で返す規約のため、
        # FundamentalSnapshot.capital_expenditureの符号規約（他ソースとの整合）を
        # 導入時に確認し、必要なら符号反転すること（本ファイルではFMPの生値をそのまま渡す）。
        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=str(fiscal_period),
            eps=_num(income.get("eps")),
            net_assets=_num(balance.get("totalStockholdersEquity")),
            net_income=_num(income.get("netIncome")),
            revenue=_num(income.get("revenue")),
            operating_income=_num(income.get("operatingIncome")),
            operating_cash_flow=_num(cashflow.get("operatingCashFlow")),
            capital_expenditure=_num(cashflow.get("capitalExpenditure")),
            interest_bearing_debt=_num(balance.get("totalDebt")),
            total_assets=_num(balance.get("totalAssets")),
            dividend=_num(profile.get("lastDiv")),
            meta=meta,
            market_cap=_num(profile.get("mktCap")),
        )

    # --- 以下はAlpha Vantageと同様、意図的に「未対応」とする ---
    # us_equityの広範スクリーニング・日次株価取得はTwelve Data側が担う設計
    # （layer1_data_acquisition_design.md 6-2）を維持し、FMPはget_fundamentals専用の
    # フォールバック候補に限定する。誤って他用途に流用されないよう、わかりやすい
    # エラーで失敗させる（Alpha Vantageのget_trading_calendar実装と同じ方針）。

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> PriceSeries:
        raise NotImplementedError(
            "FMPはget_fundamentals専用のフォールバック候補のため、日次株価は"
            "Twelve Dataリポジトリを使用すること（layer1_data_acquisition_design.md 6-2）。"
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        raise NotImplementedError(
            "FMPはget_fundamentals専用のフォールバック候補のため、銘柄マスタ取得は"
            "Twelve Dataリポジトリを使用すること。"
        )

    def get_trading_calendar(self) -> list[date]:
        raise NotImplementedError(
            "FMPはget_fundamentals専用のフォールバック候補のため、取引カレンダーは"
            "Twelve Dataリポジトリを使用すること。"
        )

    def get_earnings_calendar(self) -> list[EarningsEvent]:
        raise NotImplementedError(
            "FMPはget_fundamentals専用のフォールバック候補のため、決算発表予定日は"
            "Alpha Vantageリポジトリを使用すること。"
        )
