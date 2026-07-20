"""最終決定JSON・全候補の判断ログのGoogle Drive書き込み
（layer5_ai_judgment_design.md §3手順8・§3-2・§9）。

decision JSONは`decisions/decision_YYYYMMDDTHHMMSSZ.json`として保存する。タイムスタンプは
`run_meta.layer5_completed_at`（UTC・ISO8601、例：`2026-07-18T06:34:40Z`）をそのまま
`YYYYMMDDTHHMMSSZ`形式（ハイフン・コロン除去）へ変換して使う（§3-2）。supersede（既存
ファイルのリネーム）は行わない。秒単位までのタイムスタンプにより同日複数回実行時も
ファイル名の衝突は構造的に発生しない（§3-2）。
"""

from __future__ import annotations

from typing import Optional

from .schema_validator import validate_layer5_output


def compact_timestamp(iso_timestamp: str) -> str:
    """"2026-07-18T06:34:40Z" -> "20260718T063440Z" （§3-2の命名規則）。"""
    return iso_timestamp.replace("-", "").replace(":", "")


def build_decision_document(
    run_meta: dict,
    proposals: list,
    decision_log: list,
    rule_enforcement_log: list,
) -> dict:
    """§9の出力JSONスキーマに沿ったdecision documentを組み立てる。"""
    return {
        "run_meta": run_meta,
        "proposals": proposals,
        "decision_log": decision_log,
        "rule_enforcement_log": rule_enforcement_log,
    }


def decision_file_name(run_meta: dict) -> str:
    return f"decision_{compact_timestamp(run_meta['layer5_completed_at'])}.json"


def write_decision(drive_client, decision_document: dict, validate: bool = True) -> str:
    """decisions/へ保存し、保存先パスを返す（§3-2）。デフォルトでは保存前に
    §9のoutput schemaでバリデーションする（契約違反のJSONをそのまま保存しないため）。
    """
    if validate:
        validate_layer5_output(decision_document)
    file_name = decision_file_name(decision_document["run_meta"])
    return drive_client.write_decision(file_name, decision_document)
