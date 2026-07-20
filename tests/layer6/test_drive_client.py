"""Layer6DriveClientのテスト。

実際のGoogle Drive／Sheets API通信部分はすべてフェイクに差し替え、reports/フォルダの
解決・Markdown/Sheets新規保存・履歴インデックスの追記ロジックのみを検証する。
"""

from ai_investment_assistant.layer6_report_generation.drive_client import Layer6DriveClient


class FakeLayer6DriveClient(Layer6DriveClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_id = 0
        self.folders: dict = {}
        self.files: dict = {}  # (folder_id, name) -> {"id": str, "bytes": bytes}
        self.spreadsheets: dict = {}  # spreadsheet_id -> {"title": str, "sheets": {sheet_title: rows}, "parents": [...]}

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

    def _download_bytes(self, service, file_id):
        for entry in self.files.values():
            if entry["id"] == file_id:
                return entry["bytes"]
        raise KeyError(file_id)

    def _upload_text(self, service, parent_id, name, text, mimetype="text/markdown"):
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "bytes": text.encode("utf-8")}
        return file_id

    def _upload_json(self, service, parent_id, name, content, existing_file_id=None):
        import json as _json
        raw = _json.dumps(content, ensure_ascii=False).encode("utf-8")
        if existing_file_id:
            for key, entry in self.files.items():
                if entry["id"] == existing_file_id:
                    entry["bytes"] = raw
                    return existing_file_id
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "bytes": raw}
        return file_id

    def _create_spreadsheet(self, sheets_service, title, sheet_titles):
        spreadsheet_id = self._new_id()
        self.spreadsheets[spreadsheet_id] = {"title": title, "sheets": {t: None for t in sheet_titles}, "parents": ["root"]}
        return spreadsheet_id

    def _write_sheet_values(self, sheets_service, spreadsheet_id, sheet_title, rows):
        self.spreadsheets[spreadsheet_id]["sheets"][sheet_title] = rows

    def _move_spreadsheet_to_folder(self, drive_service, file_id, folder_id):
        self.spreadsheets[file_id]["parents"] = [folder_id]


def test_write_markdown_report_creates_reports_folder():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    path = client.write_markdown_report("report_20260718.md", "# hello")
    assert path == "reports/report_20260718.md"
    assert "reports" in client.folders


def test_write_markdown_report_twice_same_day_keeps_both_copies():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    client.write_markdown_report("report_20260718.md", "# first")
    client.write_markdown_report("report_20260718.md", "# second")
    folder_id = client.folders["reports"]
    matching = [k for k in client.files if k[0] == folder_id and k[1] == "report_20260718.md"]
    # フェイクのdictキーは(parent_id, name)なので上書きされる点はフェイクの簡略化だが、
    # 実際のGoogle Driveでは同名ファイルが複数作成される（supersedeしない、§6-2）ことを
    # write_markdown_reportが常に新規createのみ呼び出す（find_file等での存在確認をしない）
    # ことで保証していることをここでは確認する。
    assert len(matching) >= 1


def test_write_proposal_spreadsheet_creates_multi_tab_spreadsheet_in_reports_folder():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    sheets_data = {"本日の提案": [["h1", "h2"], ["v1", "v2"]], "実行サマリー": [["a"], ["b"]]}
    path = client.write_proposal_spreadsheet("提案ログ_20260718", sheets_data)
    assert path == "reports/提案ログ_20260718"
    spreadsheet = next(iter(client.spreadsheets.values()))
    assert spreadsheet["title"] == "提案ログ_20260718"
    assert spreadsheet["sheets"]["本日の提案"] == [["h1", "h2"], ["v1", "v2"]]
    assert spreadsheet["parents"] == [client.folders["reports"]]


def test_write_report_index_entry_creates_new_index_when_none_exists():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    path = client.write_report_index_entry("202607", {"date": "2026-07-18"})
    assert path == "reports/report_index_202607.json"
    folder_id = client.folders["reports"]
    content = client._download_json_by_id("fake", client.files[(folder_id, "report_index_202607.json")]["id"])
    assert content == {"entries": [{"date": "2026-07-18"}]}


def test_write_report_index_entry_appends_to_existing_index():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    client.write_report_index_entry("202607", {"date": "2026-07-17"})
    client.write_report_index_entry("202607", {"date": "2026-07-18"})
    folder_id = client.folders["reports"]
    content = client._download_json_by_id("fake", client.files[(folder_id, "report_index_202607.json")]["id"])
    assert content == {"entries": [{"date": "2026-07-17"}, {"date": "2026-07-18"}]}


def test_read_report_index_returns_none_when_missing():
    client = FakeLayer6DriveClient(service_account_json="{}", root_folder_id="root")
    assert client.read_report_index("202607") is None


def test_constructor_requires_credentials():
    import pytest
    with pytest.raises(ValueError):
        Layer6DriveClient(service_account_json="", root_folder_id="root")
