"""load_snapshot.pyのテスト（layer5_ai_judgment_design.md §3-1・§5、§12テスト方針）。"""

import json
import sys
from datetime import datetime, timedelta, timezone

import ai_investment_assistant.layer5_ai_judgment.scripts.load_snapshot as load_snapshot_module
from ai_investment_assistant.layer5_ai_judgment.scripts.load_snapshot import (
    check_pipeline_completion,
    classify_data_quality,
    evaluate_snapshot,
    main,
    run_load_snapshot,
)


class _FixedDatetime(datetime):
    """datetime.now()のみ固定値を返すフェイク（他のdatetime機能はそのまま使える）。"""

    _fixed_utc = datetime(2026, 7, 23, 20, 0, 0, tzinfo=timezone.utc)  # JSTでは翌日05:00

    @classmethod
    def now(cls, tz=None):
        return cls._fixed_utc.astimezone(tz) if tz else cls._fixed_utc

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


def test_main_default_date_str_uses_jst_not_utc(monkeypatch, tmp_path, capsys):
    """2026-07-24追加の回帰テスト：Layer4（scripts/run_daily_pipeline.py）はファイル名を
    JST基準の日付で生成するが、本スクリプトは日付引数省略時にUTC基準の日付をデフォルトに
    していたため、UTC 15:00〜23:59（JST側は既に翌日）の時間帯に実行すると、Layer4が
    実際に書き込んだ「今日」のファイルではなく別の日のファイル名を探しに行ってしまう
    不整合があった（2026-07-24のライブ実行で発覚）。UTC 20:00（=JST翌日05:00）を模擬し、
    探しに行く先が UTC日付"20260723" ではなく JST日付"20260724" であることを確認する。
    """
    monkeypatch.setattr(sys, "argv", ["load_snapshot.py"])  # 日付引数を省略
    monkeypatch.setattr(load_snapshot_module, "datetime", _FixedDatetime)
    monkeypatch.setenv("LAYER5_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAYER5_RUN_STARTED_AT", raising=False)

    # JST日付"20260724"のsnapshotだけを配置し、UTC日付"20260723"を探しに行っていたら
    # 見つからずSNAPSHOT_MISSINGになってしまうことでバグを検出する。
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    (snapshots_dir / "layer4_completed_20260724.json").write_text(
        json.dumps({"completed": True}), encoding="utf-8"
    )
    (snapshots_dir / "market_snapshot_20260724.json").write_text(
        json.dumps({"candidates": []}), encoding="utf-8"
    )

    exit_code = main()

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    # JST日付"20260724"のファイルを正しく見つけられていれば"passed"になる。UTC日付
    # "20260723"を（バグ再発時のように）探しに行った場合はflag自体が見つからず
    # "waiting"（elapsed=0のため、まだblockedにはならない）になるため、両者を明確に
    # 区別できる。
    assert result["status"] == "passed"
