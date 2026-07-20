"""候補一覧・スコア・リスク説明の整形（layer6_report_generation_design.md §6-3・§7-1）。

`proposals[]`の値をそのまま転記するのみで、意味の解釈・再計算は一切行わない（§5-1）。
"""

from __future__ import annotations

from typing import Optional

# §6-3の列順そのまま。
SHEET_COLUMNS = [
    "日付", "run_id", "推奨順位", "資産クラス", "銘柄名", "証券コード", "総合評価",
    "推奨株数", "購入価格目安", "投資金額", "損切価格", "利確価格", "利確目標騰落率(%)",
    "想定リターン(%)", "想定損失(%)", "リスクリワード比", "想定保有期間", "信頼度",
    "投資理由", "リスク要因", "テクニカルスコア", "ファンダメンタルスコア", "需給スコア",
    "マクロスコア", "ニューススコア", "ニュース不確実性", "レジーム適合スコア",
    "総合スコア", "代替候補",
]


def build_proposal_sheet_row(proposal: dict, date_str: str, run_id: str) -> dict:
    """「本日の提案」シートの1行分を、§6-3の列構成に沿った{列名: 値}の辞書として返す。"""
    score_summary = proposal.get("score_summary", {})
    news = score_summary.get("news", {})
    alternative_candidates = proposal.get("alternative_candidates", [])

    values = {
        "日付": date_str,
        "run_id": run_id,
        "推奨順位": proposal.get("rank"),
        "資産クラス": proposal.get("asset_class"),
        "銘柄名": proposal.get("name"),
        "証券コード": proposal.get("ticker"),
        "総合評価": proposal.get("overall_assessment"),
        "推奨株数": proposal.get("recommended_shares"),
        "購入価格目安": proposal.get("entry_price_basis"),
        "投資金額": proposal.get("position_amount"),
        "損切価格": proposal.get("stop_loss_price"),
        "利確価格": proposal.get("take_profit_price"),
        "利確目標騰落率(%)": proposal.get("take_profit_target_pct"),
        "想定リターン(%)": proposal.get("expected_return_pct"),
        "想定損失(%)": proposal.get("expected_loss_pct"),
        "リスクリワード比": proposal.get("risk_reward_ratio"),
        "想定保有期間": proposal.get("holding_period"),
        "信頼度": proposal.get("confidence"),
        "投資理由": proposal.get("investment_reason"),
        "リスク要因": proposal.get("risk_factors"),
        "テクニカルスコア": score_summary.get("technical"),
        "ファンダメンタルスコア": score_summary.get("fundamental"),
        "需給スコア": score_summary.get("supply_demand"),
        "マクロスコア": score_summary.get("macro"),
        "ニューススコア": news.get("score"),
        "ニュース不確実性": news.get("uncertainty"),
        "レジーム適合スコア": score_summary.get("regime_fit"),
        "総合スコア": score_summary.get("composite"),
        "代替候補": ", ".join(alternative_candidates) if alternative_candidates else "",
    }
    return values


def sheet_row_as_list(row: dict) -> list:
    """§6-3の列順（SHEET_COLUMNS）通りの値のリストに変換する（Sheets書き込み用）。"""
    return [row.get(col) for col in SHEET_COLUMNS]


def format_proposal_markdown(proposal: dict) -> str:
    """§7-1のMarkdownテンプレートに沿った、1候補分のMarkdownブロックを生成する。"""
    score_summary = proposal.get("score_summary", {})
    news = score_summary.get("news", {})
    alternative_candidates = proposal.get("alternative_candidates", [])
    alt_str = ", ".join(alternative_candidates) if alternative_candidates else "（なし）"

    lines = [
        f"### 第{proposal.get('rank')}位：{proposal.get('name')}（{proposal.get('ticker')}／{proposal.get('asset_class')}）",
        "",
        f"【総合評価】{proposal.get('overall_assessment')}",
        f"【推奨株数】{proposal.get('recommended_shares')}",
        f"【購入価格目安】{proposal.get('entry_price_basis')}",
        f"【損切価格】{proposal.get('stop_loss_price')}",
        f"【利確価格】{proposal.get('take_profit_price')}"
        f"（目標騰落率 {proposal.get('take_profit_target_pct')}%、"
        f"根拠：{proposal.get('take_profit_basis', '（記載なし）')}）",
        f"【想定リターン】{proposal.get('expected_return_pct')}%　"
        f"【想定損失】{proposal.get('expected_loss_pct')}%　"
        f"【リスクリワード比】{proposal.get('risk_reward_ratio')}",
        f"【想定保有期間】{proposal.get('holding_period')}",
        f"【信頼度】{proposal.get('confidence')}",
        "【投資理由】",
        f"{proposal.get('investment_reason')}",
        "【リスク要因】",
        f"{proposal.get('risk_factors')}",
        "【スコア内訳】",
        "",
        "| 評価軸 | スコア |",
        "|---|---|",
        f"| テクニカル | {score_summary.get('technical')} |",
        f"| ファンダメンタル | {score_summary.get('fundamental')} |",
        f"| 需給 | {score_summary.get('supply_demand')} |",
        f"| マクロ | {score_summary.get('macro')} |",
        f"| ニュース | {news.get('score')}（不確実性: {news.get('uncertainty')}） |",
        f"| 市場レジーム適合 | {score_summary.get('regime_fit')} |",
        f"| **総合** | **{score_summary.get('composite')}** |",
        "",
        f"【代替候補】{alt_str}",
    ]
    return "\n".join(lines)
