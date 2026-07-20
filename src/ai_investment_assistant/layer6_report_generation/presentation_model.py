"""decision JSON → PresentationModel（表示専用モデル）への変換
（layer6_report_generation_design.md §2・§3・§5-1）。

**絶対原則（§5-1）**：値の意味・数値・文字列を一切変更しない。許されるのは表示順序の
整列（例：`proposals`を`rank`昇順に並べる）のみであり、`rank`・スコア等の値そのものを
書き換えることは禁止する。`decision_log`・`rule_enforcement_log`の並び替えは、それぞれの
formatterの責務（§8・§9）であり、ここでは行わない（PresentationModelは変換の起点であり、
表示順序の最終決定は各formatterに委ねる）。
"""

from __future__ import annotations


def build_presentation_model(decision_document: dict) -> dict:
    """Layer5のdecision JSON（§9スキーマ）をPresentationModelへ変換する。

    現時点でのPresentationModelの実体は、`proposals`を`rank`昇順に整列した上で
    トップレベル4キーをそのまま保持する辞書である（値は一切変更しない）。
    """
    run_meta = decision_document["run_meta"]
    proposals = sorted(decision_document.get("proposals", []), key=lambda p: p["rank"])
    decision_log = decision_document.get("decision_log", [])
    rule_enforcement_log = decision_document.get("rule_enforcement_log", [])

    return {
        "run_meta": run_meta,
        "proposals": proposals,
        "decision_log": decision_log,
        "rule_enforcement_log": rule_enforcement_log,
    }
