"""評価データの読み書き（layer8_self_evaluation_design.md §6）。

`position_evaluations_YYYYMM.json`は、同一`tracking_id`の既存エントリを検出したら
上書きする形にし、単純な追記による重複レコード化を避ける（§6：二重評価が起きても
実害は軽微、という設計原則を支える）。
"""

from __future__ import annotations


def year_month_of_run_id(run_id: str) -> str:
    """run_id（例："20260718-0630"）からYYYYMM（"202607"）を導出する。"""
    date_part = run_id[:8]
    return date_part[:6]


def merge_position_evaluations(existing_doc: dict, new_evaluations: list) -> dict:
    """既存のposition_evaluations_YYYYMM.jsonへ、新規評価を上書き（同一tracking_id）
    またはなければ追加する形でマージする。
    """
    existing = existing_doc.get("evaluations", [])
    by_id = {e["tracking_id"]: e for e in existing}
    for evaluation in new_evaluations:
        by_id[evaluation["tracking_id"]] = evaluation
    return {"evaluations": list(by_id.values())}
