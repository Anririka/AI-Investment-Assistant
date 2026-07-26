"""第1段階（広域・価格データのみ）スクリーニング。

2026-07-26追加：config/universe.yaml をプレースホルダー（日本株5・米国株5）から実際の
日経225（225銘柄）・S&P500（503銘柄）構成銘柄リストへ差し替えるにあたり、ユーザーと
合意した2段階方式（項目6「残作業一覧」対応）の第1段階を実装するモジュール。

背景（レート制限の制約）：
  config/api_sources.yaml の米国株チェーンは Alpha Vantage（25回/日、
  `reserved_for: final_candidates_detail`）を先頭に置いている。母集団725銘柄すべてに
  対して scripts/run_daily_pipeline.py の既存ロジック（価格＋ファンダメンタルの2回取得/銘柄）
  をそのまま実行すると、Alpha Vantageの1日の呼び出し上限をスクリーニング用途だけで
  即座に使い切ってしまい、「最終候補の決算・EPS等の補完用途」という本来の予約枠を
  奪ってしまう（layer1_data_acquisition_design.md 6-2、alpha_vantage.pyのdocstring参照）。

  そのため、本モジュールは「価格データのみ（ファンダメンタル・時価総額は使わない）」で
  母集団全体を広く・安く一次スクリーニングし、少数（既定20銘柄/市場）に絞り込む。
  絞り込んだ銘柄のみが、従来通りの詳細フェッチ（scripts/run_daily_pipeline.pyの
  `_fetch_market_candidates`、価格＋ファンダメンタル取得）に進む「第2段階」に渡される。
  価格データの取得元は、日本株はjapan_equityチェーン（J-Quants、レート上限が緩やか）を
  そのまま流用し、米国株は新設の`us_equity_bulk_price`チェーン（Twelve Dataのみ、
  Alpha Vantageを含めない）を使う（scripts/run_daily_pipeline.py側の配線を参照）。

設計上の判断（重要）：本段階で絞り込んで対象外となった銘柄は、
`excluded_summary`（Layer4永続化・Layer6の「本日の提案_除外不採用ログ」シートの元データ）
には**記録しない**。あの一覧は「戦略的に検討したが除外した銘柄」を人間がレビューする
ためのものであり、意味的に母集団725銘柄のうち第1段階で対象外になった多数（既定約685銘柄）
をそこに載せると、本来の「除外理由の説明」という目的から外れて肥大化するだけになる
（screener.filter_universe による除外・単一銘柄のデータ取得失敗と混同されないよう、
本モジュールは意図的にscreener.pyのexcluded_summaryスキーマとは別の戻り値にしている）。
"""

from __future__ import annotations

import logging
from typing import Optional

from ..layer1_data_acquisition.models import PriceSeries
from . import technical_indicators

logger = logging.getLogger(__name__)

DEFAULT_SHORTLIST_SIZE = 20


def average_recent_volume(price_series: PriceSeries, window: int = 20) -> Optional[float]:
    """直近`window`日分の平均出来高を算出する。

    layer2_analysis.main._average_recent_volume と同じ計算だが、本モジュールは
    layer2_analysis.main（Layer2本体のスコアリング組み立て）に依存させたくないため
    （screener.pyがmain.pyを参照していないのと同じ、層内の疎結合の方針）、あえて
    同じロジックをここに複製している。
    """
    if not price_series.bars:
        return None
    bars = sorted(price_series.bars, key=lambda b: b.date)
    recent = bars[-window:]
    return sum(b.volume for b in recent) / len(recent)


def filter_by_liquidity(candidates: list, universe_config: dict) -> tuple:
    """既存のmin_avg_volume（config/universe.yaml）で流動性の下限フィルタをかける。

    `candidates`の各要素は最低限`ticker`・`asset_class`・`price_series`を持つ辞書。
    時価総額（min_market_cap）は本段階では判定しない（価格データのみでは算出できない
    ため。時価総額フィルタは第2段階のscreener.filter_universeで従来通り適用される）。

    戻り値: (通過した候補のリスト（avg_volume付加済み）, 除外された銘柄のticker集合)
    """
    passed = []
    excluded_tickers: set = set()

    for c in candidates:
        asset_cfg = universe_config.get(c["asset_class"], {})
        min_vol = asset_cfg.get("min_avg_volume")

        avg_volume = average_recent_volume(c["price_series"])
        enriched = {**c, "avg_volume": avg_volume}

        if min_vol is not None and (avg_volume or 0) < min_vol:
            excluded_tickers.add(c["ticker"])
            continue

        passed.append(enriched)

    return passed, excluded_tickers


def score_technical(candidates: list) -> tuple:
    """価格データのみで算出できるテクニカル軸スコア（technical_indicators.score_axis）で
    各候補をランク付けする。

    Layer2本番スコアリングと同じロジック（technical_indicators.py）をそのまま流用する
    ことで、「第1段階の足切りが本番の評価基準と大きく乖離する」ことを避けている
    （第1段階独自の簡易指標を新設すると、第1段階を通過した銘柄が第2段階・本番スコアで
    低評価になりやすい、という粒度不一致のリスクがあるため）。

    データ不足（新規上場等でRSI/ADX等が計算できない）銘柄はスコア算出時に例外となるが、
    1銘柄の失敗で処理全体を止めない設計方針（layer1_data_acquisition_design.md §5）に
    倣い、当該銘柄は本段階の対象から静かに除外する（excluded_tickersに理由付きで積む）。

    戻り値: (technical_score付加済みの候補のリスト, {ticker: 除外理由}の辞書)
    """
    scored = []
    excluded: dict = {}

    for c in candidates:
        try:
            axis = technical_indicators.score_axis(c["price_series"])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "stage1 technical score failed for %s (%s): %s",
                c["ticker"], c.get("asset_class"), exc,
            )
            excluded[c["ticker"]] = f"テクニカルスコア算出不可（データ不足の可能性）: {exc}"
            continue
        scored.append({**c, "stage1_technical_score": axis["axis_score"]})

    return scored, excluded


def select_shortlist(candidates: list, universe_config: dict) -> dict:
    """第1段階の全処理（流動性フィルタ→テクニカルスコアランキング→上位N件抽出）をまとめる。

    `candidates`は日本株・米国株混在でよい（`asset_class`ごとにグルーピングして処理する）。
    上位N件の「N」は`config/universe.yaml`の各asset_classブロックの
    `stage1_shortlist_size`（省略時`DEFAULT_SHORTLIST_SIZE`＝20）で指定する。

    戻り値: {
        "shortlist": {asset_class: [ticker, ...]},  # テクニカルスコア降順
        "shortlisted_candidates": [...],              # 第2段階への引き渡し不要（tickerのみ渡す設計）だが
                                                        # デバッグ・ログ用に候補全体も返す
        "stage1_excluded_count": {asset_class: int},   # 監査用（ログ出力のみ、excluded_summaryには積まない）
    }
    """
    by_asset_class: dict = {}
    for c in candidates:
        by_asset_class.setdefault(c["asset_class"], []).append(c)

    shortlist: dict = {}
    shortlisted_candidates: list = []
    stage1_excluded_count: dict = {}

    for asset_class, group in by_asset_class.items():
        asset_cfg = universe_config.get(asset_class, {})
        shortlist_size = asset_cfg.get("stage1_shortlist_size", DEFAULT_SHORTLIST_SIZE)

        liquid, liquidity_excluded = filter_by_liquidity(group, universe_config)
        scored, technical_excluded = score_technical(liquid)

        scored.sort(key=lambda c: c["stage1_technical_score"], reverse=True)
        top = scored[:shortlist_size]

        shortlist[asset_class] = [c["ticker"] for c in top]
        shortlisted_candidates.extend(top)
        stage1_excluded_count[asset_class] = (
            len(group) - len(top)
        )

        logger.info(
            "stage1 screening (%s): %d candidates -> %d liquid -> %d scored -> top %d selected "
            "(liquidity_excluded=%d, technical_score_unavailable=%d)",
            asset_class, len(group), len(liquid), len(scored), len(top),
            len(liquidity_excluded), len(technical_excluded),
        )

    return {
        "shortlist": shortlist,
        "shortlisted_candidates": shortlisted_candidates,
        "stage1_excluded_count": stage1_excluded_count,
    }
