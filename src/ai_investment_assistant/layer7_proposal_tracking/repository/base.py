"""PriceCheckRepository抽象クラス（layer7_proposal_tracking_design.md §7-1）。

`get_latest_price`の1メソッドのみを定義し、Layer7の他モジュール（`exit_evaluator.py`等）
はこのインターフェースにのみ依存する。将来価格取得APIを変更・追加しても、影響範囲は
具体実装（`price_check_repository_impl.py`）内に閉じる（§10）。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceSnapshot:
    date: date
    close: float
    high: float
    low: float
    volume: int


class PriceCheckRepository(abc.ABC):
    @abc.abstractmethod
    def get_latest_price(self, ticker: str, asset_class: str) -> PriceSnapshot:
        """当日（直近営業日）の終値・高値・安値・出来高を返す。"""
