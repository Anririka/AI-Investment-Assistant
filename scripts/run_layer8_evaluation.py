"""Layer8（自己評価層）を実データで実行する本番パイプライン。

.github/workflows/evaluation_pipeline.yml のコメントにあった
「Layer8の実際の実行ステップは、全体テスト完了後にsecrets設定を確認したうえでここへ
追加する」に対応するスクリプト（scripts/run_daily_pipeline.py・
scripts/run_layer7_tracking.py と同じ構成方針）。

実行内容（layer8_self_evaluation_design.md §4）：
  1. `Layer8DriveClient`（Google Drive／Sheets、OAuthユーザー認証）を組み立てる。
  2. `config/feedback_thresholds.yaml`の各種閾値を読み込む。
  3. `layer8_self_evaluation.main.run(...)`を実行する（Layer7完了フラグ確認→
     closed_positions読込→未評価ポジション特定→score_context取得→勝敗判定→
     セグメント集計→保存→evaluation_index更新→feedback生成）。

`year_months_to_scan`は、当月＋前月の2ヶ月分を既定でスキャンする（月境界をまたいで
クローズしたポジションの取りこぼしを避けるための単純な安全マージン。設計書§4は
「当該期間（および必要に応じ複数期間）」とだけ定めており、具体的な月数は実装判断）。

日付はJST基準（`date_str`）で計算する。Layer7が保存する完了フラグ
（`tracking/layer7_completed_YYYYMMDD.json`）もJST基準のため、これに合わせる。

本スクリプトはユニットテスト対象外（run_daily_pipeline.py・run_layer7_tracking.pyと
同様、実際の外部API・Google Driveを呼び出すライブ運用スクリプトのため）。GitHub
Actionsの手動実行（workflow_dispatch）で検証する。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from ai_investment_assistant.layer8_self_evaluation import main as layer8_main
from ai_investment_assistant.layer8_self_evaluation.drive_client import Layer8DriveClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_layer8_evaluation")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
JST = timezone(timedelta(hours=9))

MONTHS_TO_SCAN = 2  # 当月＋前月（月境界の取りこぼし防止のための単純な安全マージン）


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def _recent_year_months(base: datetime, count: int) -> list:
    """`base`月を含め、月をさかのぼった`count`ヶ月分のYYYYMM文字列を新しい順で返す。"""
    year_months = []
    year, month = base.year, base.month
    for _ in range(count):
        year_months.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return year_months


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    now_jst = _now_jst()
    date_str = now_jst.strftime("%Y%m%d")
    year_months_to_scan = _recent_year_months(now_jst, MONTHS_TO_SCAN)

    logger.info(
        "=== run_layer8_evaluation start (date_str=%s, year_months_to_scan=%s) ===",
        date_str, year_months_to_scan,
    )

    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not oauth_token_json or not folder_id:
        logger.error(
            "GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_DRIVE_FOLDER_ID not set; cannot access Google Drive."
        )
        return 1

    drive_client = Layer8DriveClient(oauth_token_json, folder_id)

    feedback_thresholds_config = _load_yaml("feedback_thresholds.yaml")
    confidence_thresholds = feedback_thresholds_config["confidence_thresholds"]
    min_recommended_sample = feedback_thresholds_config["min_recommended_sample_for_confidence"]
    win_rate_diff_threshold = feedback_thresholds_config["weight_suggestion_win_rate_diff_threshold"]

    result = layer8_main.run(
        drive_client=drive_client,
        date_str=date_str,
        year_months_to_scan=year_months_to_scan,
        confidence_thresholds=confidence_thresholds,
        min_recommended_sample=min_recommended_sample,
        win_rate_diff_threshold=win_rate_diff_threshold,
        now=now_utc,
    )

    status = result.get("status")
    if status == "ok":
        logger.info(
            "=== run_layer8_evaluation completed: new_count=%d touched_months=%s ===",
            result.get("new_count", 0), result.get("touched_months"),
        )
        return 0
    if status in ("skipped", "no_new_evaluations"):
        logger.info("=== run_layer8_evaluation completed with no action: %s ===", result)
        return 0

    logger.error("=== run_layer8_evaluation FAILED: %s ===", result)
    return 1


if __name__ == "__main__":
    sys.exit(main())
