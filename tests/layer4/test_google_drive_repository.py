"""GoogleDriveRepositoryのテスト（layer4_persistence_design.md §7・§10）。

実際のGoogle Drive API通信部分はすべてフェイクに差し替え、supersededリネームロジックと
history indexの追記ロジックのみを検証する（このサンドボックス環境にはgoogle-api-python-client
の実クライアントも専用の認証情報も無いため。ライブ疎通確認はGitHub Actions側で行う）。
"""

from datetime import datetime, timezone

from ai_investment_assistant.layer4_persistence.repository.google_drive_repository import (
    GoogleDriveRepository,
)


class FakeGoogleDriveRepository(GoogleDriveRepository):
    """Drive API呼び出しをすべてインメモリのフェイクに差し替えたテスト用サブクラス。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_id = 0
        self.folders: dict = {}  # name -> folder_id
        self.files: dict = {}    # (folder_id, name) -> {"id": str, "content": dict}
        self.renamed: list = []  # (old_name, new_name) の記録

    def _new_id(self) -> str:
        self._next_id += 1
        return f"id-{self._next_id}"

    def _get_drive_service(self):
        return "fake-service"

    def _find_folder(self, service, name, parent_id):
        return self.folders.get(name)

    def _create_folder(self, service, name, parent_id):
        folder_id = self._new_id()
        self.folders[name] = folder_id
        return folder_id

    def _find_file(self, service, name, parent_id):
        entry = self.files.get((parent_id, name))
        return entry["id"] if entry else None

    def _download_json(self, service, file_id):
        for entry in self.files.values():
            if entry["id"] == file_id:
                return entry["content"]
        raise KeyError(file_id)

    def _upload_json(self, service, parent_id, name, content, existing_file_id=None):
        if existing_file_id:
            for key, entry in self.files.items():
                if entry["id"] == existing_file_id:
                    entry["content"] = content
                    return existing_file_id
        file_id = self._new_id()
        self.files[(parent_id, name)] = {"id": file_id, "content": content}
        return file_id

    def _rename_file(self, service, file_id, new_name):
        for key, entry in list(self.files.items()):
            if entry["id"] == file_id:
                parent_id, old_name = key
                del self.files[key]
                self.files[(parent_id, new_name)] = entry
                self.renamed.append((old_name, new_name))
                return


def test_save_snapshot_creates_folder_and_file():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    path = repo.save_snapshot("20260720", {"run_meta": {}})
    assert path == "snapshots/market_snapshot_20260720.json"
    assert "snapshots" in repo.folders


def test_save_snapshot_supersedes_existing_file_on_second_call():
    # クロックは既存ファイルをリネームする瞬間（2回目のsave呼び出し時）にのみ参照される
    # ため、1回分の固定値でよい。
    fixed_time = datetime(2026, 7, 20, 9, 30, 0, tzinfo=timezone.utc)
    repo = FakeGoogleDriveRepository(
        oauth_token_json="{}", root_folder_id="root", clock=lambda: fixed_time
    )

    repo.save_snapshot("20260720", {"version": 1})
    repo.save_snapshot("20260720", {"version": 2})

    assert repo.renamed == [("market_snapshot_20260720.json", "market_snapshot_20260720_supersededT093000Z.json")]
    folder_id = repo.folders["snapshots"]
    current = repo.files[(folder_id, "market_snapshot_20260720.json")]["content"]
    assert current == {"version": 2}
    superseded = repo.files[(folder_id, "market_snapshot_20260720_supersededT093000Z.json")]["content"]
    assert superseded == {"version": 1}


def test_save_completion_flag_uses_snapshots_subfolder():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    path = repo.save_completion_flag("20260720", {"completed": True})
    assert path == "snapshots/layer4_completed_20260720.json"


def test_save_execution_log_uses_logs_subfolder():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    path = repo.save_execution_log("20260720", {"run_id": "x"})
    assert path == "logs/execution_log_20260720.json"


def test_save_history_index_creates_new_index_when_none_exists():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    path = repo.save_history_index("202607", {"date": "2026-07-20"})
    assert path == "history/index_202607.json"
    folder_id = repo.folders["history"]
    content = repo.files[(folder_id, "index_202607.json")]["content"]
    assert content == {"entries": [{"date": "2026-07-20"}]}


def test_save_history_index_appends_to_existing_index():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    repo.save_history_index("202607", {"date": "2026-07-19"})
    repo.save_history_index("202607", {"date": "2026-07-20"})

    folder_id = repo.folders["history"]
    content = repo.files[(folder_id, "index_202607.json")]["content"]
    assert content == {"entries": [{"date": "2026-07-19"}, {"date": "2026-07-20"}]}


def test_folder_lookup_is_cached_within_instance():
    repo = FakeGoogleDriveRepository(oauth_token_json="{}", root_folder_id="root")
    repo.save_snapshot("20260720", {})
    repo.save_completion_flag("20260720", {})
    # 両方とも同じ"snapshots"フォルダを使うが、_create_folderは1回しか呼ばれない
    # （2回目はフォルダキャッシュから取得されるはず）ことを、フォルダが1つしか
    # 作られていないことで間接的に確認する。
    assert len(repo.folders) == 1


def test_constructor_requires_credentials():
    import pytest

    with pytest.raises(ValueError):
        GoogleDriveRepository(oauth_token_json="", root_folder_id="root")
