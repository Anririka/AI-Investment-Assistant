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
        """注意（2026-07-23）：`spreadsheets.readonly`/`drive.readonly`ではなく、
        他クライアントと同じ`spreadsheets`/`drive`（フルスコープ）を使う。OAuth
        ユーザー認証のrefresh_tokenは、scripts/generate_google_oauth_token.pyで
        実際に同意した2スコープ（drive・spreadsheets、いずれもフル）に紐づいており、
        同意していないreadonly系スコープをrefresh時に要求すると
        `invalid_scope: Bad Request`で失敗するため（ライブ実行で確認済み）。
        """
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

    def _read_sheet_values(
        self, sheets_service: Any, spreadsheet_id: str, sheet_title: Optional[str] = None
    ) -> list:
        """`sheet_title`を省略した場合は、スプレッドシート内の先頭（唯一）のシートを
        対象に読む（2026-07-26追記：`読取仕様変更`セクション参照。1ファイル1シート
        構成のファイルではタブ名を指定する必要が無い）。

        2026-07-26追記（実データ初回検証で発覚した重大な不具合）：以前は列範囲を
        `A:Z`（A〜Z列＝26列分）に固定していたが、Layer6「本日の提案」シートは
        `SHEET_COLUMNS`（candidate_formatter.py）で29列（AC列まで）ある。26列を
        超える範囲（27列目`レジーム適合スコア`・28列目`総合スコア`・29列目
        `代替候補`）はAPIレスポンスから静かに欠落し、Layer8側で`score_summary.
        regime_fit`／`composite`が常にNoneになる不具合として発覚した（値が無いのでは
        なく、そもそも取得範囲外だった）。将来の列追加にも耐えられるよう、`ZZ`列
        （702列相当）まで広げた十分な余裕を持たせる。
        """
        range_ = f"{sheet_title}!A:ZZ" if sheet_title else "A:ZZ"
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_
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
        """reports/提案ログ_{date_str}_{sheet_name}（Layer6成果物、同日複数存在時は
        createdTime最大）を読み取り専用で参照し、{列名: 値}の辞書のリストとして返す。
        見つからない場合はNone（§9：当日の新規取り込みをスキップし次回再試行）。

        読取仕様変更（2026-07-26、実地検証を踏まえた修正）：当初はLayer6が「本日の提案」
        を含む4タブを`提案ログ_{date_str}`という1つのファイルにまとめて保存する前提
        だったが、Claude Cowork実行環境（Google Drive MCPコネクタ）でこの1ファイル・
        複数タブ構成が実現できない（xlsx→Google Sheets自動変換アップロード非対応、かつ
        base64経由の大きなバイナリ転記でファイル破損が発生することが実地検証で判明）
        ため、Layer6はタブごとに独立したファイル（`提案ログ_{date_str}_{シート名}`、
        例：`提案ログ_20260726_本日の提案`）として保存する方式に変更した
        （layer6_report_generation/local_drive_client.pyモジュールdocstring参照）。
        これに合わせ、Layer7側の読み込みも「ファイル名にシート名を含めて直接特定し、
        単一シートとして読む」方式へ変更した（タブ名指定は不要になったため
        `_read_sheet_values`の`sheet_title`は省略する）。
        """
        drive_service = self._get_drive_service()
        sheets_service = self._get_sheets_service()
        folder_id = self._get_subfolder_id(drive_service, "reports", create_if_missing=False)
        if folder_id is None:
            return None

        file_name = f"提案ログ_{date_str}_{sheet_name}"
        spreadsheet_id = self._find_latest_file_id(drive_service, file_name, folder_id)
        if spreadsheet_id is None:
            return None

        values = self._read_sheet_values(sheets_service, spreadsheet_id)
        if not values:
            return []
        header, *rows = values
        return [dict(zip(header, row)) for row in rows]
