"""バケット表に基づくスコア化の共通ユーティリティ（scoring_specification.md §2）。

バケット境界は「以上・未満」＝下限側を含む・上限側を含まない（closed-open, [a, b)）
方式に統一する（実装時の曖昧さ回避、§2確定仕様）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Bucket:
    """1つのスコアバケット。`lower <= value < upper` のときこのバケットが採用される。

    lower=Noneは「下限なし（-∞から）」、upper=Noneは「上限なし（+∞まで）」を表す
    （通常、バケット表の一番下・一番上のエントリに使う）。
    """

    lower: Optional[float]
    upper: Optional[float]
    score: float
    reason_code: str
    label: str  # reason文生成用の意味ラベル（例："健全な上昇トレンド帯"）


def score_from_buckets(value: float, buckets: list[Bucket]) -> Bucket:
    """`value`に対応するバケットを返す（[a, b)方式）。

    どのバケットにも一致しない場合はValueErrorを送出する（バケット表の定義漏れを示すため、
    ここでは値を無理に丸めたりデフォルト値を返したりしない）。
    """
    for bucket in buckets:
        lower_ok = bucket.lower is None or value >= bucket.lower
        upper_ok = bucket.upper is None or value < bucket.upper
        if lower_ok and upper_ok:
            return bucket
    raise ValueError(f"value {value!r} did not match any bucket (bucket table incomplete)")
