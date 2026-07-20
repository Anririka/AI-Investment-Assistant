"""Markdownレポート出力（layer6_report_generation_design.md §7）。"""

from __future__ import annotations

from datetime import datetime

from ..datetime_util import execution_date_jst
from ..error_report_builder import DISCLAIMER
from ..formatters.candidate_formatter import format_proposal_markdown
from ..formatters.decision_log_formatter import build_excluded_candidates_for_display
from .base import ReportSink


def _title_date(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y%m%d")
    return f"{dt.year}年{dt.month}月{dt.day}日"


def render_markdown(presentation_model: dict) -> str:
    """§7-1のテンプレート構成通りにMarkdown文字列を生成する。値は一切変更しない。"""
    run_meta = presentation_model["run_meta"]
    proposals = presentation_model.get("proposals", [])
    decision_log = presentation_model.get("decision_log", [])
    rule_enforcement_log = presentation_model.get("rule_enforcement_log", [])

    date_str = execution_date_jst(run_meta)
    gate = run_meta.get("data_quality_gate")
    gate_detail = run_meta.get("data_quality_gate_detail", {})

    lines = [
        f"# AI投資アシスタント 日次レポート — {_title_date(date_str)}",
        "",
        "## 市場環境",
        "（現在のLayer5出力には市場全体情報が含まれないため省略）",
        "",
        "## データ品質",
        f"- データ品質ゲート: {gate}",
    ]
    if gate == "warning_continued":
        warnings = gate_detail.get("warning_errors_found", [])
        codes = ", ".join(w.get("code", "") for w in warnings) if warnings else "（詳細なし）"
        lines.append(f"- 検知された警告: {codes}")
    lines.append("")

    lines.append(f"## 本日の提案（{len(proposals)}件）")
    lines.append("")
    if not proposals:
        lines.append("本日は提案なし（該当候補なし）")
    else:
        for proposal in proposals:
            lines.append(format_proposal_markdown(proposal))
            lines.append("")

    lines.append("## 除外・不採用候補")
    lines.append("")
    lines.append("| 証券コード | 判定 | 理由コード | 理由 |")
    lines.append("|---|---|---|---|")
    for entry in build_excluded_candidates_for_display(decision_log):
        reason = entry.get("reason") or ""
        lines.append(f"| {entry.get('ticker')} | {entry.get('decision')} | {entry.get('reason_code')} | {reason} |")
    lines.append("")

    lines.append("## ルール適用ログ")
    lines.append("")
    lines.append("| ルール | 適用有無 | 詳細 |")
    lines.append("|---|---|---|")
    for entry in rule_enforcement_log:
        detail = entry.get("detail") or ""
        lines.append(f"| {entry.get('rule')} | {entry.get('applied')} | {detail} |")
    lines.append("")

    score_meta_ref = run_meta.get("score_meta_ref", {})
    lines.extend([
        "## 実行ログ",
        "",
        f"- run_id: {run_meta.get('run_id')}",
        f"- 開始時刻: {run_meta.get('layer5_started_at')}",
        f"- 終了時刻: {run_meta.get('layer5_completed_at')}",
        f"- データ品質ゲート: {gate}",
        f"- スコアリングバージョン: {score_meta_ref.get('scoring_version')} / "
        f"配点バージョン: {score_meta_ref.get('weight_version')}",
        "",
        "---",
        DISCLAIMER,
    ])

    return "\n".join(lines)


class MarkdownSink(ReportSink):
    name = "markdown"

    def __init__(self, drive_client) -> None:
        self._drive_client = drive_client

    def render(self, presentation_model: dict) -> dict:
        """{"file_name": ..., "text": ...} を返す（§7-3のファイル命名規則に基づく）。"""
        date_str = execution_date_jst(presentation_model["run_meta"])
        return {
            "file_name": f"report_{date_str}.md",
            "text": render_markdown(presentation_model),
        }

    def save(self, rendered_content: dict) -> str:
        return self._drive_client.write_markdown_report(
            rendered_content["file_name"], rendered_content["text"]
        )
