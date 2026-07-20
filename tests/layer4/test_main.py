"""main.py（Layer4パイプライン全体）の統合テスト（layer4_persistence_design.md §3・§6-2・§10）。

「毒薬テスト」：手順4〜6（snapshot→execution_log→history index）のどこか1つでも失敗
すれば、completed:trueは書かれないことを全パターンで確認する。
"""

from datetime import datetime, timezone

import pytest

from ai_investment_assistant.layer4_persistence import main
from ai_investment_assistant.layer4_persistence.repository.base import PersistenceRepository

LAYER_STATUS = {"layer1": "success", "layer2": "success", "layer3": "success"}


class FakePersistenceRepository(PersistenceRepository):
    """呼び出しを記録し、指定したメソッドで例外を送出できるテスト用Repository。"""

    def __init__(self, fail_on: set = frozenset()):
        self.fail_on = fail_on
        self.saved_snapshots: list = []
        self.saved_flags: list = []
        self.saved_logs: list = []
        self.saved_history_entries: list = []

    def save_snapshot(self, date_str, content):
        if "save_snapshot" in self.fail_on:
            raise RuntimeError("Drive write failed (snapshot)")
        self.saved_snapshots.append((date_str, content))
        return f"snapshots/market_snapshot_{date_str}.json"

    def save_completion_flag(self, date_str, content):
        if "save_completion_flag" in self.fail_on:
            raise RuntimeError("Drive write failed (completion flag)")
        self.saved_flags.append((date_str, content))
        return f"snapshots/layer4_completed_{date_str}.json"

    def save_execution_log(self, date_str, content):
        if "save_execution_log" in self.fail_on:
            raise RuntimeError("Drive write failed (execution log)")
        self.saved_logs.append((date_str, content))
        return f"logs/execution_log_{date_str}.json"

    def save_history_index(self, year_month, entry):
        if "save_history_index" in self.fail_on:
            raise RuntimeError("Drive write failed (history index)")
        self.saved_history_entries.append((year_month, entry))
        return f"history/index_{year_month}.json"


def _valid_layer2_output(candidate_count=2):
    return {
        "run_meta": {"run_id": "20260720-0900", "data_quality": {"critical_errors": [], "warning_errors": []}},
        "regime": {"current_regime": "range"},
        "macro": {"axis_score": 65},
        "candidates": [{"ticker": f"T{i}"} for i in range(candidate_count)],
        "excluded_summary": [],
    }


def _fixed_clock():
    times = iter([datetime(2026, 7, 20, 9, i, 0, tzinfo=timezone.utc) for i in range(10)])
    return lambda: next(times)


def test_all_steps_succeed_writes_completed_true():
    repo = FakePersistenceRepository()
    result = main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=_valid_layer2_output(), layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )
    assert result["completed"] is True
    assert len(repo.saved_snapshots) == 1
    assert len(repo.saved_logs) == 1
    assert len(repo.saved_history_entries) == 1
    assert repo.saved_flags[-1][1]["completed"] is True
    assert repo.saved_flags[-1][1]["layer_status"]["layer4"] == "success"


@pytest.mark.parametrize("failing_step", ["save_snapshot", "save_execution_log", "save_history_index"])
def test_poison_pill_any_single_step_failure_prevents_completed_true(failing_step):
    repo = FakePersistenceRepository(fail_on={failing_step})
    result = main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=_valid_layer2_output(), layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )
    assert result["completed"] is False
    assert result["failure_reason_code"] == "PERSISTENCE_STEP_FAILED"
    # completed:trueは一度も書かれていないこと
    assert all(not flag["completed"] for _, flag in repo.saved_flags)


def test_invalid_top_level_schema_prevents_any_save_and_writes_failure_flag():
    repo = FakePersistenceRepository()
    invalid_output = _valid_layer2_output()
    del invalid_output["candidates"]

    result = main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=invalid_output, layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )

    assert result["completed"] is False
    assert result["failure_reason_code"] == "SNAPSHOT_SCHEMA_INVALID"
    assert repo.saved_snapshots == []  # snapshotは保存されない
    assert repo.saved_flags[-1][1]["completed"] is False
    assert repo.saved_flags[-1][1]["snapshot_path"] is None


def test_failure_flag_write_itself_failing_does_not_raise():
    # completed:falseのフラグ書き込み自体がDrive障害で失敗しても、パイプラインが
    # 例外を送出しない（Drive自体に書き込めない場合はフラグファイルが存在しない状態でよい、§9）
    repo = FakePersistenceRepository(fail_on={"save_snapshot", "save_completion_flag"})
    result = main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=_valid_layer2_output(), layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )
    assert result["completed"] is False
    assert repo.saved_flags == []  # フラグ書き込みも失敗したため何も記録されない


def test_execution_log_saved_files_contains_only_snapshot_at_generation_time():
    repo = FakePersistenceRepository()
    main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=_valid_layer2_output(), layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )
    _, log_content = repo.saved_logs[0]
    assert log_content["saved_files"] == ["snapshots/market_snapshot_20260720.json"]
    assert "history_index" in log_content["related_files_planned"]
    assert "completion_flag" in log_content["related_files_planned"]


def test_history_entry_reflects_candidate_and_error_counts():
    repo = FakePersistenceRepository()
    layer2_output = _valid_layer2_output(candidate_count=5)
    layer2_output["run_meta"]["data_quality"]["warning_errors"] = [{"code": "MINOR_SOURCE_TIMEOUT"}]

    main.run(
        repository=repo, date_str="20260720", year_month="202607", run_id="20260720-0900",
        layer2_output=layer2_output, layer_status=LAYER_STATUS,
        started_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc), clock=_fixed_clock(),
    )
    _, entry = repo.saved_history_entries[0]
    assert entry["candidate_count"] == 5
    assert entry["warning_errors_count"] == 1
    assert entry["blocking_errors_count"] == 0
