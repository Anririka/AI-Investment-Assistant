"""Layer1の抽象Repositoryインターフェース（layer1_data_acquisition_design.md 3-2の確定仕様）。

Layer2（分析層）は常にこれらのインターフェースのみを参照し、具体的にどのAPIを
使っているかを一切知らない構造にする（3-1）。
"""

from __future__ import annotations

import abc
from datetime import date

from .models import (
    EarningsEvent,
    FundamentalSnapshot,
    PriceSeries,
    RawNewsItem,
    TickerInfo,
    TimeSeries,
)


class MarketDataRepository(abc.ABC):
    """日本株・米国株共通の抽象契約（3-2）。"""

    @abc.abstractmethod
    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> PriceSeries:
        """日次OHLCV（始値・高値・安値・終値・出来高）の時系列を返す。"""

    @abc.abstractmethod
    def get_fundamentals(self, ticker: str) -> FundamentalSnapshot:
        """PER/PBR/ROE等の計算に必要な原データ（加工前の生数値）を返す。"""

    @abc.abstractmethod
    def get_listed_universe(self) -> list[TickerInfo]:
        """銘柄マスタ（銘柄コード・銘柄名・業種・上場市場等）を返す。"""

    @abc.abstractmethod
    def get_trading_calendar(self) -> list[date]:
        """取引日カレンダーを返す。"""

    @abc.abstractmethod
    def get_earnings_calendar(self) -> list[EarningsEvent]:
        """決算発表予定日（可能なら実績日も）を返す。"""


class NewsRepository(abc.ABC):
    """ニュース取得の抽象契約（3-2）。"""

    @abc.abstractmethod
    def fetch_news(self, query_or_tickers, since, until) -> list[RawNewsItem]:
        """記事本文・タイトル・公開日時・情報源URLを返す（要約・重要度付けはLayer3の責務）。"""


class MacroRepository(abc.ABC):
    """マクロ指標取得の抽象契約（3-2）。"""

    @abc.abstractmethod
    def get_series(self, series_id: str, start_date: date, end_date: date) -> TimeSeries:
        """FRED系列IDを指定して時系列を返す。"""
