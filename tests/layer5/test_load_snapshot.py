"""load_snapshot.pyのテスト（layer5_ai_judgment_design.md §3-1・§5、§12テスト方針）。"""

from datetime import datetime, timedelta, timezone

from ai_investment_assistant.layer5_ai_judgment.scripts.load_snapshot import (
    check_pipeline_completion,
    classify_data_quality,
    evaluate_snapshot,
    run_load_snapshot,
)

POLICY = {
    "blocking_errors": ["SNAPSHOT_MISSING", "PRICE_DATA_INVALID", "LAYER_PIPELINE_NOT_COMPLETED"],
    "warning_errors": ["NEWS_API_FAILURE_PARTIAL", "MINOR_SOURCE_TIMEOUT"],
    "completion_flag_timeout_minutes": 30,
}

NOW = datetime(2026, 7, 18, 6, 40, 0, tzinfo=timezone.utc)
STARTED = datetime(2026, 7, 18, 6, 0, 0, tzinfo=timezone.utc)


def test_completion_flag_present_and_completed_true_is_ready():
    result = check_pipeline_completion({"completed": True}, now=NOW, run_started_at=STARTED, timeout_minutes=30)
    assert result == {"ready": True, "blocked": False, "reason_code": None}


def test_completion_flag_present_but_completed_false_is_blocked_immediately():
    result = check_pipeline_completion({"completed": False}, now=STARTED + timedelta(minutes=5),
                                        run_started_at=STARTED, timeout_minutes=30)
    assert result["blocked"] is True
    assert result["reason_code"] == "LAYER_PIPELINE_NOT_COMPLETED"


def test_completion_flag_missing_within_timeout_is_waiting_not_blocked():
    result = check_pipeline_completion(None, now=STARTED + timedelta(minutes=10),
                                        run_started_at=STARTED, timeout_minutes=30)
    assert result == {"ready": False, "blocked": False, "reason_code": None}


def test_completion_flag_missing_after_timeout_is_blocked():
    result = check_pipeline_completion(None, now=STARTED + timedelta(minutes=31),
                                        run_started_at=STARTED, timeout_minutes=30)
    assert result["blocked"] is True
    assert result["reason_code"] == "LAYER_PIPELINE_NOT_COMPLETED"


def test_classify_data_quality_no_errors_passes():
    detail = classify_data_quality({"critical_errors": [], "warning_errors": []}, POLICY)
    assert detail["gate"] == "passed"


def test_classify_data_quality_blocking_code_blocks():
    dq = {"critical_errors": [{"code": "PRICE_DATA_INVALID", "message": "x", "source_layer": "layer1"}],
          "warning_errors": []}
    detail = classify_data_quality(dq, POLICY)
    assert detail["gate"] == "blocked"
    assert detail["blocking_errors_found"][0]["code"] == "PRICE_DATA_INVALID"


def test_classify_data_quality_warning_only_continues():
    dq = {"critical_errors": [], "warning_errors": [{"code": "MINOR_SOURCE_TIMEOUT", "message": "x", "source_layer": "layer1"}]}
    detail = classify_data_quality(dq, POLICY)
    assert detail["gate"] == "warning_continued"


def test_classify_data_quality_reclassifies_regardless_of_source_array():
    # Layer2がwarning_errors配列に入れていても、Layer5のポリシーでblocking扱いのcodeなら
    # blockedになる（§5-1：Layer2がどちらに入れたかは問わない）。
    dq = {"critical_errors": [], "warning_errors": [{"code": "PRICE_DATA_INVALID", "message": "x", "source_layer": "layer2"}]}
    detail = classify_data_quality(dq, POLICY)
    assert detail["gate"] == "blocked"


def test_classify_data_quality_unknown_code_defaults_to_blocking():
    dq = {"critical_errors": [{"code": "SOME_NEW_UNCLASSIFIED_ERROR", "message": "x", "source_layer": "layer1"}],
          "warning_errors": []}
    detail = classify_data_quality(dq, POLICY)
    assert detail["gate"] == "blocked"


def test_evaluate_snapshot_none_is_snapshot_missing():
    detail = evaluate_snapshot(None, POLICY)
    assert detail["gate"] == "blocked"
    assert detail["blocking_errors_found"][0]["code"] == "SNAPSHOT_MISSING"


class FakeDriveClient:
    def __init__(self, files: dict):
        self.files = files  # {(subfolder, name): content}

    def read_json(self, subfolder, file_name):
        return self.files.get((subfolder, file_name))


def _valid_snapshot():
    return {
        "run_meta": {"data_quality": {"critical_errors": [], "warning_errors": []}},
        "candidates": [],
    }


def test_run_load_snapshot_passed_end_to_end():
    client = FakeDriveClient({
        ("snapshots", "layer4_completed_20260718.json"): {"completed": True},
        ("snapshots", "market_snapshot_20260718.json"): _valid_snapshot(),
    })
    result = run_load_snapshot(client, date_str="20260718", now=NOW, run_started_at=STARTED, policy=POLICY)
    assert result["status"] == "passed"
    assert result["market_snapshot"] is not None


def test_run_load_snapshot_blocked_when_flag_missing_after_timeout():
    client = FakeDriveClient({})
    result = run_load_snapshot(
        client, date_str="20260718",
        now=STARTED + timedelta(minutes=45), run_started_at=STARTED, policy=POLICY,
    )
    assert result["status"] == "blocked"
    assert result["reason_code"] == "LAYER_PIPELINE_NOT_COMPLETED"
    assert result["market_snapshot"] is None


def test_run_load_snapshot_waiting_when_flag_missing_within_timeout():
    client = FakeDriveClient({})
    result = run_load_snapshot(
        client, date_str="20260718",
        now=STARTED + timedelta(minutes=5), run_started_at=STARTED, policy=POLICY,
    )
    assert result["status"] == "waiting"


def test_run_load_snapshot_blocked_when_snapshot_missing_despite_flag():
    client = FakeDriveClient({
        ("snapshots", "layer4_completed_20260718.json"): {"completed": True},
    })
    result = run_load_snapshot(client, date_str="20260718", now=NOW, run_started_at=STARTED, policy=POLICY)
    assert result["status"] == "blocked"
    assert result["reason_code"] == "SNAPSHOT_MISSING"
