"""スコア順・順位付け（layer2_analysis_design.md §3-9、新設）。

入力：`scorer.py`が算出した全候補（母集団フィルタを通過した全件）の候補辞書
（`asset_class`・`composite_score.total`を含む）。
処理：資産クラスごとに総合スコアの降順で並び替え、`preliminary_quant_rank`を付与する。
出力：資産クラスごとに順位付けされた**全候補**のリスト（この時点では件数の絞り込みは
行わない、§3-9）。
"""

from __future__ import annotations

from collections import defaultdict


def rank_candidates(candidates: list) -> list:
    """資産クラスごとに総合スコア降順で並び替え、`preliminary_quant_rank`を付与する。"""
    by_asset_class = defaultdict(list)
    for c in candidates:
        by_asset_class[c["asset_class"]].append(c)

    ranked: list = []
    for group in by_asset_class.values():
        sorted_group = sorted(group, key=lambda c: c["composite_score"]["total"], reverse=True)
        for rank, c in enumerate(sorted_group, start=1):
            c["preliminary_quant_rank"] = rank
            ranked.append(c)
    return ranked
