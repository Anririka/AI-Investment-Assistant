"""「想定保有期間」文字列を日数へ変換する（layer7_proposal_tracking_design.md §8-3）。

Layer5が出力する`holding_period`は自然文（例：「2〜4週間」「1ヶ月程度」）であり、厳密な
日数ではないため、機械的なパースルールで日数へ変換する。パース失敗時は
`fallback_default_days`を採用し、`parse_status: "fallback_used"`として記録する
（隠蔽しない、§9のエラー処理）。
"""

from __future__ import annotations

import re
from typing import Tuple


def parse_holding_period_days(text: str, unit_days: dict, fallback_default_days: int) -> Tuple[int, str]:
    """`text`から日数を機械的に算出する。戻り値: (日数, parse_status)。

    parse_rule（§8-3）：文字列内の数値をすべて抽出し最大値を採用する。抽出した数値に
    対応する単位（文字列中に出現する単位語のうち最長一致するもの）を掛けて日数を算出する。
    例：「2〜4週間」→ 4×7 = 28日。
    """
    if not text:
        return fallback_default_days, "fallback_used"

    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers:
        return fallback_default_days, "fallback_used"
    max_number = max(float(n) for n in numbers)

    matched_unit = None
    for unit in sorted(unit_days.keys(), key=len, reverse=True):
        if unit in text:
            matched_unit = unit
            break

    if matched_unit is None:
        return fallback_default_days, "fallback_used"

    days = int(round(max_number * unit_days[matched_unit]))
    return days, "parsed"
