"""GoogleDriveRepository（layer4_persistence_design.md §2・§7・§11、現行の唯一の具体実装）。

同名ファイルが既に存在する場合はsupersededにリネームしてから新規保存する
（§7-1、market_snapshot／layer4_completed／execution_logに適用）。history/indexだけは
「削除せず蓄積」する性質上、既存内容を読み込んでエントリを追記する更新方式を取る（§7-2）。

Google Drive APIとの実際の通信部分（_get_drive_service以下の各メソッド）は、テストで
容易にモック・サブクラス化できるよう小さなメソッドに分離している
（layer1_data_acquisition.caching.GoogleDriveCacheStoreと同じパターン）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .base import PersistenceRepository


class GoogleDriveRepository(PersistenceRepository):
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

    # --- Google Drive API呼び出し（実際の通信、lazy import） -----------------------

    def _get_drive_service(self) -> Any:
        from googleapiclient.discovery import build

        from ...common.google_oauth_auth import build_oauth_credentials

        credentials = build_oauth_credentials(
            self._oauth_token_json, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credentials)

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

    def _download_json(self, service: Any, file_id: str) -> dict:
        import io
        import json as _json

        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return _json.loads(buffer.getvalue().decode("utf-8"))

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

    def _rename_file(self, service: Any, file_id: str, new_name: str) -> None:
        service.files().update(fileId=file_id, body={"name": new_name}).execute()

    # --- 共通ロジック ---------------------------------------------------------------

    def _get_subfolder_id(self, service: Any, name: str) -> str:
        if name in self._folder_cache:
            return self._folder_cache[name]
        folder_id = self._find_folder(service, name, self._root_folder_id)
        if folder_id is None:
            folder_id = self._create_folder(service, name, self._root_folder_id)
        self._folder_cache[name] = folder_id
        return folder_id

    def _save_with_supersede(self, subfolder: str, file_name: str, content: dict) -> str:
        """同名ファイルが存在すればsupersededへリネームしてから新規保存する（§7-1）。"""
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, subfolder)

        existing_file_id = self._find_file(service, file_name, folder_id)
        if existing_file_id is not None:
            timestamp = self._clock().strftime("%H%M%S")
            stem, _, ext = file_name.rpartition(".")
            superseded_name = f"{stem}_supersededT{timestamp}Z.{ext}"
            self._rename_file(service, existing_file_id, superseded_name)

        self._upload_json(service, folder_id, file_name, content)
        return f"{subfolder}/{file_name}"

    # --- PersistenceRepository実装 ---------------------------------------------------

    def save_snapshot(self, date_str: str, content: dict) -> str:
        return self._save_with_supersede("snapshots", f"market_snapshot_{date_str}.json", content)

    def save_completion_flag(self, date_str: str, content: dict) -> str:
        return self._save_with_supersede("snapshots", f"layer4_completed_{date_str}.json", content)

    def save_execution_log(self, date_str: str, content: dict) -> str:
        return self._save_with_supersede("logs", f"execution_log_{date_str}.json", content)

    def save_history_index(self, year_month: str, entry: dict) -> str:
        """history/index_{year_month}.jsonに`entry`を追記する（supersede方式ではなく更新方式、§7-2）。"""
        service = self._get_drive_service()
        folder_id = self._get_subfolder_id(service, "history")
        file_name = f"index_{year_month}.json"

        existing_file_id = self._find_file(service, file_name, folder_id)
        index_content = self._download_json(service, existing_file_id) if existing_file_id else {"entries": []}
        index_content["entries"].append(entry)

        self._upload_json(service, folder_id, file_name, index_content, existing_file_id=existing_file_id)
        return f"history/{file_name}"
