"""rule_enforcement_formatter.pyのテスト（layer6_report_generation_design.md §9）。"""

from ai_investment_assistant.layer6_report_generation.formatters.rule_enforcement_formatter import (
    RULE_ENFORCEMENT_COLUMNS,
    build_rule_enforcement_row,
    rule_enforcement_row_as_list,
)


def test_build_rule_enforcement_row_includes_applied_false_entries():
    row = build_rule_enforcement_row({"rule": "confidence_gate", "applied": False}, "20260718", "run1")
    assert row["適用有無"] is False
    assert row["ルール名"] == "confidence_gate"


def test_build_rule_enforcement_row_blank_detail_when_missing():
    row = build_rule_enforcement_row({"rule": "confidence_gate", "applied": False}, "20260718", "run1")
    assert row["詳細"] == ""


def test_rule_enforcement_row_as_list_matches_columns():
    row = build_rule_enforcement_row({"rule": "x", "applied": True, "detail": "d"}, "20260718", "run1")
    values = rule_enforcement_row_as_list(row)
    assert len(values) == len(RULE_ENFORCEMENT_COLUMNS)
    assert values[RULE_ENFORCEMENT_COLUMNS.index("詳細")] == "d"
