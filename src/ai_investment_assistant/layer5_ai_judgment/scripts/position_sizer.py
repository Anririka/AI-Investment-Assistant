"""推奨株数・損切価格・利確価格の確定計算（layer5_ai_judgment_design.md §8）。

LLMは「何を買うべきか・なぜか」を判断するが、「いくら・何株買うか」は必ずこの
モジュール（Python）が決定的に計算する（§0・§7の原則）。

算出式（§8をそのまま踏襲。total_capitalはconfig/capital_policy.yamlで確定した値を
そのまま使うことで、割合ベースのルール自体は変更せず、テスト期間中の縮小運用にも
恒久の300万円運用にも同じ計算式を適用できるようにする）：

    1銘柄あたり投資上限額 = total_capital × per_position_cap_pct(既定33%)
    投資可能な残余資金 = available_capital（他候補への配分を逐次消費した後の値）
    推奨株数(仮) = min(投資上限額 ÷ 購入価格, 残余資金 ÷ 購入価格)
    日本株: floor(仮/100)×100 に切り下げ。米国株等: floor(仮) に切り下げ。
    損切価格 = 購入価格 × (1 - stop_loss_pct(既定10%))
    利確価格 = 購入価格 × (1 + take_profit_target_pct/100)（範囲補正後の値を使う）
"""

from __future__ import annotations

import math
from typing import Optional

PER_POSITION_CAP_PCT = 0.33
STOP_LOSS_PCT = 0.10


def resolve_take_profit_target_pct(llm_value, policy: dict) -> tuple:
    """take_profit_target_pctの許容範囲チェック（§8）。

    戻り値: (採用する%, rule_enforcement_logエントリ or None)
    """
    min_pct = policy["min_pct"]
    max_pct = policy["max_pct"]
    default_pct = policy["default_pct"]

    if llm_value is None or not isinstance(llm_value, (int, float)) or isinstance(llm_value, bool):
        return default_pct, {
            "rule": "take_profit_target_pct_missing_or_invalid",
            "applied": True,
            "detail": f"LLMのtake_profit_target_pctが欠落・無効なため既定値{default_pct}%を適用",
        }

    if llm_value < min_pct or llm_value > max_pct:
        clamped = max(min_pct, min(max_pct, llm_value))
        return clamped, {
            "rule": "take_profit_target_pct_out_of_range",
            "applied": True,
            "detail": f"LLM値{llm_value}%は許容範囲[{min_pct}, {max_pct}]外のため{clamped}%へ補正",
        }

    return llm_value, None


def _floor_shares(raw_shares: float, asset_class: str) -> int:
    if raw_shares <= 0:
        return 0
    if asset_class == "japan_equity":
        return int(math.floor(raw_shares / 100.0)) * 100
    return int(math.floor(raw_shares))


def size_position(
    candidate: dict,
    available_capital: float,
    total_capital: float,
    take_profit_policy: dict,
    per_position_cap_pct: float = PER_POSITION_CAP_PCT,
    stop_loss_pct: float = STOP_LOSS_PCT,
) -> dict:
    """単一候補の推奨株数・損切/利確価格を確定計算する。

    `candidate`は最低限 ticker・asset_class・entry_price_basis（購入価格）を持ち、
    任意で take_profit_target_pct・take_profit_basis・reference_price_type・
    reference_price を持つ辞書（LLM出力のproposals要素相当）。

    戻り値: 0株になった場合は {"excluded": True, "reason_code": "INSUFFICIENT_FUNDS_ZERO_SHARES"}。
    それ以外は sizing結果 dict（recommended_shares・position_amount・stop_loss_price・
    take_profit_price・rule_enforcement_log_entries・remaining_available_capital 等）。
    """
    entry_price = candidate["entry_price_basis"]
    asset_class = candidate["asset_class"]

    per_position_cap = total_capital * per_position_cap_pct
    affordable_by_cap = per_position_cap / entry_price if entry_price else 0
    affordable_by_remaining = available_capital / entry_price if entry_price else 0
    raw_shares = min(affordable_by_cap, affordable_by_remaining)

    shares = _floor_shares(raw_shares, asset_class)

    if shares <= 0:
        return {
            "ticker": candidate["ticker"],
            "excluded": True,
            "reason_code": "INSUFFICIENT_FUNDS_ZERO_SHARES",
            "remaining_available_capital": available_capital,
        }

    position_amount = shares * entry_price
    stop_loss_price = entry_price * (1 - stop_loss_pct)

    tp_pct, tp_log_entry = resolve_take_profit_target_pct(
        candidate.get("take_profit_target_pct"), take_profit_policy
    )
    take_profit_price = entry_price * (1 + tp_pct / 100.0)

    rule_entries = []
    if tp_log_entry is not None:
        rule_entries.append({"ticker": candidate["ticker"], **tp_log_entry})

    return {
        "ticker": candidate["ticker"],
        "excluded": False,
        "recommended_shares": shares,
        "entry_price_basis": entry_price,
        "position_amount": position_amount,
        "stop_loss_price": stop_loss_price,
        "take_profit_target_pct": tp_pct,
        "take_profit_price": take_profit_price,
        "rule_enforcement_log_entries": rule_entries,
        "remaining_available_capital": available_capital - position_amount,
    }


def allocate_positions(
    candidates: list,
    available_capital: float,
    total_capital: float,
    take_profit_policy: dict,
) -> dict:
    """採用済み候補（最大3件、推奨順位順）を順に処理し、残余資金を逐次消費しながら
    配分する（§8「複数候補の同時配分」）。0株になった候補はproposalsに含めず、
    decision_logへnot_selected/INSUFFICIENT_FUNDS_ZERO_SHARESとして記録する。

    戻り値: {"proposals": [...], "decision_log_entries": [...], "rule_enforcement_log": [...]}
    """
    remaining = available_capital
    proposals = []
    decision_log_entries = []
    rule_enforcement_log = []

    for candidate in candidates:
        result = size_position(candidate, remaining, total_capital, take_profit_policy)
        if result["excluded"]:
            decision_log_entries.append({
                "ticker": result["ticker"],
                "decision": "not_selected",
                "reason_code": result["reason_code"],
                "reason": "position_sizer.pyの資金管理計算により、推奨株数が0株となったため除外",
            })
            continue

        remaining = result["remaining_available_capital"]
        rule_enforcement_log.extend(result["rule_enforcement_log_entries"])
        proposals.append({**candidate, **{
            "recommended_shares": result["recommended_shares"],
            "position_amount": result["position_amount"],
            "stop_loss_price": result["stop_loss_price"],
            "take_profit_target_pct": result["take_profit_target_pct"],
            "take_profit_price": result["take_profit_price"],
        }})

    return {
        "proposals": proposals,
        "decision_log_entries": decision_log_entries,
        "rule_enforcement_log": rule_enforcement_log,
    }
