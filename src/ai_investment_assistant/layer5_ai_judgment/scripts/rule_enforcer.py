"""LLM判断結果へのハードルール機械的強制（layer5_ai_judgment_design.md §7・§7-1）。

- 信頼度50未満の"buy"提案は、様子見（hold）へ強制変更する（§7・多層防御の安全網）。
- 1日の新規提案（"buy"）が3件を超える場合、以下の優先順位で上位3件のみ採用する（§7-1、確定）：
    1. Layer2 preliminary_quant_rank（最優先）
    2. composite_score（同点タイブレーク）
    3. LLM confidence
    4. LLMが提示した推奨順位（最終タイブレークのみ）
  ただし、LLMが「ポートフォリオ集中リスク」等の理由で明示的に不採用と判断した候補は、
  その判断をそのまま尊重する（rule_enforcer.pyはLLMが"buy"として残した集合に対しての
  み絞り込みを行い、LLMが除外した候補を復活させることはしない）。

- セクター集中度の警告（2026-08-12追加、§7-2）：2026-08-12に、既存保有の商船三井(9104)と
  同一セクター（海運）の日本郵船(9101)がセクター重複を一切考慮されずに新規提案された
  実例が発生した。原因はconfig/sector_mapping.yamlがプレースホルダーのままだったことに
  加え、そもそもセクター集中の考慮がLLMへの「配慮してください」という非機械的な指示
  （プロンプトのみ）に依存していたことだった。ユーザーとの合意（2026-08-12）により、
  「同一セクターの銘柄を自動的に除外する」のではなく「機械的に検知してログに警告として
  記録し、採用するかどうかの最終判断はユーザー自身が行う」方針とする。理由：セクターを
  跨いだ買い増しが常に不適切とは限らず（強い確信があれば意図的な同一セクター追加も
  あり得るため）、確信度ゲート・日次上限と同様「機械的に見落とさない」ことを目的とする。
"""

from __future__ import annotations

from typing import Optional

MIN_CONFIDENCE = 50
MAX_DAILY_PROPOSALS = 3


def apply_confidence_gate(candidates: list, min_confidence: int = MIN_CONFIDENCE) -> tuple:
    """"buy"提案のうちconfidence<min_confidenceのものを"hold"へ強制変更する。

    `candidates`はLLM出力（overall_assessment・confidence等を持つ辞書）のリスト。
    戻り値: (更新後のcandidatesリスト, rule_enforcement_logエントリ1件)
    """
    updated = []
    downgraded_tickers = []

    for c in candidates:
        if c.get("overall_assessment") == "buy" and c.get("confidence", 0) < min_confidence:
            updated.append({**c, "overall_assessment": "hold", "confidence_gate_forced": True})
            downgraded_tickers.append(c["ticker"])
        else:
            updated.append(c)

    log_entry = {
        "rule": "confidence_gate",
        "applied": bool(downgraded_tickers),
    }
    if downgraded_tickers:
        log_entry["detail"] = (
            f"信頼度{min_confidence}未満のため様子見へ強制変更: {downgraded_tickers}"
        )

    return updated, log_entry


def _priority_key(candidate: dict) -> tuple:
    """§7-1の優先順位に基づくソートキー（昇順ソートで優先度の高い順に並ぶよう設計）。"""
    preliminary_quant_rank = candidate.get("preliminary_quant_rank", float("inf"))
    composite_score = candidate.get("composite_score", float("-inf"))
    confidence = candidate.get("confidence", float("-inf"))
    llm_rank = candidate.get("rank", float("inf"))
    return (preliminary_quant_rank, -composite_score, -confidence, llm_rank)


def enforce_daily_limit(buy_candidates: list, max_per_day: int = MAX_DAILY_PROPOSALS) -> tuple:
    """LLMが"buy"と判断した候補のうち、3件を超える場合に§7-1の優先順位で上位3件に絞り込む。

    LLMが明示的に除外した候補（この関数に渡す前段でLLMが"buy"以外とした候補）は
    この関数の対象外であり、ここで復活することは無い（呼び出し側で"buy"のみを渡すこと）。

    戻り値: (adopted候補のリスト, not_selectedとなった候補のdecision_logエントリのリスト,
             rule_enforcement_logエントリ1件)
    """
    if len(buy_candidates) <= max_per_day:
        return list(buy_candidates), [], {"rule": "daily_proposal_limit", "applied": False}

    ordered = sorted(buy_candidates, key=_priority_key)
    adopted = ordered[:max_per_day]
    dropped = ordered[max_per_day:]

    not_selected_entries = [
        {
            "ticker": c["ticker"],
            "decision": "not_selected",
            "rank": c.get("rank"),
            "reason_code": "DAILY_PROPOSAL_LIMIT_EXCEEDED",
            "reason": (
                "LLMは買い候補としたが、preliminary_quant_rank→composite_score→confidence→"
                "LLM推奨順位の優先順位（§7-1）に基づき、1日の新規提案上限3件の対象外となった。"
                "LLMによる除外ではなくPython側の機械的判定である。"
            ),
        }
        for c in dropped
    ]

    log_entry = {
        "rule": "daily_proposal_limit",
        "applied": True,
        "detail": (
            f"LLMは{len(buy_candidates)}件を買い推奨としたが、§7-1の優先順位に基づき"
            f"上位{max_per_day}件に調整（対象外: {[c['ticker'] for c in dropped]}）"
        ),
    }

    return adopted, not_selected_entries, log_entry


def check_sector_concentration_warning(
    adopted_candidates: list,
    portfolio_positions: list,
    sector_mapping: dict,
) -> dict:
    """採用済み（enforce_daily_limit適用後）の買い提案について、(a)既存保有ポジション、
    (b)同日の他の採用提案、のいずれかと同一セクターの銘柄が無いかを機械的にチェックする
    （§7-2、2026-08-12追加）。

    自動除外・信頼度変更・提案順位の変更は一切行わない。あくまで「見落とし防止の警告
    ログ」であり、同一セクター銘柄を採用するかどうかの最終判断はユーザー自身が行う
    （2026-08-12ユーザー明示合意）。sectorが"unknown"の銘柄同士は、実際に同一セクター
    かどうか不明であり誤検知の元となるため、比較対象から除外する。

    `adopted_candidates`は{"ticker": str, ...}を持つ辞書のリスト（enforce_daily_limit後の
    採用済み候補）。`portfolio_positions`はportfolio_state["positions"]（各要素は
    {"ticker": str, "sector": str, ...}）。`sector_mapping`はticker→sector名の辞書
    （config/sector_mapping.yamlの`sectors`）。

    戻り値: rule_enforcement_logエントリ1件
        {"rule": "sector_concentration_warning", "applied": bool, "detail": Optional[str]}
    """
    adopted_sector_by_ticker = {
        c["ticker"]: sector_mapping.get(c["ticker"], "unknown") for c in adopted_candidates
    }
    held_sector_by_ticker = {
        p["ticker"]: p.get("sector", "unknown") for p in portfolio_positions
    }

    warnings = []
    for ticker, sector in adopted_sector_by_ticker.items():
        if sector == "unknown":
            continue

        overlapping_held = sorted(
            t for t, s in held_sector_by_ticker.items() if s == sector and t != ticker
        )
        overlapping_same_day = sorted(
            t for t, s in adopted_sector_by_ticker.items() if s == sector and t != ticker
        )

        if not overlapping_held and not overlapping_same_day:
            continue

        parts = []
        if overlapping_held:
            parts.append(f"既存保有({'、'.join(overlapping_held)})")
        if overlapping_same_day:
            parts.append(f"同日の他の採用提案({'、'.join(overlapping_same_day)})")
        warnings.append(f"{ticker}（{sector}）が{'・'.join(parts)}とセクター重複")

    log_entry = {
        "rule": "sector_concentration_warning",
        "applied": bool(warnings),
    }
    if warnings:
        log_entry["detail"] = "; ".join(warnings)

    return log_entry
