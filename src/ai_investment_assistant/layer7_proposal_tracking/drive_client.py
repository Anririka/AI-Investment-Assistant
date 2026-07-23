"""Layer7がGoogle Drive／Google Sheetsを読み書きするための薄いクライアント
（layer7_proposal_tracking_design.md §6・§5-1）。

2種類の読み書きを扱う：
- `tracking/`配下のJSONファイル（read-modify-write方式で更新。§6-6の前提により、
  同一実行単位の重複起動は発生しないものとする）
- Layer6が`reports/`フォルダへ保存したGoogle Sheets「本日の提案」シートの**読み取り専用**
  参照（§5-1・§5-2：Layer6成果物は一切書き換えない）

`tracking/layer7_completed_YYYYMMDD.json`のみ、Layer4・Layer6の完了フラグ／インデックス
と同様、同日複数回実行時は`createdTime`最大のものを正とする方式を採る（§6-5）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional


class Layer7DriveClient:
    def __init__(
        self,
        oauth_token_json: str,
        root_folder_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not oauth_token_json or not root_folder_id:
            raise ValueError("oauth_token_json and root_folder_id are required")
        self._oauth_token_json = oauth_token_json
        self._root_folder_id = root_folder_id
        self._clock = clock
        self._folder_cache: dict = {}

    # --- lazy import／実API呼び出し ---------------------------------------------------

    def _get_drive_service(self) -> Any:
        from googleapiclient.discovery import build

        from ..common.google_oauth_auth import build_oauth_credentials

        credentials = build_oauth_credentials(
            self._oauth_token_json, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credentials)

    def _get_sheets_service(self) -> Any:
        from googleapiclient.discovery import build

        from ..common.google_oauth_auth import build_oauth_credentials

        credentials = build_oauth_credentials(
            self._oauth_token_json,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        return build("sheets", "v4", credentials=credentials)

    def _find_folder(self, service: Any, name: str, parent_id: str) -> Optional[str]:
        query = (
            f"name = '{name}' and '{parent_id}' in parents and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None

    def _create_folder(self, service: Any, name: str, parent_id: str) -> str:
        metadata = {
            "name": name,
            "parents": [parent_id],
            "mimeType": "application/vnd.google-apps.folder",
        }
        created = service.files().create(body=metadata, fields="id").execute()
        return created["id"]

    def _find_file(self, service: Any, name: str, parent_id: str) -> Optional[str]:
        query = f"name = '{name}' and '{parent_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None

    def _find_latest_file_id(self, service: Any, name: str, parent_id: str) -> Optional[str]:
        """同名ファイルが複数存在する場合、createdTimeが最大のものを返す（§6-5）。"""
        query = f"name = '{name}' and '{parent_id}' in parents and trashed = false"
        results = service.files().list(
            q=query, fields="files(id, name, createdTime)", orderBy="createdTime desc"
        ).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None

    def _download_bytes(self, service: Any, file_id: str) -> bytes:
        import io

        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _upload_json(
        self, service: Any, parent_id: str, name: str, content: dict, existing_file_id: Optional[str] = None
    ) -> str:
        import io
        import json as _json

        from googleapiclient.http import MediaIoBaseUpload

        raw = _json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype="application/json")
        if existing_file_id:
            service.files().update(fileId=existing_file_id, media_body=media).execute()
            return existing_file_id
        metadata = {"name": name, "parents": [parent_id]}
        created = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return created["id"]

    def _read_sheet_values(self, sheets_service: Any, spreadsheet_id: str, sheet_title: str) -> list:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{sheet_title}!A:Z"
        ).execute()
        return result.get("values", [])

    # --- 共通ロジック ---------------------------------------------------------------

    def _get_subfolder_id(self, service: Any, name: str, create_if_missing: bool = True) -> Optional[str]:
        if name in self._folder_cache:
            return self._folder_cache[name]
        folder_id = self._find_folder(service, name, self._root_folder_id)
        if folder_id is None and create_if_missing:
            folder_id = self._create_folder(service, name, self._root_folder_id)
        if folder_id is not None:
            self._folder_cache[name] = folder_id
        return folder_id

    def _download_json_by_id(self, service: Any, file_id: str) -> dict:
        import json as _json

        return _json.loads(self._download_bytes(service, file_id).decode("utf-8"))

    # --- 公開API：tracking/配下（read-modify-write、§6-6） -----------------------------

    def read_tracking_json(self, file_name: str) -> Optional[dict]:
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "tracking", create_if_missing=False)
        if folder_id is None:
            return None
        file_id = self._find_file(service, file_name, folder_id)
        if file_id is None:
            return None
        return self._download_json_by_id(service, file_id)

    def write_tracking_json(self, file_name: str, content: dict) -> str:
        """既存ファイルがあれば更新、無ければ新規作成する（read-modify-write、§6-6）。"""
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "tracking")
        existing_file_id = self._find_file(service, file_name, folder_id)
        self._upload_json(service, folder_id, file_name, content, existing_file_id=existing_file_id)
        return f"tracking/{file_name}"

    # --- 公開API：完了フラグ（同日複数生成を許容し、createdTime最大を正とする、§6-5） -------

    def write_completion_flag(self, file_name: str, content: dict) -> str:
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "tracking")
        self._upload_json(service, folder_id, file_name, content)
        return f"tracking/{file_name}"

    def read_latest_completion_flag(self, file_name: str) -> Optional[dict]:
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "tracking", create_if_missing=False)
        if folder_id is None:
            return None
        file_id = self._find_latest_file_id(service, file_name, folder_id)
        if file_id is None:
            return None
        return self._download_json_by_id(service, file_id)

    # --- 公開API：Layer6成果物の読み取り専用参照（§5-1・§5-2） --------------------------

    def read_proposal_sheet_rows(self, date_str: str, sheet_name: str = "本日の提案") -> Optional[list]:
        """reports/提案ログ_{date_str}（Layer6成果物、同日複数存在時はcreatedTime最大）の
        指定タブを読み取り専用で参照し、{列名: 値}の辞書のリストとして返す。
        見つからない場合はNone（§9：当日の新規取り込みをスキップし次回再試行）。
        """
        drive_service = self._get_drive_service()
        sheets_service = self._get_sheets_service()
        folder_id = self._get_subfolder_id(drive_service, "reports", create_if_missing=False)
        if folder_id is None:
            return None

        file_name = f"提案ログ_{date_str}"
        spreadsheet_id = self._find_latest_file_id(drive_service, file_name, folder_id)
        if spreadsheet_id is None:
            return None

        values = self._read_sheet_values(sheets_service, spreadsheet_id, sheet_name)
        if not values:
            return []
        header, *rows = values
        return [dict(zip(header, row)) for row in rows]
