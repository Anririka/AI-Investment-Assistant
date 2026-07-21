"""reason_code別／score帯別／資産クラス別／保有期間別の成績集計
（layer8_self_evaluation_design.md §7-1-2〜§7-6）。
"""

from __future__ import annotations

from typing import Optional

SCORE_AXES = ["technical", "fundamental", "supply_demand", "macro", "news_score", "regime_fit", "composite"]


def score_band(score: float) -> str:
    """§7-3の固定バケット（0-59/60-69/70-79/80-89/90-100）。"""
    if score < 60:
        return "0-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def holding_period_band(days: int) -> str:
    """§7-6の固定バケット（〜7日/8〜14日/15〜30日/31日超）。"""
    if days <= 7:
        return "〜7日"
    if days <= 14:
        return "8〜14日"
    if days <= 30:
        return "15〜30日"
    return "31日超"


def confidence_label(count: int, thresholds: dict) -> str:
    """§7-1-2の基準でconfidenceラベルを決定する。"""
    low = thresholds["low_sample"]
    medium = thresholds["medium_sample"]
    normal = thresholds["normal"]

    if count <= low["max_count"]:
        return "low_sample"
    if medium["min_count"] <= count <= medium["max_count"]:
        return "medium_sample"
    if count >= normal["min_count"]:
        return "normal"
    return "low_sample"


def _win_rate_and_avg_return(group: list) -> tuple:
    count = len(group)
    win_rate = sum(1 for e in group if e["outcome"] == "win") / count
    avg_return_pct = sum(e["final_return_pct"] for e in group) / count
    return count, win_rate, avg_return_pct


def aggregate_by_reason_code(evaluations: list, thresholds: dict) -> list:
    """§7-2：1ポジションが複数コードを持つ場合、該当する全コードの集計に含める（多重集計）。"""
    groups: dict = {}
    for e in evaluations:
        if e.get("reason_code_extraction_status") != "success":
            continue
        for code in e.get("extracted_reason_codes", []):
            groups.setdefault(code, []).append(e)

    result = []
    for code, group in groups.items():
        count, win_rate, avg_return_pct = _win_rate_and_avg_return(group)
        result.append({
            "reason_code": code, "count": count, "win_rate": win_rate,
            "avg_return_pct": avg_return_pct, "confidence": confidence_label(count, thresholds),
        })
    return result


def aggregate_by_score_band(evaluations: list, thresholds: dict) -> list:
    """§7-3：score_context_availableなポジションのみが対象（score_summaryが無ければ集計不能）。"""
    groups: dict = {}
    for e in evaluations:
        if not e.get("score_context_available") or e.get("score_summary") is None:
            continue
        for axis in SCORE_AXES:
            value = e["score_summary"].get(axis)
            if value is None:
                continue
            band = score_band(value)
            groups.setdefault((axis, band), []).append(e)

    result = []
    for (axis, band), group in groups.items():
        count, win_rate, avg_return_pct = _win_rate_and_avg_return(group)
        result.append({
            "axis": axis, "band": band, "count": count, "win_rate": win_rate,
            "avg_return_pct": avg_return_pct, "confidence": confidence_label(count, thresholds),
        })
    return result


def aggregate_by_asset_class(evaluations: list) -> list:
    """§7-5：セクター情報が存在しないため「資産クラス別成績」として実装する。"""
    groups: dict = {}
    for e in evaluations:
        asset_class = e.get("asset_class")
        if asset_class is None:
            continue
        groups.setdefault(asset_class, []).append(e)

    result = []
    for asset_class, group in groups.items():
        count, win_rate, avg_return_pct = _win_rate_and_avg_return(group)
        result.append({"asset_class": asset_class, "count": count, "win_rate": win_rate, "avg_return_pct": avg_return_pct})
    return result


def aggregate_by_holding_period(evaluations: list) -> list:
    """§7-6：Layer7の`holding_days`実測値を使うため、抽出の限界・欠落は発生しない。"""
    groups: dict = {}
    for e in evaluations:
        band = holding_period_band(e["holding_days"])
        groups.setdefault(band, []).append(e)

    result = []
    for band, group in groups.items():
        count, win_rate, avg_return_pct = _win_rate_and_avg_return(group)
        result.append({"band": band, "count": count, "win_rate": win_rate, "avg_return_pct": avg_return_pct})
    return result
