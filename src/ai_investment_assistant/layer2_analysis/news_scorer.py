"""ニュース軸（layer2_analysis_design.md §3-6、scoring_specification.md §3-5）。

入力：Layer3が構造化した`StructuredNewsItem`相当の辞書（本モジュールは生記事本文を
受け取らない）。各記事は以下のキーを持つことを期待する：
  category, target_tickers, impact_direction（"positive"/"neutral"/"negative"）,
  confidence（0-1）, importance（0-100）, published_at, age_hours, news_schema_version

`score`（中心傾向）と`uncertainty`（評価の割れ具合）を分離して出力する（§3-6の重要事項）。
"""

from __future__ import annotations

import math
from typing import Optional

from .exceptions import SchemaVersionError

_DIRECTION_SIGN = {"positive": 1, "neutral": 0, "negative": -1}


def _decay_factor(age_hours: Optional[float], decay_curve: list) -> tuple:
    """config/news_decay.yamlのdecay_curveから時間減衰係数を求める。"""
    if age_hours is None:
        age_hours = 0.0
    for entry in decay_curve:
        within = entry.get("within_hours")
        if within is None or age_hours <= within:
            return entry["factor"], entry.get("reason_code", "NEWS_DECAY_UNKNOWN")
    # 万一どのエントリにも一致しない場合は最後のエントリを使う
    last = decay_curve[-1]
    return last["factor"], last.get("reason_code", "NEWS_DECAY_UNKNOWN")


def _check_schema_version(news_schema_version: str, compatibility_config: dict) -> None:
    news_cfg = compatibility_config.get("news_schema", {})
    accept_major = news_cfg.get("accept_major_version")
    major = news_schema_version.split(".")[0]
    if accept_major is not None and str(major) != str(accept_major):
        raise SchemaVersionError(
            f"news_schema_version={news_schema_version} のメジャーバージョンが"
            f"accept_major_version={accept_major} と不一致（§3-6のSchemaVersionError）"
        )


def score_axis(
    news_items: list,
    decay_curve: list,
    schema_compatibility_config: dict,
    normalize_scale: float = 200.0,
) -> dict:
    """ニュース軸のscore/uncertaintyを算出する（§3-5の計算式）。

    該当ニュースが無い場合はscore=50・uncertainty=0を返す（§3-5「該当記事が無い場合」）。
    メジャーバージョン不一致のnews_schema_versionを検知した場合はSchemaVersionErrorを
    送出する（呼び出し側でrun_logへのcritical記録を行う）。
    """
    if not news_items:
        return {
            "relevant_items": [],
            "score": 50,
            "uncertainty": 0,
            "axis_score_reason": "本日該当ニュースなし",
        }

    contributions = []
    for item in news_items:
        _check_schema_version(item["news_schema_version"], schema_compatibility_config)

        direction_sign = _DIRECTION_SIGN[item["impact_direction"]]
        decay, decay_reason_code = _decay_factor(item.get("age_hours"), decay_curve)
        contribution = item["importance"] * item["confidence"] * direction_sign * decay

        category = item.get("category", "general")
        contributions.append(
            {
                "news_schema_version": item["news_schema_version"],
                "reason_code": f"NEWS_{category.upper()}",
                "headline": item.get("headline", ""),
                "source": item.get("source", ""),
                "category": category,
                "impact_direction": item["impact_direction"],
                "impact_horizon": item.get("impact_horizon"),
                "confidence": item["confidence"],
                "importance": item["importance"],
                "published_at": item.get("published_at"),
                "age_hours": item.get("age_hours"),
                "time_decay_factor": decay,
                "decay_reason_code": decay_reason_code,
                "contribution": contribution,
            }
        )

    positive_mass = sum(c["contribution"] for c in contributions if c["contribution"] > 0)
    negative_mass = sum(-c["contribution"] for c in contributions if c["contribution"] < 0)
    total_mass = positive_mass + negative_mass

    # normalize: tanhで飽和させ、±normalize_scaleで概ね±50点に収まるよう正規化する（§3-5）
    net = positive_mass - negative_mass
    score = 50 + 50 * math.tanh(net / normalize_scale)
    score = max(0.0, min(100.0, score))

    uncertainty = (100 * 2 * min(positive_mass, negative_mass) / total_mass) if total_mass > 0 else 0.0

    reason = (
        f"関連ニュース{len(contributions)}件、正の寄与合計={positive_mass:.1f}、"
        f"負の寄与合計={negative_mass:.1f}、uncertainty={uncertainty:.1f}"
    )

    return {
        "relevant_items": contributions,
        "score": round(score, 2),
        "uncertainty": round(uncertainty, 2),
        "axis_score_reason": reason,
    }
