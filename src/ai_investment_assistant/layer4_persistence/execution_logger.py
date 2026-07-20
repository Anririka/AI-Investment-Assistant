"""execution_log_YYYYMMDD.jsonの生成（layer4_persistence_design.md §5-3）。

`saved_files`には、このexecution_log自身が生成される時点で既に保存済みの成果物のみを
含める（現時点ではmarket_snapshotのみ）。history index・completion flagはまだ書き込まれて
いないため`related_files_planned`に分離して記録する（§5-3の重要な注記）。
"""

from __future__ import annotations

from datetime import datetime

from .completion_flag_writer import _iso_z
from .repository.base import PersistenceRepository


def build_execution_log(
    run_id: str,
    schema_version: str,
    started_at: datetime,
    completed_at: datetime,
    saved_files: list,
    save_destination: str,
    related_files_planned: dict,
    errors: list,
    warnings: list,
) -> dict:
    return {
        "run_id": run_id,
        "schema_version": schema_version,
        "started_at": _iso_z(started_at),
        "completed_at": _iso_z(completed_at),
        "saved_files": saved_files,
        "saved_count": len(saved_files),
        "save_destination": save_destination,
        "related_files_planned": related_files_planned,
        "errors": errors,
        "warnings": warnings,
    }


def write_execution_log(repository: PersistenceRepository, date_str: str, log: dict) -> str:
    return repository.save_execution_log(date_str, log)
