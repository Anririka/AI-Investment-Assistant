"""layer8_export_builder.pyのテスト（layer7_proposal_tracking_design.md §13、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.layer8_export_builder import (
    LAYER8_EXPORT_FIELDS,
    build_layer8_export_entries,
    build_layer8_export_entry,
)


def _closed_position():
    return {
        "tracking_id": "TRK-1", "run_id": "run1", "ticker": "NVDA", "name": "NVIDIA Corporation",
        "entry_price": 100.0, "exit_price": 115.0, "holding_days": 18,
        "max_unrealized_gain_pct": 16.2, "max_unrealized_loss_pct": -1.1,
        "final_return_pct": 15.0, "exit_reason": "take_profit", "recommended_shares": 4,
    }


def test_build_layer8_export_entry_has_exactly_the_specified_fields():
    entry = build_layer8_export_entry(_closed_position())
    assert set(entry.keys()) == set(LAYER8_EXPORT_FIELDS)
    assert "name" not in entry
    assert "recommended_shares" not in entry


def test_build_layer8_export_entries_processes_all():
    entries = build_layer8_export_entries([_closed_position(), _closed_position()])
    assert len(entries) == 2
