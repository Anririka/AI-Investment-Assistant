"""exit_evaluator.pyのテスト（layer7_proposal_tracking_design.md §8-2、§11テスト方針）。"""

from datetime import date

from ai_investment_assistant.layer7_proposal_tracking.exit_evaluator import compute_judge_date, evaluate_exit


def _position(**overrides):
    base = {
        "tracking_id": "TRK-1", "entry_date": "2026-07-01", "entry_price": 100.0,
        "stop_loss_price": 90.0, "take_profit_price": 115.0, "holding_period_days_parsed": 28,
        "latest_price": {"date": "2026-07-05", "close": 100.0, "high": 105.0, "low": 95.0, "volume": 1000},
    }
    base.update(overrides)
    return base


def test_compute_judge_date_28_days_from_entry():
    judge_date = compute_judge_date("2026-07-01", 28)
    assert judge_date == date(2026, 7, 28)


def test_evaluate_exit_stop_loss_when_low_at_or_below_stop_loss_price():
    position = _position(latest_price={"date": "2026-07-05", "close": 92.0, "high": 96.0, "low": 89.0, "volume": 1})
    result = evaluate_exit(position, today=date(2026, 7, 5))
    assert result == {"status": "stop_loss", "exit_price": 90.0, "exit_reason": "stop_loss"}


def test_evaluate_exit_take_profit_when_high_at_or_above_take_profit_price():
    position = _position(latest_price={"date": "2026-07-05", "close": 116.0, "high": 116.0, "low": 101.0, "volume": 1})
    result = evaluate_exit(position, today=date(2026, 7, 5))
    assert result == {"status": "take_profit", "exit_price": 115.0, "exit_reason": "take_profit"}


def test_evaluate_exit_both_conditions_same_day_prefers_stop_loss():
    # 当日の値幅が損切ライン・利確ラインの両方を跨いだ場合、損切を優先する（§8-2ルール3）
    position = _position(latest_price={"date": "2026-07-05", "close": 100.0, "high": 120.0, "low": 85.0, "volume": 1})
    result = evaluate_exit(position, today=date(2026, 7, 5))
    assert result["status"] == "stop_loss"
    assert result["exit_price"] == 90.0


def test_evaluate_exit_holding_period_not_yet_expired_continues_active():
    # entry_date=7/1, holding_period_days_parsed=28 -> judge_date=7/28。7/27はまだ継続。
    position = _position()
    result = evaluate_exit(position, today=date(2026, 7, 27))
    assert result == {"status": "active", "exit_price": None, "exit_reason": None}


def test_evaluate_exit_holding_period_expires_exactly_on_judge_date():
    position = _position()
    result = evaluate_exit(position, today=date(2026, 7, 28))
    assert result["status"] == "holding_period_expired"
    assert result["exit_price"] == 100.0  # latest_price.close


def test_evaluate_exit_holding_period_expires_when_judge_date_already_passed():
    # judge_date（非営業日等）を過ぎて初めて実行された場合も終了扱いになる（§8-2）
    position = _position()
    result = evaluate_exit(position, today=date(2026, 8, 2))
    assert result["status"] == "holding_period_expired"


def test_evaluate_exit_no_latest_price_yet_only_holding_period_can_trigger():
    position = _position(latest_price=None)
    result = evaluate_exit(position, today=date(2026, 7, 20))
    assert result == {"status": "active", "exit_price": None, "exit_reason": None}
