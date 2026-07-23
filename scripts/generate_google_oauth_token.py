"""Google Drive/Sheets用のOAuth 2.0リフレッシュトークンを、最初の1回だけ発行するための
ローカル専用スクリプト（対話的なブラウザ同意画面を経由するため、GitHub Actions上では
実行できない。必ず自分のPC上で1回だけ実行すること）。

背景：Googleのサービスアカウントには個人のGoogle Drive（マイドライブ）の保存容量がなく、
共有フォルダへの新規ファイル作成が`403 insufficientParentPermissions`で失敗する
（詳細はsrc/ai_investment_assistant/common/google_oauth_auth.pyのdocstring参照）。
そのためLayer1・Layer4・Layer6〜8のすべてのGoogle Drive/Sheets書き込みは、本人の
OAuth 2.0リフレッシュトークンを使う方式に統一する。このスクリプトはその発行専用。

事前準備（Google Cloud Console側の作業、詳細な手順はユーザーへ別途案内する）：
  1. 対象プロジェクトでGoogle Drive API・Google Sheets APIを有効化する
  2. 「APIとサービス」→「認証情報」→「OAuth クライアント ID を作成」
     アプリケーションの種類は「デスクトップアプリ」を選択する
  3. 作成後、JSON形式でダウンロードする（ファイル名は任意。例：client_secret.json）

使い方：
  python scripts/generate_google_oauth_token.py /path/to/client_secret.json

実行するとブラウザが開き、Google Driveに書き込ませたい本人のGoogleアカウント
（例：anri2026@...）でログイン・同意する。完了すると、GitHub Secretsの
`GOOGLE_OAUTH_TOKEN_JSON`にそのまま貼り付けられるJSON文字列が標準出力に表示される。

注意：このスクリプトはgoogle-auth-oauthlibに依存する。requirements.txtに含まれているが、
ローカル開発・この一度限りの発行作業でのみ使用し、GitHub Actions上の本番実行では
使用しない（本番はgoogle-authのgoogle.oauth2.credentials.Credentialsのみで足りる）。
"""

from __future__ import annotations

import json
import sys

# Layer6（スプレッドシート書き込み）まで含めた、全レイヤー共通で必要な最大範囲のスコープ。
# drive/spreadsheetsのフルスコープはreadonly相当のアクセスも包含するため、
# レイヤーごとに個別のトークンを発行する必要はない。
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "使い方: python scripts/generate_google_oauth_token.py /path/to/client_secret.json",
            file=sys.stderr,
        )
        return 1

    client_secret_path = sys.argv[1]

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "[FAIL] google-auth-oauthlib がインストールされていません。"
            "`pip install google-auth-oauthlib` を実行してから再試行してください。",
            file=sys.stderr,
        )
        return 1

    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes=SCOPES)
    except FileNotFoundError:
        print(f"[FAIL] ファイルが見つかりません: {client_secret_path}", file=sys.stderr)
        return 1

    print("[INFO] ブラウザが開きます。書き込ませたいGoogleアカウントでログイン・同意してください。")
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        print(
            "[FAIL] refresh_tokenが取得できませんでした。既にこのクライアントで同意済みの"
            "アカウントの場合、Googleアカウントの「サードパーティ製アプリとサービス」設定で"
            "一度アクセスを取り消してから再実行してください。",
            file=sys.stderr,
        )
        return 1

    token_json = json.dumps(
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
        }
    )

    print("\n[OK] 発行に成功しました。以下のJSON文字列をGitHub Secretsの")
    print("     GOOGLE_OAUTH_TOKEN_JSON にそのまま貼り付けてください：\n")
    print(token_json)
    print(
        "\n[注意] このトークンをコピーした後、ローカルの画面上・履歴・チャットログ等に"
        "平文のまま残さないよう、貼り付けが完了したら消去してください。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
