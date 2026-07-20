"""需給軸（layer2_analysis_design.md §3-3、scoring_specification.md §3-3）。

入力：`PriceSeries`の出来高列（過去25日分以上）、（取得できれば）信用倍率。
信用倍率はJ-Quants Freeプランでは常時欠損するため、欠損時は残り2指標で100%按分する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..layer1_data_acquisition.models import PriceSeries
from .bucket import Bucket, score_from_buckets
from .reallocation import WeightedItem, weighted_axis_score

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

VOLUME_SURGE_BUCKETS = [
    Bucket(3.0, None, 90, "SUPD_VOL_SURGE_EXTREME", "出来高急増（3倍以上）"),
    Bucket(2.0, 3.0, 80, "SUPD_VOL_SURGE_HIGH", "出来高急増（2〜3倍）"),
    Bucket(1.5, 2.0, 65, "SUPD_VOL_SURGE_MODERATE", "出来高増加（1.5〜2倍）"),
    Bucket(0.8, 1.5, 55, "SUPD_VOL_SURGE_NORMAL", "通常の出来高"),
    Bucket(None, 0.8, 40, "SUPD_VOL_SURGE_LOW", "出来高低下"),
]

VOLUME_MA_DEV_BUCKETS = [
    Bucket(50, None, 85, "SUPD_VOL_MA_DEV_HIGH", "出来高moving average大幅上振れ"),
    Bucket(20, 50, 70, "SUPD_VOL_MA_DEV_MODERATE", "出来高moving average上振れ"),
    Bucket(-20, 20, 55, "SUPD_VOL_MA_DEV_NEUTRAL", "出来高moving average中立"),
    Bucket(None, -20, 40, "SUPD_VOL_MA_DEV_LOW", "出来高moving average下振れ"),
]

MARGIN_RATIO_BUCKETS = [
    Bucket(None, 1, 80, "SUPD_MARGIN_RATIO_SHORT_HEAVY", "信用売り優勢"),
    Bucket(1, 3, 60, "SUPD_MARGIN_RATIO_NEUTRAL", "中立"),
    Bucket(3, 6, 40, "SUPD_MARGIN_RATIO_LONG_HEAVY", "信用買い優勢"),
    Bucket(6, None, 25, "SUPD_MARGIN_RATIO_EXTREME_LONG", "信用買い極端に優勢"),
]


@dataclass(frozen=True)
class SubScore:
    indicator: str
    reason_code: str
    score: float
    weight_in_axis: float
    reason: str


def compute_raw_indicators(series: PriceSeries) -> dict:
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas is required for supply_demand")
    volume = pd.Series([bar.volume for bar in sorted(series.bars, key=lambda b: b.date)])
    if len(volume) < 2:
        return {"volume_surge_ratio": None, "volume_ma_deviation_pct": None}

    avg20 = volume.rolling(20, min_periods=1).mean()
    ma5 = volume.rolling(5, min_periods=1).mean()
    ma25 = volume.rolling(25, min_periods=1).mean()

    latest_volume = volume.iloc[-1]
    surge_ratio = latest_volume / avg20.iloc[-2] if len(avg20) > 1 and avg20.iloc[-2] else None
    ma_dev_pct = (ma5.iloc[-1] / ma25.iloc[-1] - 1) * 100 if ma25.iloc[-1] else None

    return {"volume_surge_ratio": surge_ratio, "volume_ma_deviation_pct": ma_dev_pct}


def score_axis(series: PriceSeries, margin_ratio: Optional[float] = None) -> dict:
    """需給軸のスコアを算出する（§3-3・§3-7）。"""
    raw = compute_raw_indicators(series)
    weights = {"VolumeSurgeRatio": 45, "VolumeMADeviation": 35, "MarginRatio": 20}

    sub_scores: list[SubScore] = []
    items: list[WeightedItem] = []

    if raw["volume_surge_ratio"] is None:
        items.append(WeightedItem("VolumeSurgeRatio", weights["VolumeSurgeRatio"], None))
    else:
        b = score_from_buckets(raw["volume_surge_ratio"], VOLUME_SURGE_BUCKETS)
        reason = f"出来高急増率={raw['volume_surge_ratio']:.2f}倍、{b.label}"
        sub_scores.append(SubScore("VolumeSurgeRatio", b.reason_code, b.score, weights["VolumeSurgeRatio"], reason))
        items.append(WeightedItem("VolumeSurgeRatio", weights["VolumeSurgeRatio"], b.score, b.reason_code))

    if raw["volume_ma_deviation_pct"] is None:
        items.append(WeightedItem("VolumeMADeviation", weights["VolumeMADeviation"], None))
    else:
        b = score_from_buckets(raw["volume_ma_deviation_pct"], VOLUME_MA_DEV_BUCKETS)
        reason = f"出来高MA乖離率={raw['volume_ma_deviation_pct']:.1f}%、{b.label}"
        sub_scores.append(SubScore("VolumeMADeviation", b.reason_code, b.score, weights["VolumeMADeviation"], reason))
        items.append(WeightedItem("VolumeMADeviation", weights["VolumeMADeviation"], b.score, b.reason_code))

    if margin_ratio is None:
        items.append(WeightedItem("MarginRatio", weights["MarginRatio"], None))
    else:
        b = score_from_buckets(margin_ratio, MARGIN_RATIO_BUCKETS)
        reason = f"信用倍率={margin_ratio:.2f}倍、{b.label}"
        sub_scores.append(SubScore("MarginRatio", b.reason_code, b.score, weights["MarginRatio"], reason))
        items.append(WeightedItem("MarginRatio", weights["MarginRatio"], b.score, b.reason_code))

    axis_score, realloc = weighted_axis_score(items)

    reason = "、".join(s.reason for s in sub_scores) if sub_scores else "需給データなし"
    if realloc.missing:
        reason += f"（欠損指標: {', '.join(realloc.missing)}、残り指標へ比例配分済み）"

    return {
        "raw": {**raw, "margin_ratio": margin_ratio},
        "sub_scores": [s.__dict__ for s in sub_scores],
        "axis_score": round(axis_score, 2),
        "axis_score_reason": reason,
        "missing_indicators": list(realloc.missing),
    }
