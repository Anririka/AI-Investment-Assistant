"""decision_logの整形（layer6_report_generation_design.md §8）。

`decision_log`の全件を省略せず表示する（Ver2「AI判断ログの完全保存」要件、§8）。
表示順序の並び替え（`decision`種別→`rank`昇順→`ticker`昇順）は整列であり、値そのものは
一切変更しない（§5-1）。`reason`が存在しない場合は空欄とし、推測的な補完はしない。
"""

from __future__ import annotations

_DECISION_ORDER = {"rejected": 0, "not_selected": 1, "adopted": 2}


def _sort_key(entry: dict) -> tuple:
    decision_rank = _DECISION_ORDER.get(entry.get("decision"), len(_DECISION_ORDER))
    rank = entry.get("rank")
    has_rank = 0 if rank is not None else 1
    rank_value = rank if rank is not None else 0
    ticker = entry.get("ticker", "")
    return (decision_rank, has_rank, rank_value, ticker)


def sort_decision_log(decision_log: list) -> list:
    """§8の表示順序（rejected→not_selected、同一種別内はrank昇順、rank無しはticker昇順）
    へ並び替える。値そのものは変更しない（新しいリストを返すのみで各要素は同一オブジェクト）。

    注：`adopted`のエントリも含めて全件を扱う（Sheets/Markdownの「除外・不採用ログ」側の
    表示では呼び出し側が`decision != "adopted"`でフィルタする、§6-4）。
    """
    return sorted(decision_log, key=_sort_key)


def build_excluded_log_row(entry: dict, date_str: str, run_id: str) -> dict:
    """「除外・不採用ログ」シート／Markdownテーブルの1行分（§6-4）。"""
    return {
        "日付": date_str,
        "run_id": run_id,
        "証券コード": entry.get("ticker"),
        "判定": entry.get("decision"),
        "順位": entry.get("rank") if entry.get("rank") is not None else "",
        "理由コード": entry.get("reason_code"),
        "理由": entry.get("reason") if entry.get("reason") is not None else "",
    }


EXCLUDED_LOG_COLUMNS = ["日付", "run_id", "証券コード", "判定", "順位", "理由コード", "理由"]


def excluded_log_row_as_list(row: dict) -> list:
    return [row.get(col) for col in EXCLUDED_LOG_COLUMNS]


def build_excluded_candidates_for_display(decision_log: list) -> list:
    """`adopted`以外の全件を、§8の表示順序で返す（採用済みは別セクション/シートで表示済みのため
    ここには含めない）。
    """
    non_adopted = [e for e in decision_log if e.get("decision") != "adopted"]
    return sort_decision_log(non_adopted)
