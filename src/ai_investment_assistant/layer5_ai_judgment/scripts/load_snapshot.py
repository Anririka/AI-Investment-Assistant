"""Layer5のsnapshot読み込み・実行タイミング調整・データ品質ゲート判定
（layer5_ai_judgment_design.md §3-1・§5）。

Claude Coworkスケジュールタスクが自身のBashツールでこのスクリプトを実行する。
完了フラグの存在確認・エラーコードの分類は機械的な判定であり、LLMの暗算・裁量に
委ねずコードで行う（§0の原則をデータ品質ゲートにも適用する）。

判定はLayer2出力のrun_meta.data_quality.critical_errors／warning_errorsの両方に
含まれる各エントリのcodeフィールドに対して行う。Layer2自身がどちらの配列に入れたかは
問わず、Layer5がconfig/data_quality_policy.yamlで独自に再分類する（§5-1）。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "data_quality_policy.yaml"

# 2026-07-24追加（回帰対応）：Layer4（scripts/run_daily_pipeline.py）はmarket_snapshot_*.json
# 等のファイル名をJST基準の日付（now_jst.strftime("%Y%m%d")）で生成している。本スクリプトが
# 日付引数省略時にUTC基準の日付をデフォルトにしていたため、UTC 15:00〜23:59（JST既に翌日）
# の時間帯にLayer5を実行すると、Layer4が書き込んだ「今日」のファイルではなく前日分の
# ファイル名を探しに行ってしまい、実データが存在するのに見つからない不整合が生じていた
# （2026-07-24のライブ実行で発覚：Layer4は"20260724"のファイルを書いたが、Layer5は
# デフォルトで"20260723"を探し、古い（別の日の）ファイルを読んでしまっていた）。
# Layer4と同じJST基準に統一する。
_JST = timezone(timedelta(hours=9))


def load_policy(config_path: Path = _CONFIG_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_pipeline_completion(
    flag: Optional[dict],
    now: datetime,
    run_started_at: datetime,
    timeout_minutes: int,
) -> dict:
    """layer4_completed_YYYYMMDD.jsonの状態から、Layer5を実行してよいかを判定する（§3-1）。

    戻り値: {"ready": bool, "blocked": bool, "reason_code": Optional[str]}
    - ready=True: completed:trueが確認できた。snapshotの読み込みへ進んでよい。
    - blocked=True: 規定時間超過でフラグ未到達、またはcompleted:falseが確認できた。
      LLM推論を行わず様子見で確定する（reason_code: LAYER_PIPELINE_NOT_COMPLETED）。
    - ready=False かつ blocked=False: まだ規定時間内でフラグ未到達（待機継続。呼び出し側で
      再実行する運用を想定）。
    """
    if flag is not None and flag.get("completed") is True:
        return {"ready": True, "blocked": False, "reason_code": None}

    if flag is not None and flag.get("completed") is False:
        return {"ready": False, "blocked": True, "reason_code": "LAYER_PIPELINE_NOT_COMPLETED"}

    elapsed_minutes = (now - run_started_at).total_seconds() / 60
    if elapsed_minutes >= timeout_minutes:
        return {"ready": False, "blocked": True, "reason_code": "LAYER_PIPELINE_NOT_COMPLETED"}
    return {"ready": False, "blocked": False, "reason_code": None}


def classify_data_quality(data_quality: dict, policy: dict) -> dict:
    """critical_errors／warning_errorsの各エントリのcodeを、Layer5のポリシーで再分類する。

    分類されないcode（policyのどちらのリストにも無いcode）は、安全側に倒し
    blocking扱いとする（未知のエラーコードで投資判断を続行しないため）。

    戻り値: {"gate": "passed"|"warning_continued"|"blocked",
             "blocking_errors_found": [...], "warning_errors_found": [...]}
    """
    blocking_codes = set(policy.get("blocking_errors", []))
    warning_codes = set(policy.get("warning_errors", []))

    all_errors = list(data_quality.get("critical_errors", [])) + list(
        data_quality.get("warning_errors", [])
    )

    blocking_found = []
    warning_found = []
    for error in all_errors:
        code = error.get("code")
        if code in blocking_codes:
            blocking_found.append(error)
        elif code in warning_codes:
            warning_found.append(error)
        else:
            # 未分類のエラーコードは安全側に倒しblocking扱いとする。
            blocking_found.append(error)

    if blocking_found:
        gate = "blocked"
    elif warning_found:
        gate = "warning_continued"
    else:
        gate = "passed"

    return {
        "gate": gate,
        "blocking_errors_found": blocking_found,
        "warning_errors_found": warning_found,
    }


def evaluate_snapshot(market_snapshot: Optional[dict], policy: dict) -> dict:
    """market_snapshotが取得できたかどうかも含めた、データ品質ゲートの最終判定（§5）。"""
    if market_snapshot is None:
        return {
            "gate": "blocked",
            "blocking_errors_found": [{"code": "SNAPSHOT_MISSING", "message": "market_snapshotが見つかりません"}],
            "warning_errors_found": [],
        }
    data_quality = market_snapshot.get("run_meta", {}).get("data_quality", {})
    return classify_data_quality(data_quality, policy)


def run_load_snapshot(
    drive_client,
    date_str: str,
    now: datetime,
    run_started_at: datetime,
    policy: dict,
) -> dict:
    """load_snapshot.pyの本体処理（§3手順2〜3）。

    戻り値には少なくとも以下を含む：
      status: "blocked" | "waiting" | "passed" | "warning_continued"
      reason_code: Optional[str]
      market_snapshot: Optional[dict]
      data_quality_gate_detail: dict
    """
    flag = drive_client.read_json("snapshots", f"layer4_completed_{date_str}.json")
    completion = check_pipeline_completion(
        flag, now=now, run_started_at=run_started_at,
        timeout_minutes=policy.get("completion_flag_timeout_minutes", 30),
    )

    if not completion["ready"] and not completion["blocked"]:
        return {
            "status": "waiting",
            "reason_code": None,
            "market_snapshot": None,
            "data_quality_gate_detail": {"blocking_errors_found": [], "warning_errors_found": []},
        }

    if completion["blocked"]:
        return {
            "status": "blocked",
            "reason_code": completion["reason_code"],
            "market_snapshot": None,
            "data_quality_gate_detail": {
                "blocking_errors_found": [{"code": completion["reason_code"], "message": "Layer1-4パイプライン未完了"}],
                "warning_errors_found": [],
            },
        }

    market_snapshot = drive_client.read_json("snapshots", f"market_snapshot_{date_str}.json")
    detail = evaluate_snapshot(market_snapshot, policy)

    if detail["gate"] == "blocked":
        return {
            "status": "blocked",
            "reason_code": detail["blocking_errors_found"][0]["code"],
            "market_snapshot": None,
            "data_quality_gate_detail": detail,
        }

    return {
        "status": detail["gate"],  # "passed" | "warning_continued"
        "reason_code": None,
        "market_snapshot": market_snapshot,
        "data_quality_gate_detail": detail,
    }


def main() -> int:
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(_JST).strftime("%Y%m%d")
    run_started_at_env = os.environ.get("LAYER5_RUN_STARTED_AT")
    run_started_at = (
        datetime.fromisoformat(run_started_at_env.replace("Z", "+00:00"))
        if run_started_at_env
        else datetime.now(timezone.utc)
    )
    policy = load_policy()

    # LAYER5_LOCAL_DATA_DIRが設定されている場合、Google Drive MCPコネクタ経由で
    # エージェントが既に取得済みのローカルファイルを読む（Coworkサンドボックスの
    # googleapis.comネットワーク遮断への対応。local_drive_client.py参照）。
    local_data_dir = os.environ.get("LAYER5_LOCAL_DATA_DIR")
    if local_data_dir:
        from .local_drive_client import LocalDriveClient

        client = LocalDriveClient(base_dir=local_data_dir)
    else:
        from .drive_client import Layer5DriveClient

        oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", "")
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
        if not oauth_token_json or not folder_id:
            print(json.dumps({"status": "blocked", "reason_code": "PORTFOLIO_STATE_INVALID",
                               "error": "LAYER5_LOCAL_DATA_DIR、または"
                               "GOOGLE_OAUTH_TOKEN_JSON/GOOGLE_DRIVE_FOLDER_IDが未設定"}))
            return 1
        client = Layer5DriveClient(oauth_token_json=oauth_token_json, root_folder_id=folder_id)

    result = run_load_snapshot(client, date_str=date_str, now=datetime.now(timezone.utc),
                                run_started_at=run_started_at, policy=policy)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
