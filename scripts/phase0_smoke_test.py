"""Phase0 smoke test.

Phase0の完了基準（docs/00_SystemArchitecture.md §9）：
「GitHub Actions実行環境・Google Drive連携・シークレット管理・config/初期セットアップが
完了し、空のパイプラインが起動できること」

このスクリプトはLayer1のRepositoryを一切呼び出さない。確認するのは以下の2点のみ：
  1. config/api_sources.yaml が読み込める（config/初期セットアップの確認）
  2. Google DriveのOAuth 2.0ユーザー認証と対象フォルダへの到達性（Google Drive連携の確認）

Layer1の実装（各Repositoryクラス・フォールバック・キャッシュ）はPhase1で行う。

注意（2026-07-22）：サービスアカウント認証は個人のGoogle Drive（マイドライブ）の保存容量を
持たないため使用しない（詳細はai_investment_assistant.common.google_oauth_auth参照）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def check_config() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config" / "api_sources.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    print(f"[OK] config/api_sources.yaml loaded: {list(config.keys())}")
    return config


def check_google_drive() -> None:
    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not oauth_token_json or not folder_id:
        print(
            "[SKIP] GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_DRIVE_FOLDER_ID が"
            "未設定のため、Google Drive疎通確認をスキップします"
            "（Secrets未設定の初回ローカル実行では想定内）。"
        )
        return

    from googleapiclient.discovery import build

    from ai_investment_assistant.common.google_oauth_auth import build_oauth_credentials

    credentials = build_oauth_credentials(
        oauth_token_json, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive = build("drive", "v3", credentials=credentials)
    folder = drive.files().get(fileId=folder_id, fields="id, name").execute()
    print(f"[OK] Google Drive folder reachable: {folder['name']} ({folder['id']})")


def main() -> int:
    try:
        check_config()
        check_google_drive()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Phase0 smoke test failed: {exc}", file=sys.stderr)
        return 1
    print("[DONE] Phase0 smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
