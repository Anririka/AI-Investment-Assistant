"""マクロ軸（layer2_analysis_design.md §3-4、scoring_specification.md §3-4）。

入力：`TimeSeries`（FRED経由：米10年国債利回り・FF金利・失業率・CPI・PPI・GDP・景気先行指数）。
この軸は銘柄非依存（当日1回だけ計算し、全銘柄・全資産クラス共通で使い回す、§3-4）。

セクター感応度補正（§3-4）：Ver1ではデフォルト無効（全スタイルタグ係数1.0）。
`config/scoring_weights.yaml`の`macro_sector_correction`を通じて、将来人間レビューで
調整可能なインターフェースのみ用意する（自動学習は行わない）。
"""

from __future__ import annotations

from typing import Optional

from ..layer1_data_acquisition.models import TimeSeries

# 変化率が小さい場合は「横ばい」とみなす閾値（指標ごとの単位に応じた絶対値の目安）
_FLAT_THRESHOLD = {
    "us_10y_yield": 0.05,   # %ポイント
    "fed_funds_rate": 0.05,
    "unemployment_rate": 0.05,
    "cpi_yoy": 0.1,
    "ppi_yoy": 0.1,
    "gdp_growth": 0.2,
    "leading_index": 0.1,
}

MACRO_WEIGHTS = {
    "us_10y_yield": 20, "fed_funds_rate": 20, "unemployment_rate": 15,
    "cpi_yoy": 15, "ppi_yoy": 10, "gdp_growth": 10, "leading_index": 10,
}


def _direction(change: Optional[float], series_id: str) -> str:
    if change is None:
        return "flat"
    threshold = _FLAT_THRESHOLD.get(series_id, 0.1)
    if change > threshold:
        return "up"
    if change < -threshold:
        return "down"
    return "flat"


def _latest_and_change(series: TimeSeries):
    if not series.points:
        return None, None
    points = sorted(series.points, key=lambda p: p.date)
    latest = points[-1].value
    change = latest - points[-2].value if len(points) > 1 else None
    return latest, change


_INDICATOR_TABLES = {
    "us_10y_yield": {
        "down": (80, "MACRO_US10Y_FALLING", "米10年国債利回りが低下"),
        "flat": (60, "MACRO_US10Y_FLAT", "米10年国債利回りが横ばい"),
        "up": (35, "MACRO_US10Y_RISING", "米10年国債利回りが上昇"),
    },
    "fed_funds_rate": {
        "down": (80, "MACRO_FFR_CUT_EXPECTED", "FF金利は利下げ方向"),
        "flat": (60, "MACRO_FFR_HOLD_EXPECTED", "FF金利は据え置き方向"),
        "up": (30, "MACRO_FFR_HIKE_EXPECTED", "FF金利は利上げ方向"),
    },
    "unemployment_rate": {
        "down": (70, "MACRO_UNRATE_IMPROVING", "失業率が改善"),
        "flat": (60, "MACRO_UNRATE_FLAT", "失業率が横ばい"),
        "up": (40, "MACRO_UNRATE_WORSENING", "失業率が悪化"),
    },
    "cpi_yoy": {
        "down": (80, "MACRO_INFLATION_DECELERATING", "CPIが鈍化"),
        "flat": (60, "MACRO_INFLATION_INLINE", "CPIが予想通り"),
        "up": (30, "MACRO_INFLATION_ACCELERATING", "CPIが加速"),
    },
    "ppi_yoy": {
        "down": (80, "MACRO_INFLATION_DECELERATING", "PPIが鈍化"),
        "flat": (60, "MACRO_INFLATION_INLINE", "PPIが予想通り"),
        "up": (30, "MACRO_INFLATION_ACCELERATING", "PPIが加速"),
    },
    "gdp_growth": {
        "up": (80, "MACRO_GDP_BEAT", "GDP成長率が予想を上回る"),
        "flat": (60, "MACRO_GDP_INLINE", "GDP成長率が予想並み"),
        "down": (30, "MACRO_GDP_MISS", "GDP成長率が予想を下回る"),
    },
    "leading_index": {
        "up": (75, "MACRO_LEI_RISING", "景気先行指数が上昇"),
        "flat": (55, "MACRO_LEI_FLAT", "景気先行指数が横ばい"),
        "down": (35, "MACRO_LEI_FALLING", "景気先行指数が低下"),
    },
}


def score_indicator(series_id: str, series: TimeSeries) -> dict:
    """1つのマクロ系列をスコア化する（§3-4のバケット表）。"""
    latest, change = _latest_and_change(series)
    if latest is None:
        return {
            "value": None, "change": None, "score": 50,
            "reason_code": f"MACRO_{series_id.upper()}_NO_DATA",
            "reason": f"{series_id}のデータが取得できないため中立扱い",
        }
    direction = _direction(change, series_id)
    score, reason_code, reason_label = _INDICATOR_TABLES[series_id][direction]
    return {
        "value": latest, "change": change, "score": score,
        "reason_code": reason_code, "reason": f"{reason_label}（実測値={latest:.2f}）",
    }


def score_axis(series_map: dict) -> dict:
    """マクロ軸全体のスコアを算出する（§3-4）。

    `series_map`は{series_id: TimeSeries}の辞書（us_10y_yield/fed_funds_rate/
    unemployment_rate/cpi_yoy/ppi_yoy/gdp_growth/leading_indexの7キー）。
    """
    indicator_results = {}
    weighted_sum = 0.0
    total_weight = 0.0
    reasons = []

    for series_id, weight in MACRO_WEIGHTS.items():
        series = series_map.get(series_id)
        if series is None:
            continue
        result = score_indicator(series_id, series)
        indicator_results[series_id] = result
        weighted_sum += result["score"] * weight
        total_weight += weight
        reasons.append(result["reason"])

    axis_score = (weighted_sum / total_weight) if total_weight else 50.0

    return {
        "series": indicator_results,
        "axis_score": round(axis_score, 2),
        "axis_score_reason": "、".join(reasons) if reasons else "マクロデータなし、中立扱い",
    }


def apply_sector_sensitivity(base_macro_score: float, style_tags: list, correction_config: dict) -> float:
    """セクター感応度補正を適用する（§3-4、Ver1はデフォルト全て1.0）。

    `candidate_macro_score = clamp(base_macro_axis_score × sector_sensitivity_factor[style_tag], 0, 100)`
    複数スタイルタグを持つ場合は、該当する係数の平均を用いる。
    """
    factors = [correction_config.get(tag, correction_config.get("default", 1.0)) for tag in style_tags]
    factor = sum(factors) / len(factors) if factors else correction_config.get("default", 1.0)
    return max(0.0, min(100.0, base_macro_score * factor))
