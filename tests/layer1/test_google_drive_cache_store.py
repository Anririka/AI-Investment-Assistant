"""GoogleDriveCacheStore / build_default_cache_storeのテスト。

実際のGoogle Drive API通信部分（_get_drive_service等）はサブクラス化して
フェイクに差し替え、get/set/flushのオーケストレーションロジックのみを検証する
（このサンドボックス環境にはgoogle-api-python-clientが無いため、実APIクライアント
そのものはテストしない。ライブ疎通確認はGitHub Actions側で行う）。
"""

from ai_investment_assistant.layer1_data_acquisition.caching import (
    GoogleDriveCacheStore,
    InMemoryCacheStore,
    build_default_cache_store,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeGoogleDriveCacheStore(GoogleDriveCacheStore):
    """Drive API呼び出しをすべてフェイクに差し替えたテスト用サブクラス。"""

    def __init__(self, *args, existing_remote_data=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.remote_bytes = None
        if existing_remote_data is not None:
            import pickle

            self.remote_bytes = pickle.dumps(existing_remote_data)
            self._drive_file_id = "existing-file-id"
        self.upload_calls = 0
        self.create_calls = 0

    def _get_drive_service(self):
        return "fake-service"  # 実際には使わない（他メソッドをオーバーライドしているため）

    def _find_file_id(self, service):
        return "existing-file-id" if self.remote_bytes is not None else None

    def _download_bytes(self, service, file_id):
        return self.remote_bytes

    def _upload_bytes(self, service, raw_bytes):
        if self._drive_file_id:
            self.upload_calls += 1
        else:
            self.create_calls += 1
            self._drive_file_id = "new-file-id"
        self.remote_bytes = raw_bytes


def test_get_returns_none_when_no_remote_file_exists():
    store = FakeGoogleDriveCacheStore(
        service_account_json="{}", folder_id="folder-1"
    )
    assert store.get("some-key") is None


def test_set_then_get_within_same_instance():
    store = FakeGoogleDriveCacheStore(service_account_json="{}", folder_id="folder-1")
    store.set("k", "v")
    assert store.get("k") == "v"


def test_flush_does_nothing_when_not_dirty():
    store = FakeGoogleDriveCacheStore(service_account_json="{}", folder_id="folder-1")
    store.flush()
    assert store.upload_calls == 0
    assert store.create_calls == 0


def test_flush_creates_new_file_when_none_existed():
    store = FakeGoogleDriveCacheStore(service_account_json="{}", folder_id="folder-1")
    store.set("k", "v")
    store.flush()
    assert store.create_calls == 1
    assert store.upload_calls == 0


def test_flush_updates_existing_file():
    store = FakeGoogleDriveCacheStore(
        service_account_json="{}", folder_id="folder-1", existing_remote_data={"old": ("value", None)}
    )
    store.set("new-key", "new-value")
    store.flush()
    assert store.upload_calls == 1
    assert store.create_calls == 0


def test_loads_existing_remote_data_on_first_access():
    store = FakeGoogleDriveCacheStore(
        service_account_json="{}",
        folder_id="folder-1",
        existing_remote_data={"prior-key": ("prior-value", None)},
    )
    assert store.get("prior-key") == "prior-value"


def test_ttl_expiry_marks_dirty_and_flush_persists_removal():
    clock = FakeClock()
    store = FakeGoogleDriveCacheStore(
        service_account_json="{}",
        folder_id="folder-1",
        clock=clock,
        existing_remote_data={"k": ("v", 10.0)},
    )
    clock.now = 5
    assert store.get("k") == "v"

    clock.now = 11
    assert store.get("k") is None  # TTL経過で削除される

    store.flush()
    assert store.upload_calls == 1  # 削除（変更）があったのでflushで書き戻される


def test_constructor_requires_credentials():
    import pytest

    with pytest.raises(ValueError):
        GoogleDriveCacheStore(service_account_json="", folder_id="folder-1")
    with pytest.raises(ValueError):
        GoogleDriveCacheStore(service_account_json="{}", folder_id="")


def test_build_default_cache_store_uses_in_memory_when_env_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)

    store = build_default_cache_store()

    assert isinstance(store, InMemoryCacheStore)


def test_build_default_cache_store_uses_google_drive_when_env_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder-123")

    store = build_default_cache_store()

    assert isinstance(store, GoogleDriveCacheStore)
