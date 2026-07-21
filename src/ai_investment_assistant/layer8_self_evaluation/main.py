"""Layer8パイプラインのエントリポイント（layer8_self_evaluation_design.md §4）。

トランザクション原則（§6）：`position_evaluations_YYYYMM.json`・`segment_stats_YYYYMM.json`・
`feedback_YYYYMM.json`（該当する場合）をすべて保存できてから、最後に
`evaluation_index.json`を更新する。途中で失敗した場合、`evaluation_index.json`は
更新しない（次回実行時、当該`tracking_id`は「未評価」のままとなり再評価される。
二重評価は起こり得るが、「評価済み扱いなのに永久に評価されない」事故は起こらない）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import (
    closed_position_loader,
    evaluation_index,
    evaluation_store,
    feedback_builder,
    outcome_analyzer,
    segment_analyzer,
)
from .score_context_loader import derive_sheet_date


def run(
    drive_client,
    date_str: str,
    year_months_to_scan: list,
    confidence_thresholds: dict,
    min_recommended_sample: int,
    win_rate_diff_threshold: float,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)

    # --- 手順2：Layer7完了フラグの確認（§4-3） -----------------------------------------
    flag = drive_client.read_latest_layer7_completed_flag(date_str)
    if flag is None or not flag.get("completed"):
        return {"status": "skipped", "reason_code": "LAYER7_NOT_COMPLETED"}

    # --- 手順3：closed_positions_YYYYMM.jsonの読込（必要に応じ複数期間、§4手順3） --------
    all_closed = []
    for ym in year_months_to_scan:
        doc = drive_client.read_closed_positions(ym) or {"positions": []}
        all_closed.extend(doc.get("positions", []))

    # --- 手順4：未評価ポジションの特定（§4-1） -----------------------------------------
    index_doc = drive_client.read_evaluation_json("evaluation_index.json") or {"evaluated_tracking_ids": []}
    evaluated_ids_before = evaluation_index.evaluated_ids_set(index_doc)
    unevaluated = closed_position_loader.select_unevaluated(all_closed, evaluated_ids_before)

    # --- 手順5：未評価0件ならここで終了。feedbackも生成しない（§4-2） -------------------
    if not unevaluated:
        return {"status": "no_new_evaluations", "new_count": 0}

    # --- 手順6〜8：score_context取得・reason_code抽出・勝敗判定 -------------------------
    sheet_rows_cache: dict = {}
    new_evaluations = []
    for position in unevaluated:
        sheet_date = derive_sheet_date(position["run_id"])
        if sheet_date not in sheet_rows_cache:
            sheet_rows_cache[sheet_date] = drive_client.read_proposal_sheet_rows(sheet_date)
        new_evaluations.append(outcome_analyzer.build_evaluation_entry(position, sheet_rows_cache[sheet_date]))

    new_ids = [e["tracking_id"] for e in new_evaluations]
    # evaluation_index.jsonはまだ書き込まない（§6のトランザクション原則）が、
    # total_closed_all_time算出のためにマージ後の件数だけ先に計算しておく。
    all_time_count = len(evaluated_ids_before | set(new_ids))

    by_month: dict = {}
    for evaluation in new_evaluations:
        ym = evaluation_store.year_month_of_run_id(evaluation["run_id"])
        by_month.setdefault(ym, []).append(evaluation)

    try:
        touched_months = []
        for ym, evaluations_this_month in by_month.items():
            # --- 手順10：position_evaluations_YYYYMM.jsonの保存（上書きマージ） ---------
            existing_doc = drive_client.read_evaluation_json(f"position_evaluations_{ym}.json") or {"evaluations": []}
            merged_doc = evaluation_store.merge_position_evaluations(existing_doc, evaluations_this_month)
            drive_client.write_evaluation_json(f"position_evaluations_{ym}.json", merged_doc)

            all_evaluations_for_month = merged_doc["evaluations"]
            overall_stats = outcome_analyzer.compute_overall_stats(all_evaluations_for_month)
            reason_code_perf = segment_analyzer.aggregate_by_reason_code(all_evaluations_for_month, confidence_thresholds)
            score_band_perf = segment_analyzer.aggregate_by_score_band(all_evaluations_for_month, confidence_thresholds)
            asset_class_perf = segment_analyzer.aggregate_by_asset_class(all_evaluations_for_month)
            holding_period_perf = segment_analyzer.aggregate_by_holding_period(all_evaluations_for_month)

            segment_stats_doc = {
                "overall_stats": overall_stats,
                "reason_code_performance": reason_code_perf,
                "score_band_performance": score_band_perf,
                "asset_class_performance": asset_class_perf,
                "holding_period_performance": holding_period_perf,
            }
            drive_client.write_evaluation_json(f"segment_stats_{ym}.json", segment_stats_doc)

            # --- 手順11：feedback_YYYYMM.jsonの生成（新規評価が1件以上ある月のみ、§4-2） ---
            if feedback_builder.should_generate_feedback(len(evaluations_this_month)):
                feedback_doc = feedback_builder.build_feedback(
                    period=f"{ym[:4]}-{ym[4:]}",
                    generated_at=now.isoformat().replace("+00:00", "Z"),
                    total_closed_this_period=len(evaluations_this_month),
                    total_closed_all_time=all_time_count,
                    min_recommended_sample=min_recommended_sample,
                    overall_stats=overall_stats,
                    reason_code_performance=reason_code_perf,
                    score_band_performance=score_band_perf,
                    asset_class_performance=asset_class_perf,
                    holding_period_performance=holding_period_perf,
                    win_rate_diff_threshold=win_rate_diff_threshold,
                )
                drive_client.write_evaluation_json(f"feedback_{ym}.json", feedback_doc)

            touched_months.append(ym)

        # --- 手順10最終ステップ：evaluation_index.jsonの更新（他の全保存成功後、§6） -------
        updated_index = evaluation_index.merge_evaluated_ids(index_doc, new_ids)
        drive_client.write_evaluation_json("evaluation_index.json", updated_index)

    except Exception as exc:  # noqa: BLE001
        # §6：途中失敗時はevaluation_index.jsonを更新しない。次回実行時に再評価される。
        return {"status": "error", "error": str(exc), "new_count": 0}

    return {"status": "ok", "new_count": len(new_evaluations), "touched_months": touched_months}
