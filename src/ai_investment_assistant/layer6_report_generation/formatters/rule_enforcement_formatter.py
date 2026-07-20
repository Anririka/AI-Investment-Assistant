"""rule_enforcement_logの整形（layer6_report_generation_design.md §9）。

`applied: false`のエントリも省略せず表示する（Ver2の透明性要件、§9）。`detail`が
存在しない場合は空欄とする。並び替えは行わず、Layer5が出力した順序をそのまま使う
（設計書にrule_enforcement_logの並び替え仕様は無いため、原本順序を保持する）。
"""

from __future__ import annotations

RULE_ENFORCEMENT_COLUMNS = ["日付", "run_id", "ルール名", "適用有無", "詳細"]


def build_rule_enforcement_row(entry: dict, date_str: str, run_id: str) -> dict:
    return {
        "日付": date_str,
        "run_id": run_id,
        "ルール名": entry.get("rule"),
        "適用有無": entry.get("applied"),
        "詳細": entry.get("detail") if entry.get("detail") is not None else "",
    }


def rule_enforcement_row_as_list(row: dict) -> list:
    return [row.get(col) for col in RULE_ENFORCEMENT_COLUMNS]
