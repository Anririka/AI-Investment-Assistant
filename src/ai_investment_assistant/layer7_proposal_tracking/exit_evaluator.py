"""利確／損切／保有期間終了の判定ロジック（layer7_proposal_tracking_design.md §8）。

判定順序（§8-2）：
1. 損切判定：当日安値がstop_loss_price以下 → stop_loss
2. 利確判定（1に該当しない場合）：当日高値がtake_profit_price以上 → take_profit
   （同日に両方満たす場合は1が先に判定されるため、自動的に損切優先となる）
3. 保有期間終了判定（1・2に該当しない場合）：judge_date = entry_date +
   (holding_period_days_parsed - 1) に到達していれば → holding_period_expired
4. いずれにも該当しなければ → active（継続）
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def compute_judge_date(entry_date, holding_period_days_parsed: int) -> date:
    """保有期間終了の判定基準日（§8-2ルール4）。"""
    return _parse_date(entry_date) + timedelta(days=holding_period_days_parsed - 1)


def evaluate_exit(position: dict, today) -> dict:
    """position（latest_priceが既に当日分に更新済みであること）から終了判定を行う。

    戻り値: {"status": ..., "exit_price": Optional[float], "exit_reason": Optional[str]}
    `status`が"active"の場合はexit_price/exit_reasonともにNone。
    """
    today = _parse_date(today) if not isinstance(today, date) else today
    latest_price = position.get("latest_price")

    if latest_price is not None:
        if latest_price["low"] <= position["stop_loss_price"]:
            return {"status": "stop_loss", "exit_price": position["stop_loss_price"], "exit_reason": "stop_loss"}

        if latest_price["high"] >= position["take_profit_price"]:
            return {"status": "take_profit", "exit_price": position["take_profit_price"], "exit_reason": "take_profit"}

    judge_date = compute_judge_date(position["entry_date"], position["holding_period_days_parsed"])
    if today >= judge_date:
        exit_price = latest_price["close"] if latest_price is not None else None
        return {"status": "holding_period_expired", "exit_price": exit_price, "exit_reason": "holding_period_expired"}

    return {"status": "active", "exit_price": None, "exit_reason": None}
