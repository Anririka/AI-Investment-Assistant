"""Layer6 Google Sheets「本日の提案」シートから新規追跡対象を取り込む
（layer7_proposal_tracking_design.md §4手順2・§5-1・§6-2）。

読み取り専用（§2非責務）：Layer6が保存した値は一切変更せずそのまま転記する。
既に`active_positions.json`に登録済みの`run_id`＋`ticker`の組み合わせはスキップする
（重複取り込み防止、§9）。
"""

from __future__ import annotations

from typing import Optional, Tuple

from .holding_period_parser import parse_holding_period_days
from .repository.price_check_repository_impl import infer_asset_class

# Layer6詳細設計書§6-3の列構成のうち、Layer7が利用する9列（§5-1）。
REQUIRED_SHEET_COLUMNS = [
    "run_id", "日付", "証券コード", "銘柄名", "購入価格目安", "損切価格", "利確価格",
    "想定保有期間", "推奨株数",
]


def build_tracking_id(run_id: str, ticker: str) -> str:
    return f"TRK-{run_id}-{ticker}"


def _existing_keys(existing_positions: list) -> set:
    return {(p["run_id"], p["ticker"]) for p in existing_positions}


def ingest_new_positions(
    sheet_rows: list,
    existing_positions: list,
    unit_days: dict,
    fallback_default_days: int,
) -> Tuple[list, list]:
    """新規追跡対象を組み立てる。

    `sheet_rows`はLayer6の「本日の提案」シートの各行（{列名: 値}の辞書、§6-3の列名の
    まま）。戻り値: (新規position辞書のリスト, スキップされた重複キーのリスト)。
    """
    existing = _existing_keys(existing_positions)
    new_positions = []
    skipped = []

    for row in sheet_rows:
        run_id = row["run_id"]
        ticker = row["証券コード"]
        key = (run_id, ticker)
        if key in existing:
            skipped.append(key)
            continue

        holding_period_raw = row.get("想定保有期間")
        days, parse_status = parse_holding_period_days(holding_period_raw, unit_days, fallback_default_days)

        new_positions.append({
            "tracking_id": build_tracking_id(run_id, ticker),
            "run_id": run_id,
            "ticker": ticker,
            "name": row.get("銘柄名"),
            "asset_class": row.get("資産クラス") or infer_asset_class(ticker),
            "entry_date": row.get("日付"),
            "entry_price": row.get("購入価格目安"),
            "stop_loss_price": row.get("損切価格"),
            "take_profit_price": row.get("利確価格"),
            "holding_period_raw": holding_period_raw,
            "holding_period_days_parsed": days,
            "parse_status": parse_status,
            "recommended_shares": row.get("推奨株数"),
            "status": "active",
            "latest_price": None,
            "max_unrealized_gain_pct": 0.0,
            "max_unrealized_loss_pct": 0.0,
            "last_checked_at": None,
        })
        existing.add(key)

    return new_positions, skipped
