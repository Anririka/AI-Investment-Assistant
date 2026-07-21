"""アクティブポジションの現在価格取得（layer7_proposal_tracking_design.md §4手順4・§7）。

`PriceCheckRepository`経由で当日の市場価格を取得し、`latest_price`・
`max_unrealized_gain_pct`／`max_unrealized_loss_pct`（§6-2、これまでの最大値を逐次更新）
を更新する。特定ティッカーの価格取得失敗時は当該ポジションを`active`のまま維持し、
次回実行時に再試行する（データ欠損を理由に強制決済しない、§9）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Tuple


def update_position_price(position: dict, repository, now: Callable[[], datetime] = None) -> Tuple[dict, bool]:
    """1ポジション分の価格を取得・反映する。戻り値: (更新後position, 成功したか)。

    取得失敗時は例外を送出せず、position を変更せずそのまま返す（§9：既存の`active`状態を
    維持し、次回実行時に再試行するため）。
    """
    now = now or (lambda: datetime.now(timezone.utc))
    try:
        snapshot = repository.get_latest_price(position["ticker"], position.get("asset_class"))
    except Exception:  # noqa: BLE001
        return position, False

    entry_price = position["entry_price"]
    gain_pct_today = (snapshot.high - entry_price) / entry_price * 100 if entry_price else 0.0
    loss_pct_today = (snapshot.low - entry_price) / entry_price * 100 if entry_price else 0.0

    updated = {
        **position,
        "latest_price": {
            "date": snapshot.date.isoformat() if hasattr(snapshot.date, "isoformat") else snapshot.date,
            "close": snapshot.close,
            "high": snapshot.high,
            "low": snapshot.low,
            "volume": snapshot.volume,
        },
        "max_unrealized_gain_pct": max(position.get("max_unrealized_gain_pct", 0.0), gain_pct_today),
        "max_unrealized_loss_pct": min(position.get("max_unrealized_loss_pct", 0.0), loss_pct_today),
        "last_checked_at": now().isoformat().replace("+00:00", "Z"),
    }
    return updated, True


def update_all_positions(positions: list, repository, now: Callable[[], datetime] = None) -> Tuple[list, list]:
    """全アクティブポジションの価格を更新する。戻り値: (更新後positionsリスト, 失敗したtickerのリスト)。"""
    updated_positions = []
    failed_tickers = []
    for position in positions:
        updated, ok = update_position_price(position, repository, now=now)
        updated_positions.append(updated)
        if not ok:
            failed_tickers.append(position["ticker"])
    return updated_positions, failed_tickers
