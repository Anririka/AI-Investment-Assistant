"""main.py（Layer7パイプライン全体）の統合テスト（layer7_proposal_tracking_design.md §4・§9）。

「毒薬テスト」：手順2〜9のどこかで例外が発生すれば、completed:trueは書かれないことを確認する。
"""

from datetime import date, datetime, timezone

import pytest

from ai_investment_assistant.layer7_proposal_tracking import main
from ai_investment_assistant.layer7_proposal_tracking.repository.base import PriceSnapshot

UNIT_DAYS = {"日": 1, "週間": 7, "週": 7, "ヶ月": 30, "か月": 30, "カ月": 30}
FALLBACK = 90


class FakeDriveClient:
    def __init__(self, sheet_rows=None, active_positions=None, manual_close_requests=None, fail_on=frozenset()):
        self.tracking_files = {}
        if active_positions is not None:
            self.tracking_files["active_positions.json"] = {"positions": active_positions}
        if manual_close_requests is not None:
            self.tracking_files["manual_close_requests.json"] = {"requests": manual_close_requests}
        self._sheet_rows = sheet_rows
        self.completion_flags = []
        self.fail_on = fail_on

    def read_tracking_json(self, file_name):
        if file_name in self.fail_on:
            raise RuntimeError(f"read failed: {file_name}")
        return self.tracking_files.get(file_name)

    def write_tracking_json(self, file_name, content):
        if file_name in self.fail_on:
            raise RuntimeError(f"write failed: {file_name}")
        self.tracking_files[file_name] = content
        return f"tracking/{file_name}"

    def read_proposal_sheet_rows(self, date_str, sheet_name="本日の提案"):
        if "sheet" in self.fail_on:
            raise RuntimeError("sheet read failed")
        return self._sheet_rows

    def write_completion_flag(self, file_name, content):
        self.completion_flags.append((file_name, content))
        return f"tracking/{file_name}"


class FakeRepository:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def get_latest_price(self, ticker, asset_class):
        return self.snapshots[ticker]


def _sheet_row(**overrides):
    base = {
        "run_id": "20260718-0630", "日付": "2026-07-18", "証券コード": "NVDA",
        "銘柄名": "NVIDIA Corporation", "購入価格目安": 100.0, "損切価格": 90.0,
        "利確価格": 115.0, "想定保有期間": "2〜4週間", "推奨株数": 4,
    }
    base.update(overrides)
    return base


def test_run_ingests_new_position_and_keeps_it_active():
    client = FakeDriveClient(sheet_rows=[_sheet_row()], active_positions=[])
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=105, high=108, low=98, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       now=datetime(2026, 7, 18, 21, 0, 0, tzinfo=timezone.utc), today=date(2026, 7, 18))
    assert result["completed"] is True
    assert result["active_positions_count"] == 1
    assert client.tracking_files["active_positions.json"]["positions"][0]["ticker"] == "NVDA"
    assert client.completion_flags[-1][1]["completed"] is True


def test_run_skips_duplicate_ingestion():
    existing = [{"run_id": "20260718-0630", "ticker": "NVDA", "tracking_id": "TRK-20260718-0630-NVDA",
                 "entry_date": "2026-07-18", "entry_price": 100.0, "stop_loss_price": 90.0,
                 "take_profit_price": 115.0, "holding_period_days_parsed": 28, "asset_class": "us_equity",
                 "max_unrealized_gain_pct": 0.0, "max_unrealized_loss_pct": 0.0, "latest_price": None}]
    client = FakeDriveClient(sheet_rows=[_sheet_row()], active_positions=existing)
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=105, high=108, low=98, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       today=date(2026, 7, 18))
    assert result["active_positions_count"] == 1
    assert result["skipped_duplicates"] == [("20260718-0630", "NVDA")]


def test_run_closes_position_on_stop_loss_and_records_closed_positions_file():
    active = [{"run_id": "r1", "ticker": "NVDA", "tracking_id": "TRK-1", "entry_date": "2026-07-01",
               "entry_price": 100.0, "stop_loss_price": 90.0, "take_profit_price": 115.0,
               "holding_period_days_parsed": 28, "asset_class": "us_equity",
               "max_unrealized_gain_pct": 0.0, "max_unrealized_loss_pct": 0.0, "latest_price": None}]
    client = FakeDriveClient(sheet_rows=None, active_positions=active)
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=91, high=95, low=88, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       today=date(2026, 7, 18))
    assert result["completed"] is True
    assert result["active_positions_count"] == 0
    assert len(result["closed_positions"]) == 1
    assert result["closed_positions"][0]["exit_reason"] == "stop_loss"
    assert client.tracking_files["closed_positions_202607.json"]["positions"][0]["ticker"] == "NVDA"


def test_run_manual_close_takes_priority_over_automatic_stop_loss():
    active = [{"run_id": "r1", "ticker": "NVDA", "tracking_id": "TRK-1", "entry_date": "2026-07-01",
               "entry_price": 100.0, "stop_loss_price": 90.0, "take_profit_price": 115.0,
               "holding_period_days_parsed": 28, "asset_class": "us_equity",
               "max_unrealized_gain_pct": 0.0, "max_unrealized_loss_pct": 0.0, "latest_price": None}]
    manual_requests = [{"tracking_id": "TRK-1", "exit_price": 105.0, "exit_date": "2026-07-18", "note": "手動決済"}]
    client = FakeDriveClient(sheet_rows=None, active_positions=active, manual_close_requests=manual_requests)
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=91, high=95, low=88, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       today=date(2026, 7, 18))
    assert len(result["closed_positions"]) == 1
    closed = result["closed_positions"][0]
    assert closed["exit_reason"] == "manual_close"
    assert closed["exit_price"] == 105.0
    assert client.tracking_files["manual_close_requests.json"]["requests"] == []


def test_run_missing_layer6_sheet_skips_ingestion_but_continues_tracking():
    active = [{"run_id": "r1", "ticker": "NVDA", "tracking_id": "TRK-1", "entry_date": "2026-07-01",
               "entry_price": 100.0, "stop_loss_price": 90.0, "take_profit_price": 115.0,
               "holding_period_days_parsed": 28, "asset_class": "us_equity",
               "max_unrealized_gain_pct": 0.0, "max_unrealized_loss_pct": 0.0, "latest_price": None}]
    client = FakeDriveClient(sheet_rows=None, active_positions=active)
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=105, high=108, low=98, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       today=date(2026, 7, 18))
    assert result["completed"] is True
    assert result["new_positions_count"] == 0
    assert result["active_positions_count"] == 1


@pytest.mark.parametrize("failing_file", ["active_positions.json"])
def test_poison_pill_step_failure_prevents_completed_true(failing_file):
    client = FakeDriveClient(sheet_rows=[_sheet_row()], active_positions=[], fail_on={failing_file})
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=105, high=108, low=98, volume=1000)})
    result = main.run(client, repo, date_str="20260718", unit_days=UNIT_DAYS, fallback_default_days=FALLBACK,
                       today=date(2026, 7, 18))
    assert result["completed"] is False
    assert client.completion_flags[-1][1]["completed"] is False
    assert client.completion_flags[-1][1]["failure_reason_code"] == "LAYER7_STEP_FAILED"
