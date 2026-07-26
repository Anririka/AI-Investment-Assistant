"""生成レポート自体の履歴保存・履歴インデックス管理
（layer6_report_generation_design.md §6-6）。

`reports/report_index_YYYYMM.json`は、Layer4の`history/index_YYYYMM.json`と同じ
「既存ファイルを読み込んで追記」パターンを踏襲する軽量インデックスである。
Layer5の`decisions/`・Layer4の`history/`とは責務・保存先を分離する（§6-6）。
"""

from __future__ import annotations

from typing import Optional

from .datetime_util import execution_date_jst


def build_report_index_entry(
    date_str: str,
    run_id: str,
    sheet_file: Optional[str],
    proposal_count: int,
    top_ticker: Optional[str],
    top_composite_score: Optional[float],
    data_quality_gate: str,
) -> dict:
    return {
        "date": date_str,
        "run_id": run_id,
        "sheet_file": sheet_file,
        "proposal_count": proposal_count,
        "top_ticker": top_ticker,
        "top_composite_score": top_composite_score,
        "data_quality_gate": data_quality_gate,
    }


def build_report_index_entry_from_presentation_model(presentation_model: dict, sheet_file: Optional[str]) -> dict:
    """PresentationModel（rank昇順に整列済み）から履歴インデックスの1エントリを組み立てる。

    `proposals`は既にrank昇順のため、先頭要素がtop_ticker／top_composite_scoreとなる。

    2026-07-26修正（Layer6実データ初回検証で発覚）：以前は`date_str`を
    `layer5_completed_at`（UTC）の日付部分をそのまま切り出して算出していたが、
    ファイル名（`report_YYYYMMDD.md`・`提案ログ_YYYYMMDD`）はJST基準（§6-2・§7-3）の
    ため、UTC 15:00〜23:59（JST側は既に翌日）に実行された場合、インデックスの`date`が
    実際のファイル名の日付と1日ずれる不整合があった（Layer4・Layer5で過去に発覚したのと
    同種のJST/UTC不整合。§6-2参照）。`execution_date_jst`で統一する。
    """
    run_meta = presentation_model["run_meta"]
    proposals = presentation_model.get("proposals", [])
    top = proposals[0] if proposals else None

    return build_report_index_entry(
        date_str=execution_date_jst(run_meta),
        run_id=run_meta.get("run_id"),
        sheet_file=sheet_file,
        proposal_count=len(proposals),
        top_ticker=top.get("ticker") if top else None,
        top_composite_score=top.get("score_summary", {}).get("composite") if top else None,
        data_quality_gate=run_meta.get("data_quality_gate"),
    )


def build_failure_entry(date_str: str, run_id: Optional[str], detail: str) -> dict:
    """両方のSinkが失敗した場合、失敗自体を履歴インデックスに記録する（§10）。"""
    return {
        "date": date_str,
        "run_id": run_id,
        "sheet_file": None,
        "proposal_count": None,
        "top_ticker": None,
        "top_composite_score": None,
        "data_quality_gate": None,
        "status": "report_generation_failed",
        "detail": detail,
    }


def write_report_index_entry(drive_client, year_month: str, entry: dict) -> str:
    return drive_client.write_report_index_entry(year_month, entry)
