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

    def get_index_daily_prices(
        self, index_code: str, start_date: date, end_date: date
    ) -> PriceSeries:
        """指数（TOPIX等）の日次四本値を取得する（V2 API `/indices/bars/daily`）。

        2026-07-23〜24のライブ実行で、市場レジーム判定に使っていたプレースホルダー
        ティッカー「998407」（Yahoo!ファイナンス上の日経平均株価コード）が、
        個別銘柄用の`/equities/bars/daily`エンドポイントでは常に取得失敗することが
        判明した。二次情報（Qiitaの解説記事等）で調査したところ、そもそも日経平均株価
        （日経225）はJ-Quantsでは提供されていない可能性が高い（算出元の日本経済新聞社
        からの別途ライセンスが必要なため）。J-Quants自身が公式に提供する指数はTOPIX
        （東証株価指数、指数コード"0000"）であり、専用のエンドポイント
        `/indices/bars/daily`（`code`パラメータで対象指数を指定）が用意されている。
        そのため、市場レジーム判定の基準指数を日経平均株価からTOPIXへ切り替えた
        （run_daily_pipeline.py参照）。

        注意：個別銘柄用エンドポイントとは異なるレスポンス形状の可能性があるため、
        フィールド名は`get_daily_prices`同様の短縮形（O/H/L/C）と、二次情報にあった
        正式名（Open/High/Low/Close）の両方を試す。実際のライブレスポンスは
        まだ確認できていないため、想定したフィールドが見つからない場合は診断のため
        警告ログに実際の行データのキー一覧を残す。
        """
        payload = self._request(
            "/indices/bars/daily",
            params={"code": index_code, "from": start_date.isoformat(), "to": end_date.isoformat()},
        )
        rows = payload.get("data", [])

        def _field(row: dict, *keys: str):
            for key in keys:
                if key in row:
                    return row[key]
            return None

        bars = []
        for row in rows:
            open_ = _field(row, "O", "Open")
            high = _field(row, "H", "High")
            low = _field(row, "L", "Low")
            close = _field(row, "C", "Close")
            if None in (open_, high, low, close):
                import logging

                logging.getLogger(__name__).warning(
                    "get_index_daily_prices(%s): expected O/H/L/C or Open/High/Low/Close "
                    "fields not found; actual row keys=%s", index_code, list(row.keys()),
                )
                continue
            bars.append(
                PriceBar(
                    date=datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                    open=float(open_),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=0,  # 指数に出来高の概念はないため常に0
                )
            )
        meta = DataFetchMeta(source_used="jquants", fetched_at=datetime.utcnow(), success=True)
        return PriceSeries(ticker=index_code, currency="JPY", bars=tuple(bars), meta=meta)

    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        """財務情報を取得する（V2 API `/fins/summary`）。

        2026-07-22のGitHub Actionsライブ実行で、当初想定していた`/equities/financials`が
        403「The requested endpoint does not exist」で失敗することが判明した。J-Quants
        公式サイト（jpx-jquants.com/ja/spec/fin-summary）等の情報を基に、正しいV2の
        財務情報エンドポイントである`/fins/summary`へ修正した（フィールド名も実際の
        レスポンス構造 `DiscDate`／`CurPerType`／`Sales`／`OP`／`NP`／`EPS`／`TA`／`Eq`／
        `CFO`／`DivAnn`に合わせて修正）。

        注意（2026-07-23追加）：トップレベルのキー名も`fins_summary`/`summary`という
        想定は未検証のまま（当時は疎通確認できず二次情報のみで判断）だった。同日、
        `get_listed_universe`で同様に想定していたトップレベルキー（`equities`）が誤りで
        実際は`data`だったことが判明した（`/equities/bars/daily`と同じ命名パターン）ため、
        本メソッドも`data`をJ-Quants V2共通のトップレベルキーとして優先的に試すよう修正した
        （`fins_summary`/`summary`は後方互換のフォールバックとして残す）。想定した
        キーがいずれも見つからない、または該当銘柄の開示データが0件の場合は、診断のため
        警告ログに実際のレスポンス形状を残す（時価総額の近似計算がnet_income/epsの欠損で
        常に失敗する問題の切り分けのため、2026-07-23のライブ実行で必要になった）。

        注意（未確認の項目）：`capital_expenditure`（設備投資額）・
        `interest_bearing_debt`（有利子負債）に対応するフィールド名は、公式ドキュメント
        （無料プランで参照可能な範囲）から確認できなかった。誤ったフィールド名を
        推測で埋めるより、確実に存在が確認できる範囲のみをマッピングし、この2項目は
        Noneのまま返す（scoring_specification.md §4の欠損時再配分ルールにより、
        該当サブ指標は同一軸内の他指標へ自動的に比例配分される）。有料プランの
        `/fins/details`エンドポイントであれば取得できる可能性があるが、本リポジトリの
        契約プラン（light）の範囲外のため未対応とする。

        注意（2026-07-23追加、回帰）：2026-07-23のライブ実行で、`NP`・`EPS`等の数値項目が
        JSON上は数値ではなく文字列（例："4500000000000"）で返ってくることが判明した
        （`fundamentals.net_income / fundamentals.eps`が`TypeError: unsupported operand
        type(s) for /: 'str' and 'str'`で失敗し、japan_equity側の候補取得全体が
        クラッシュした）。Alpha VantageRepository（`_to_float`）と同様のパターンで、
        数値フィールドは明示的にfloat変換する。
        """
        payload = self._request("/fins/summary", params={"code": ticker})
        rows = payload.get("data", payload.get("fins_summary", payload.get("summary")))
        if not rows:
            import logging

            logging.getLogger(__name__).warning(
                "get_fundamentals(%s): no rows found under 'data'/'fins_summary'/'summary'; "
                "actual top-level keys=%s", ticker, list(payload.keys()),
            )
            rows = []
        row = rows[0] if rows else {}

        def _to_float(value):
            if value in (None, "", "None", "-"):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        meta = DataFetchMeta(source_used="jquants", fetched_at=datetime.utcnow())
        return FundamentalSnapshot(
            ticker=ticker,
            fiscal_period=row.get("CurPerType", ""),
            eps=_to_float(row.get("EPS")),
            net_assets=_to_float(row.get("Eq")),
            net_income=_to_float(row.get("NP")),
            revenue=_to_float(row.get("Sales")),
            operating_income=_to_float(row.get("OP")),
            operating_cash_flow=_to_float(row.get("CFO")),
            capital_expenditure=None,
            interest_bearing_debt=None,
            total_assets=_to_float(row.get("TA")),
            dividend=_to_float(row.get("DivAnn")),
            meta=meta,
        )

    def get_listed_universe(self) -> list[TickerInfo]:
        """上場銘柄一覧を取得する（V2 API `/equities/master`）。

        2026-07-23のGitHub Actionsライブ実行（1回目）で、当初想定していたフィールド名
        （`equities`/`code`/`name`/`sector_code`/`market`/`market_cap`）では
        0件しか取得できないことが判明した。二次情報（note.com等のJ-Quants V2解説記事）を
        基に、行ごとのフィールド名は`Code`・`CoName`（会社名）・`S33`/`S33Nm`（33業種区分
        コード・名称）・`Mkt`/`MktNm`（市場区分）に修正した。

        トップレベルのキー名も同時に修正が必要だった：同日2回目のライブ実行で、診断ログ
        （追加済み）が実際のキーは`equities`ではなく`data`であることを明らかにした
        （`/equities/bars/daily`と同じ命名パターン）。これで`equities`キー不在の問題は解消。

        注意（未解決）：`market_cap`に対応するフィールドは、公式ドキュメント・二次情報の
        いずれからも確認できなかった（J-Quants自体が時価総額を直接は提供していない
        可能性が高い）。誤ったフィールド名を推測で埋めるより、Noneのままにしている
        （screener.py側でmarket_cap=Noneはmin_market_cap未満として扱われ除外される。
        この扱いを変えるかどうかは別途ユーザーと相談が必要な設計判断であり、本メソッドの
        修正だけでは「候補0件」問題は解消しない）。
        """
        payload = self._request("/equities/master")
        rows = payload.get("data")
        if rows is None:
            import logging

            logging.getLogger(__name__).warning(
                "get_listed_universe: expected key 'data' not found in response; "
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
