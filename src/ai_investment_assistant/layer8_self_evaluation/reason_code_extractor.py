"""investment_reasonからreason_codeパターンを抽出する（ベストエフォート、
layer8_self_evaluation_design.md §7-4）。

`investment_reason`は自然文であり、reason_codeの言及は必須フォーマットではないため、
100%の網羅性・正確性は保証しない。抽出できなかった場合は無理に推測せず
`extracted_reason_codes: []`・`reason_code_extraction_status: "no_match"`とする。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

_PATTERN = re.compile(r"\b(?:TECH|FUND|SUPD|MACRO|NEWS|REGIME)_[A-Z0-9_]+\b")


def extract_reason_codes(investment_reason: Optional[str]) -> Tuple[list, str]:
    """戻り値: (抽出されたreason_codeのリスト（出現順・重複排除）, status)。

    statusは"success"（1件以上抽出できた）または"no_match"。
    """
    if not investment_reason:
        return [], "no_match"

    matches = _PATTERN.findall(investment_reason)
    if not matches:
        return [], "no_match"

    seen = []
    for code in matches:
        if code not in seen:
            seen.append(code)
    return seen, "success"
