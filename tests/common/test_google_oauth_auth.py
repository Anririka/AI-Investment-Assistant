"""build_oauth_credentials()のテスト。

実際にGoogleへネットワーク通信するCredentialsの中身（refresh_token等）が正しく
組み立てられているかのみを検証する（実際のトークン更新はモックしない、
googleapiclient.discovery.build()呼び出し時にgoogle-authが内部で処理するため）。

このサンドボックス環境にはgoogle-auth自体がインストールされていないため（他レイヤーの
Google Drive系テストと同じ制約、tests/layer1/test_google_drive_cache_store.py参照）、
google.oauth2.credentialsがimportできない場合はスキップする。GitHub Actions側では
requirements.txtにより google-auth がインストールされるため、実際にこのテストが実行される。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("google.oauth2.credentials")

from ai_investment_assistant.common.google_oauth_auth import build_oauth_credentials  # noqa: E402


def test_build_oauth_credentials_sets_fields_from_json():
    token_json = json.dumps(
        {"client_id": "client-1", "client_secret": "secret-1", "refresh_token": "refresh-1"}
    )

    credentials = build_oauth_credentials(
        token_json, scopes=["https://www.googleapis.com/auth/drive"]
    )

    assert credentials.client_id == "client-1"
    assert credentials.client_secret == "secret-1"
    assert credentials.refresh_token == "refresh-1"
    assert credentials.token_uri == "https://oauth2.googleapis.com/token"
    assert credentials.scopes == ["https://www.googleapis.com/auth/drive"]
    # まだrefresh()していないため、有効なアクセストークンは持たない
    assert credentials.token is None


@pytest.mark.parametrize("missing_field", ["client_id", "client_secret", "refresh_token"])
def test_build_oauth_credentials_raises_when_field_missing(missing_field):
    info = {"client_id": "client-1", "client_secret": "secret-1", "refresh_token": "refresh-1"}
    del info[missing_field]

    with pytest.raises(ValueError, match=missing_field):
        build_oauth_credentials(json.dumps(info), scopes=["https://www.googleapis.com/auth/drive"])


def test_build_oauth_credentials_raises_on_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        build_oauth_credentials("not-json", scopes=["https://www.googleapis.com/auth/drive"])
