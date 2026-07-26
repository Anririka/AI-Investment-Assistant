"""history_writer.pyのテスト（layer6_report_generation_design.md §6-6・§10）。"""

from ai_investment_assistant.layer6_report_generation.history_writer import (
    build_failure_entry,
    build_report_index_entry,
    build_report_index_entry_from_presentation_model,
    write_report_index_entry,
)
from ai_investment_assistant.layer6_report_generation.presentation_model import build_presentation_model
from .sample_data import sample_decision_document


def test_build_report_index_entry_fields():
    entry = build_report_index_entry(
        date_str="2026-07-18", run_id="20260718-0630", sheet_file="reports/提案ログ_20260718",
        proposal_count=2, top_ticker="NVDA", top_composite_score=79, data_quality_gate="passed",
    )
    assert entry["proposal_count"] == 2
    assert entry["top_ticker"] == "NVDA"


def test_build_report_index_entry_from_presentation_model_uses_top_ranked_proposal():
    model = build_presentation_model(sample_decision_document())
    entry = build_report_index_entry_from_presentation_model(model, sheet_file="reports/提案ログ_20260718")
    assert entry["top_ticker"] == "NVDA"  # rank 1
    assert entry["top_composite_score"] == 79
    assert entry["proposal_count"] == 2
    assert entry["date"] == "20260718"


def test_build_report_index_entry_from_presentation_model_uses_jst_date_across_day_boundary():
    """2026-07-26追加、回帰テスト：Layer6の実データ初回検証で、UTC 15:00〜23:59
    （JST側は既に翌日）に完了した場合、以前のコードは`layer5_completed_at`のUTC日付を
    そのまま切り出していたため、ファイル名（`report_YYYYMMDD.md`等、JST基準・§6-2）の
    日付と1日ずれていた。`execution_date_jst`で統一し、ズレないことを確認する
    （Layer4・Layer5で過去に発覚したのと同種のJST/UTC不整合の再発防止）。
    """
    model = build_presentation_model(sample_decision_document())
    model["run_meta"]["layer5_completed_at"] = "2026-07-25T23:09:35Z"  # JST では 2026-07-26 08:09
    entry = build_report_index_entry_from_presentation_model(model, sheet_file="reports/提案ログ_20260726")
    assert entry["date"] == "20260726"


def test_build_report_index_entry_from_presentation_model_handles_zero_proposals():
    model = build_presentation_model(sample_decision_document(gate="blocked"))
    entry = build_report_index_entry_from_presentation_model(model, sheet_file=None)
    assert entry["top_ticker"] is None
    assert entry["proposal_count"] == 0


def test_build_failure_entry_records_status():
    entry = build_failure_entry("20260718", "run1", "all sinks failed")
    assert entry["status"] == "report_generation_failed"
    assert entry["detail"] == "all sinks failed"


class FakeDriveClient:
    def __init__(self):
        self.entries = []

    def write_report_index_entry(self, year_month, entry):
        self.entries.append((year_month, entry))
        return f"reports/report_index_{year_month}.json"


def test_write_report_index_entry_delegates_to_drive_client():
    client = FakeDriveClient()
    path = write_report_index_entry(client, "202607", {"date": "2026-07-18"})
    assert path == "reports/report_index_202607.json"
    assert client.entries == [("202607", {"date": "2026-07-18"})]
