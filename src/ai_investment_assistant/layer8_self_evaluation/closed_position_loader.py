"""Layer7の`closed_positions_YYYYMM.json`から未評価ポジションを特定する
（layer8_self_evaluation_design.md §4手順3・4、§4-1）。

読み取り専用（§2非責務）：Layer7が保存した値は一切変更しない。
"""

from __future__ import annotations

from typing import Iterable


def select_unevaluated(closed_positions: list, evaluated_tracking_ids: Iterable) -> list:
    """`closed_positions`のうち、`evaluated_tracking_ids`に含まれていないもの（＝未評価）
    のみを返す（月をまたいだ横断判定は、呼び出し側が複数月分の`closed_positions`を
    連結して渡すことで実現する）。
    """
    evaluated = set(evaluated_tracking_ids)
    return [p for p in closed_positions if p["tracking_id"] not in evaluated]
