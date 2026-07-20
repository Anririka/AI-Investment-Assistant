"""history_indexer.pyのテスト（layer4_persistence_design.md §5-4）。"""

from ai_investment_assistant.layer4_persistence.history_indexer import build_history_entry


def test_build_history_entry_fields():
    entry = build_history_entry(
        date_str="2026-07-20", run_id="20260720-0900", status="completed",
        candidate_count=27, blocking_errors_count=0, warning_errors_count=1,
        snapshot_path="snapshots/market_snapshot_20260720.json",
    )
    assert entry["date"] == "2026-07-20"
    assert entry["candidate_count"] == 27
    assert entry["snapshot_path"] == "snapshots/market_snapshot_20260720.json"
