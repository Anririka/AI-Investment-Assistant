"""proposal_ingester.pyのテスト（layer7_proposal_tracking_design.md §4手順2・§6-2、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.proposal_ingester import (
    build_tracking_id,
    ingest_new_positions,
)

UNIT_DAYS = {"日": 1, "週間": 7, "週": 7, "ヶ月": 30, "か月": 30, "カ月": 30}
FALLBACK = 90


def _sheet_row(**overrides):
    base = {
        "run_id": "20260718-0630", "日付": "2026-07-18", "証券コード": "NVDA",
        "銘柄名": "NVIDIA Corporation", "購入価格目安": 333.74, "損切価格": 300.37,
        "利確価格": 383.80, "想定保有期間": "2〜4週間", "推奨株数": 4,
    }
    base.update(overrides)
    return base


def test_build_tracking_id_format():
    assert build_tracking_id("20260718-0630", "NVDA") == "TRK-20260718-0630-NVDA"


def test_ingest_new_positions_creates_position_preserving_values():
    new_positions, skipped = ingest_new_positions([_sheet_row()], [], UNIT_DAYS, FALLBACK)
    assert skipped == []
    assert len(new_positions) == 1
    position = new_positions[0]
    assert position["tracking_id"] == "TRK-20260718-0630-NVDA"
    assert position["entry_price"] == 333.74
    assert position["stop_loss_price"] == 300.37
    assert position["take_profit_price"] == 383.80
    assert position["recommended_shares"] == 4
    assert position["holding_period_days_parsed"] == 28
    assert position["status"] == "active"
    assert position["latest_price"] is None


def test_ingest_new_positions_skips_existing_run_id_ticker_combo():
    existing = [{"run_id": "20260718-0630", "ticker": "NVDA"}]
    new_positions, skipped = ingest_new_positions([_sheet_row()], existing, UNIT_DAYS, FALLBACK)
    assert new_positions == []
    assert skipped == [("20260718-0630", "NVDA")]


def test_ingest_new_positions_same_run_new_ticker_not_skipped():
    existing = [{"run_id": "20260718-0630", "ticker": "AMD"}]
    new_positions, skipped = ingest_new_positions([_sheet_row()], existing, UNIT_DAYS, FALLBACK)
    assert len(new_positions) == 1
    assert skipped == []


def test_ingest_new_positions_infers_asset_class_from_numeric_ticker():
    row = _sheet_row(証券コード="7203", 銘柄名="トヨタ自動車")
    new_positions, _ = ingest_new_positions([row], [], UNIT_DAYS, FALLBACK)
    assert new_positions[0]["asset_class"] == "japan_equity"


def test_ingest_new_positions_records_fallback_parse_status():
    row = _sheet_row(想定保有期間="しばらく")
    new_positions, _ = ingest_new_positions([row], [], UNIT_DAYS, FALLBACK)
    assert new_positions[0]["parse_status"] == "fallback_used"
    assert new_positions[0]["holding_period_days_parsed"] == FALLBACK
