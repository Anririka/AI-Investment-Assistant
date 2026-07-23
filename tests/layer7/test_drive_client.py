"""Layer7DriveClientのテスト。

実際のGoogle Drive／Sheets API通信部分はすべてフェイクに差し替え、tracking/配下の
read-modify-write・完了フラグのcreatedTime最大判定・Layer6 Sheetsの読み取り専用参照
ロジックのみを検証する。
"""

from ai_investment_assistant.layer7_proposal_tracking.drive_client import Layer7DriveClient


class FakeLayer7DriveClient(Layer7DriveClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_id = 0
        self.folders: dict = {}
        self.files: dict = {}  # (folder_id, name) -> {"id": str, "bytes": bytes, "created_order": int}
        self.spreadsheet_values: dict = {}  # spreadsheet_id -> {sheet_title: [[...]]}
        self._created_counter = 0

    def _new_id(self) -> str:
        self._next_id += 1
        return f"id-{self._next_id}"

    def _get_drive_service(self):
        return "fake-drive-service"

    def _get_sheets_service(self):
        return "fake-sheets-service"

    def _find_folder(self, service, name, parent_id):
        return self.folders.get(name)

    def _create_folder(self, service, name, parent_id):
        folder_id = self._new_id()
        self.folders[name] = folder_id
        return folder_id

    def _find_file(self, service, name, parent_id):
        entry = self.files.get((parent_id, name))
        return entry["id"] if entry else None

    def _find_latest_file_id(self, service, name, parent_id):
        matching = [(k, v) for k, v in self.files.items() if k[0] == parent_id and k[1] == name]
        if not matching:
            return None
        matching.sort(key=lambda kv: kv[1]["created_order"], reverse=True)
        return matching[0][1]["id"]

    def _download_bytes(self, service, file_id):
        for entry in self.files.values():
            if entry["id"] == file_id:
                return entry["bytes"]
        raise KeyError(file_id)

    def _upload_json(self, service, parent_id, name, content, existing_file_id=None):
        import json as _json
        raw = _json.dumps(content, ensure_ascii=False).encode("utf-8")
        if existing_file_id:
            for entry in self.files.values():
                if entry["id"] == existing_file_id:
                    entry["bytes"] = raw
                    return existing_file_id
        self._created_counter += 1
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "bytes": raw, "created_order": self._created_counter}
        return file_id

    def add_spreadsheet(self, folder_id, name, sheet_values, created_order=None):
        self._created_counter += 1
        order = created_order if created_order is not None else self._created_counter
        file_id = self._new_id()
        self.files[(folder_id, name)] = {"id": file_id, "bytes": b"", "created_order": order}
        self.spreadsheet_values[file_id] = sheet_values
        return file_id

    def _read_sheet_values(self, sheets_service, spreadsheet_id, sheet_title):
        return self.spreadsheet_values.get(spreadsheet_id, {}).get(sheet_title, [])


def test_read_tracking_json_returns_none_when_missing():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_tracking_json("active_positions.json") is None


def test_write_tracking_json_creates_then_reads_back():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.write_tracking_json("active_positions.json", {"positions": [{"tracking_id": "TRK-1"}]})
    content = client.read_tracking_json("active_positions.json")
    assert content == {"positions": [{"tracking_id": "TRK-1"}]}


def test_write_tracking_json_updates_existing_file_in_place():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.write_tracking_json("active_positions.json", {"positions": []})
    folder_id = client.folders["tracking"]
    file_count_before = len([k for k in client.files if k[0] == folder_id and k[1] == "active_positions.json"])
    client.write_tracking_json("active_positions.json", {"positions": [{"tracking_id": "TRK-1"}]})
    file_count_after = len([k for k in client.files if k[0] == folder_id and k[1] == "active_positions.json"])
    assert file_count_before == file_count_after == 1  # 上書き（read-modify-write）で新規ファイルは増えない
    assert client.read_tracking_json("active_positions.json") == {"positions": [{"tracking_id": "TRK-1"}]}


def test_write_completion_flag_creates_new_file_each_time():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.write_completion_flag("layer7_completed_20260718.json", {"completed": False, "n": 1})
    client.write_completion_flag("layer7_completed_20260718.json", {"completed": True, "n": 2})
    latest = client.read_latest_completion_flag("layer7_completed_20260718.json")
    assert latest == {"completed": True, "n": 2}


def test_read_latest_completion_flag_returns_none_when_missing():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_latest_completion_flag("layer7_completed_20260718.json") is None


def test_read_proposal_sheet_rows_returns_none_when_reports_folder_missing():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_proposal_sheet_rows("20260718") is None


def test_read_proposal_sheet_rows_parses_header_and_rows():
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["reports"] = "reports-id"
    client.add_spreadsheet("reports-id", "提案ログ_20260718", {
        "本日の提案": [["run_id", "証券コード"], ["20260718-0630", "NVDA"]],
    })
    rows = client.read_proposal_sheet_rows("20260718")
    assert rows == [{"run_id": "20260718-0630", "証券コード": "NVDA"}]


def test_read_proposal_sheet_rows_uses_the_latest_write_when_rerun_same_day():
    # Google Drive上では同名ファイルが複数存在しうる（Layer6§6-2）が、このフェイクの
    # 簡易実装ではdictキーが(folder_id, name)であるため物理的な重複までは表現できない。
    # ここでは「再実行で内容が更新されたら、読み取りは常に最新の内容を返す」という
    # createdTime最大判定の実質的な振る舞いのみを検証する。
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["reports"] = "reports-id"
    client.add_spreadsheet("reports-id", "提案ログ_20260718", {"本日の提案": [["run_id"], ["old"]]}, created_order=1)
    client.add_spreadsheet("reports-id", "提案ログ_20260718", {"本日の提案": [["run_id"], ["new"]]}, created_order=2)
    rows = client.read_proposal_sheet_rows("20260718")
    assert rows == [{"run_id": "new"}]


def test_constructor_requires_credentials():
    import pytest
    with pytest.raises(ValueError):
        Layer7DriveClient(oauth_token_json="", root_folder_id="root")
