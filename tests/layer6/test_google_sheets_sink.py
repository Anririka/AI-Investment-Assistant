"""google_sheets_sink.pyのテスト（layer6_report_generation_design.md §6）。"""

from ai_investment_assistant.layer6_report_generation.presentation_model import build_presentation_model
from ai_investment_assistant.layer6_report_generation.sinks.google_sheets_sink import (
    GoogleSheetsSink,
    SHEET_NAME_EXCLUDED,
    SHEET_NAME_PROPOSALS,
    SHEET_NAME_RULES,
    SHEET_NAME_SUMMARY,
    build_sheets_data,
)
from .sample_data import sample_decision_document


def test_build_sheets_data_has_four_sheets():
    model = build_presentation_model(sample_decision_document())
    sheets = build_sheets_data(model, date_str="20260718")
    assert set(sheets.keys()) == {SHEET_NAME_PROPOSALS, SHEET_NAME_EXCLUDED, SHEET_NAME_RULES, SHEET_NAME_SUMMARY}


def test_proposals_sheet_has_header_plus_two_rows():
    model = build_presentation_model(sample_decision_document())
    sheets = build_sheets_data(model, date_str="20260718")
    rows = sheets[SHEET_NAME_PROPOSALS]
    assert len(rows) == 1 + 2  # header + NVDA + AMD
    header = rows[0]
    assert "証券コード" in header


def test_excluded_sheet_excludes_adopted_entries():
    model = build_presentation_model(sample_decision_document())
    sheets = build_sheets_data(model, date_str="20260718")
    rows = sheets[SHEET_NAME_EXCLUDED][1:]  # skip header
    tickers = [row[2] for row in rows]  # 証券コードは3列目
    assert "6723" in tickers
    assert "TSM" in tickers
    assert "NVDA" not in tickers


def test_rules_sheet_includes_applied_false():
    model = build_presentation_model(sample_decision_document())
    sheets = build_sheets_data(model, date_str="20260718")
    rows = sheets[SHEET_NAME_RULES][1:]
    applied_values = [row[3] for row in rows]  # 適用有無は4列目
    assert False in applied_values


def test_summary_sheet_has_run_meta_fields():
    model = build_presentation_model(sample_decision_document())
    sheets = build_sheets_data(model, date_str="20260718")
    row = sheets[SHEET_NAME_SUMMARY][1]
    assert row[1] == "20260718-0630"  # run_id


class FakeDriveClient:
    def __init__(self):
        self.saved = {}

    def write_proposal_spreadsheet(self, file_name, sheets_data):
        self.saved[file_name] = sheets_data
        return f"reports/{file_name}"


def test_google_sheets_sink_render_and_save_uses_jst_date_filename():
    model = build_presentation_model(sample_decision_document())
    client = FakeDriveClient()
    sink = GoogleSheetsSink(client)
    path = sink.render_and_save(model)
    assert path == "reports/提案ログ_20260718"
    assert "提案ログ_20260718" in client.saved
