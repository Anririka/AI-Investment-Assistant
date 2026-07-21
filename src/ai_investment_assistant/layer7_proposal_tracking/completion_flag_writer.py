"""tracking/layer7_completed_YYYYMMDD.json の生成（layer7_proposal_tracking_design.md
§4手順10・§6-5、Layer8との完了フラグ契約）。

Layer4の完了フラグ書き込み原則（layer4_persistence_design.md §3手順7・§6-2）と同じ
思想を、Layer7→Layer8間のタイミング調整にも適用する：全保存処理が成功した場合のみ
`completed: true`を書き込む。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def _iso_z(dt: datetime) -> str:
    iso = dt.isoformat()
    return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso


def build_completion_flag(
    completed: bool,
    completed_at: datetime,
    run_date: str,
    failure_reason_code: Optional[str] = None,
) -> dict:
    flag = {
        "completed": completed,
        "completed_at": _iso_z(completed_at),
        "run_date": run_date,
    }
    if failure_reason_code is not None:
        flag["failure_reason_code"] = failure_reason_code
    return flag
