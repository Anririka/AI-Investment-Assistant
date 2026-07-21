"""tracking_history_writer.pyのテスト（layer7_proposal_tracking_design.md §6-4、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.tracking_history_writer import build_daily_snapshot_entries


def test_build_daily_snapshot_entries_includes_active_and_closed():
    active = [{"tracking_id": "TRK-A", "status": "active", "entry_price": 100.0,
               "latest_price": {"close": 110.0}}]
    closed = [{"tracking_id": "TRK-B", "exit_reason": "take_profit", "exit_price": 383.80,
               "final_return_pct": 15.0}]
    entries = build_daily_snapshot_entries("20260718", active, closed)
    assert len(entries) == 2
    active_entry = next(e for e in entries if e["tracking_id"] == "TRK-A")
    assert active_entry["unrealized_return_pct"] == 10.0
    closed_entry = next(e for e in entries if e["tracking_id"] == "TRK-B")
    assert closed_entry["status"] == "take_profit"
    assert closed_entry["unrealized_return_pct"] == 15.0
