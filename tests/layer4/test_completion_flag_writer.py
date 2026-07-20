"""completion_flag_writer.pyのテスト（layer4_persistence_design.md §5-2）。"""

from datetime import datetime, timezone

from ai_investment_assistant.layer4_persistence.completion_flag_writer import build_completion_flag


def test_success_flag_has_no_failure_reason_code():
    flag = build_completion_flag(
        completed=True,
        completed_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc),
        layer_status={"layer1": "success", "layer2": "success", "layer3": "success", "layer4": "success"},
        snapshot_path="snapshots/market_snapshot_20260720.json",
    )
    assert flag["completed"] is True
    assert flag["completed_at"] == "2026-07-20T09:00:00Z"
    assert "failure_reason_code" not in flag


def test_failure_flag_includes_reason_code_and_null_snapshot_path():
    flag = build_completion_flag(
        completed=False,
        completed_at=datetime(2026, 7, 20, 9, 5, 0, tzinfo=timezone.utc),
        layer_status={"layer1": "success", "layer2": "success", "layer3": "failed", "layer4": "not_started"},
        snapshot_path=None,
        failure_reason_code="SCORING_FAILED",
    )
    assert flag["completed"] is False
    assert flag["snapshot_path"] is None
    assert flag["failure_reason_code"] == "SCORING_FAILED"
