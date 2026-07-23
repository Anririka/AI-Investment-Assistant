"""Layer8DriveClientのテスト。

実際のGoogle Drive／Sheets API通信部分はすべてフェイクに差し替え、tracking/・reports/
（Layer6・Layer7成果物の読み取り専用参照）とevaluation/（read-modify-write）の
ロジックのみを検証する。
"""

from ai_investment_assistant.layer8_self_evaluation.drive_client import Layer8DriveClient


class FakeLayer8DriveClient(Layer8DriveClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_id = 0
        self.folders: dict = {}
        self.files: dict = {}
        self.spreadsheet_values: dict = {}
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
        entry = self.files.get((parent_id, name))
        return entry["id"] if entry else None

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
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "bytes": raw}
        return file_id

    def add_json_file(self, folder_id, name, content):
        import json as _json
        file_id = self._new_id()
        self.files[(folder_id, name)] = {"id": file_id, "bytes": _json.dumps(content, ensure_ascii=False).encode("utf-8")}
        return file_id

    def add_spreadsheet(self, folder_id, name, sheet_values):
        file_id = self._new_id()
        self.files[(folder_id, name)] = {"id": file_id, "bytes": b""}
        self.spreadsheet_values[file_id] = sheet_values
        return file_id

    def _read_sheet_values(self, sheets_service, spreadsheet_id, sheet_title):
        return self.spreadsheet_values.get(spreadsheet_id, {}).get(sheet_title, [])


def test_read_closed_positions_returns_none_when_missing():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_closed_positions("202607") is None


def test_read_closed_positions_returns_parsed_content():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["tracking"] = "tracking-id"
    client.add_json_file("tracking-id", "closed_positions_202607.json", {"positions": [{"tracking_id": "TRK-1"}]})
    result = client.read_closed_positions("202607")
    assert result == {"positions": [{"tracking_id": "TRK-1"}]}


def test_read_latest_layer7_completed_flag_returns_none_when_missing():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_latest_layer7_completed_flag("20260718") is None


def test_read_latest_layer7_completed_flag_returns_content():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["tracking"] = "tracking-id"
    client.add_json_file("tracking-id", "layer7_completed_20260718.json", {"completed": True})
    assert client.read_latest_layer7_completed_flag("20260718") == {"completed": True}


def test_read_proposal_sheet_rows_parses_header_and_rows():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["reports"] = "reports-id"
    client.add_spreadsheet("reports-id", "提案ログ_20260718", {
        "本日の提案": [["run_id", "証券コード"], ["20260718-0630", "NVDA"]],
    })
    rows = client.read_proposal_sheet_rows("20260718")
    assert rows == [{"run_id": "20260718-0630", "証券コード": "NVDA"}]


def test_read_proposal_sheet_rows_returns_none_when_reports_folder_missing():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    assert client.read_proposal_sheet_rows("20260718") is None


def test_write_evaluation_json_creates_then_reads_back():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.write_evaluation_json("evaluation_index.json", {"evaluated_tracking_ids": ["TRK-1"]})
    assert client.read_evaluation_json("evaluation_index.json") == {"evaluated_tracking_ids": ["TRK-1"]}


def test_write_evaluation_json_updates_existing_in_place():
    client = FakeLayer8DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.write_evaluation_json("evaluation_index.json", {"evaluated_tracking_ids": ["TRK-1"]})
    client.write_evaluation_json("evaluation_index.json", {"evaluated_tracking_ids": ["TRK-1", "TRK-2"]})
    folder_id = client.folders["evaluation"]
    matching = [k for k in client.files if k[0] == folder_id and k[1] == "evaluation_index.json"]
    assert len(matching) == 1


def test_constructor_requires_credentials():
    import pytest
    with pytest.raises(ValueError):
        Layer8DriveClient(oauth_token_json="", root_folder_id="root")
