"""candidate_formatter.pyのテスト（layer6_report_generation_design.md §6-3・§7-1）。"""

from ai_investment_assistant.layer6_report_generation.formatters.candidate_formatter import (
    SHEET_COLUMNS,
    build_proposal_sheet_row,
    format_proposal_markdown,
    sheet_row_as_list,
)
from .sample_data import sample_decision_document


def _nvda_proposal():
    doc = sample_decision_document()
    return next(p for p in doc["proposals"] if p["ticker"] == "NVDA")


def test_build_proposal_sheet_row_has_all_columns():
    row = build_proposal_sheet_row(_nvda_proposal(), date_str="20260718", run_id="20260718-0630")
    assert set(row.keys()) == set(SHEET_COLUMNS)


def test_build_proposal_sheet_row_preserves_values_without_recalculation():
    proposal = _nvda_proposal()
    row = build_proposal_sheet_row(proposal, date_str="20260718", run_id="20260718-0630")
    assert row["証券コード"] == "NVDA"
    assert row["推奨株数"] == proposal["recommended_shares"]
    assert row["総合スコア"] == proposal["score_summary"]["composite"]
    assert row["ニュース不確実性"] == proposal["score_summary"]["news"]["uncertainty"]
    assert row["代替候補"] == "AMD (rank 4), AVGO (rank 6)"


def test_sheet_row_as_list_matches_column_order():
    row = build_proposal_sheet_row(_nvda_proposal(), date_str="20260718", run_id="20260718-0630")
    values = sheet_row_as_list(row)
    assert values[SHEET_COLUMNS.index("証券コード")] == "NVDA"
    assert len(values) == len(SHEET_COLUMNS)


def test_format_proposal_markdown_includes_key_fields():
    text = format_proposal_markdown(_nvda_proposal())
    assert "第1位" in text
    assert "NVDA" in text
    assert "NVIDIA Corporation" in text
    assert "78" in text  # confidence
    assert "不確実性: 35" in text
    assert "AMD (rank 4), AVGO (rank 6)" in text


def test_format_proposal_markdown_no_alternative_candidates_shows_placeholder():
    doc = sample_decision_document()
    amd = next(p for p in doc["proposals"] if p["ticker"] == "AMD")
    text = format_proposal_markdown(amd)
    assert "（なし）" in text
