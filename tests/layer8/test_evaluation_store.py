"""evaluation_store.pyのテスト（layer8_self_evaluation_design.md §6、§11テスト方針）。"""

from ai_investment_assistant.layer8_self_evaluation.evaluation_store import (
    merge_position_evaluations,
    year_month_of_run_id,
)


def test_year_month_of_run_id():
    assert year_month_of_run_id("20260718-0630") == "202607"


def test_merge_position_evaluations_appends_new_entries():
    existing = {"evaluations": [{"tracking_id": "TRK-A", "outcome": "win"}]}
    merged = merge_position_evaluations(existing, [{"tracking_id": "TRK-B", "outcome": "loss"}])
    ids = {e["tracking_id"] for e in merged["evaluations"]}
    assert ids == {"TRK-A", "TRK-B"}


def test_merge_position_evaluations_overwrites_existing_same_tracking_id_without_duplicating():
    existing = {"evaluations": [{"tracking_id": "TRK-A", "outcome": "loss"}]}
    merged = merge_position_evaluations(existing, [{"tracking_id": "TRK-A", "outcome": "win"}])
    assert len(merged["evaluations"]) == 1
    assert merged["evaluations"][0]["outcome"] == "win"


def test_merge_position_evaluations_handles_empty_existing():
    merged = merge_position_evaluations({}, [{"tracking_id": "TRK-A", "outcome": "win"}])
    assert len(merged["evaluations"]) == 1
