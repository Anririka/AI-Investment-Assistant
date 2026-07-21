"""AI改善用feedback_YYYYMM.jsonの生成（layer8_self_evaluation_design.md §8）。

`weight_adjustment_suggestions`はあくまで人間レビュー用の「提案」であり、
`config/scoring_weights.yaml`等への自動反映は一切行わない（Ver2確定方針）。
`review_status`は常に`"pending_human_review"`で始まる。

重要な実装上の注記：weight_adjustment_suggestionsの生成条件・target_configの
導出方法（reason_codeの接頭辞からscoring_weights.yamlのパスへの対応付け）は、
設計書に具体的なアルゴリズムの明記が無いため、config/feedback_thresholds.yamlの
`weight_suggestion_win_rate_diff_threshold`を用いた最小限のヒューリスティックとして
実装した（§10「将来調整可能にする」の方針に沿い、閾値は設定ファイルに切り出し済み）。
いずれの提案も`requires_human_review: true`・`review_status: pending_human_review`と
なるため、この実装上の判断が投資判断に直接影響することはない。
"""

from __future__ import annotations

from typing import Optional

_AXIS_PREFIX_MAP = {
    "TECH": "technical", "FUND": "fundamental", "SUPD": "supply_demand",
    "MACRO": "macro", "NEWS": "news", "REGIME": "regime_fit",
}


def should_generate_feedback(new_evaluations_count: int) -> bool:
    """§4-2：新規評価が1件以上ある場合のみtrue（0件の月はfeedbackを生成・更新しない）。"""
    return new_evaluations_count > 0


def build_sample_size(
    total_closed_this_period: int, total_closed_all_time: int, min_recommended_sample: int
) -> dict:
    return {
        "total_closed_this_period": total_closed_this_period,
        "total_closed_all_time": total_closed_all_time,
        "min_recommended_sample_for_confidence": min_recommended_sample,
        "sufficient_for_reliable_analysis": total_closed_all_time >= min_recommended_sample,
    }


def _derive_target_config(reason_code: str) -> Optional[str]:
    prefix, _, remainder = reason_code.partition("_")
    axis = _AXIS_PREFIX_MAP.get(prefix)
    if axis is None or not remainder:
        return None
    sub_key = remainder.split("_")[0]
    return f"config/scoring_weights.yaml#{axis}.{sub_key}"


def build_weight_adjustment_suggestions(
    reason_code_performance: list, overall_win_rate: Optional[float], win_rate_diff_threshold: float
) -> list:
    """reason_code別勝率が全体勝率から一定以上乖離している場合のみ、増減の方向性を提案する。"""
    if overall_win_rate is None:
        return []

    suggestions = []
    for entry in reason_code_performance:
        diff = entry["win_rate"] - overall_win_rate
        if abs(diff) < win_rate_diff_threshold:
            continue

        target_config = _derive_target_config(entry["reason_code"])
        direction = "increase" if diff > 0 else "decrease"
        observation = (
            f"{entry['reason_code']}が付与された提案の勝率({entry['win_rate']:.1%})が"
            f"全体平均({overall_win_rate:.1%})を{'上回っている' if diff > 0 else '下回っている'}"
        )
        suggestions.append({
            "target_config": target_config,
            "current_weight": None,
            "observation": observation,
            "suggested_direction": direction,
            "confidence": f"{entry['confidence']}（サンプル数{entry['count']}件、統計的有意性は未検証）",
            "requires_human_review": True,
        })
    return suggestions


def build_feedback(
    period: str,
    generated_at: str,
    total_closed_this_period: int,
    total_closed_all_time: int,
    min_recommended_sample: int,
    overall_stats: dict,
    reason_code_performance: list,
    score_band_performance: list,
    asset_class_performance: list,
    holding_period_performance: list,
    win_rate_diff_threshold: float,
) -> dict:
    """§8のfeedback_YYYYMM.jsonスキーマ通りに組み立てる。"""
    return {
        "period": period,
        "generated_at": generated_at,
        "sample_size": build_sample_size(total_closed_this_period, total_closed_all_time, min_recommended_sample),
        "overall_stats": overall_stats,
        "reason_code_performance": reason_code_performance,
        "score_band_performance": score_band_performance,
        "_confidence_scale_note": (
            "confidenceは0〜9件=low_sample、10〜29件=medium_sample、30件以上=normal（§7-1-2）"
        ),
        "asset_class_performance": asset_class_performance,
        "holding_period_performance": holding_period_performance,
        "weight_adjustment_suggestions": build_weight_adjustment_suggestions(
            reason_code_performance, overall_stats.get("win_rate"), win_rate_diff_threshold
        ),
        "review_status": "pending_human_review",
    }
