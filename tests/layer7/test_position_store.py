"""position_store.pyのテスト（layer7_proposal_tracking_design.md §6-2・§6-3、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.position_store import (
    build_closed_position,
    remove_position,
    year_month_of,
)


def _position(**overrides):
    base = {
        "tracking_id": "TRK-20260701-0900-NVDA", "run_id": "20260701-0900", "ticker": "NVDA",
        "name": "NVIDIA Corporation", "entry_date": "2026-07-01", "entry_price": 100.0,
        "max_unrealized_gain_pct": 16.2, "max_unrealized_loss_pct": -1.1, "recommended_shares": 4,
    }
    base.update(overrides)
    return base


def test_build_closed_position_computes_holding_days_inclusive():
    closed = build_closed_position(_position(), exit_price=115.0, exit_date="2026-07-18", exit_reason="take_profit",
                                    closed_at="2026-07-18T21:05:00Z")
    assert closed["holding_days"] == 18  # 7/1〜7/18 inclusive


def test_build_closed_position_computes_final_return_pct():
    closed = build_closed_position(_position(), exit_price=115.0, exit_date="2026-07-18", exit_reason="take_profit",
                                    closed_at="2026-07-18T21:05:00Z")
    assert closed["final_return_pct"] == 15.0


def test_build_closed_position_preserves_max_unrealized_fields():
    closed = build_closed_position(_position(), exit_price=115.0, exit_date="2026-07-18", exit_reason="take_profit",
                                    closed_at="2026-07-18T21:05:00Z")
    assert closed["max_unrealized_gain_pct"] == 16.2
    assert closed["max_unrealized_loss_pct"] == -1.1


def test_remove_position_filters_by_tracking_id():
    positions = [_position(tracking_id="TRK-A"), _position(tracking_id="TRK-B")]
    remaining = remove_position(positions, "TRK-A")
    assert [p["tracking_id"] for p in remaining] == ["TRK-B"]


def test_year_month_of_derives_from_date_string():
    assert year_month_of("2026-07-18") == "202607"
