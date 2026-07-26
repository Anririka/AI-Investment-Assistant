"""position_store.pyのテスト（layer7_proposal_tracking_design.md §6-2・§6-3、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.position_store import (
    build_closed_position,
    normalize_position_numeric_fields,
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


def test_normalize_position_numeric_fields_converts_legacy_string_values():
    """2026-07-26追加、回帰テスト：Google Drive上に文字列型のまま永続化されて
    しまった過去のエントリ（実データ初回検証で発覚）が、読み込み時に数値へ補正
    されることを確認する。"""
    legacy_position = _position(
        entry_price="2897", stop_loss_price="2607.3", take_profit_price="3244.64",
        recommended_shares="28",
    )
    normalized = normalize_position_numeric_fields(legacy_position)
    assert normalized["entry_price"] == 2897.0
    assert isinstance(normalized["entry_price"], float)
    assert normalized["stop_loss_price"] == 2607.3
    assert normalized["take_profit_price"] == 3244.64
    assert normalized["recommended_shares"] == 28
    assert isinstance(normalized["recommended_shares"], int)


def test_normalize_position_numeric_fields_is_idempotent_for_already_numeric_values():
    position = _position(stop_loss_price=95.0, take_profit_price=120.0)
    normalized = normalize_position_numeric_fields(position)
    assert normalized["entry_price"] == 100.0
    assert normalized["stop_loss_price"] == 95.0
    assert normalized["take_profit_price"] == 120.0
    assert normalized["recommended_shares"] == 4


def test_normalize_position_numeric_fields_leaves_missing_fields_untouched():
    position = {"tracking_id": "TRK-A"}
    normalized = normalize_position_numeric_fields(position)
    assert normalized == {"tracking_id": "TRK-A"}
