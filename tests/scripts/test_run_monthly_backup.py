"""run_monthly_backup.py（項目7、月次バックアップ）のテスト。

実際のGoogle Drive API通信部分はすべてフェイクに差し替え、フォルダ再帰走査・
Google純正フォーマットのエクスポート振り分け・Zip組み立てロジックのみを検証する
（tests/layer4/test_google_drive_repository.pyと同じ方針）。
"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_monthly_backup import DriveBackupCollector  # noqa: E402


class FakeDriveBackupCollector(DriveBackupCollector):
    """Drive API呼び出しをすべてインメモリのフェイクツリーに差し替えたテスト用サブクラス。

    `tree`は {folder_id: [{"id":..., "name":..., "mimeType":...}, ...]} 形式。
    `file_bytes`は {file_id: bytes}（通常ファイル用）、
    `export_bytes`は {(file_id, export_mime_type): bytes}（Google純正フォーマット用）。
    """

    def __init__(self, tree: dict, file_bytes: dict, export_bytes: dict):
        super().__init__(oauth_token_json="{}")
        self.tree = tree
        self.file_bytes = file_bytes
        self.export_bytes = export_bytes
        self.export_calls: list = []

    def _get_drive_service(self):
        return "fake-service"

    def _list_children(self, service, folder_id):
        return self.tree.get(folder_id, [])

    def _download_file_bytes(self, service, file_id):
        return self.file_bytes[file_id]

    def _export_file_bytes(self, service, file_id, export_mime_type):
        self.export_calls.append((file_id, export_mime_type))
        return self.export_bytes[(file_id, export_mime_type)]


def test_collect_files_downloads_regular_files_at_root():
    tree = {
        "root": [
            {"id": "f1", "name": "README.txt", "mimeType": "text/plain"},
        ]
    }
    collector = FakeDriveBackupCollector(tree, {"f1": b"hello"}, {})
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("README.txt", b"hello")]


def test_collect_files_recurses_into_subfolders_with_path_prefix():
    tree = {
        "root": [
            {"id": "folder1", "name": "snapshots", "mimeType": "application/vnd.google-apps.folder"},
        ],
        "folder1": [
            {"id": "f1", "name": "market_snapshot_20260728.json", "mimeType": "application/json"},
        ],
    }
    collector = FakeDriveBackupCollector(tree, {"f1": b"{}"}, {})
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("snapshots/market_snapshot_20260728.json", b"{}")]


def test_collect_files_recurses_multiple_levels():
    tree = {
        "root": [{"id": "a", "name": "a", "mimeType": "application/vnd.google-apps.folder"}],
        "a": [{"id": "b", "name": "b", "mimeType": "application/vnd.google-apps.folder"}],
        "b": [{"id": "f1", "name": "deep.json", "mimeType": "application/json"}],
    }
    collector = FakeDriveBackupCollector(tree, {"f1": b"deep"}, {})
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("a/b/deep.json", b"deep")]


def test_collect_files_exports_native_google_sheet_as_xlsx():
    tree = {
        "root": [
            {
                "id": "sheet1",
                "name": "提案ログ_20260726_本日の提案",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            },
        ]
    }
    xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    collector = FakeDriveBackupCollector(tree, {}, {("sheet1", xlsx_mime): b"XLSXDATA"})
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("提案ログ_20260726_本日の提案.xlsx", b"XLSXDATA")]
    assert collector.export_calls == [("sheet1", xlsx_mime)]


def test_collect_files_exports_native_google_doc_as_docx():
    tree = {
        "root": [
            {"id": "doc1", "name": "report_20260726", "mimeType": "application/vnd.google-apps.document"},
        ]
    }
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    collector = FakeDriveBackupCollector(tree, {}, {("doc1", docx_mime): b"DOCXDATA"})
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("report_20260726.docx", b"DOCXDATA")]


def test_collect_files_skips_unsupported_google_native_type_without_crashing():
    tree = {
        "root": [
            {"id": "form1", "name": "some_form", "mimeType": "application/vnd.google-apps.form"},
            {"id": "f2", "name": "next.json", "mimeType": "application/json"},
        ]
    }
    collector = FakeDriveBackupCollector(tree, {"f2": b"ok"}, {})
    results = list(collector.collect_files("fake-service", "root"))
    # フォーム等はスキップされるが、後続のファイルの走査は継続する（1件の失敗で全体を止めない）
    assert results == [("next.json", b"ok")]


def test_collect_files_skips_single_download_failure_and_continues():
    tree = {
        "root": [
            {"id": "bad", "name": "broken.json", "mimeType": "application/json"},
            {"id": "good", "name": "ok.json", "mimeType": "application/json"},
        ]
    }
    collector = FakeDriveBackupCollector(tree, {"good": b"fine"}, {})  # "bad"のIDをfile_bytesに入れない
    results = list(collector.collect_files("fake-service", "root"))
    assert results == [("ok.json", b"fine")]


def test_build_zip_writes_all_collected_files(tmp_path):
    tree = {
        "root": [
            {"id": "f1", "name": "a.json", "mimeType": "application/json"},
            {"id": "folder1", "name": "sub", "mimeType": "application/vnd.google-apps.folder"},
        ],
        "folder1": [
            {"id": "f2", "name": "b.csv", "mimeType": "text/csv"},
        ],
    }
    collector = FakeDriveBackupCollector(tree, {"f1": b'{"x":1}', "f2": b"a,b\n1,2\n"}, {})
    output_path = tmp_path / "backup.zip"

    result = collector.build_zip("root", output_path)

    assert result == {"file_count": 2}
    assert output_path.exists()
    with zipfile.ZipFile(output_path) as zf:
        names = set(zf.namelist())
        assert names == {"a.json", "sub/b.csv"}
        assert zf.read("a.json") == b'{"x":1}'
        assert zf.read("sub/b.csv") == b"a,b\n1,2\n"
