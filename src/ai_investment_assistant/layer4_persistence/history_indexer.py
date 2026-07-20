"""history/index_YYYYMM.jsonの更新（layer4_persistence_design.md §5-4）。

過去実行をmarket_snapshot全文を開かずに参照できるようにするための軽量インデックス。
"""

from __future__ import annotations

from typing import Optional

from .repository.base import PersistenceRepository


def build_history_entry(
    date_str: str,
    run_id: str,
    status: str,
    candidate_count: int,
    blocking_errors_count: int,
    warning_errors_count: int,
    snapshot_path: Optional[str],
) -> dict:
    return {
        "date": date_str,
        "run_id": run_id,
        "status": status,
        "candidate_count": candidate_count,
        "blocking_errors_count": blocking_errors_count,
        "warning_errors_count": warning_errors_count,
        "snapshot_path": snapshot_path,
    }


def write_history_entry(repository: PersistenceRepository, year_month: str, entry: dict) -> str:
    return repository.save_history_index(year_month, entry)
