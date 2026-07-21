"""PriceCheckRepositoryの具体実装（layer7_proposal_tracking_design.md §7-2・§7-3）。

Layer1が既に構築したデータ取得クライアント（`RepositoryFactory`が組み立てる
`MarketDataRepository`チェーン）をライブラリとして再利用する。Layer1の
`RepositoryFactory`・`config/api_sources.yaml`・具体Repositoryクラス自体への変更は
一切行わない（§7-2）。Layer7は1営業日1回、直近の価格のみを取得する（§7-3）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict

from .base import PriceCheckRepository, PriceSnapshot


class LookbackPriceCheckRepository(PriceCheckRepository):
    """`get_daily_prices`が返す時系列のうち、直近日のバーのみをPriceSnapshotとして返す。

    `chains`は{"japan_equity": MarketDataRepository, "us_equity": MarketDataRepository}
    のように、asset_classごとに既に組み立て済みのLayer1リポジトリ（チェーン）を渡す。
    """

    def __init__(
        self,
        chains: Dict[str, object],
        lookback_days: int = 7,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._chains = chains
        self._lookback_days = lookback_days
        self._clock = clock

    def get_latest_price(self, ticker: str, asset_class: str) -> PriceSnapshot:
        chain = self._chains.get(asset_class)
        if chain is None:
            raise ValueError(f"no repository chain configured for asset_class={asset_class}")

        today = self._clock()
        start_date = today - timedelta(days=self._lookback_days)
        series = chain.get_daily_prices(ticker, start_date, today)

        if not series.bars:
            raise ValueError(f"no price bars returned for ticker={ticker}")

        latest = max(series.bars, key=lambda bar: bar.date)
        return PriceSnapshot(date=latest.date, close=latest.close, high=latest.high, low=latest.low, volume=latest.volume)

    @classmethod
    def from_repository_factory(cls, factory, lookback_days: int = 7) -> "LookbackPriceCheckRepository":
        """Layer1の`RepositoryFactory`から、japan_equity/us_equityの2チェーンを組み立てる。"""
        chains = {
            "japan_equity": factory.build_chain("japan_equity"),
            "us_equity": factory.build_chain("us_equity"),
        }
        return cls(chains, lookback_days=lookback_days)


def infer_asset_class(ticker: str) -> str:
    """tickerからasset_classを推定する。

    layer6_report_generation_design.md §6-3の「本日の提案」シート列構成には`資産クラス`
    列自体が含まれておらず、layer7_proposal_tracking_design.md §5-1が定めるLayer7の
    利用可能列9つにも`資産クラス`は含まれていない（設計書間の細部の未接続）。config/
    universe.yamlの実例（日本株は"7203"のような数字のみのコード、米国株は"AAPL"の
    ようなアルファベットのティッカー）に基づき、数字のみで構成されるティッカーは
    japan_equity、それ以外はus_equityとして扱う、という最小限の補完ルールをここに置く。
    """
    return "japan_equity" if ticker.isdigit() else "us_equity"
