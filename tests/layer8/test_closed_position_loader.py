"""closed_position_loader.pyのテスト（layer8_self_evaluation_design.md §4-1、§11テスト方針）。"""

from ai_investment_assistant.layer8_self_evaluation.closed_position_loader import select_unevaluated


def test_select_unevaluated_excludes_already_evaluated_across_months():
    closed_positions = [
        {"tracking_id": "TRK-JUNE", "run_id": "20260615-0900"},
        {"tracking_id": "TRK-JULY", "run_id": "20260718-0630"},
    ]
    # TRK-JUNEは前月に既に評価済み（月をまたいでも正しく除外される）
    unevaluated = select_unevaluated(closed_positions, {"TRK-JUNE"})
    assert [p["tracking_id"] for p in unevaluated] == ["TRK-JULY"]


def test_select_unevaluated_returns_all_when_none_evaluated():
    closed_positions = [{"tracking_id": "TRK-A"}, {"tracking_id": "TRK-B"}]
    assert len(select_unevaluated(closed_positions, set())) == 2


def test_select_unevaluated_no_duplicate_reevaluation():
    closed_positions = [{"tracking_id": "TRK-A"}]
    assert select_unevaluated(closed_positions, {"TRK-A"}) == []
