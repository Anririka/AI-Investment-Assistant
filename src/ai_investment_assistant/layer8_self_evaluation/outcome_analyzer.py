"""勝率・平均利益率/損失率・Profit Factor等の算出（layer8_self_evaluation_design.md §7-1）。"""

from __future__ import annotations

from typing import Optional, Tuple

from . import reason_code_extractor
from .score_context_loader import find_score_context


def classify_outcome(final_return_pct: float) -> str:
    """`final_return_pct > 0`を"win"、以下を"loss"とする（`exit_reason`ではなく実際の
    損益率の符号で判定する。§7-1）。
    """
    return "win" if final_return_pct > 0 else "loss"


def compute_pnl_amount(entry_price: float, exit_price: float, recommended_shares: float) -> float:
    return (exit_price - entry_price) * recommended_shares


def build_evaluation_entry(closed_position: dict, sheet_rows: Optional[list]) -> dict:
    """§6-1のposition_evaluations_YYYYMM.jsonエントリを組み立てる。

    `sheet_rows`はLayer6「本日の提案」シートの行（Noneの場合はシート自体が見つからな
    かったことを意味し、`score_context_available: false`として記録する、§5-3）。
    """
    entry_price = closed_position["entry_price"]
    exit_price = closed_position["exit_price"]
    recommended_shares = closed_position.get("recommended_shares", 0)
    final_return_pct = closed_position["final_return_pct"]

    pnl_amount = compute_pnl_amount(entry_price, exit_price, recommended_shares)
    outcome = classify_outcome(final_return_pct)

    score_context = find_score_context(sheet_rows, closed_position["ticker"])

    evaluation = {
        "tracking_id": closed_position["tracking_id"],
        "run_id": closed_position["run_id"],
        "ticker": closed_position["ticker"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "recommended_shares": recommended_shares,
        "holding_days": closed_position["holding_days"],
        "exit_reason": closed_position["exit_reason"],
        "final_return_pct": final_return_pct,
        "pnl_amount": pnl_amount,
        "outcome": outcome,
        "max_unrealized_gain_pct": closed_position.get("max_unrealized_gain_pct"),
        "max_unrealized_loss_pct": closed_position.get("max_unrealized_loss_pct"),
        "score_context_available": score_context is not None,
    }

    if score_context is not None:
        investment_reason = score_context.get("investment_reason")
        codes, status = reason_code_extractor.extract_reason_codes(investment_reason)
        evaluation["score_summary"] = score_context["score_summary"]
        evaluation["extracted_reason_codes"] = codes
        evaluation["reason_code_extraction_status"] = status
        evaluation["asset_class"] = score_context.get("asset_class")
    else:
        evaluation["score_summary"] = None
        evaluation["extracted_reason_codes"] = []
        evaluation["reason_code_extraction_status"] = "no_match"
        evaluation["asset_class"] = None

    return evaluation


def compute_profit_factor(evaluations: list) -> Tuple[Optional[float], Optional[str]]:
    """§7-1のProfit Factor算出（ゼロ除算の扱いを含む）。戻り値: (値, note)。"""
    total_gain = sum(e["pnl_amount"] for e in evaluations if e["pnl_amount"] > 0)
    total_loss = abs(sum(e["pnl_amount"] for e in evaluations if e["pnl_amount"] < 0))

    if total_loss > 0:
        return total_gain / total_loss, None
    if total_gain > 0 and total_loss == 0:
        return None, "全勝のため算出不能（損失0）"
    if total_gain == 0 and total_loss > 0:
        return 0.0, None
    return None, "クローズ済みポジションが無いため算出不能"


def compute_overall_stats(evaluations: list) -> dict:
    """§7-1の基本統計一式を算出する。"""
    total = len(evaluations)
    if total == 0:
        profit_factor, note = compute_profit_factor([])
        return {
            "win_rate": None, "avg_win_pct": None, "avg_loss_pct": None,
            "profit_factor": profit_factor, "profit_factor_note": note,
            "take_profit_rate": None, "stop_loss_rate": None,
        }

    wins = [e for e in evaluations if e["outcome"] == "win"]
    losses = [e for e in evaluations if e["outcome"] == "loss"]
    take_profits = [e for e in evaluations if e["exit_reason"] == "take_profit"]
    stop_losses = [e for e in evaluations if e["exit_reason"] == "stop_loss"]

    win_rate = len(wins) / total
    avg_win_pct = sum(e["final_return_pct"] for e in wins) / len(wins) if wins else None
    avg_loss_pct = sum(e["final_return_pct"] for e in losses) / len(losses) if losses else None
    profit_factor, note = compute_profit_factor(evaluations)

    return {
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "profit_factor": profit_factor,
        "profit_factor_note": note,
        "take_profit_rate": len(take_profits) / total,
        "stop_loss_rate": len(stop_losses) / total,
    }
