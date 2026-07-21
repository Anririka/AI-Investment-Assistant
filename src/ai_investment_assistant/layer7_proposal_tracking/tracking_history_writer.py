"""tracking_history_YYYYMM.json への追記（layer7_proposal_tracking_design.md §4手順8・§6-4）。

当日時点の全ポジション（アクティブ・クローズ済み双方）のスナップショットを追記する。
"""

from __future__ import annotations

from typing import Optional


def build_history_entries_for_active(date_str: str, active_positions: list) -> list:
    entries = []
    for position in active_positions:
        latest_price = position.get("latest_price")
        entry_price = position.get("entry_price")
        close = latest_price["close"] if latest_price else None
        unrealized_return_pct = (
            (close - entry_price) / entry_price * 100 if (close is not None and entry_price) else None
        )
        entries.append({
            "date": date_str,
            "tracking_id": position["tracking_id"],
            "status": position.get("status", "active"),
            "close": close,
            "unrealized_return_pct": unrealized_return_pct,
        })
    return entries


def build_history_entries_for_closed(date_str: str, closed_positions: list) -> list:
    entries = []
    for position in closed_positions:
        entries.append({
            "date": date_str,
            "tracking_id": position["tracking_id"],
            "status": position["exit_reason"],
            "close": position.get("exit_price"),
            "unrealized_return_pct": position.get("final_return_pct"),
        })
    return entries


def build_daily_snapshot_entries(date_str: str, active_positions: list, newly_closed_positions: list) -> list:
    """§6-4のtracking_history_YYYYMM.jsonエントリ群を、当日分まとめて組み立てる。"""
    return (
        build_history_entries_for_active(date_str, active_positions)
        + build_history_entries_for_closed(date_str, newly_closed_positions)
    )
