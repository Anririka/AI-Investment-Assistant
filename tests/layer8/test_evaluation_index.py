"""evaluation_index.pyのテスト（layer8_self_evaluation_design.md §4-1、§11テスト方針）。"""

from ai_investment_assistant.layer8_self_evaluation.evaluation_index import (
    evaluated_ids_set,
    merge_evaluated_ids,
)


def test_evaluated_ids_set_defaults_to_empty():
    assert evaluated_ids_set({}) == set()


def test_evaluated_ids_set_returns_existing_ids():
    assert evaluated_ids_set({"evaluated_tracking_ids": ["TRK-A", "TRK-B"]}) == {"TRK-A", "TRK-B"}


def test_merge_evaluated_ids_adds_new_without_duplicating():
    index_doc = {"evaluated_tracking_ids": ["TRK-A"]}
    updated = merge_evaluated_ids(index_doc, ["TRK-B", "TRK-A"])
    assert set(updated["evaluated_tracking_ids"]) == {"TRK-A", "TRK-B"}
    assert len(updated["evaluated_tracking_ids"]) == 2
