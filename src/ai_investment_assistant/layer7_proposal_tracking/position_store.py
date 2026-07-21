"""active_positions.json / closed_positions_YYYYMM.json の組み立てロジック
（layer7_proposal_tracking_design.md §6-2・§6-3）。

`active_positions.json`は直近1回分の`latest_price`のみを保持する薄いファイルとし、
日次の全価格履歴は持たせない（§6-2）。実際のGoogle Driveへの読み書きは
`drive_client.py`が担う。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def build_closed_position(
    position: dict,
    exit_price: Optional[float],
    exit_date,
    exit_reason: str,
    closed_at: str,
) -> dict:
    """§6-3のclosed_positions_YYYYMM.jsonエントリを組み立てる。"""
    entry_date = _parse_date(position["entry_date"])
    exit_date_parsed = _parse_date(exit_date)
    holding_days = (exit_date_parsed - entry_date).days + 1

    entry_price = position["entry_price"]
    final_return_pct = (
        (exit_price - entry_price) / entry_price * 100 if (exit_price is not None and entry_price) else None
    )

    return {
        "tracking_id": position["tracking_id"],
        "run_id": position["run_id"],
        "ticker": position["ticker"],
        "name": position.get("name"),
        "entry_date": position["entry_date"],
        "entry_price": entry_price,
        "exit_date": exit_date_parsed.isoformat(),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_days": holding_days,
        "max_unrealized_gain_pct": position.get("max_unrealized_gain_pct", 0.0),
        "max_unrealized_loss_pct": position.get("max_unrealized_loss_pct", 0.0),
        "final_return_pct": final_return_pct,
        "recommended_shares": position.get("recommended_shares"),
        "closed_at": closed_at,
    }


def remove_position(positions: list, tracking_id: str) -> list:
    """`tracking_id`に一致するpositionをリストから除外した新しいリストを返す。"""
    return [p for p in positions if p["tracking_id"] != tracking_id]


def year_month_of(date_str) -> str:
    parsed = _parse_date(date_str)
    return f"{parsed.year:04d}{parsed.month:02d}"
