"""Layer5がGoogle Driveを読み書きするための薄いクライアント
（layer5_ai_judgment_design.md §3-1・§4-2・§3-2）。

Layer4のPersistenceRepository（保存専用、layer4_persistence/repository/base.py §11）とは
意図的に別実装とする。Layer4のRepositoryは「読み込みはLayer5の責務であり、Layer4の
Repositoryに依存させない」という設計（§11）のため読み込みメソッドを一切持たない。
Layer5は逆に、①layer4_completedフラグ・market_snapshotの読み込み、②取引記録CSVの
読み込み（load_portfolio_state.pyはLayer1のRepositoryパターンとも無関係、§4-2）、
③decision JSONの新規保存のみ（supersedeなし、§3-2）という、Layer4とは異なる読み書き
パターンを必要とするため、専用のクライアントとして新設する。

低レベルのGoogle Drive API呼び出し部分は、GoogleDriveRepository（layer4_persistence）と
同じ「小さなメソッドに分離し、テストではサブクラス化してフェイクに差し替える」パターンを
踏襲する（テストの書き方も同一パターンで揃える）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional


class Layer5DriveClient:
    def __init__(
        self,
        service_account_json: str,
        root_folder_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not service_account_json or not root_folder_id:
            raise ValueError("service_account_json and root_folder_id are required")
        self._service_account_json = service_account_json
        self._root_folder_id = root_folder_id
        self._clock = clock
        self._folder_cache: dict = {}

    # --- Google Drive API呼び出し（実際の通信、lazy import） -----------------------

    def _get_drive_service(self) -> Any:
        import json as _json

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = _json.loads(self._service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
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

    def _list_file_names_by_prefix(self, service: Any, prefix: str, parent_id: str) -> list:
        """指定フォルダ内の、名前がprefixで始まるファイル名を降順（辞書順）で列挙する。

        取引記録_*.csv のようにファイル名にタイムスタンプ（YYYYMMDDTHHMMSSZ形式）が
        含まれる場合、辞書順の降順＝日時の降順となるため、先頭が最新スナップショットになる。
        """
        query = f"'{parent_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])
        return sorted((f["name"] for f in files if f["name"].startswith(prefix)), reverse=True)

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

    def _upload_json(self, service: Any, parent_id: str, name: str, content: dict) -> str:
        import io
        import json as _json

        from googleapiclient.http import MediaIoBaseUpload

        raw = _json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype="application/json")
        metadata = {"name": name, "parents": [parent_id]}
        created = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return created["id"]

    # --- 共通ロジック ---------------------------------------------------------------

    def _get_subfolder_id(self, service: Any, name: str, create_if_missing: bool = False) -> Optional[str]:
        if name in self._folder_cache:
            return self._folder_cache[name]
        folder_id = self._find_folder(service, name, self._root_folder_id)
        if folder_id is None and create_if_missing:
            folder_id = self._create_folder(service, name, self._root_folder_id)
        if folder_id is not None:
            self._folder_cache[name] = folder_id
        return folder_id

    def _resolve_parent_id(
        self, service: Any, subfolder: Optional[str], create_if_missing: bool = False
    ) -> Optional[str]:
        if not subfolder:
            return self._root_folder_id
        return self._get_subfolder_id(service, subfolder, create_if_missing=create_if_missing)

    # --- 公開API ---------------------------------------------------------------------

    def read_json(self, subfolder: Optional[str], file_name: str) -> Optional[dict]:
        """指定ファイルが存在すればパースして返す。フォルダ・ファイルが無ければNone。"""
        import json as _json

        service = self._get_drive_service()
        parent_id = self._resolve_parent_id(service, subfolder)
        if parent_id is None:
            return None
        file_id = self._find_file(service, file_name, parent_id)
        if file_id is None:
            return None
        return _json.loads(self._download_bytes(service, file_id).decode("utf-8"))

    def read_latest_text_by_prefix(self, subfolder: Optional[str], name_prefix: str) -> Optional[tuple]:
        """subfolder内でname_prefixから始まる最新（ファイル名のタイムスタンプが最大）の
        ファイルをテキストとしてダウンロードする。(file_name, text) を返す。1件も無ければNone。
        """
        service = self._get_drive_service()
        parent_id = self._resolve_parent_id(service, subfolder)
        if parent_id is None:
            return None
        names = self._list_file_names_by_prefix(service, name_prefix, parent_id)
        if not names:
            return None
        latest_name = names[0]
        file_id = self._find_file(service, latest_name, parent_id)
        if file_id is None:
            return None
        text = self._download_bytes(service, file_id).decode("utf-8-sig")
        return latest_name, text

    def write_decision(self, file_name: str, content: dict) -> str:
        """decisions/{file_name} に新規保存する（supersedeなし。§3-2：秒単位タイムスタンプに
        より同日複数回実行時もファイル名の衝突は構造的に発生しないため、既存ファイルの
        リネーム・上書きは行わない）。
        """
        service = self._get_drive_service()
        folder_id = self._resolve_parent_id(service, "decisions", create_if_missing=True)
        self._upload_json(service, folder_id, file_name, content)
        return f"decisions/{file_name}"
