"""Google Drive「AI投資アシスタント」フォルダ全体を月次でZip化し、GitHub Releasesの
アセットとしてアップロードするためのバックアップスクリプト（項目7「残作業一覧」対応）。

設計方針：
  - 本スクリプトはGoogle Drive側の処理（フォルダを再帰的に走査し、全ファイルをダウンロード
    してZipにまとめる）のみを担当する。GitHub Releasesの作成・アセットアップロードは
    `gh` CLI（GitHub Actionsランナーにプリインストール済み）にワークフロー側で任せる
    （.github/workflows/monthly_backup.yml参照）。GitHub API呼び出しをPython側で
    再実装せず、既存の枯れたCLIツールに委譲する方が壊れにくいという判断による。
  - 差分バックアップではなく、実行時点のGoogle Driveフォルダの完全なスナップショットを
    毎回作成する（月ごとの増分計算はしない。過去分は同じ月に複数回実行しても、別タグの
    Releaseとして重複保存されるだけで、既存のバックアップを壊すことはない）。
  - Google Docs／Sheets／Slides等のGoogle純正フォーマットのファイルは、`files().get_media()`
    では中身をダウンロードできない（エクスポートが必要な仕様）。`export()`で相当する
    Office形式（xlsx/docx/pptx）に変換してZipへ含める。これにより、例えば
    「提案ログ_YYYYMMDD_本日の提案」（CSV→Sheets自動変換済みのネイティブSheetsファイル、
    layer6_report_generation設計のとおり）も、全シート・全内容を保った状態でバックアップ
    できる（Sheetsのexportをcsvにすると先頭タブしか取得できないため、xlsxを選んでいる）。
  - JSON／CSV／Markdown等、既にバイナリ実体を持つファイル（Layer1〜8がGoogle Driveへ
    保存する大半のファイル）はそのまま`get_media()`でダウンロードする。

テスト方針：`_get_drive_service`以下の小さなメソッドをフェイクに差し替える既存パターン
（layer4_persistence/repository/google_drive_repository.pyのテストと同じ方式）を踏襲する。
"""

from __future__ import annotations

import logging
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_monthly_backup")

# Google純正フォーマット → エクスポート時に使うOffice互換MIMEタイプと拡張子。
# フォームやサイト等、対応表に無いGoogle純正タイプは対象外としてスキップする（ログに記録）。
GOOGLE_NATIVE_EXPORT_MAP = {
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx",
    ),
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx",
    ),
}
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveBackupCollector:
    """Google Driveフォルダを再帰的に走査し、全ファイルをローカルZipへ書き出す。"""

    def __init__(self, oauth_token_json: str) -> None:
        if not oauth_token_json:
            raise ValueError("oauth_token_json is required")
        self._oauth_token_json = oauth_token_json

    # --- Google Drive API呼び出し（実際の通信、テストではフェイクに差し替える） -----------

    def _get_drive_service(self) -> Any:
        from googleapiclient.discovery import build

        from ai_investment_assistant.common.google_oauth_auth import build_oauth_credentials

        # 2026-07-28追加（実データ初回検証で発覚した回帰）：drive.readonlyスコープを
        # 指定していたところ、既存のGOOGLE_OAUTH_TOKEN_JSON（scripts/generate_google_oauth_token.py
        # で発行済みのリフレッシュトークン）が同意した範囲に含まれておらず、
        # `invalid_scope: Bad Request`でトークンのリフレッシュ自体が失敗した。OAuthの
        # リフレッシュトークンは、最初の同意画面で許可されたスコープの範囲内でしか
        # アクセストークンを再発行できない仕様のため、意味的に「読み取り専用でより狭い」
        # スコープであっても、元の同意に無い文字列を新たに要求すると失敗する。
        # Layer1（caching.py）・Layer4（google_drive_repository.py）と同じ
        # "https://www.googleapis.com/auth/drive"（フルスコープ、既に同意済み）に統一する。
        credentials = build_oauth_credentials(
            self._oauth_token_json,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        return build("drive", "v3", credentials=credentials)

    def _list_children(self, service: Any, folder_id: str) -> list:
        """`folder_id`直下のファイル・フォルダ一覧を返す（trashed除外、ページング対応）。

        戻り値の各要素: {"id": str, "name": str, "mimeType": str}
        """
        children: list = []
        page_token: Optional[str] = None
        while True:
            response = (
                service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                .execute()
            )
            children.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return children

    def _download_file_bytes(self, service: Any, file_id: str) -> bytes:
        """Google純正でない通常ファイル（JSON/CSV/Markdown等）の中身をそのままダウンロードする。"""
        import io

        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _export_file_bytes(self, service: Any, file_id: str, export_mime_type: str) -> bytes:
        """Google純正フォーマット（Sheets/Docs/Slides）をOffice互換形式へ変換して取得する。"""
        import io

        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    # --- 再帰走査・Zip組み立て ---------------------------------------------------------

    def collect_files(self, service: Any, folder_id: str, path_prefix: str = ""):
        """`folder_id`配下を再帰的に走査し、(zip内相対パス, ファイル内容bytes)を順に返す。"""
        for child in self._list_children(service, folder_id):
            name = child["name"]
            mime_type = child["mimeType"]
            rel_path = f"{path_prefix}{name}" if not path_prefix else f"{path_prefix}/{name}"

            if mime_type == GOOGLE_FOLDER_MIME_TYPE:
                yield from self.collect_files(service, child["id"], path_prefix=rel_path)
                continue

            if mime_type in GOOGLE_NATIVE_EXPORT_MAP:
                export_mime_type, ext = GOOGLE_NATIVE_EXPORT_MAP[mime_type]
                try:
                    content = self._export_file_bytes(service, child["id"], export_mime_type)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("export failed for %s (%s): %s", rel_path, mime_type, exc)
                    continue
                yield f"{rel_path}{ext}", content
                continue

            if mime_type.startswith("application/vnd.google-apps."):
                # フォーム等、対応表に無いGoogle純正タイプはバックアップ対象外（1件の失敗で
                # 全体を止めない、layer1_data_acquisition_design.md §5と同じ設計方針）。
                logger.warning("skipping unsupported Google-native type %s (%s)", rel_path, mime_type)
                continue

            try:
                content = self._download_file_bytes(service, child["id"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("download failed for %s: %s", rel_path, exc)
                continue
            yield rel_path, content

    def build_zip(self, root_folder_id: str, output_path: Path) -> dict:
        """`root_folder_id`配下の全ファイルをZip化し、`output_path`へ書き出す。

        戻り値: {"file_count": int, "skipped": bool}（呼び出し元のログ用）
        """
        service = self._get_drive_service()
        file_count = 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel_path, content in self.collect_files(service, root_folder_id):
                zf.writestr(rel_path, content)
                file_count += 1
        return {"file_count": file_count}


def main() -> int:
    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not oauth_token_json or not folder_id:
        logger.error(
            "GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_DRIVE_FOLDER_ID not set; cannot back up Google Drive."
        )
        return 1

    now_utc = datetime.now(timezone.utc)
    tag = now_utc.strftime("%Y%m")
    output_path = Path("backup_output") / f"ai_investment_assistant_backup_{tag}.zip"

    collector = DriveBackupCollector(oauth_token_json)
    result = collector.build_zip(folder_id, output_path)

    logger.info(
        "=== monthly backup completed: %s (%d files) ===", output_path, result["file_count"]
    )

    # GitHub Actionsワークフロー側（gh release create）が参照できるよう、
    # zipパス・タグ名をGITHUB_OUTPUTへ書き出す。
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"backup_zip_path={output_path}\n")
            f.write(f"backup_tag=backup-{tag}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
