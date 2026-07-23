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
        """財務情報を取得する（V2 API `/fins/summary`）。

        2026-07-22のGitHub Actionsライブ実行で、当初想定していた`/equities/financials`が
        403「The requested endpoint does not exist」で失敗することが判明した。J-Quants
        公式サイト（jpx-jquants.com/ja/spec/fin-summary）等の情報を基に、正しいV2の
        財務情報エンドポイントである`/fins/summary`へ修正した（フィールド名も実際の
        レスポンス構造 `DiscDate`／`CurPerType`／`Sales`／`OP`／`NP`／`EPS`／`TA`／`Eq`／
        `CFO`／`DivAnn`に合わせて修正）。

        注意（未確認の項目）：`capital_expenditure`（設備投資額）・
        `interest_bearing_debt`（有利子負債）に対応するフィールド名は、公式ドキュメント
        （無料プランで参照可能な範囲）から確認できなかった。誤ったフィールド名を
        推測で埋めるより、確実に存在が確認できる範囲のみをマッピングし、この2項目は
        Noneのまま返す（scoring_specification.md §4の欠損時再配分ルールにより、
        該当サブ指標は同一軸内の他指標へ自動的に比例配分される）。有料プランの
        `/fins/details`エンドポイントであれば取得できる可能性があるが、本リポジトリの
        契約プラン（light）の範囲外のため未対応とする。
        """
        payload = self._request("/fins/summary", params={"code": ticker})
        rows = payload.get("fins_summary", payload.get("summary", []))
        row = rows[0] if rows else {}
        meta = DataFetchMeta(source_used="jquants", fetched_at=datetime.utcnow())
        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=row.get("CurPerType", ""),
            eps=row.get("EPS"),
            net_assets=row.get("Eq"),
            net_income=row.get("NP"),
            revenue=row.get("Sales"),
            operating_income=row.get("OP"),
            operating_cash_flow=row.get("CFO"),
            capital_expenditure=None,
            interest_bearing_debt=None,
            total_assets=row.get("TA"),
            dividend=row.get("DivAnn"),
            meta=meta,
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        """上場銘柄一覧を取得する（V2 API `/equities/master`）。

        2026-07-23のGitHub Actionsライブ実行で、当初想定していたフィールド名
        （`equities`/`code`/`name`/`sector_code`/`market`/`market_cap`）では
        0件しか取得できないことが判明した（config/universe.yamlのtickerと
        一致するエントリが1件もヒットしない）。二次情報（note.com等のJ-Quants V2
        解説記事）を基に、実際のフィールド名は`Code`・`CoName`（会社名）・
        `S33`/`S33Nm`（33業種区分コード・名称）・`Mkt`/`MktNm`（市場区分）である
        可能性が高いと判断し、修正した。

        注意：`market_cap`に対応するフィールドは、公式ドキュメント・二次情報の
        いずれからも確認できなかった（J-Quants自体が時価総額を直接は提供して
        いない可能性が高い）。誤ったフィールド名を推測で埋めるより、Noneのままに
        している（screener.py側でmarket_cap=Noneはmin_market_cap未満として扱われ、
        除外される。この扱いを変えるかどうかは別途ユーザーと相談が必要な設計判断）。

        また、トップレベルのキー名（`equities`）自体も未確認のため、想定した
        キーが見つからない場合は診断用にpayloadの実際のキー一覧をログに残す。
        """
        payload = self._request("/equities/master")
        rows = payload.get("equities")
        if rows is None:
            import logging

            logging.getLogger(__name__).warning(
                "get_listed_universe: expected key 'equities' not found in response; "
                "actual top-level keys=%s", list(payload.keys()),
            )
            rows = []
        return [
            TickerInfo(
                ticker=row.get("Code", row.get("code", "")),
                name=row.get("CoName", row.get("name", "")),
                sector_code=row.get("S33", row.get("sector_code")),
                market=row.get("Mkt", row.get("market")),
                market_cap=row.get("market_cap"),
            )
            for row in rows
        ]

    def get_trading_calendar(self) -> list[date]:
        """取引カレンダーを取得する（V2 API `/markets/calendar`）。

        2026-07-22時点、当初想定していた`/markets/trading_calendar`は誤りである
        可能性が高いことが二次情報（jpx-jquants.com/ja/spec/mkt-cal等）から判明した。
        `/markets/calendar`へ修正したが、レスポンスのフィールド名（`calendar`／
        `date`／`is_trading_day`）自体はまだライブ検証できていない想定ベースのため、
        引き続き実地確認が必要（このメソッドはrun_daily_pipeline.pyからまだ
        呼び出されていない）。
        """
        payload = self._request("/markets/calendar")
        return [
            datetime.strptime(row["date"], "%Y-%m-%d").date()
            for row in payload.get("calendar", [])
            if row.get("is_trading_day")
        ]

    def get_earnings_calendar(self) -> list[EarningsEvent]:
        """決算発表予定日を取得する（V2 API `/equities/earnings-calendar`）。

        2026-07-22時点、当初想定していた`/equities/earnings_calendar`（アンダースコア）は
        誤りである可能性が高いことが二次情報（jpx-jquants.com/ja/spec/eq-earnings-cal等）
        から判明した。`/equities/earnings-calendar`（ハイフン）へ修正したが、レスポンスの
        フィールド名自体はまだライブ検証できていない想定ベースのため、引き続き実地確認が
        必要（このメソッドはrun_daily_pipeline.pyからまだ呼び出されていない）。
        """
        payload = self._request("/equities/earnings-calendar")
        return [
            EarningsEvent(
                ticker=row["code"],
                announcement_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                is_confirmed=row.get("is_confirmed", False),
            )
            for row in payload.get("events", [])
        ]
