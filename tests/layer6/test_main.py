"""main.py（Layer6パイプライン全体）の統合テスト
（layer6_report_generation_design.md §3・§10）。"""

from datetime import datetime, timezone

from ai_investment_assistant.layer6_report_generation import main
from .sample_data import sample_decision_document


class FakeDriveClient:
    def __init__(self):
        self.markdown_saved = {}
        self.index_entries = []

    def write_markdown_report(self, file_name, text):
        self.markdown_saved[file_name] = text
        return f"reports/{file_name}"

    def write_report_index_entry(self, year_month, entry):
        self.index_entries.append((year_month, entry))
        return f"reports/report_index_{year_month}.json"


class FakeSink:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self._result = result or f"reports/fake_{name}"
        self._error = error
        self.called_with = None

    def render_and_save(self, presentation_model):
        self.called_with = presentation_model
        if self._error:
            raise RuntimeError(self._error)
        return self._result


def test_run_missing_decision_document_writes_markdown_only():
    client = FakeDriveClient()
    result = main.run(None, sinks=[], drive_client=client, now=datetime(2026, 7, 18, 7, 0, 0, tzinfo=timezone.utc))
    assert result["status"] == "error"
    assert result["reason_code"] == "DECISION_JSON_MISSING"
    assert "report_20260718.md" in client.markdown_saved
    assert "Layer5の出力が確認できません" in client.markdown_saved["report_20260718.md"]


def test_run_schema_violation_writes_diagnostic_markdown_only():
    client = FakeDriveClient()
    invalid = sample_decision_document()
    del invalid["proposals"]
    result = main.run(invalid, sinks=[], drive_client=client, now=datetime(2026, 7, 18, 7, 0, 0, tzinfo=timezone.utc))
    assert result["status"] == "error"
    assert result["reason_code"] == "SCHEMA_VIOLATION"
    assert len(client.markdown_saved) == 1


def test_run_blocked_gate_writes_simplified_report_and_history_entry():
    client = FakeDriveClient()
    document = sample_decision_document(gate="blocked")
    sinks = [FakeSink("google_sheets"), FakeSink("markdown")]
    result = main.run(document, sinks=sinks, drive_client=client)
    assert result["status"] == "blocked"
    assert "report_20260718.md" in client.markdown_saved
    assert "様子見" in client.markdown_saved["report_20260718.md"]
    # blocked時は通常のSinkは呼ばれない（§10：ブロック時は簡易レポートのみ）
    assert all(sink.called_with is None for sink in sinks)
    assert len(client.index_entries) == 1
    assert client.index_entries[0][1]["status"] == "blocked"


def test_run_passed_gate_calls_all_sinks_and_records_history():
    client = FakeDriveClient()
    document = sample_decision_document(gate="passed")
    sinks = [FakeSink("google_sheets"), FakeSink("markdown")]
    result = main.run(document, sinks=sinks, drive_client=client)
    assert result["status"] == "ok"
    assert result["sink_results"]["google_sheets"] == "reports/fake_google_sheets"
    assert result["sink_results"]["markdown"] == "reports/fake_markdown"
    assert all(sink.called_with is not None for sink in sinks)
    assert len(client.index_entries) == 1
    entry = client.index_entries[0][1]
    assert entry["top_ticker"] == "NVDA"


def test_run_one_sink_failure_does_not_block_the_other():
    client = FakeDriveClient()
    document = sample_decision_document(gate="passed")
    failing_sheets = FakeSink("google_sheets", error="Sheets API timeout")
    working_markdown = FakeSink("markdown")
    result = main.run(document, sinks=[failing_sheets, working_markdown], drive_client=client)
    assert result["status"] == "ok"
    assert "google_sheets" in result["sink_errors"]
    assert result["sink_results"]["markdown"] == "reports/fake_markdown"
    assert working_markdown.called_with is not None


def test_run_all_sinks_failing_records_failure_entry():
    client = FakeDriveClient()
    document = sample_decision_document(gate="passed")
    sinks = [FakeSink("google_sheets", error="e1"), FakeSink("markdown", error="e2")]
    result = main.run(document, sinks=sinks, drive_client=client)
    assert result["status"] == "error"
    assert result["sink_results"] == {}
    assert len(client.index_entries) == 1
    entry = client.index_entries[0][1]
    assert entry["status"] == "report_generation_failed"
