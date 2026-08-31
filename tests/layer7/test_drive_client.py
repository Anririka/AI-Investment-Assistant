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

    def add_spreadsheet(self, folder_id, name, rows, created_order=None):
        """2026-07-26変更：1ファイル1シート構成になったため、`rows`は
        [[ヘッダー], [データ行], ...] を直接渡す（タブ名をキーにした辞書ではない）。
        """
        self._created_counter += 1
        order = created_order if created_order is not None else self._created_counter
        file_id = self._new_id()
        self.files[(folder_id, name)] = {"id": file_id, "bytes": b"", "created_order": order}
        self.spreadsheet_values[file_id] = rows
        return file_id

    def _read_sheet_values(self, sheets_service, spreadsheet_id, sheet_title=None):
        return self.spreadsheet_values.get(spreadsheet_id, [])


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
    client.add_spreadsheet(
        "reports-id", "提案ログ_20260718_本日の提案",
        [["run_id", "証券コード"], ["20260718-0630", "NVDA"]],
    )
    rows = client.read_proposal_sheet_rows("20260718")
    assert rows == [{"run_id": "20260718-0630", "証券コード": "NVDA"}]


def test_read_proposal_sheet_rows_uses_the_latest_write_when_rerun_same_day():
    # Google Drive上では同名ファイルが複数存在しうる（Layer6§6-2）が、このフェイクの
    # 簡易実装ではdictキーが(folder_id, name)であるため物理的な重複までは表現できない。
    # ここでは「再実行で内容が更新されたら、読み取りは常に最新の内容を返す」という
    # createdTime最大判定の実質的な振る舞いのみを検証する。
    client = FakeLayer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    client.folders["reports"] = "reports-id"
    client.add_spreadsheet("reports-id", "提案ログ_20260718_本日の提案", [["run_id"], ["old"]], created_order=1)
    client.add_spreadsheet("reports-id", "提案ログ_20260718_本日の提案", [["run_id"], ["new"]], created_order=2)
    rows = client.read_proposal_sheet_rows("20260718")
    assert rows == [{"run_id": "new"}]


class _RangeCapturingSheetsService:
    """`_read_sheet_values`が実際にSheets APIへ渡すrange文字列を検証するための
    最小限のフェイク（FakeLayer7DriveClientは`_read_sheet_values`自体を上書きして
    しまうため、このクラス単体では実装のrange構築ロジックを検証できない）。
    """

    def __init__(self):
        self.captured_range = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):  # noqa: A002
        self.captured_range = range
        return self

    def execute(self):
        return {"values": []}


def test_read_sheet_values_requests_a_wide_column_range():
    """2026-07-26追加、回帰テスト：以前は列範囲が`A:Z`（26列まで）に固定されており、
    Layer6「本日の提案」シートの29列全ては取得できず、27〜29列目
    （レジーム適合スコア／総合スコア／代替候補）がAPIレスポンスから欠落し、
    Layer8側でNoneとして記録される不具合が実データで発生した（drive_client.pyの
    `_read_sheet_values`docstring参照）。26列を超える範囲まで要求することを確認する。
    """
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    service = _RangeCapturingSheetsService()
    client._read_sheet_values(service, "sheet-id")
    assert service.captured_range == "A:ZZ"


def test_constructor_requires_credentials():
    import pytest
    with pytest.raises(ValueError):
        Layer7DriveClient(oauth_token_json="", root_folder_id="root")


# --- _execute_with_retry（2026-08-31追加、実運用障害対応） --------------------------
#
# 2026-08-31、GitHub Actions本番実行でGoogle Sheets APIのvalues.getが
# `HttpError 500 "Internal error encountered."`で失敗し、Layer7が本日分の位置追跡・
# 損切/利確判定を一切実行できないまま失敗する事故が発生した。5xx系（Googleサーバー側の
# 一時的な障害）はリトライし、4xx系（リトライしても解決しないエラー）は即座に
# 再送出することを検証する。


def _http_error(status: int, message: bytes = b'{"error": {"message": "boom"}}'):
    from googleapiclient.errors import HttpError
    import httplib2

    return HttpError(httplib2.Response({"status": status}), message)


class _FlakyRequest:
    """`.execute()`を呼ぶたびに`side_effects`の先頭を1つずつ消費するフェイク。
    値が例外インスタンスならそれをraiseし、それ以外はそのまま返す。
    """

    def __init__(self, side_effects: list):
        self._side_effects = list(side_effects)
        self.call_count = 0

    def execute(self):
        self.call_count += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def test_execute_with_retry_succeeds_immediately_when_no_error():
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root")
    request = _FlakyRequest(["ok"])
    assert client._execute_with_retry(request) == "ok"
    assert request.call_count == 1


def test_execute_with_retry_retries_on_5xx_then_succeeds():
    sleeps = []
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root", sleep=sleeps.append)
    request = _FlakyRequest([_http_error(500), _http_error(503), "ok"])
    assert client._execute_with_retry(request) == "ok"
    assert request.call_count == 3
    assert sleeps == [1.0, 2.0]  # 指数バックオフ（1秒→2秒）


def test_execute_with_retry_raises_immediately_on_4xx_without_sleeping():
    sleeps = []
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root", sleep=sleeps.append)
    request = _FlakyRequest([_http_error(403)])
    import pytest
    from googleapiclient.errors import HttpError
    with pytest.raises(HttpError):
        client._execute_with_retry(request)
    assert request.call_count == 1
    assert sleeps == []


def test_execute_with_retry_gives_up_after_max_attempts_and_raises_last_error():
    sleeps = []
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root", sleep=sleeps.append)
    request = _FlakyRequest([_http_error(500), _http_error(500), _http_error(500)])
    import pytest
    from googleapiclient.errors import HttpError
    with pytest.raises(HttpError):
        client._execute_with_retry(request)
    assert request.call_count == 3  # 既定のmax_attempts=3回で打ち切り
    assert sleeps == [1.0, 2.0]  # 3回目失敗後はもうスリープせず即座に再送出


def test_execute_with_retry_does_not_retry_non_http_errors():
    # HttpError以外（ネットワーク断など想定外の例外）は本対応のスコープ外のため
    # そのまま即座に伝播することを確認する（誤って無限にリトライしないこと）。
    sleeps = []
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root", sleep=sleeps.append)
    request = _FlakyRequest([ConnectionError("boom")])
    import pytest
    with pytest.raises(ConnectionError):
        client._execute_with_retry(request)
    assert request.call_count == 1
    assert sleeps == []


class _FlakySheetsService:
    """`_read_sheet_values`が実際に`_execute_with_retry`経由で`.execute()`を
    呼んでいることを、実際のGoogleAPIリクエストチェーン形状（`spreadsheets().values()
    .get(...)`）を模したフェイクで検証する。
    """

    def __init__(self, side_effects: list):
        self._request = _FlakyRequest(side_effects)

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):  # noqa: A002
        return self._request


def test_read_sheet_values_recovers_from_transient_5xx_error():
    # 2026-08-31の実障害の直接的な回帰テスト：Google Sheets側の一時的な500エラーが
    # 1回発生しても、_read_sheet_values全体としては正常に値を返せることを確認する。
    client = Layer7DriveClient(oauth_token_json="{}", root_folder_id="root", sleep=lambda _s: None)
    service = _FlakySheetsService([_http_error(500), {"values": [["run_id"], ["20260831-0630"]]}])
    result = client._read_sheet_values(service, "sheet-id")
    assert result == [["run_id"], ["20260831-0630"]]
