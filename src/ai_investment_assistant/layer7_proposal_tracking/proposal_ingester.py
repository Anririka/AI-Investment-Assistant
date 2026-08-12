"""Layer6 Google Sheets「本日の提案」シートから新規追跡対象を取り込む
（layer7_proposal_tracking_design.md §4手順2・§5-1・§6-2）。

読み取り専用（§2非責務）：Layer6が保存した値は一切変更せずそのまま転記する。
既に`active_positions.json`に登録済みの`run_id`＋`ticker`の組み合わせはスキップする
（重複取り込み防止、§9）。

2026-08-09追加（実運用で発覚した設計ギャップ対応）：本モジュールは従来、「本日の提案」
シートに載った提案を、ユーザーが実際に購入したかどうかの確認手段なしに、全件「約定済み」
として無条件に取り込んでいた（購入価格目安をそのまま実際の取得価格として記録）。実運用で
「3件提案されたうち1件は買わなかった」というケースが発生し、この確認手段の不在が実害
（買っていない銘柄が架空のポジションとして追跡され続ける）に直結することが判明した。
`purchase_confirmations`（任意引数、tracking/配下の`purchase_confirmations_YYYYMMDD.json`
から読み込む想定、証券コードをキーとする辞書）により、銘柄ごとに「実際に購入したか」
「実際の約定価格・株数（提案と異なる場合）」を上書きできるようにする。

2026-08-12追記（重大バグ再発・既定動作の反転）：上記の初回対応は「confirmationファイルが
存在しない、または該当銘柄のエントリが無い場合は、従来通り『提案＝約定済み』として扱う
（後方互換）」という設計だった。しかし、confirmationファイルの提出はユーザーが購入した
「その日のうちに」行う必要があり、実運用では購入報告が翌日以降になることが多く、結果的に
ほぼ毎日「未購入の提案がphantomポジションとして自動追跡される」事故が繰り返し発生した
（2026-08-11・8-12提案分で、日本郵船・HPQ・電通グループ等の未購入銘柄、およびSBUX・
三井化学の重複ポジションが実際に発生し、手動でのDriveデータ復旧が必要になった）。

この経緯を踏まえ、既定動作を反転する：**confirmationファイルが存在しない、または該当
銘柄のエントリが無い、またはエントリはあるが`purchased`が明示的に`True`でない場合は、
「購入していない」ものとして扱い、取り込みを見送る**（旧仕様の完全な反転。後方互換は
もう維持しない）。取り込みには`purchased: true`の明示が必須となる。

この変更により、確認ファイルが用意されていない日は何も自動追跡されなくなる
（false positive＝架空ポジションの追跡を防ぐことを、false negative＝実際の購入の追跡が
遅れることより優先する。前者は事後のデータ復旧作業を要するのに対し、後者は後から
purchase_confirmationsを用意して次回実行時に取り込むだけで済むため、実害の非対称性から
この優先順位とした）。
"""

from __future__ import annotations

from typing import Optional, Tuple

from .holding_period_parser import parse_holding_period_days
from .position_store import normalize_position_numeric_fields
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
    purchase_confirmations: Optional[dict] = None,
) -> Tuple[list, list, list]:
    """新規追跡対象を組み立てる。

    `sheet_rows`はLayer6の「本日の提案」シートの各行（{列名: 値}の辞書、§6-3の列名の
    まま）。`purchase_confirmations`は証券コードをキーとする辞書
    （例：`{"SBUX": {"purchased": False}, "2801": {"purchased": True,
    "actual_entry_price": 1758.0, "actual_shares": 46}}`）。

    2026-08-12：`purchased`が明示的に`True`のエントリのみ取り込む（確認ファイルが無い・
    該当銘柄のエントリが無い・`purchased`がFalseまたは欠落、のいずれも「未購入」扱い。
    上記モジュールdocstring参照）。

    戻り値: (新規position辞書のリスト, スキップされた重複キーのリスト,
    購入されなかったとして取り込みを見送ったキーのリスト)。
    """
    confirmations = purchase_confirmations or {}
    existing = _existing_keys(existing_positions)
    new_positions = []
    skipped = []
    not_purchased = []

    for row in sheet_rows:
        run_id = row["run_id"]
        ticker = row["証券コード"]
        key = (run_id, ticker)
        if key in existing:
            skipped.append(key)
            continue

        confirmation = confirmations.get(ticker)
        if confirmation is None or confirmation.get("purchased") is not True:
            not_purchased.append(key)
            continue

        entry_price = row.get("購入価格目安")
        recommended_shares = row.get("推奨株数")
        if confirmation.get("actual_entry_price") is not None:
            entry_price = confirmation["actual_entry_price"]
        if confirmation.get("actual_shares") is not None:
            recommended_shares = confirmation["actual_shares"]

        holding_period_raw = row.get("想定保有期間")
        days, parse_status = parse_holding_period_days(holding_period_raw, unit_days, fallback_default_days)

        new_position = normalize_position_numeric_fields({
            "tracking_id": build_tracking_id(run_id, ticker),
            "run_id": run_id,
            "ticker": ticker,
            "name": row.get("銘柄名"),
            "asset_class": row.get("資産クラス") or infer_asset_class(ticker),
            "entry_date": row.get("日付"),
            "entry_price": entry_price,
            "stop_loss_price": row.get("損切価格"),
            "take_profit_price": row.get("利確価格"),
            "holding_period_raw": holding_period_raw,
            "holding_period_days_parsed": days,
            "parse_status": parse_status,
            "recommended_shares": recommended_shares,
            "status": "active",
            "latest_price": None,
            "max_unrealized_gain_pct": 0.0,
            "max_unrealized_loss_pct": 0.0,
            "last_checked_at": None,
        })
        # Google Sheets APIが数値セルも文字列として返すため（position_store.
        # normalize_position_numeric_fieldsのdocstring参照）、組み立て直後に数値へ補正する。
        new_positions.append(new_position)
        existing.add(key)

    return new_positions, skipped, not_purchased
