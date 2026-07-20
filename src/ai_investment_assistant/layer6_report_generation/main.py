"""Layer6パイプラインのエントリポイント（layer6_report_generation_design.md §3・§10）。

入力はdecision JSONオブジェクトのみ（§4）。1つのSinkの失敗が他のSinkの実行を妨げない
（§3手順5・§10）よう、各Sinkは独立してtry/exceptで実行する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..layer5_ai_judgment.scripts.schema_validator import SchemaValidationError, validate_layer5_output
from . import error_report_builder, history_writer
from .datetime_util import execution_date_jst
from .presentation_model import build_presentation_model


def run(
    decision_document: Optional[dict],
    sinks: list,
    drive_client,
    now: Optional[datetime] = None,
) -> dict:
    """Layer6の全ステップを実行する。

    `sinks`はconfig/report_sinks.yamlのenabled_sinksに基づき、呼び出し側が既に組み立てた
    ReportSinkインスタンスのリスト（現行はGoogleSheetsSink・MarkdownSink、§11）。
    `drive_client`はエラーレポート（Markdownのみ）の保存にも使う。
    """
    now = now or datetime.now(timezone.utc)

    # --- 手順1相当：decision JSON自体が存在しない場合（§10） ---------------------------
    if decision_document is None:
        text = error_report_builder.build_missing_decision_report()
        date_str = now.strftime("%Y%m%d")
        path = drive_client.write_markdown_report(f"report_{date_str}.md", text)
        return {"status": "error", "reason_code": "DECISION_JSON_MISSING", "sink_results": {"markdown": path}}

    # --- トップレベルキー欠落等、契約違反の検査（§10） ---------------------------------
    try:
        validate_layer5_output(decision_document)
    except SchemaValidationError as exc:
        text = error_report_builder.build_schema_violation_report(str(exc))
        date_str = now.strftime("%Y%m%d")
        path = drive_client.write_markdown_report(f"report_{date_str}.md", text)
        return {"status": "error", "reason_code": "SCHEMA_VIOLATION", "sink_results": {"markdown": path}}

    # --- 手順3：PresentationModelへの変換（値は一切変更しない、§5-1） -------------------
    presentation_model = build_presentation_model(decision_document)
    run_meta = presentation_model["run_meta"]
    gate = run_meta.get("data_quality_gate")
    date_str = execution_date_jst(run_meta)
    year_month = date_str[:6]

    # --- 手順4：データ品質ゲートがblockedの場合、通常フローを実行しない（§10） ----------
    if gate == "blocked":
        text = error_report_builder.build_blocked_report(decision_document)
        path = drive_client.write_markdown_report(f"report_{date_str}.md", text)
        entry = {
            **history_writer.build_failure_entry(date_str, run_meta.get("run_id"), "data_quality_gate=blocked"),
            "status": "blocked",
        }
        history_writer.write_report_index_entry(drive_client, year_month, entry)
        return {"status": "blocked", "sink_results": {"markdown": path}}

    # --- 手順5：各Sinkを独立して実行する（1つの失敗が他をブロックしない、§3手順5） --------
    sink_results = {}
    sink_errors = {}
    for sink in sinks:
        try:
            sink_results[sink.name] = sink.render_and_save(presentation_model)
        except Exception as exc:  # noqa: BLE001
            sink_errors[sink.name] = str(exc)

    # --- 手順6：履歴インデックスへの追記 -----------------------------------------------
    if sink_results:
        sheet_file = sink_results.get("google_sheets")
        entry = history_writer.build_report_index_entry_from_presentation_model(presentation_model, sheet_file)
        if sink_errors:
            entry = {**entry, "partial_failure": sink_errors}
    else:
        # 両方（あるいは有効な全て）のSinkが失敗した場合、失敗自体を記録する（§10）
        entry = history_writer.build_failure_entry(
            date_str, run_meta.get("run_id"), f"all sinks failed: {sink_errors}"
        )

    history_writer.write_report_index_entry(drive_client, year_month, entry)

    return {
        "status": "ok" if sink_results else "error",
        "sink_results": sink_results,
        "sink_errors": sink_errors,
    }
