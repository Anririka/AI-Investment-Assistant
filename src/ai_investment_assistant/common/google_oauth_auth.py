"""Google Drive／Google SheetsのためのOAuth 2.0ユーザー認証ヘルパー。

背景（2026-07-22、Google Drive `403 insufficientParentPermissions`の根本原因調査）：
Googleのサービスアカウントは個人のGoogle Drive（マイドライブ）の保存容量（ストレージ
クォータ）を一切持たない。共有フォルダへの「編集者」権限があっても、それは既存コンテンツへの
アクセス権が得られるだけで、新規ファイルを計上する容量そのものは得られない。そのため
`files().create()`は、共有設定・フォルダIDが完全に正しくても`403 insufficientParentPermissions`
で失敗する。これはGoogle公式ドキュメント・複数のコミュニティ報告で確認された仕様上の制約であり、
設定ミスでは解決できない（有料のGoogle Workspace「共有ドライブ」を使う以外の回避策がない）。

このため、Layer1（キャッシュ）・Layer4（永続化）・Layer6〜8（レポート／トラッキング／
自己評価）のすべてのGoogle Drive・Sheets書き込みは、サービスアカウントのJSON鍵ではなく、
実際のGoogleアカウント本人のOAuth 2.0リフレッシュトークンを使う方式に統一する。これにより、
作成されるファイルは本人の「マイドライブ」の容量として計上され、クォータの問題が起きない。

リフレッシュトークンは`scripts/generate_google_oauth_token.py`で最初の1回だけ、ローカルPCで
対話的に（ブラウザの同意画面を経由して）発行する。発行後は`GOOGLE_OAUTH_TOKEN_JSON`という
1つのJSON文字列としてGitHub Secrets等に保存し、以降は自動でアクセストークンが更新される
（google-auth-httplib2がgoogleapiclientのbuild()呼び出し時に必要に応じてrefreshする）。
"""

from __future__ import annotations

import json as _json
from typing import Any, Sequence

REQUIRED_FIELDS = ("client_id", "client_secret", "refresh_token")


def build_oauth_credentials(oauth_token_json: str, scopes: Sequence[str]) -> Any:
    """`oauth_token_json`（`{"client_id":..., "client_secret":..., "refresh_token":...}`）から
    `google.oauth2.credentials.Credentials`を構築する。

    サービスアカウント方式（`service_account.Credentials.from_service_account_info`）とは
    異なり、こちらはユーザー本人のrefresh_tokenを用いてアクセストークンを都度発行する方式。
    """
    from google.oauth2.credentials import Credentials

    info = _json.loads(oauth_token_json)
    missing = [key for key in REQUIRED_FIELDS if not info.get(key)]
    if missing:
        raise ValueError(
            f"oauth_token_json is missing required field(s): {', '.join(missing)}"
        )

    return Credentials(
        token=None,
        refresh_token=info["refresh_token"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=list(scopes),
    )
