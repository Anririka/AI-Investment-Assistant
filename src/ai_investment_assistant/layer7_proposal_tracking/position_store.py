"""active_positions.json / closed_positions_YYYYMM.json の組み立てロジック
（layer7_proposal_tracking_design.md §6-2・§6-3）。

`active_positions.json`は直近1回分の`latest_price`のみを保持する薄いファイルとし、
日次の全価格履歴は持たせない（§6-2）。実際のGoogle Driveへの読み書きは
`drive_client.py`が担う。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


# 2026-07-26追加（実データ初回検証で発覚）：Google Sheets APIの`spreadsheets.values.get`
# はデフォルト（valueRenderOption=FORMATTED_VALUE）で数値セルも表示用文字列（例："2897"）
# として返すため、修正前のproposal_ingester.pyはこれらのフィールドを文字列のまま
# active_positions.jsonへ永続化していた実例がある。price_checker.py（entry_priceの
# 算術演算）・exit_evaluator.py（stop_loss_price/take_profit_priceの比較演算）・
# build_closed_position（下記、entry_priceの算術演算）はいずれも数値型を前提とするため、
# `unsupported operand type(s) for -: 'float' and 'str'`のようなTypeErrorになっていた。
NUMERIC_FLOAT_FIELDS = ("entry_price", "stop_loss_price", "take_profit_price")
NUMERIC_INT_FIELDS = ("recommended_shares",)


def _to_number(value, cast):
    """値そのもの（例：2897）は変えず、Python上の型表現（文字列→数値）のみを補正する。
    "値は一切変更しない"原則に対する例外ではなく、表示形式の変換として扱う
    （Layer6詳細設計書§5-1の「単位変換・丸め処理は表示形式の変換として許容する」と
    同じ考え方）。
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return cast(value)
    text = str(value).replace(",", "")
    # int("28.0")はValueErrorになるため、int変換は必ずfloat経由にする。
    return cast(float(text)) if cast is int else cast(text)


def normalize_position_numeric_fields(position: dict) -> dict:
    """`entry_price`等の数値フィールドが文字列で永続化されていた場合に数値へ補正する。

    新規取り込み分（proposal_ingester.py、修正済み）は既に正しい型で組み立てられる
    ため、この関数は実質的に何もしない（冪等）。Google Drive上に既に文字列のまま
    保存されてしまった過去のエントリを読み込むたびに適用することで、後続処理を
    安全にする。
    """
    updated = dict(position)
    for field in NUMERIC_FLOAT_FIELDS:
        if field in updated:
            updated[field] = _to_number(updated[field], float)
    for field in NUMERIC_INT_FIELDS:
        if field in updated:
            updated[field] = _to_number(updated[field], int)
    return updated


def build_closed_position(
    position: dict,
    exit_price: Optional[float],
    exit_date,
    exit_reason: str,
    closed_at: str,
) -> dict:
    """§6-3のclosed_positions_YYYYMM.jsonエントリを組み立てる。"""
    entry_date = _parse_date(position["entry_date"])
    exit_date_parsed = _parse_date(exit_date)
    holding_days = (exit_date_parsed - entry_date).days + 1

    entry_price = position["entry_price"]
    final_return_pct = (
        (exit_price - entry_price) / entry_price * 100 if (exit_price is not None and entry_price) else None
    )

    return {
        "tracking_id": position["tracking_id"],
        "run_id": position["run_id"],
        "ticker": position["ticker"],
        "name": position.get("name"),
        "entry_date": position["entry_date"],
        "entry_price": entry_price,
        "exit_date": exit_date_parsed.isoformat(),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_days": holding_days,
        "max_unrealized_gain_pct": position.get("max_unrealized_gain_pct", 0.0),
        "max_unrealized_loss_pct": position.get("max_unrealized_loss_pct", 0.0),
        "final_return_pct": final_return_pct,
        "recommended_shares": position.get("recommended_shares"),
        "closed_at": closed_at,
    }


def remove_position(positions: list, tracking_id: str) -> list:
    """`tracking_id`に一致するpositionをリストから除外した新しいリストを返す。"""
    return [p for p in positions if p["tracking_id"] != tracking_id]


def year_month_of(date_str) -> str:
    parsed = _parse_date(date_str)
    return f"{parsed.year:04d}{parsed.month:02d}"
