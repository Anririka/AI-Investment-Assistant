"""manual_close_requests.json の読込・処理・削除（layer7_proposal_tracking_design.md §8-4）。

必須項目は`tracking_id`のみ。`exit_price`／`exit_date`が省略された場合、Layer7は次回
実行時点の最新取得価格・実行日をそれぞれ採用する。存在しない`tracking_id`が指定された
場合はエラーとして記録し、リクエストは削除せず残す（§9、誤って握りつぶさないため）。
"""

from __future__ import annotations

from typing import Optional


def process_manual_close_requests(
    active_positions: list,
    requests: list,
    default_exit_date: str,
) -> dict:
    """戻り値: {"closed": [(position, exit_price, exit_date, note), ...],
                "remaining_requests": [...], "errors": [...]}

    `closed`の各要素は、`position_store.build_closed_position`にそのまま渡せる形の
    タプル（position辞書・exit_price・exit_date・note）。呼び出し側が
    `exit_reason="manual_close"`で組み立てる。
    """
    positions_by_id = {p["tracking_id"]: p for p in active_positions}
    closed = []
    remaining_requests = []
    errors = []

    for request in requests:
        tracking_id = request.get("tracking_id")
        position = positions_by_id.get(tracking_id)
        if position is None:
            errors.append({
                "tracking_id": tracking_id,
                "reason": "指定されたtracking_idはactive_positions.jsonに存在しません",
            })
            remaining_requests.append(request)
            continue

        exit_price = request.get("exit_price")
        if exit_price is None and position.get("latest_price") is not None:
            exit_price = position["latest_price"]["close"]
        exit_date = request.get("exit_date") or default_exit_date

        closed.append((position, exit_price, exit_date, request.get("note")))
        # 処理済みのリクエストはキューから削除する（remaining_requestsに含めない）

    return {"closed": closed, "remaining_requests": remaining_requests, "errors": errors}
