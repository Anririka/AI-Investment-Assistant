"""統合モジュール（layer2_analysis_design.md §3-7）。

各軸モジュールが返すサブスコア群を集約し、総合スコア（composite_score）を算出して、
§5-1のJSONスキーマにおける`candidates[]`の1要素分を組み立てる。
"""

from __future__ import annotations

from datetime import datetime

SCORING_VERSION = "1.0.0"
WEIGHT_VERSION = "2026-07"


def compute_composite_score(
    technical_score: float,
    fundamental_score: float,
    supply_demand_score: float,
    macro_score: float,
    news_score: float,
    regime_fit_score: float,
    axis_weights: dict,
) -> dict:
    """総合スコアを加重平均で算出する（scoring_specification.md §5）。

    ニュース軸は`score`（中心傾向）のみを用いる。`uncertainty`は計算に含めない（§3-6）。
    """
    scores = {
        "technical": technical_score,
        "fundamental": fundamental_score,
        "supply_demand": supply_demand_score,
        "macro": macro_score,
        "news": news_score,
        "regime": regime_fit_score,
    }
    total = sum(scores[axis] * axis_weights[axis] / 100 for axis in scores)

    return {
        "total": round(total, 2),
        "breakdown_weights": dict(axis_weights),
        "calculation_note": (
            "各軸スコア（newsは`score`フィールドを使用、`uncertainty`は計算に含めない）"
            "×配点の加重平均。欠損指標は同軸内で比例配分済み"
        ),
        "score_meta": {"scoring_version": SCORING_VERSION, "weight_version": WEIGHT_VERSION},
    }


def build_candidate(
    asset_class: str,
    ticker: str,
    name: str,
    style_tags: list,
    data_quality: dict,
    technical: dict,
    fundamental: dict,
    supply_demand: dict,
    news: dict,
    macro_axis_score: float,
    regime_fit: dict,
    axis_weights: dict,
) -> dict:
    """1銘柄分の`candidates[]`要素を組み立てる（layer2_analysis_design.md §5-1）。"""
    composite = compute_composite_score(
        technical_score=technical["axis_score"],
        fundamental_score=fundamental["axis_score"],
        supply_demand_score=supply_demand["axis_score"],
        macro_score=macro_axis_score,
        news_score=news["score"],
        regime_fit_score=regime_fit["score"],
        axis_weights=axis_weights,
    )

    return {
        "asset_class": asset_class,
        "ticker": ticker,
        "name": name,
        "style_tags": style_tags,
        "data_quality": data_quality,
        "technical": technical,
        "fundamental": fundamental,
        "supply_demand": supply_demand,
        "news": news,
        "macro_axis_score_ref": macro_axis_score,
        "regime_fit": regime_fit,
        "composite_score": composite,
    }


def build_run_meta(
    run_id: str,
    analysis_started_at: datetime,
    analysis_completed_at: datetime,
    critical_errors: list,
    warning_errors: list,
    degraded_sources: list,
    excluded_candidates_count: int,
) -> dict:
    """`run_meta`を組み立てる（§5-1）。"""
    return {
        "run_id": run_id,
        "analysis_started_at": analysis_started_at.isoformat() + "Z"
        if analysis_started_at.tzinfo is None
        else analysis_started_at.isoformat(),
        "analysis_completed_at": analysis_completed_at.isoformat() + "Z"
        if analysis_completed_at.tzinfo is None
        else analysis_completed_at.isoformat(),
        "score_meta": {"scoring_version": SCORING_VERSION, "weight_version": WEIGHT_VERSION},
        "data_quality": {
            "critical_errors": critical_errors,
            "warning_errors": warning_errors,
            "degraded_sources": degraded_sources,
            "excluded_candidates_count": excluded_candidates_count,
        },
    }
