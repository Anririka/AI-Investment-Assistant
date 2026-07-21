"""evaluation/evaluation_index.json（評価済みtracking_idの横断インデックス）の
読み書き・増分判定（layer8_self_evaluation_design.md §4-1）。

月次分割された`position_evaluations_YYYYMM.json`を毎回横断検索することはせず、
この軽量インデックスのみを増分判定の唯一の根拠とする。
"""

from __future__ import annotations

from typing import Iterable


def evaluated_ids_set(index_doc: dict) -> set:
    return set(index_doc.get("evaluated_tracking_ids", []))


def merge_evaluated_ids(index_doc: dict, new_tracking_ids: Iterable) -> dict:
    """既存のインデックスに新規評価済みtracking_idを重複なく追記する。

    §6のトランザクション原則により、この関数（＝evaluation_index.jsonの更新）は
    他の3ファイル（position_evaluations／segment_stats／feedback）の保存が
    すべて成功した後の最終ステップとしてのみ呼び出すこと。
    """
    existing = evaluated_ids_set(index_doc)
    updated = existing | set(new_tracking_ids)
    return {"evaluated_tracking_ids": sorted(updated)}
