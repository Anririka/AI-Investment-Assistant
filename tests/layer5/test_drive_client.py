"""Layer5DriveClientのテスト。

実際のGoogle Drive API通信部分はすべてフェイクに差し替え、フォルダ解決・最新ファイル
検索（タイムスタンプ降順）・decision新規保存（supersedeなし）ロジックのみを検証する
（tests/layer4/test_google_drive_repository.pyと同じフェイク差し替えパターン）。
"""

from ai_investment_assistant.layer5_ai_judgment.scripts.drive_client import Layer5DriveClient


class FakeLayer5DriveClient(Layer5DriveClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_id = 0
        self.folders: dict = {}
        self.files: dict = {}  # (folder_id, name) -> {"id": str, "bytes": bytes}

    def _new_id(self) -> str:
        self._next_id += 1
        return f"id-{self._next_id}"

    def _get_drive_service(self):
        return "fake-service"

    def _find_folder(self, service, name, parent_id):
        return self.folders.get(name)

    def _create_folder(self, service, name, parent_id):
        folder_id = self._new_id()
        self.folders[name] = folder_id
        return folder_id

    def _find_file(self, service, name, parent_id):
        entry = self.files.get((parent_id, name))
        return entry["id"] if entry else None

    def _list_file_names_by_prefix(self, service, prefix, parent_id):
        names = [name for (folder_id, name) in self.files if folder_id == parent_id and name.startswith(prefix)]
        return sorted(names, reverse=True)

    def _download_bytes(self, service, file_id):
        for entry in self.files.values():
            if entry["id"] == file_id:
                return entry["bytes"]
        raise KeyError(file_id)

    def _upload_json(self, service, parent_id, name, content):
        import json as _json
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "bytes": _json.dumps(content, ensure_ascii=False).encode("utf-8")}
        return file_id

    def add_file(self, folder_id, name, bytes_content):
        self.files[(folder_id, name)] = {"id": self._new_id(), "bytes": bytes_content}


def test_read_json_returns_none_when_folder_missing():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    assert client.read_json("snapshots", "market_snapshot_20260718.json") is None


def test_read_json_returns_parsed_content():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    client.folders["snapshots"] = "snapshots-id"
    client.add_file("snapshots-id", "market_snapshot_20260718.json", b'{"a": 1}')
    result = client.read_json("snapshots", "market_snapshot_20260718.json")
    assert result == {"a": 1}


def test_read_json_with_no_subfolder_uses_root():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    client.add_file("root", "layer4_completed_20260718.json", b'{"completed": true}')
    result = client.read_json(None, "layer4_completed_20260718.json")
    assert result == {"completed": True}


def test_read_latest_text_by_prefix_picks_lexicographically_max_name():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    client.add_file("root", "取引記録_20260701T000000Z.csv", "old".encode("utf-8"))
    client.add_file("root", "取引記録_20260717T014126Z.csv", "new".encode("utf-8"))
    result = client.read_latest_text_by_prefix(None, "取引記録_")
    assert result == ("取引記録_20260717T014126Z.csv", "new")


def test_read_latest_text_by_prefix_returns_none_when_no_match():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    assert client.read_latest_text_by_prefix(None, "取引記録_") is None


def test_write_decision_creates_decisions_folder_and_file_without_supersede():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    path = client.write_decision("decision_20260718T063440Z.json", {"run_meta": {}})
    assert path == "decisions/decision_20260718T063440Z.json"
    assert "decisions" in client.folders


def test_write_decision_twice_same_day_does_not_overwrite_first():
    client = FakeLayer5DriveClient(service_account_json="{}", root_folder_id="root")
    client.write_decision("decision_20260718T063440Z.json", {"run": 1})
    client.write_decision("decision_20260718T091500Z.json", {"run": 2})
    folder_id = client.folders["decisions"]
    assert (folder_id, "decision_20260718T063440Z.json") in client.files
    assert (folder_id, "decision_20260718T091500Z.json") in client.files


def test_constructor_requires_credentials():
    import pytest
    with pytest.raises(ValueError):
        Layer5DriveClient(service_account_json="", root_folder_id="root")
