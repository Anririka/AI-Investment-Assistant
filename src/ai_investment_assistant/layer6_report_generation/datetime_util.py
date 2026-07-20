"""実行日（JST基準）の導出（layer6_report_generation_design.md §6-2）。

ファイル名（`提案ログ_YYYYMMDD`／`report_YYYYMMDD.md`）の`YYYYMMDD`はJST基準の実行日
とする（§6-2）。Layer5の`run_meta.layer5_completed_at`はUTCのISO8601文字列であるため、
JST（UTC+9、夏時間なし）へ変換した上で日付部分のみを取り出す。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def execution_date_jst(run_meta: dict) -> str:
    """run_meta.layer5_completed_at（UTC ISO8601）からJST基準のYYYYMMDDを求める。"""
    completed_at = run_meta["layer5_completed_at"]
    dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    dt_jst = dt.astimezone(JST)
    return dt_jst.strftime("%Y%m%d")
