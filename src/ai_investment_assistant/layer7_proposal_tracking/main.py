"""Layer7パイプラインのエントリポイント（layer7_proposal_tracking_design.md §4）。

手順2〜9が全て成功した場合のみ、`tracking/layer7_completed_YYYYMMDD.json`を
`completed: true`で書き込む（Layer4の完了フラグと同じ「全体不可分」の原則、§4手順10）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable, Optional

from . import (
    completion_flag_writer,
    exit_evaluator,
    layer8_export_builder,
    manual_close_processor,
    position_store,
    price_checker,
    proposal_ingester,
    tracking_history_writer,
)

REQUIRED_SHEET_COLUMNS = proposal_ingester.REQUIRED_SHEET_COLUMNS


def run(
    drive_client,
    price_repository,
    date_str: str,
    unit_days: dict,
    fallback_default_days: int,
    now: Optional[datetime] = None,
    today: Optional[date] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    today = today or now.date()

    try:
        # --- 手順2：新規取り込み ---------------------------------------------------
        active_positions_doc = drive_client.read_tracking_json("active_positions.json") or {"positions": []}
        existing_positions = active_positions_doc.get("positions", [])

        sheet_rows = drive_client.read_proposal_sheet_rows(date_str)
        skipped_duplicates = []
        if sheet_rows is not None:
            new_positions, skipped_duplicates = proposal_ingester.ingest_new_positions(
                sheet_rows, existing_positions, unit_days, fallback_default_days
            )
            existing_positions = existing_positions + new_positions
        # sheet_rowsがNone（Layer6シート未検出）の場合、新規取り込みはスキップし
        # 既存のアクティブポジションの価格チェックのみ継続する（§9）。

        # --- 手順3〜4：価格取得 -----------------------------------------------------
        updated_positions, failed_tickers = price_checker.update_all_positions(
            existing_positions, price_repository, now=lambda: now
        )

        # --- 手順5：自動判定 ---------------------------------------------------------
        evaluated = []
        for position in updated_positions:
            verdict = exit_evaluator.evaluate_exit(position, today)
            evaluated.append({**position, "_auto_verdict": verdict})

        # --- 手順6：manual_close処理（§8-5：自動判定より優先） -----------------------
        manual_close_doc = drive_client.read_tracking_json("manual_close_requests.json") or {"requests": []}
        manual_result = manual_close_processor.process_manual_close_requests(
            updated_positions, manual_close_doc.get("requests", []), default_exit_date=today.isoformat()
        )
        manually_closed_ids = {p["tracking_id"] for (p, _, _, _) in manual_result["closed"]}

        # --- 手順7：クローズ処理 -----------------------------------------------------
        closed_positions = []
        remaining_active = []
        closed_at = now.isoformat().replace("+00:00", "Z")

        for entry in evaluated:
            tracking_id = entry["tracking_id"]
            if tracking_id in manually_closed_ids:
                continue  # manual_close側でまとめて処理する
            verdict = entry["_auto_verdict"]
            position = {k: v for k, v in entry.items() if k != "_auto_verdict"}
            if verdict["status"] == "active":
                remaining_active.append(position)
            else:
                closed_positions.append(
                    position_store.build_closed_position(
                        position, verdict["exit_price"], today, verdict["exit_reason"], closed_at
                    )
                )

        for position, exit_price, exit_date, _note in manual_result["closed"]:
            closed_positions.append(
                position_store.build_closed_position(position, exit_price, exit_date, "manual_close", closed_at)
            )

        # --- 手順8：履歴スナップショット ---------------------------------------------
        history_entries = tracking_history_writer.build_daily_snapshot_entries(
            date_str, remaining_active, closed_positions
        )

        # --- 手順9：Layer8向けエクスポートデータ（closed_positions_YYYYMM.jsonが本体） ---
        layer8_export_entries = layer8_export_builder.build_layer8_export_entries(closed_positions)

        # --- 保存 ---------------------------------------------------------------------
        drive_client.write_tracking_json("active_positions.json", {"positions": remaining_active})
        drive_client.write_tracking_json("manual_close_requests.json", {"requests": manual_result["remaining_requests"]})

        closed_by_month: dict = {}
        for closed in closed_positions:
            ym = position_store.year_month_of(closed["exit_date"])
            closed_by_month.setdefault(ym, []).append(closed)
        for ym, new_entries in closed_by_month.items():
            existing_doc = drive_client.read_tracking_json(f"closed_positions_{ym}.json") or {"positions": []}
            existing_doc["positions"] = existing_doc.get("positions", []) + new_entries
            drive_client.write_tracking_json(f"closed_positions_{ym}.json", existing_doc)

        history_ym = date_str[:6]
        history_doc = drive_client.read_tracking_json(f"tracking_history_{history_ym}.json") or {"entries": []}
        history_doc["entries"] = history_doc.get("entries", []) + history_entries
        drive_client.write_tracking_json(f"tracking_history_{history_ym}.json", history_doc)

    except Exception as exc:  # noqa: BLE001
        flag = completion_flag_writer.build_completion_flag(
            completed=False, completed_at=now, run_date=date_str, failure_reason_code="LAYER7_STEP_FAILED"
        )
        try:
            drive_client.write_completion_flag(f"layer7_completed_{date_str}.json", flag)
        except Exception:  # noqa: BLE001
            pass
        return {"completed": False, "error": str(exc)}

    # --- 手順10：全ステップ成功時のみcompleted:trueを書く -----------------------------
    flag = completion_flag_writer.build_completion_flag(completed=True, completed_at=now, run_date=date_str)
    drive_client.write_completion_flag(f"layer7_completed_{date_str}.json", flag)

    return {
        "completed": True,
        "new_positions_count": len(sheet_rows) - len(skipped_duplicates) if sheet_rows else 0,
        "skipped_duplicates": skipped_duplicates,
        "failed_price_tickers": failed_tickers,
        "active_positions_count": len(remaining_active),
        "closed_positions": closed_positions,
        "manual_close_errors": manual_result["errors"],
        "layer8_export_entries": layer8_export_entries,
    }
