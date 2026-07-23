"""Layer1の正規化データスキーマ（layer1_data_acquisition_design.md 4章の確定仕様）。

取得元（J-Quants・Alpha Vantage・Twelve Data・FRED・NewsAPI・GDELT等）によらず、
Layer2以降はこれらの型のみを参照する（ソース差異を意識しないための最重要ポイント）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class DataFetchMeta:
    """戻り値に必ず付随する取得メタ情報（3-2）。"""

    source_used: str
    fetched_at: datetime
    is_delayed: bool = False
    delay_reason: Optional[str] = None
    success: bool = True
    error_detail: Optional[str] = None


@dataclass(frozen=True)
class PriceBar:
    """日次OHLCV1件分。"""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class PriceSeries:
    """日次OHLCVの時系列（4章）。"""

    ticker: str
    currency: str
    bars: tuple[PriceBar, ...]
    meta: DataFetchMeta


@dataclass(frozen=True)
class FundamentalSnapshot:
    """PER/PBR/ROE等の計算に必要な、加工前の原データ（4章・3-2）。

    比率計算はLayer2の責務のため、ここでは生数値のみを保持する。

    `market_cap`（2026-07-23追加）：時価総額そのものを情報源が直接提供する場合にのみ
    設定する（例：Alpha Vantage OVERVIEWの`MarketCapitalization`、Twelve Data
    `/statistics`の`market_capitalization`）。既存フィールドのみで運用してきた
    呼び出し元との後方互換のため、デフォルト値`None`を持つ末尾フィールドとして追加した
    （米国株のmarket_capが常時取得不能だった問題への対応、run_daily_pipeline.py
    冒頭docstringのギャップ5参照）。情報源が直接提供しない場合（J-Quants等）は
    Noneのままとし、呼び出し元（run_daily_pipeline.py）側でnet_income/epsからの
    近似計算にフォールバックする。
    """

    ticker: str
    fiscal_period: str
    eps: Optional[float]
    net_assets: Optional[float]
    net_income: Optional[float]
    revenue: Optional[float]
    operating_income: Optional[float]
    operating_cash_flow: Optional[float]
    capital_expenditure: Optional[float]
    interest_bearing_debt: Optional[float]
    total_assets: Optional[float]
    dividend: Optional[float]
    meta: DataFetchMeta
    market_cap: Optional[float] = None


@dataclass(frozen=True)
class TickerInfo:
    """銘柄マスタ1件分（4章）。"""

    ticker: str
    name: str
    sector_code: Optional[str]
    market: Optional[str]
    market_cap: Optional[float]


@dataclass(frozen=True)
class EarningsEvent:
    """決算発表予定日（可能なら実績日も、3-2）。"""

    ticker: str
    announcement_date: date
    is_confirmed: bool = False


@dataclass(frozen=True)
class RawNewsItem:
    """ニュース記事1件分（要約・構造化前、4章）。"""

    title: str
    body: str
    published_at: datetime
    source_url: str
    source_name: str


@dataclass(frozen=True)
class TimeSeriesPoint:
    """マクロ指標の時系列1点分。"""

    date: date
    value: float


@dataclass(frozen=True)
class TimeSeries:
    """マクロ指標の時系列（4章）。"""

    series_id: str
    points: tuple[TimeSeriesPoint, ...]
    meta: DataFetchMeta
