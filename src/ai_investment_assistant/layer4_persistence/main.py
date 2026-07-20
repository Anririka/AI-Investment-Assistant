"""Layer4パイプラインのエントリポイント（layer4_persistence_design.md §3）。

書き込み順序を厳密に固定する：market_snapshot → execution_log → history index →
completion flag。**全て成功した場合のみ`completed: true`を書く**（§6-2、Layer5との
契約の核）。途中で1つでも失敗すれば完了フラグは`completed:true`にならない
（全体不可分の原則、§9）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from . import completion_flag_writer, execution_logger, history_indexer, snapshot_writer
from .repository.base import PersistenceRepository
from .schema_validator import SchemaValidationError, validate_market_snapshot

SCHEMA_VERSION = "1.0"


def run(
    repository: PersistenceRepository,
    date_str: str,
    year_month: str,
    run_id: str,
    layer2_output: dict,
    layer_status: dict,
    started_at: datetime,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    """Layer4の全ステップを実行する。戻り値: {"completed": bool, ...}。"""
    data_quality = layer2_output.get("run_meta", {}).get("data_quality", {})
    errors: list = []
    warnings: list = list(data_quality.get("warning_errors", []))

    # 手順3：Schemaバリデーション（トップレベルキーの存在のみ、§3）
    try:
        validate_market_snapshot(layer2_output)
    except SchemaValidationError as exc:
        return _write_failure_flag(
            repository, date_str, layer_status, clock(), "SNAPSHOT_SCHEMA_INVALID", str(exc)
        )

    try:
        # 手順4：market_snapshotの保存
        snapshot_path = snapshot_writer.write_snapshot(repository, date_str, layer2_output)
        saved_files = [snapshot_path]

        # 手順5：execution_logの保存（この時点で保存済みなのはsnapshotのみ、§5-3）
        exec_log = execution_logger.build_execution_log(
            run_id=run_id,
            schema_version=SCHEMA_VERSION,
            started_at=started_at,
            completed_at=clock(),
            saved_files=saved_files,
            save_destination="google_drive:AI投資アシスタント",
            related_files_planned={
                "history_index": f"history/index_{year_month}.json",
                "completion_flag": f"snapshots/layer4_completed_{date_str}.json",
            },
            errors=errors,
            warnings=warnings,
        )
        execution_logger.write_execution_log(repository, date_str, exec_log)

        # 手順6：history indexの追記
        candidates = layer2_output.get("candidates", [])
        history_entry = history_indexer.build_history_entry(
            date_str=date_str,
            run_id=run_id,
            status="completed",
            candidate_count=len(candidates),
            blocking_errors_count=len(data_quality.get("critical_errors", [])),
            warning_errors_count=len(data_quality.get("warning_errors", [])),
            snapshot_path=snapshot_path,
        )
        history_indexer.write_history_entry(repository, year_month, history_entry)

    except Exception as exc:  # noqa: BLE001
        return _write_failure_flag(
            repository, date_str, layer_status, clock(), "PERSISTENCE_STEP_FAILED", str(exc)
        )

    # 手順7：手順4〜6が全て成功した場合のみcompleted:trueを書く
    success_layer_status = {**layer_status, "layer4": "success"}
    flag = completion_flag_writer.build_completion_flag(
        completed=True,
        completed_at=clock(),
        layer_status=success_layer_status,
        snapshot_path=snapshot_path,
    )
    completion_flag_writer.write_completion_flag(repository, date_str, flag)

    return {"completed": True, "snapshot_path": snapshot_path}


def _write_failure_flag(
    repository: PersistenceRepository,
    date_str: str,
    layer_status: dict,
    completed_at: datetime,
    failure_reason_code: str,
    error_message: str,
) -> dict:
    """失敗時：completed:falseの完了フラグを書き込む。Drive自体に書けない場合は
    完了フラグファイル自体が存在しない状態になる（§9、安全側に倒れる）。"""
    failure_layer_status = {**layer_status, "layer4": "failed"}
    flag = completion_flag_writer.build_completion_flag(
        completed=False,
        completed_at=completed_at,
        layer_status=failure_layer_status,
        snapshot_path=None,
        failure_reason_code=failure_reason_code,
    )
    try:
        repository.save_completion_flag(date_str, flag)
    except Exception:  # noqa: BLE001
        pass  # Drive自体に書き込めない場合は完了フラグファイル自体が存在しない状態でよい（§9）

    return {"completed": False, "failure_reason_code": failure_reason_code, "error": error_message}
