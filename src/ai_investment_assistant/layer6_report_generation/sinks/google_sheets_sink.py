"""Google Sheets出力（layer6_report_generation_design.md §6）。

1ファイル内に4つのシート（タブ）を持たせる構成（§6-1）：
本日の提案／除外・不採用ログ／ルール適用ログ／実行サマリー。
"""

from __future__ import annotations

from ..datetime_util import execution_date_jst
from ..formatters.candidate_formatter import SHEET_COLUMNS, build_proposal_sheet_row, sheet_row_as_list
from ..formatters.decision_log_formatter import (
    EXCLUDED_LOG_COLUMNS,
    build_excluded_candidates_for_display,
    build_excluded_log_row,
    excluded_log_row_as_list,
)
from ..formatters.rule_enforcement_formatter import (
    RULE_ENFORCEMENT_COLUMNS,
    build_rule_enforcement_row,
    rule_enforcement_row_as_list,
)
from .base import ReportSink

SHEET_NAME_PROPOSALS = "本日の提案"
SHEET_NAME_EXCLUDED = "除外・不採用ログ"
SHEET_NAME_RULES = "ルール適用ログ"
SHEET_NAME_SUMMARY = "実行サマリー"


def build_sheets_data(presentation_model: dict, date_str: str) -> dict:
    """§6-1〜§6-5の4シート分のデータを{シート名: [[ヘッダー], [行], ...]}として組み立てる。"""
    run_meta = presentation_model["run_meta"]
    run_id = run_meta.get("run_id")
    proposals = presentation_model.get("proposals", [])
    decision_log = presentation_model.get("decision_log", [])
    rule_enforcement_log = presentation_model.get("rule_enforcement_log", [])

    proposal_rows = [sheet_row_as_list(build_proposal_sheet_row(p, date_str, run_id)) for p in proposals]

    excluded_rows = [
        excluded_log_row_as_list(build_excluded_log_row(entry, date_str, run_id))
        for entry in build_excluded_candidates_for_display(decision_log)
    ]

    rule_rows = [
        rule_enforcement_row_as_list(build_rule_enforcement_row(entry, date_str, run_id))
        for entry in rule_enforcement_log
    ]

    score_meta_ref = run_meta.get("score_meta_ref", {})
    summary_rows = [[
        date_str, run_id, run_meta.get("layer5_started_at"), run_meta.get("layer5_completed_at"),
        run_meta.get("data_quality_gate"), score_meta_ref.get("scoring_version"),
        score_meta_ref.get("weight_version"),
    ]]
    summary_columns = ["日付", "run_id", "開始時刻", "終了時刻", "データ品質ゲート", "スコアリングバージョン", "配点バージョン"]

    return {
        SHEET_NAME_PROPOSALS: [SHEET_COLUMNS] + proposal_rows,
        SHEET_NAME_EXCLUDED: [EXCLUDED_LOG_COLUMNS] + excluded_rows,
        SHEET_NAME_RULES: [RULE_ENFORCEMENT_COLUMNS] + rule_rows,
        SHEET_NAME_SUMMARY: [summary_columns] + summary_rows,
    }


class GoogleSheetsSink(ReportSink):
    name = "google_sheets"

    def __init__(self, drive_client) -> None:
        self._drive_client = drive_client

    def render(self, presentation_model: dict) -> dict:
        date_str = execution_date_jst(presentation_model["run_meta"])
        return {
            "file_name": f"提案ログ_{date_str}",
            "sheets_data": build_sheets_data(presentation_model, date_str),
        }

    def save(self, rendered_content: dict) -> str:
        return self._drive_client.write_proposal_spreadsheet(
            rendered_content["file_name"], rendered_content["sheets_data"]
        )
