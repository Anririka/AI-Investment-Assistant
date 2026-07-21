"""completion_flag_writer.pyのテスト（layer7_proposal_tracking_design.md §6-5、§11テスト方針）。"""

from datetime import datetime, timezone

from ai_investment_assistant.layer7_proposal_tracking.completion_flag_writer import build_completion_flag


def test_build_completion_flag_success():
    flag = build_completion_flag(True, datetime(2026, 7, 18, 21, 10, 0, tzinfo=timezone.utc), "2026-07-18")
    assert flag == {"completed": True, "completed_at": "2026-07-18T21:10:00Z", "run_date": "2026-07-18"}


def test_build_completion_flag_failure_includes_reason_code():
    flag = build_completion_flag(
        False, datetime(2026, 7, 18, 21, 12, 0, tzinfo=timezone.utc), "2026-07-18",
        failure_reason_code="PRICE_FETCH_FAILED",
    )
    assert flag["completed"] is False
    assert flag["failure_reason_code"] == "PRICE_FETCH_FAILED"
