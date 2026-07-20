"""重要度のルールベース補正（layer3_news_processing_design.md §4-2、新設）。

決算・M&A・FOMC等の重大イベントカテゴリについて、LLMの出力を上書きするのではなく
下限（フロア）を設ける補正を適用する。補正の事実は隠蔽せず記録する（§8）。
"""

from __future__ import annotations


def apply_importance_floor(llm_importance: int, category: str, config: dict) -> dict:
    """`final_importance = max(llm_importance, category_importance_floor.get(category, default_floor))`。

    戻り値: {"importance": 最終値, "importance_llm_raw": LLMの元の値, "importance_source": "llm"|"rule_floor_applied"}
    """
    floor_map = config.get("category_importance_floor", {})
    default_floor = config.get("default_floor", 0)
    floor = floor_map.get(category, default_floor)

    final_importance = max(llm_importance, floor)
    source = "rule_floor_applied" if final_importance > llm_importance else "llm"

    return {
        "importance": final_importance,
        "importance_llm_raw": llm_importance,
        "importance_source": source,
    }
