"""Layer8（自己評価層）へ渡す評価データの生成（layer7_proposal_tracking_design.md §13）。

クローズしたポジションから、§13で定義された10フィールドのみを過不足なく抽出する
（closed_positions_YYYYMM.jsonにはLayer7内部用の`name`等の付随情報も含まれるが、
Layer8向けエクスポートは契約として明示された項目のみに絞る）。
"""

from __future__ import annotations

LAYER8_EXPORT_FIELDS = [
    "tracking_id", "run_id", "ticker", "entry_price", "exit_price", "holding_days",
    "max_unrealized_gain_pct", "max_unrealized_loss_pct", "final_return_pct", "exit_reason",
]


def build_layer8_export_entry(closed_position: dict) -> dict:
    return {field: closed_position.get(field) for field in LAYER8_EXPORT_FIELDS}


def build_layer8_export_entries(closed_positions: list) -> list:
    return [build_layer8_export_entry(p) for p in closed_positions]
