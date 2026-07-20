"""Layer5へ渡す最終JSON生成（layer2_analysis_design.md §3-10、新設）。

入力：`ranking.py`が出力した順位付け済み全候補、`regime_detector.py`／`macro_evaluator.py`
の当日共通データ、`screener.py`の除外銘柄リスト。
処理：`config/llm_input.yaml`の資産クラスごとの件数上限に従い上位候補のみを抽出し、
除外分を`excluded_summary`に追記して、§5のJSONスキーマに沿って最終JSONを組み立てる。

母集団全件の生データはここでは渡さず、上限件数分のみを含める（プロンプト肥大化・
コスト増を避けるため）。順位付け済み全候補はGoogle Drive上の`decision_log`に別途保存
する想定（Layer4の責務、本モジュールはその保存自体は行わない）。
"""

from __future__ import annotations

from collections import defaultdict


def build_output(
    run_meta: dict,
    regime: dict,
    macro: dict,
    ranked_candidates: list,
    excluded_summary: list,
    candidate_limits: dict,
    max_total_candidates: int,
) -> tuple:
    """最終JSONを組み立てる。戻り値: (output_dict, warning_messages)。"""
    by_asset_class = defaultdict(list)
    for c in ranked_candidates:
        by_asset_class[c["asset_class"]].append(c)

    selected: list = []
    all_excluded = list(excluded_summary)

    for asset_class, group in by_asset_class.items():
        limit = candidate_limits.get(asset_class, 0)
        sorted_group = sorted(group, key=lambda c: c["preliminary_quant_rank"])
        selected.extend(sorted_group[:limit])
        for c in sorted_group[limit:]:
            all_excluded.append(
                {
                    "ticker": c["ticker"],
                    "asset_class": c["asset_class"],
                    "reason_code": "CANDIDATE_LIMIT_EXCEEDED",
                    "reason": f"{asset_class}の上位{limit}件に入らなかったため今回は非採用",
                }
            )

    warnings = []
    if len(selected) > max_total_candidates:
        warnings.append(
            f"selected candidates ({len(selected)}) exceeded max_total_candidates "
            f"({max_total_candidates})"
        )

    output = {
        "run_meta": run_meta,
        "regime": regime,
        "macro": macro,
        "candidates": selected,
        "excluded_summary": all_excluded,
    }
    return output, warnings


def shorten_reasons_for_budget(output: dict, max_reason_chars: int = 40) -> dict:
    """トークン予算超過時の調整その1：各候補の`reason`文字列を短縮する（§3-10-1）。

    `reason_code`は変更しないため、機械可読な情報は失われない。
    """
    for candidate in output["candidates"]:
        for axis_key in ("technical", "fundamental", "supply_demand"):
            axis = candidate.get(axis_key)
            if not axis:
                continue
            for sub in axis.get("sub_scores", []):
                if len(sub.get("reason", "")) > max_reason_chars:
                    sub["reason"] = sub["reason"][:max_reason_chars] + "..."
    return output


def drop_lowest_scoring_candidates(output: dict, count: int) -> dict:
    """トークン予算超過時の調整その2：総合スコアが低い候補から順に除外する（§3-10-1）。"""
    candidates = sorted(output["candidates"], key=lambda c: c["composite_score"]["total"])
    to_drop = candidates[:count]
    keep_tickers = {c["ticker"] for c in candidates[count:]}

    for c in to_drop:
        output["excluded_summary"].append(
            {
                "ticker": c["ticker"],
                "asset_class": c["asset_class"],
                "reason_code": "PROMPT_BUDGET_EXCEEDED",
                "reason": "トークン予算超過のため低スコア候補から除外",
            }
        )
    output["candidates"] = [c for c in output["candidates"] if c["ticker"] in keep_tickers]
    return output
