"""price_checker.pyのテスト（layer7_proposal_tracking_design.md §7・§9、§11テスト方針）。"""

from datetime import date, datetime, timezone

from ai_investment_assistant.layer7_proposal_tracking.price_checker import update_all_positions, update_position_price
from ai_investment_assistant.layer7_proposal_tracking.repository.base import PriceSnapshot


class FakeRepository:
    def __init__(self, snapshots=None, fail_tickers=None):
        self.snapshots = snapshots or {}
        self.fail_tickers = fail_tickers or set()

    def get_latest_price(self, ticker, asset_class):
        if ticker in self.fail_tickers:
            raise RuntimeError("price fetch failed")
        return self.snapshots[ticker]


def _position(**overrides):
    base = {"ticker": "NVDA", "asset_class": "us_equity", "entry_price": 100.0,
            "max_unrealized_gain_pct": 0.0, "max_unrealized_loss_pct": 0.0}
    base.update(overrides)
    return base


def test_update_position_price_success_updates_latest_price_and_extremes():
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 18), close=110, high=115, low=95, volume=1000)})
    position = _position()
    updated, ok = update_position_price(position, repo, now=lambda: datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))
    assert ok is True
    assert updated["latest_price"]["close"] == 110
    assert updated["max_unrealized_gain_pct"] == 15.0  # (115-100)/100*100
    assert updated["max_unrealized_loss_pct"] == -5.0  # (95-100)/100*100
    assert updated["last_checked_at"] == "2026-07-18T21:00:00Z"


def test_update_position_price_keeps_running_max_across_calls():
    repo = FakeRepository({"NVDA": PriceSnapshot(date=date(2026, 7, 19), close=108, high=112, low=105, volume=1000)})
    position = _position(max_unrealized_gain_pct=15.0, max_unrealized_loss_pct=-5.0)
    updated, _ = update_position_price(position, repo)
    # 今日のhigh(112)による含み益率12%は既存の15%より小さいため更新されない
    assert updated["max_unrealized_gain_pct"] == 15.0
    assert updated["max_unrealized_loss_pct"] == -5.0


def test_update_position_price_failure_keeps_position_unchanged():
    repo = FakeRepository(fail_tickers={"NVDA"})
    position = _position()
    updated, ok = update_position_price(position, repo)
    assert ok is False
    assert updated == position


def test_update_all_positions_reports_failed_tickers_without_raising():
    repo = FakeRepository(
        snapshots={"AMD": PriceSnapshot(date=date(2026, 7, 18), close=150, high=155, low=145, volume=500)},
        fail_tickers={"NVDA"},
    )
    positions = [_position(ticker="NVDA"), _position(ticker="AMD")]
    updated, failed = update_all_positions(positions, repo)
    assert failed == ["NVDA"]
    assert len(updated) == 2
