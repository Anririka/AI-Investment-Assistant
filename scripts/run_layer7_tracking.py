"""Layer7（提案トラッキング層）を実データで実行する本番パイプライン。

.github/workflows/tracking_pipeline.yml のコメントにあった
「Layer7の実際の実行ステップは、全体テスト完了後にsecrets設定を確認したうえでここへ追加する」
に対応するスクリプト（scripts/run_daily_pipeline.py と同じ構成方針）。

実行内容（layer7_proposal_tracking_design.md §4・§7）：
  1. `Layer7DriveClient`（Google Drive／Sheets、OAuthユーザー認証）を組み立てる。
  2. Layer1の`RepositoryFactory`（`config/api_sources.yaml`）から、既存の
     japan_equity／us_equityチェーンをそのまま再利用して`LookbackPriceCheckRepository`を
     組み立てる（§7-2：Layer1のクラス・設定・契約は一切変更しない。既にdata_pipeline.yml
     の本番実行で使われているのと同じRepositoryFactory・同じsecretsを再利用するため、
     新規のAPIキー取得は不要）。
  3. `config/holding_period_parser.yaml`の`unit_days`・`fallback_default_days`を読み込む。
  4. `layer7_proposal_tracking.main.run(...)`を実行する（新規取り込み→価格取得→
     利確/損切/期間満了判定→manual_close処理→クローズ処理→履歴保存→完了フラグ書き込み）。

日付はJST基準（`date_str`・`today`）で計算する。Layer6が保存するファイル名
（`提案ログ_YYYYMMDD_本日の提案`等、2026-07-26以降の分割ファイル形式）もJST基準のため、
これに合わせる。

本スクリプトはユニットテスト対象外（run_daily_pipeline.pyと同様、実際の外部API・
Google Driveを呼び出すライブ運用スクリプトのため）。GitHub Actionsの手動実行
（workflow_dispatch）で検証する。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from ai_investment_assistant.layer1_data_acquisition.caching import build_default_cache_store
from ai_investment_assistant.layer1_data_acquisition.factory import RepositoryFactory
from ai_investment_assistant.layer7_proposal_tracking import main as layer7_main
from ai_investment_assistant.layer7_proposal_tracking.drive_client import Layer7DriveClient
from ai_investment_assistant.layer7_proposal_tracking.repository.price_check_repository_impl import (
    LookbackPriceCheckRepository,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_layer7_tracking")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
JST = timezone(timedelta(hours=9))

# layer7_proposal_tracking_design.md §7-3：1営業日1回、直近の価格のみを取得する。
# 週末・祝日を挟んでも直近の取引日のバーを拾えるよう、1週間分の幅を持たせる
# （price_check_repository_impl.pyのLookbackPriceCheckRepositoryのデフォルトと同じ）。
PRICE_LOOKBACK_DAYS = 7


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    now_jst = _now_jst()
    date_str = now_jst.strftime("%Y%m%d")
    today = now_jst.date()

    logger.info("=== run_layer7_tracking start (date_str=%s) ===", date_str)

    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not oauth_token_json or not folder_id:
        logger.error(
            "GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_DRIVE_FOLDER_ID not set; cannot access Google Drive."
        )
        return 1

    drive_client = Layer7DriveClient(oauth_token_json, folder_id)

    api_sources_config = _load_yaml("api_sources.yaml")
    cache_store = build_default_cache_store()
    factory = RepositoryFactory(api_sources_config, cache_store=cache_store)
    price_repository = LookbackPriceCheckRepository.from_repository_factory(
        factory, lookback_days=PRICE_LOOKBACK_DAYS
    )

    holding_period_config = _load_yaml("holding_period_parser.yaml")
    unit_days = holding_period_config["unit_days"]
    fallback_default_days = holding_period_config["fallback_default_days"]

    result = layer7_main.run(
        drive_client=drive_client,
        price_repository=price_repository,
        date_str=date_str,
        unit_days=unit_days,
        fallback_default_days=fallback_default_days,
        now=now_utc,
        today=today,
    )

    if result.get("completed"):
        logger.info(
            "=== run_layer7_tracking completed successfully: new=%d active=%d closed=%d "
            "skipped_duplicates=%s failed_price_tickers=%s ===",
            result.get("new_positions_count", 0),
            result.get("active_positions_count", 0),
            len(result.get("closed_positions", [])),
            result.get("skipped_duplicates"),
            result.get("failed_price_tickers"),
        )
        return 0

    logger.error("=== run_layer7_tracking FAILED: %s ===", result)
    return 1


if __name__ == "__main__":
    sys.exit(main())
