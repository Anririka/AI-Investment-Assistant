"""母集団フィルタリング（layer2_analysis_design.md §3-8、責務縮小版）。

入力：`config/universe.yaml`（銘柄マスタ、時価総額・出来高の下限条件）＋各候補の生データ。
処理：母集団フィルタリング、母集団全体の分布統計（配当利回りパーセンタイル）の計算・付加、
データ品質ゲートによる除外。
出力：フィルタ・統計付加済みの候補リスト＋除外銘柄と理由コードのリスト。

ランキング・JSON組み立ての処理は一切持たない（§3-8、単一責任の原則）。
"""

from __future__ import annotations


def filter_universe(candidates: list, universe_config: dict) -> tuple:
    """時価総額・出来高条件・データ品質ゲートで候補をフィルタリングする（§3-8）。

    `candidates`の各要素は最低限`ticker`・`asset_class`を持ち、任意で`market_cap`・
    `avg_volume`・`is_delayed`を持つ辞書。

    戻り値: (合格した候補のリスト, 除外された候補の理由コード付きリスト)
    """
    passed = []
    excluded = []

    for c in candidates:
        asset_cfg = universe_config.get(c["asset_class"], {})
        min_cap = asset_cfg.get("min_market_cap")
        min_vol = asset_cfg.get("min_avg_volume")

        if c.get("is_delayed"):
            excluded.append(
                {
                    "ticker": c["ticker"],
                    "asset_class": c["asset_class"],
                    "reason_code": "DATA_DELAYED_12W",
                    "reason": "J-Quants Freeプランの12週遅延によりデータ品質ゲートで除外",
                }
            )
            continue

        if min_cap is not None and (c.get("market_cap") or 0) < min_cap:
            excluded.append(
                {
                    "ticker": c["ticker"],
                    "asset_class": c["asset_class"],
                    "reason_code": "MARKET_CAP_TOO_SMALL",
                    "reason": f"時価総額が下限（{min_cap}）未満",
                }
            )
            continue

        if min_vol is not None and (c.get("avg_volume") or 0) < min_vol:
            excluded.append(
                {
                    "ticker": c["ticker"],
                    "asset_class": c["asset_class"],
                    "reason_code": "VOLUME_TOO_LOW",
                    "reason": f"平均出来高が下限（{min_vol}）未満",
                }
            )
            continue

        passed.append(c)

    return passed, excluded


def compute_dividend_yield_percentiles(candidates: list) -> dict:
    """母集団全体の配当利回り分布からパーセンタイルを計算する（§3-2）。

    戻り値: {ticker: percentile}（0〜1、1.0に近いほど利回り上位）。
    無配（dividend_yield=0）の銘柄はパーセンタイル計算の母数から除外し、
    fundamental_metrics.py側で別途「無配」バケットとして扱う。
    """
    yields = [(c["ticker"], c["dividend_yield"]) for c in candidates if c.get("dividend_yield")]
    if not yields:
        return {}

    sorted_yields = sorted(yields, key=lambda x: x[1])
    n = len(sorted_yields)
    return {ticker: (idx + 1) / n for idx, (ticker, _) in enumerate(sorted_yields)}
