"""CachingRepositoryDecorator（layer1_data_acquisition_design.md 6章・7章の確定仕様）。

任意のRepositoryをラップし、呼び出し前にキャッシュを確認する。
永続化先はGoogle Driveに一本化する設計（7-2）のため、`CacheStore`を抽象化し、
本番はGoogle Drive実装、テスト・ローカル開発はインメモリ実装を使えるようにする。
"""

from __future__ import annotations

import abc
import time
from datetime import date
from typing import Any, Callable, Optional


class CacheStore(abc.ABC):
    """キャッシュの永続化先を抽象化するインターフェース。"""

    @abc.abstractmethod
    def get(self, key: str) -> Optional[Any]:
        ...

    @abc.abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        ...


class InMemoryCacheStore(CacheStore):
    """実行内メモリキャッシュ（7-1の1.）。テスト・単一run内の重複排除に使う。

    本番の永続キャッシュ（Google Drive、7-1の2.）は別途`GoogleDriveCacheStore`等として
    実装し、同じ`CacheStore`インターフェースでこのクラスと差し替える。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._store: dict[str, tuple[Any, Optional[float]]] = {}
        self._clock = clock

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._clock() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        expires_at = self._clock() + ttl_seconds if ttl_seconds is not None else None
        self._store[key] = (value, expires_at)


class GoogleDriveCacheStore(CacheStore):
    """Google Driveをバックエンドとする永続キャッシュ（7-1の2.、7-2確定方針）。

    実行開始時にDrive上の1ファイル（キャッシュ全体をpickle化したもの）を読み込み、
    実行終了時に変更があれば`flush()`で書き戻す想定（7-2「毎回Driveから読み込み、
    実行終了時にDriveへ書き戻す」）。呼び出し側（Layer1の実行スクリプト）は、
    run終了時に必ず`flush()`を呼ぶこと。

    Google Drive APIとの実際の通信部分（_get_drive_service/_find_file_id/
    _download_bytes/_upload_bytes）は、テストで容易にモック・サブクラス化できるよう
    小さなメソッドに分離している。

    値の(de)serializationにはpickleを用いる。ここでのpickleは自分自身が書き込んだ
    データのみを読み込む（外部から供給される信頼できないデータをunpickleすることは
    無い）ため、pickleの安全性上の懸念は生じない設計としている。
    """

    def __init__(
        self,
        service_account_json: str,
        folder_id: str,
        file_name: str = "layer1_cache_index.pkl",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not service_account_json or not folder_id:
            raise ValueError("service_account_json and folder_id are required")
        self._service_account_json = service_account_json
        self._folder_id = folder_id
        self._file_name = file_name
        self._clock = clock
        self._data: Optional[dict] = None
        self._drive_file_id: Optional[str] = None
        self._dirty = False

    def _get_drive_service(self) -> Any:
        import json as _json

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = _json.loads(self._service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credentials)

    def _find_file_id(self, service: Any) -> Optional[str]:
        query = f"name = '{self._file_name}' and '{self._folder_id}' in parents and trashed = false"
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

    def _upload_bytes(self, service: Any, raw_bytes: bytes) -> None:
        import io

        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(raw_bytes), mimetype="application/octet-stream")
        if self._drive_file_id:
            service.files().update(fileId=self._drive_file_id, media_body=media).execute()
        else:
            metadata = {"name": self._file_name, "parents": [self._folder_id]}
            created = service.files().create(body=metadata, media_body=media, fields="id").execute()
            self._drive_file_id = created["id"]

    def _ensure_loaded(self) -> None:
        if self._data is not None:
            return
        import pickle

        service = self._get_drive_service()
        file_id = self._find_file_id(service)
        if file_id is None:
            self._data = {}
            return
        raw_bytes = self._download_bytes(service, file_id)
        self._data = pickle.loads(raw_bytes) if raw_bytes else {}
        self._drive_file_id = file_id

    def get(self, key: str) -> Optional[Any]:
        self._ensure_loaded()
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._clock() > expires_at:
            del self._data[key]
            self._dirty = True
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        self._ensure_loaded()
        expires_at = self._clock() + ttl_seconds if ttl_seconds is not None else None
        self._data[key] = (value, expires_at)
        self._dirty = True

    def flush(self) -> None:
        """実行終了時に呼び出す。変更（新規取得・TTL失効削除）があればDriveへ書き戻す。"""
        if not self._dirty or self._data is None:
            return
        import pickle

        service = self._get_drive_service()
        self._upload_bytes(service, pickle.dumps(self._data))
        self._dirty = False


def build_default_cache_store() -> CacheStore:
    """環境変数からCacheStoreを自動選択する。

    `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`・`GOOGLE_DRIVE_FOLDER_ID`が両方設定されて
    いればGoogleDriveCacheStore（本番用）を、そうでなければInMemoryCacheStore
    （ローカル開発・テスト用）を返す。
    """
    import os

    service_account_json = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if service_account_json and folder_id:
        return GoogleDriveCacheStore(service_account_json, folder_id)
    return InMemoryCacheStore()


class CachingRepositoryDecorator:
    """Repositoryの主要メソッド呼び出しを`(source, ticker, ...)`をキーにキャッシュする。

      確定済み日次データ（get_daily_prices） : TTLなし（7-2、一度取得したら再取得しない）
      ファンダメンタルデータ（get_fundamentals）: TTL 7日（7-2）
      ニュース（fetch_news）                  : キャッシュ対象外（7-2）、そのまま委譲する
    """

    FUNDAMENTALS_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, repository: Any, cache_store: CacheStore, source_name: str) -> None:
        self._repository = repository
        self._cache_store = cache_store
        self._source_name = source_name

    def get_daily_prices(self, ticker: str, start_date: date, end_date: date) -> Any:
        key = f"{self._source_name}:daily_prices:{ticker}:{start_date}:{end_date}"
        cached = self._cache_store.get(key)
        if cached is not None:
            return cached
        result = self._repository.get_daily_prices(ticker, start_date, end_date)
        self._cache_store.set(key, result)
        return result

    def get_fundamentals(self, ticker: str) -> Any:
        key = f"{self._source_name}:fundamentals:{ticker}"
        cached = self._cache_store.get(key)
        if cached is not None:
            return cached
        result = self._repository.get_fundamentals(ticker)
        self._cache_store.set(key, result, ttl_seconds=self.FUNDAMENTALS_TTL_SECONDS)
        return result

    def __getattr__(self, item: str) -> Any:
        # キャッシュ対象外のメソッド（fetch_news等）はそのまま委譲する（7-2）
        return getattr(self._repository, item)
