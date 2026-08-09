"""取引記録_*.csvから現在の保有ポジション・残余投資可能資金を算出する
（layer5_ai_judgment_design.md §4-2）。

`load_portfolio_state.py`はGoogle Driveを直接読む専用のローダーであり、Layer1の
Repositoryパターンとは無関係（外部市場データではなくユーザー自身の取引記録であるため、
§4-2）。取引記録CSVの列は以下の通り（ユーザー提供のフォーマットに準拠）：

日付, 資産クラス, 銘柄名, 証券コード, 売買種別, 株数, 約定単価, 手数料, 為替レート,
損切りライン, 利確ライン, AI提案根拠要約, AI信頼度, 保有ステータス, 実現損益, メモ

「保有ステータス」が"保有中"の行のみを現在の保有ポジションとして集計する。
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

_CAPITAL_POLICY_PATH = Path(__file__).resolve().parents[4] / "config" / "capital_policy.yaml"
_SECTOR_MAPPING_PATH = Path(__file__).resolve().parents[4] / "config" / "sector_mapping.yaml"

HOLDING_STATUS = "保有中"

REQUIRED_COLUMNS = [
    "日付", "資産クラス", "銘柄名", "証券コード", "売買種別", "株数", "約定単価",
    "手数料", "為替レート", "損切りライン", "利確ライン", "AI提案根拠要約",
    "AI信頼度", "保有ステータス", "実現損益", "メモ",
]


class PortfolioStateError(Exception):
    """取引記録CSVが読み込めない・必須列が欠落している場合に送出する
    （reason_code: PORTFOLIO_STATE_INVALID、layer5_ai_judgment_design.md §10）。
    """


def load_capital_policy(config_path: Path = _CAPITAL_POLICY_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sector_mapping(config_path: Path = _SECTOR_MAPPING_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("sectors", {})


def resolve_total_capital(capital_policy: dict) -> float:
    """test_phase.enabledがtrueであれば、その値を投資可能資金として使う（人為的な
    上限であり、AIが自動調整するものではない。config/capital_policy.yaml参照）。
    そうでなければ恒久設計値（full_scale.total_capital）を使う。

    2026-08-09追記：当初test_phase.total_capitalは「投資可能資金の総額」を絞る設定
    として使っていたが、実際のユーザーの意図は「総額は300万円のままでよいが、
    1銘柄あたりの購入金額をしばらくの間25万円以下に抑えたい」というものだった
    （config/capital_policy.yamlの2026-08-09追記コメント参照）。そのため運用上は
    test_phase.enabledをfalseにし、1銘柄あたりの上限はresolve_absolute_per_position_cap()
    側で扱う。本関数自体のロジックは変更していない（将来、総額そのものを絞りたい
    正当な理由が生じた場合のために残す）。
    """
    test_phase = capital_policy.get("test_phase", {})
    if test_phase.get("enabled"):
        return float(test_phase["total_capital"])
    return float(capital_policy["full_scale"]["total_capital"])


def resolve_absolute_per_position_cap(capital_policy: dict) -> Optional[float]:
    """per_position_cap.enabledがtrueであれば、1銘柄あたりの購入金額の絶対額上限
    （円）を返す。無効、または設定自体が無い場合はNone（上限なし、from
    position_sizer.pyのtotal_capital×33%のみが適用される）を返す。

    2026-08-09追加（実運用で判明したユーザー意図とのズレの是正）：システム稼働直後の
    リスク低減のため、1銘柄あたりの購入金額を一時的に25万円以下へ抑えたいという
    ユーザーの意図を反映する。投資可能資金の総額（resolve_total_capital）とは独立した
    別軸の制約であり、両者を混同しないこと（config/capital_policy.yaml参照）。
    """
    cap = capital_policy.get("per_position_cap", {})
    if cap.get("enabled"):
        return float(cap["max_amount"])
    return None


def _to_float(value: Optional[str], default: float = 0.0) -> float:
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def parse_trade_record_csv(text: str) -> list:
    """取引記録CSVをパースし、行の辞書リストを返す。必須列が欠落していれば
    PortfolioStateErrorを送出する。
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise PortfolioStateError("取引記録CSVにヘッダー行がありません")
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise PortfolioStateError(f"取引記録CSVに必須列が欠落しています: {missing}")
    return list(reader)


def build_portfolio_state(
    rows: list,
    total_capital: float,
    sector_mapping: dict,
    as_of: str,
    absolute_per_position_cap: Optional[float] = None,
) -> dict:
    """保有中の行のみを対象に、保有ポジション・残余投資可能資金・セクター集中度を
    算出する（§4-2のportfolio_stateスキーマそのものを組み立てる）。

    `為替レート`は日本株では1.0（省略時も1.0扱い）、米国株等では円換算のためのレートと
    して扱い、`invested_amount`は常に円換算後の値とする（total_capitalが円建てのため）。

    `absolute_per_position_cap`（2026-08-09追加）：resolve_absolute_per_position_cap()の
    結果をそのまま返り値に含める（LLMがposition_sizer.allocate_positions()呼び出し時に
    そのまま渡せるようにするため）。Noneの場合は上限なし。
    """
    positions = []
    sector_concentration: dict = {}
    total_invested = 0.0

    for row in rows:
        if row.get("保有ステータス") != HOLDING_STATUS:
            continue

        ticker = row["証券コード"]
        asset_class = row["資産クラス"]
        shares = _to_float(row.get("株数"))
        entry_price = _to_float(row.get("約定単価"))
        fx_rate = _to_float(row.get("為替レート"), default=1.0) or 1.0

        invested_amount = shares * entry_price * fx_rate
        sector = sector_mapping.get(ticker, "unknown")

        positions.append({
            "ticker": ticker,
            "asset_class": asset_class,
            "sector": sector,
            "invested_amount": invested_amount,
            "entry_price": entry_price,
            "shares": shares,
        })

        total_invested += invested_amount
        sector_concentration[sector] = sector_concentration.get(sector, 0.0) + invested_amount

    return {
        "as_of": as_of,
        "total_capital": total_capital,
        "total_invested": total_invested,
        "available_capital": total_capital - total_invested,
        "positions": positions,
        "sector_concentration": sector_concentration,
        "absolute_per_position_cap": absolute_per_position_cap,
    }


def run_load_portfolio_state(
    drive_client,
    capital_policy: dict,
    sector_mapping: dict,
    as_of: Optional[datetime] = None,
    csv_subfolder: Optional[str] = None,
    csv_name_prefix: str = "取引記録_",
) -> dict:
    """load_portfolio_state.pyの本体処理。

    戻り値: {"status": "ok"|"blocked", "reason_code": Optional[str], "portfolio_state": Optional[dict]}
    """
    as_of = as_of or datetime.now(timezone.utc)
    latest = drive_client.read_latest_text_by_prefix(csv_subfolder, csv_name_prefix)

    total_capital = resolve_total_capital(capital_policy)
    absolute_per_position_cap = resolve_absolute_per_position_cap(capital_policy)

    if latest is None:
        # 取引記録ファイルが1件も無い＝新規稼働時等はポジション0件として正常に扱う
        # （ファイルが存在するのに読めない場合とは区別する）。
        portfolio_state = build_portfolio_state(
            [], total_capital, sector_mapping, as_of.isoformat().replace("+00:00", "Z"),
            absolute_per_position_cap=absolute_per_position_cap,
        )
        return {"status": "ok", "reason_code": None, "portfolio_state": portfolio_state}

    _file_name, text = latest
    try:
        rows = parse_trade_record_csv(text)
    except PortfolioStateError as exc:
        return {"status": "blocked", "reason_code": "PORTFOLIO_STATE_INVALID", "portfolio_state": None, "error": str(exc)}

    portfolio_state = build_portfolio_state(
        rows, total_capital, sector_mapping, as_of.isoformat().replace("+00:00", "Z"),
        absolute_per_position_cap=absolute_per_position_cap,
    )
    return {"status": "ok", "reason_code": None, "portfolio_state": portfolio_state}


def main() -> int:
    capital_policy = load_capital_policy()
    sector_mapping = load_sector_mapping()

    # LAYER5_LOCAL_DATA_DIRが設定されている場合、Google Drive MCPコネクタ経由で
    # エージェントが既に取得済みのローカルファイルを読む（local_drive_client.py参照）。
    local_data_dir = os.environ.get("LAYER5_LOCAL_DATA_DIR")
    if local_data_dir:
        from .local_drive_client import LocalDriveClient

        client = LocalDriveClient(base_dir=local_data_dir)
    else:
        from .drive_client import Layer5DriveClient

        oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", "")
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
        if not oauth_token_json or not folder_id:
            print(json.dumps({"status": "blocked", "reason_code": "PORTFOLIO_STATE_INVALID",
                               "error": "LAYER5_LOCAL_DATA_DIR、または"
                               "GOOGLE_OAUTH_TOKEN_JSON/GOOGLE_DRIVE_FOLDER_IDが未設定"}))
            return 1
        client = Layer5DriveClient(oauth_token_json=oauth_token_json, root_folder_id=folder_id)

    result = run_load_portfolio_state(client, capital_policy, sector_mapping)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
