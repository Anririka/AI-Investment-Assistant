"""LocalDriveClientのテスト（Google Drive MCPコネクタ方式への移行、§ローカルI/Oアダプタ）。

Layer5DriveClientと同じ公開インターフェースを、実際のファイルシステム（pytestの
tmp_pathフィクスチャ）に対して検証する。
"""

import json

from ai_investment_assistant.layer5_ai_judgment.scripts.local_drive_client import LocalDriveClient


def test_read_json_returns_none_when_file_missing(tmp_path):
    client = LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_json("snapshots", "market_snapshot_20260718.json") is None


def test_read_json_returns_parsed_content(tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    (snapshots_dir / "market_snapshot_20260718.json").write_text(
        json.dumps({"a": 1}), encoding="utf-8"
    )
    client = LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_json("snapshots", "market_snapshot_20260718.json") == {"a": 1}


def test_read_json_with_no_subfolder_uses_base_dir_root(tmp_path):
    (tmp_path / "layer4_completed_20260718.json").write_text(
        json.dumps({"completed": True}), encoding="utf-8"
    )
    client = LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_json(None, "layer4_completed_20260718.json") == {"completed": True}


def test_read_latest_text_by_prefix_picks_lexicographically_max_name(tmp_path):
    (tmp_path / "取引記録_20260701T000000Z.csv").write_text("old", encoding="utf-8")
    (tmp_path / "取引記録_20260717T014126Z.csv").write_text("new", encoding="utf-8")
    client = LocalDriveClient(base_dir=str(tmp_path))
    result = client.read_latest_text_by_prefix(None, "取引記録_")
    assert result == ("取引記録_20260717T014126Z.csv", "new")


def test_read_latest_text_by_prefix_returns_none_when_no_match(tmp_path):
    client = LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_latest_text_by_prefix(None, "取引記録_") is None


def test_read_latest_text_by_prefix_returns_none_when_directory_missing(tmp_path):
    client = LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_latest_text_by_prefix("nonexistent", "取引記録_") is None


def test_write_decision_creates_decisions_dir_and_file(tmp_path):
    client = LocalDriveClient(base_dir=str(tmp_path))
    path = client.write_decision("decision_20260718T063440Z.json", {"run_meta": {}})
    assert path == str(tmp_path / "decisions" / "decision_20260718T063440Z.json")
    saved = json.loads((tmp_path / "decisions" / "decision_20260718T063440Z.json").read_text(encoding="utf-8"))
    assert saved == {"run_meta": {}}


def test_write_decision_twice_same_day_keeps_both_files(tmp_path):
    client = LocalDriveClient(base_dir=str(tmp_path))
    client.write_decision("decision_20260718T063440Z.json", {"run": 1})
    client.write_decision("decision_20260718T091500Z.json", {"run": 2})
    decisions_dir = tmp_path / "decisions"
    assert (decisions_dir / "decision_20260718T063440Z.json").exists()
    assert (decisions_dir / "decision_20260718T091500Z.json").exists()
