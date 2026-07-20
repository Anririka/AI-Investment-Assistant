"""layer4_completed_YYYYMMDD.jsonの生成（layer4_persistence_design.md §5-2、Layer5との契約の核）。

§3手順4〜6が全て成功した場合のみ`completed: true`で書き込む（「毒薬テスト」対応）。
Layer5詳細設計書§3-1で定義された構造をそのまま採用する（変更しない）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .repository.base import PersistenceRepository


def _iso_z(dt: datetime) -> str:
    iso = dt.isoformat()
    return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso


def build_completion_flag(
    completed: bool,
    completed_at: datetime,
    layer_status: dict,
    snapshot_path: Optional[str],
    failure_reason_code: Optional[str] = None,
) -> dict:
    flag = {
        "completed": completed,
        "completed_at": _iso_z(completed_at),
        "layer_status": layer_status,
        "snapshot_path": snapshot_path,
    }
    if failure_reason_code is not None:
        flag["failure_reason_code"] = failure_reason_code
    return flag


def write_completion_flag(repository: PersistenceRepository, date_str: str, flag: dict) -> str:
    return repository.save_completion_flag(date_str, flag)
