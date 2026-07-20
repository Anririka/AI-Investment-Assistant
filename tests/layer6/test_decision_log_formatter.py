"""decision_log_formatter.pyのテスト（layer6_report_generation_design.md §8）。"""

from ai_investment_assistant.layer6_report_generation.formatters.decision_log_formatter import (
    build_excluded_candidates_for_display,
    build_excluded_log_row,
    sort_decision_log,
)


def test_sort_decision_log_orders_rejected_before_not_selected():
    entries = [
        {"ticker": "B", "decision": "not_selected", "rank": 4},
        {"ticker": "A", "decision": "rejected"},
    ]
    sorted_entries = sort_decision_log(entries)
    assert [e["ticker"] for e in sorted_entries] == ["A", "B"]


def test_sort_decision_log_orders_by_rank_ascending_within_same_decision():
    entries = [
        {"ticker": "C", "decision": "not_selected", "rank": 5},
        {"ticker": "B", "decision": "not_selected", "rank": 4},
    ]
    sorted_entries = sort_decision_log(entries)
    assert [e["ticker"] for e in sorted_entries] == ["B", "C"]


def test_sort_decision_log_falls_back_to_ticker_when_rank_missing():
    entries = [
        {"ticker": "Z", "decision": "rejected"},
        {"ticker": "A", "decision": "rejected"},
    ]
    sorted_entries = sort_decision_log(entries)
    assert [e["ticker"] for e in sorted_entries] == ["A", "Z"]


def test_sort_decision_log_does_not_mutate_values():
    entries = [{"ticker": "A", "decision": "rejected", "reason_code": "X"}]
    sorted_entries = sort_decision_log(entries)
    assert sorted_entries[0] == entries[0]


def test_build_excluded_candidates_for_display_excludes_adopted():
    entries = [
        {"ticker": "NVDA", "decision": "adopted", "rank": 1},
        {"ticker": "TSM", "decision": "not_selected", "rank": 4},
    ]
    displayed = build_excluded_candidates_for_display(entries)
    assert [e["ticker"] for e in displayed] == ["TSM"]


def test_build_excluded_log_row_blank_reason_when_missing():
    row = build_excluded_log_row({"ticker": "X", "decision": "rejected", "reason_code": "Y"}, "20260718", "run1")
    assert row["理由"] == ""
    assert row["順位"] == ""
