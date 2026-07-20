"""欠損時の重み再配分ロジック（scoring_specification.md §4の共通仕様）。

1. あるサブ指標が欠損の場合、その配点を0にするのではなく、同一軸内の他の取得済み
   サブ指標へ、元の配点比率を保ったまま比例配分する。
2. 軸全体が完全に欠損する場合はデフォルト中立スコア（50点）を採用する。
3. 再配分が発生した場合は、どの指標が欠損しどう按分したかを記録する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

NEUTRAL_SCORE = 50.0


@dataclass(frozen=True)
class WeightedItem:
    """軸内の1サブ指標。`score=None`は欠損を表す。"""

    name: str
    weight: float  # 元の配点（軸内でのウェイト、パーセント表記の数値。合計100を想定）
    score: Optional[float]
    reason_code: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class ReallocationResult:
    effective_weights: dict  # name -> 再配分後のウェイト（欠損項目は含まれない）
    reallocated: bool
    missing: tuple  # 欠損項目名のタプル


def reallocate(items: list[WeightedItem]) -> ReallocationResult:
    """欠損したサブ指標の配点を、残りの指標へ元の比率を保ったまま比例配分する（§4-1）。"""
    available = [it for it in items if it.score is not None]
    missing = tuple(it.name for it in items if it.score is None)

    if not available:
        return ReallocationResult(effective_weights={}, reallocated=True, missing=missing)

    total_available_weight = sum(it.weight for it in available)
    effective_weights = {
        it.name: (it.weight / total_available_weight) * 100.0 for it in available
    }
    return ReallocationResult(
        effective_weights=effective_weights, reallocated=bool(missing), missing=missing
    )


def weighted_axis_score(items: list[WeightedItem]) -> tuple:
    """再配分後のウェイトで加重平均した軸スコアを返す。

    軸全体が欠損する場合は`NEUTRAL_SCORE`（50点、§4-2）を返す。
    戻り値: (axis_score, ReallocationResult)
    """
    result = reallocate(items)
    if not result.effective_weights:
        return NEUTRAL_SCORE, result

    total = 0.0
    for it in items:
        if it.score is None:
            continue
        total += it.score * result.effective_weights[it.name] / 100.0
    return total, result
