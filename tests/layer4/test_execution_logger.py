"""execution_logger.pyのテスト（layer4_persistence_design.md §5-3）。

saved_filesには生成時点で既に保存済みの成果物のみを含み、history index・completion flag
は`related_files_planned`に分離されることを確認する（§5-3の重要な注記）。
"""

from datetime import datetime, timezone

from ai_investment_assistant.layer4_persistence.execution_logger import build_execution_log


def test_saved_files_contains_only_snapshot():
    log = build_execution_log(
        run_id="20260720-0900",
        schema_version="1.0",
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 20, 9, 5, 0, tzinfo=timezone.utc),
        saved_files=["snapshots/market_snapshot_20260720.json"],
        save_destination="google_drive:AI投資アシスタント",
        related_files_planned={
            "history_index": "history/index_202607.json",
            "completion_flag": "snapshots/layer4_completed_20260720.json",
        },
        errors=[],
        warnings=[],
    )
    assert log["saved_files"] == ["snapshots/market_snapshot_20260720.json"]
    assert "history/index_202607.json" not in log["saved_files"]
    assert log["related_files_planned"]["history_index"] == "history/index_202607.json"


def test_saved_count_matches_saved_files_length():
    log = build_execution_log(
        run_id="r", schema_version="1.0", started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 20, tzinfo=timezone.utc), saved_files=["a.json", "b.json"],
        save_destination="google_drive:x", related_files_planned={}, errors=[], warnings=[],
    )
    assert log["saved_count"] == 2
