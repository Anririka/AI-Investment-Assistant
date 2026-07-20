"""schema_validator.pyのテスト（layer4_persistence_design.md §3手順3・§8・§10）。

正常なmarket_snapshot／トップレベルキー欠落のケース双方で、期待通りの判定になることを確認する。
"""

import pytest

from ai_investment_assistant.layer4_persistence.schema_validator import (
    SchemaValidationError,
    validate_completion_flag,
    validate_execution_log,
    validate_market_snapshot,
)


def _valid_snapshot():
    return {
        "run_meta": {"run_id": "20260720-0900"},
        "regime": {"current_regime": "range"},
        "macro": {"axis_score": 65},
        "candidates": [],
        "excluded_summary": [],
    }


def test_valid_snapshot_passes():
    validate_market_snapshot(_valid_snapshot())  # 例外が出なければOK


def test_missing_top_level_key_raises_schema_validation_error():
    snapshot = _valid_snapshot()
    del snapshot["candidates"]
    with pytest.raises(SchemaValidationError):
        validate_market_snapshot(snapshot)


def test_internal_score_details_are_not_validated_by_layer4():
    # candidatesの中身が空でも、スコアの範囲不正でも、トップレベルキーさえあればLayer4は通す
    snapshot = _valid_snapshot()
    snapshot["candidates"] = [{"totally": "unstructured", "composite_score": "not-a-number"}]
    validate_market_snapshot(snapshot)  # 例外が出ないことの確認（Layer2の責務範囲）


def test_valid_completion_flag_passes():
    validate_completion_flag(
        {
            "completed": True,
            "completed_at": "2026-07-20T09:00:00Z",
            "layer_status": {"layer1": "success", "layer2": "success", "layer3": "success", "layer4": "success"},
        }
    )


def test_valid_execution_log_passes():
    validate_execution_log(
        {
            "run_id": "20260720-0900",
            "schema_version": "1.0",
            "started_at": "2026-07-20T09:00:00Z",
            "completed_at": "2026-07-20T09:05:00Z",
            "saved_files": ["snapshots/market_snapshot_20260720.json"],
            "saved_count": 1,
            "save_destination": "google_drive:AI投資アシスタント",
            "errors": [],
            "warnings": [],
        }
    )
