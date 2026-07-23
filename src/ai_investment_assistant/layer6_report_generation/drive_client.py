"""Layer6がGoogle Drive／Google Sheetsへ書き込むための薄いクライアント
（layer6_report_generation_design.md §6・§7-3・§6-6）。

Markdownレポート（`reports/report_YYYYMMDD.md`）・Google Sheets（複数タブ構成）・
レポート履歴インデックス（`reports/report_index_YYYYMM.json`）の3種類の書き込みを扱う。
Layer5の`decisions/`（AI判断の生JSON置き場）・Layer4の`history/`（パイプライン実行履歴）
とは責務・保存先フォルダを分離する（§6-6）。

低レベルのAPI呼び出しは、他レイヤーのDrive系クライアントと同じ「小さなメソッドに分離し
テストではサブクラス化してフェイクに差し替える」パターンを踏襲する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional


class Layer6DriveClient:
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
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
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

    def _upload_text(
        self, service: Any, parent_id: str, name: str, text: str, mimetype: str = "text/markdown"
    ) -> str:
        import io

        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype=mimetype)
        metadata = {"name": name, "parents": [parent_id]}
        created = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return created["id"]

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

    def _create_spreadsheet(self, sheets_service: Any, title: str, sheet_titles: list) -> str:
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": sheet_title}} for sheet_title in sheet_titles],
        }
        created = sheets_service.spreadsheets().create(body=body, fields="spreadsheetId").execute()
        return created["spreadsheetId"]

    def _write_sheet_values(self, sheets_service: Any, spreadsheet_id: str, sheet_title: str, rows: list) -> None:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_title}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

    def _move_spreadsheet_to_folder(self, drive_service: Any, file_id: str, folder_id: str) -> None:
        drive_service.files().update(
            fileId=file_id, addParents=folder_id, removeParents="root", fields="id, parents"
        ).execute()

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

    # --- 公開API ---------------------------------------------------------------------

    def write_markdown_report(self, file_name: str, text: str) -> str:
        """reports/{file_name} へMarkdownを新規保存する（supersedeなし。§6-2・§7-3：
        同日再実行時も旧ファイルは残し、新ファイルを同名で作成する。最新判定は
        createdTimeで行う既存運用に委ねる）。
        """
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "reports")
        self._upload_text(service, folder_id, file_name, text, mimetype="text/markdown")
        return f"reports/{file_name}"

    def write_proposal_spreadsheet(self, file_name: str, sheets_data: dict) -> str:
        """`sheets_data`（{シート名: [[ヘッダー行], [データ行], ...]}）から複数タブの
        スプレッドシートを作成し、reports/フォルダへ配置する（§6-1・§6-2）。
        """
        drive_service = self._get_drive_service()
        sheets_service = self._get_sheets_service()
        folder_id = self._get_subfolder_id(drive_service, "reports")

        sheet_titles = list(sheets_data.keys())
        spreadsheet_id = self._create_spreadsheet(sheets_service, file_name, sheet_titles)
        for sheet_title, rows in sheets_data.items():
            self._write_sheet_values(sheets_service, spreadsheet_id, sheet_title, rows)
        self._move_spreadsheet_to_folder(drive_service, spreadsheet_id, folder_id)
        return f"reports/{file_name}"

    def read_report_index(self, year_month: str) -> Optional[dict]:
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "reports")
        file_name = f"report_index_{year_month}.json"
        file_id = self._find_file(service, file_name, folder_id)
        if file_id is None:
            return None
        import json as _json

        return _json.loads(self._download_bytes(service, file_id).decode("utf-8"))

    def write_report_index_entry(self, year_month: str, entry: dict) -> str:
        """reports/report_index_YYYYMM.json に`entry`を追記する（§6-6、Layer4の
        history_indexerと同じ「既存ファイルを読み込んで追記」パターン）。
        """
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "reports")
        file_name = f"report_index_{year_month}.json"

        existing_file_id = self._find_file(service, file_name, folder_id)
        index_content = (
            self._download_json_by_id(service, existing_file_id) if existing_file_id else {"entries": []}
        )
        index_content["entries"].append(entry)

        self._upload_json(service, folder_id, file_name, index_content, existing_file_id=existing_file_id)
        return f"reports/{file_name}"

    def _download_json_by_id(self, service: Any, file_id: str) -> dict:
        import json as _json

        return _json.loads(self._download_bytes(service, file_id).decode("utf-8"))
