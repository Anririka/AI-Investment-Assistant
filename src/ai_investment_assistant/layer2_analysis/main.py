"""Layer2パイプラインのエントリポイント（layer2_analysis_design.md §3-7〜§3-10・§4・§5）。

既存の各モジュール（technical_indicators／fundamental_metrics／supply_demand／
macro_evaluator／regime_detector／news_scorer／scorer／screener／ranking／
json_builder）は個々に実装・テスト済みである。本モジュールはそれらを設計書どおりの
順序で呼び出す「配線（グルー）」のみを担い、各軸のスコアリングロジック自体は一切
再実装しない（本タスクの指示どおり）。

責務境界（重要、layer2_analysis_design.md §4）：Layer2はLayer1が取得済みの正規化
データ（`PriceSeries`／`FundamentalSnapshot`／`TimeSeries`）と、Layer3が構造化済みの
ニュース（`StructuredNewsItem`相当の辞書）を**受け取るだけ**であり、Layer1・Layer3の
Repositoryを直接呼び出すことはしない（データ取得はLayer1・Layer3の責務）。実際に
Layer1／Layer3を呼び出して本モジュールへ渡すデータを組み立てるのは、
`scripts/run_daily_pipeline.py`（層をまたぐ運用スクリプト）の役割である。

処理順序（§4・§3-7〜§3-10）：
  1. マクロ軸・市場レジームを当日1回だけ計算する（銘柄非依存、§3-4・§3-5）
  2. ニュースのnews_schema_versionを事前検証する（§3-6）
  3. screener.pyで母集団フィルタリング＋配当利回りパーセンタイル付加（§3-8）
  4. 銘柄ごとにテクニカル／ファンダメンタル／需給／ニュース／レジーム適合の各軸を
     スコア化し、scorer.build_candidateで統合する（§3-7）
  5. ranking.pyで順位付け（§3-9）
  6. json_builder.pyで件数上限・プロンプト予算を適用し最終JSONを組み立てる（§3-10）

エラー処理方針（1銘柄・1データソースの失敗で全体を止めない、Layer1詳細設計書§5-2・
layer2_analysis_design.md §10のcritical_errors/warning_errors語彙と整合）：
  - 銘柄単位のスコア計算で例外が発生した場合：`SCORING_FAILED`のcritical_errorsとして
    記録し、当該銘柄のみを結果から除外して処理を継続する。
  - ニュースのnews_schema_versionのメジャーバージョンが不一致の記事がある場合：
    `SCHEMA_VERSION_ERROR`のcritical_errorsとして記録し、当該記事のみを除外して
    処理は継続する（scoring_specification.md・layer3_news_processing_design.md §8-2の
    「当該記事（または当日のニュース処理全体）」という記述のうち、1件の異常記事で
    当日全体のニュース分析を止めてしまわない前者の解釈を採用した）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from ..layer1_data_acquisition.models import FundamentalSnapshot, PriceSeries
from . import (
    fundamental_metrics,
    json_builder,
    macro_evaluator,
    news_scorer,
    ranking,
    regime_detector,
    scorer,
    screener,
    supply_demand,
    technical_indicators,
)

logger = logging.getLogger(__name__)


# --- 銘柄非依存の準備処理 ---------------------------------------------------------


def _filter_valid_news_schema(news_items: list, schema_compatibility_config: dict) -> tuple:
    """news_schema_versionのメジャーバージョンを検証し、不正な記事のみを除外する（§3-6）。

    Layer3詳細設計書§8-2の判定ルール（メジャー一致で受理、不一致でSchemaVersionError）を
    ここで適用する。news_scorer.py自体も同じ検証を行うが、本関数は「当該記事のみを
    除外して当日のニュース処理全体は継続する」という運用判断のための事前フィルタである。
    """
    news_cfg = schema_compatibility_config.get("news_schema", {})
    accept_major = news_cfg.get("accept_major_version")
    valid_items: list = []
    invalid_count = 0
    for item in news_items:
        version = str(item.get("news_schema_version", ""))
        major = version.split(".")[0] if version else ""
        if accept_major is not None and major != str(accept_major):
            invalid_count += 1
            continue
        valid_items.append(item)
    return valid_items, invalid_count


def _select_news_for_ticker(news_items: list, ticker: str) -> list:
    """Layer3の`StructuredNewsItem`一覧から、対象銘柄に関連する記事のみを抽出する。

    `affected_companies`（layer3_news_processing_design.md §8）に対象ticker が含まれる
    記事のみを対象銘柄のニュースとする。`news_scorer.score_axis`が期待するキー名との
    差異は`source_name`→`source`のみのため、ここで読み替える（値自体の加工はしない）。
    """
    selected: list = []
    for item in news_items:
        companies = item.get("affected_companies") or []
        if not any(c.get("ticker") == ticker for c in companies):
            continue
        selected.append({**item, "source": item.get("source_name", item.get("source", ""))})
    return selected


def _average_recent_volume(price_series: PriceSeries, window: int = 20) -> Optional[float]:
    """直近`window`日分の平均出来高を算出する（screener.pyの`avg_volume`条件用）。

    呼び出し側（scripts/run_daily_pipeline.py）が`avg_volume`を明示的に渡さない場合の
    フォールバックとして使用する簡易計算（Layer1のTickerInfoは市場全体の統計値を
    保持しないため、この近似で代用する）。
    """
    if not price_series.bars:
        return None
    bars = sorted(price_series.bars, key=lambda b: b.date)
    recent = bars[-window:]
    return sum(b.volume for b in recent) / len(recent)


def _latest_close(price_series: PriceSeries) -> Optional[float]:
    if not price_series.bars:
        return None
    return sorted(price_series.bars, key=lambda b: b.date)[-1].close


def _compute_dividend_yield(fundamentals: FundamentalSnapshot, price_series: PriceSeries) -> Optional[float]:
    """配当利回り＝配当金÷株価を算出する（screener.compute_dividend_yield_percentiles入力用）。

    無配（`dividend`が0またはNone）の場合はNoneを返し、screener側のパーセンタイル計算の
    母数から除外される（screener.py §3-2の仕様どおり）。
    """
    if not fundamentals.dividend:
        return None
    price = _latest_close(price_series)
    if not price:
        return None
    return fundamentals.dividend / price


def _derive_per_pbr(market_cap: Optional[float], fundamentals: FundamentalSnapshot) -> tuple:
    """PER・PBRを時価総額と財務諸表の合計値から算出する。

    layer2_analysis_design.md §3-2「PER・PBRは時価総額を要するため、呼び出し側
    （screener.py／scorer.py）が計算して渡す」という記述に対応する、本モジュール
    （層をまたぐ配線）での実装。Layer1の`FundamentalSnapshot`には1株あたり指標
    （発行済株式数）が含まれないため、1株単位ではなく合計値ベースの恒等式
    （PER = 時価総額 ÷ 当期純利益、PBR = 時価総額 ÷ 純資産）を用いる。
    これは1株あたりの計算（株価÷EPS、株価÷BPS）と数学的に同値である。
    """
    per = (market_cap / fundamentals.net_income) if market_cap and fundamentals.net_income else None
    pbr = (market_cap / fundamentals.net_assets) if market_cap and fundamentals.net_assets else None
    return per, pbr


def _build_screening_entry(raw: dict) -> dict:
    """1銘柄分の生データから、screener.filter_universeが要求する辞書を組み立てる。"""
    price_series = raw["price_series"]
    avg_volume = raw.get("avg_volume")
    if avg_volume is None:
        avg_volume = _average_recent_volume(price_series)
    return {
        "ticker": raw["ticker"],
        "asset_class": raw["asset_class"],
        "market_cap": raw.get("market_cap"),
        "avg_volume": avg_volume,
        "is_delayed": bool(raw.get("is_delayed", False)),
        "dividend_yield": _compute_dividend_yield(raw["fundamentals"], price_series),
    }


def _score_one_candidate(
    raw: dict,
    macro_result: dict,
    regime_result: dict,
    news_items: list,
    dividend_percentile: Optional[float],
    axis_weights: dict,
    per_scorer,
    macro_correction_config: dict,
    news_decay_config: dict,
    schema_compatibility_config: dict,
) -> dict:
    """1銘柄分の`candidates[]`要素を組み立てる（各軸モジュール呼び出し＋scorer.build_candidate）。"""
    ticker = raw["ticker"]
    price_series = raw["price_series"]
    fundamentals = raw["fundamentals"]
    style_tags = list(raw.get("style_tags") or [])

    technical = technical_indicators.score_axis(price_series)

    per, pbr = _derive_per_pbr(raw.get("market_cap"), fundamentals)
    fundamental = fundamental_metrics.score_axis(
        fundamentals,
        per=per,
        pbr=pbr,
        dividend_yield_percentile=dividend_percentile,
        prior_year_eps=raw.get("prior_year_eps"),
        prior_year_revenue=raw.get("prior_year_revenue"),
        prior_year_fcf=raw.get("prior_year_fcf"),
        per_scorer=per_scorer,
        sector_code=raw.get("sector_code"),
    )

    supply = supply_demand.score_axis(price_series, margin_ratio=raw.get("margin_ratio"))

    ticker_news = _select_news_for_ticker(news_items, ticker)
    news = news_scorer.score_axis(
        ticker_news, news_decay_config.get("decay_curve", []), schema_compatibility_config
    )

    candidate_macro_score = macro_evaluator.apply_sector_sensitivity(
        macro_result["axis_score"], style_tags, macro_correction_config
    )
    regime_fit = regime_detector.score_fit(regime_result["regime"], style_tags)

    missing_fields = (
        [f"technical.{name}" for name in technical.get("missing_indicators", [])]
        + [f"fundamental.{name}" for name in fundamental.get("missing_indicators", [])]
        + [f"supply_demand.{name}" for name in supply.get("missing_indicators", [])]
    )
    data_quality = {"is_delayed": bool(raw.get("is_delayed", False)), "missing_fields": missing_fields}

    return scorer.build_candidate(
        asset_class=raw["asset_class"],
        ticker=ticker,
        name=raw.get("name", ticker),
        style_tags=style_tags,
        data_quality=data_quality,
        technical=technical,
        fundamental=fundamental,
        supply_demand=supply,
        news=news,
        macro_axis_score=candidate_macro_score,
        regime_fit=regime_fit,
        axis_weights=axis_weights,
    )


def _estimate_tokens(output: dict) -> int:
    """プロンプトの概算トークン数を見積もる（§3-10-1「簡易的には文字数÷4等の概算」）。"""
    return len(json.dumps(output, ensure_ascii=False)) // 4


def _apply_prompt_budget(output: dict, llm_input_config: dict) -> dict:
    """トークン予算超過時の調整（§3-10-1の優先順位：①reason短縮→②低スコア候補除外）。"""
    prompt_budget = llm_input_config.get("prompt_budget", {})
    active_provider = llm_input_config.get("active_provider", "claude")
    budget = prompt_budget.get(active_provider)
    if not budget:
        return output

    estimated = _estimate_tokens(output)
    if estimated <= budget:
        return output

    logger.warning(
        "prompt budget exceeded (estimated=%d, budget=%d for provider=%s); shortening reasons",
        estimated, budget, active_provider,
    )
    output = json_builder.shorten_reasons_for_budget(output)
    estimated = _estimate_tokens(output)

    max_drops = len(output["candidates"])
    dropped = 0
    while estimated > budget and dropped < max_drops:
        output = json_builder.drop_lowest_scoring_candidates(output, count=1)
        estimated = _estimate_tokens(output)
        dropped += 1

    if estimated > budget:
        logger.warning("prompt budget still exceeded after dropping lowest scoring candidates")

    return output


# --- エントリポイント -------------------------------------------------------------


def run(
    run_id: str,
    analysis_started_at: datetime,
    candidates_raw: list,
    index_price_series: PriceSeries,
    macro_series_map: dict,
    news_items: list,
    universe_config: dict,
    scoring_weights_config: dict,
    news_decay_config: dict,
    schema_compatibility_config: dict,
    llm_input_config: dict,
    strategy_bias: dict,
    upstream_critical_errors: Optional[list] = None,
    upstream_warning_errors: Optional[list] = None,
    upstream_excluded_summary: Optional[list] = None,
    degraded_sources: Optional[list] = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    """Layer2パイプライン全体を実行し、Layer5への最終JSON（layer2_output）を返す。

    引数:
      candidates_raw: 銘柄ごとの生データの辞書のリスト。各要素は以下のキーを持つ：
        ticker, asset_class, name, style_tags, sector_code（任意）,
        price_series（`PriceSeries`）, fundamentals（`FundamentalSnapshot`）,
        market_cap（任意）, avg_volume（任意、省略時は直近20日平均出来高で代用）,
        is_delayed（任意、既定False）, margin_ratio（任意）,
        prior_year_eps／prior_year_revenue／prior_year_fcf（任意、前年同期比の
        成長率算出用。Layer1の`get_fundamentals`は単一時点の値のみを返す契約のため、
        これらを供給できない場合はNoneのままでよく、当該サブ指標は欠損として
        同一軸内の他指標へ比例配分される、scoring_specification.md §4）。
      index_price_series: 市場レジーム判定用の指数（日経平均等）の`PriceSeries`（§3-5）。
      macro_series_map: {series_id: TimeSeries}（マクロ軸用、§3-4）。
      news_items: Layer3が構造化した`StructuredNewsItem`相当の辞書のリスト（当日分全件）。
      strategy_bias: 現在のレジームに対応する資産クラス別の推奨スタイルバイアス
        （`{"japan_equity": "neutral", ...}`。設計書§3-5が参照する`config/risk_rules.yaml`の
        レジーム→戦略マッピングは本リポジトリに未整備のため、呼び出し側で解決済みの
        辞書を渡す契約とした。詳細はscripts/run_daily_pipeline.pyのコメントを参照）。
      upstream_critical_errors／upstream_warning_errors／upstream_excluded_summary：
        Layer1・Layer3側で既に発生したエラー・除外銘柄（例：単一銘柄のデータ取得失敗）を
        そのまま`run_meta.data_quality`／`excluded_summary`へ引き継ぐための引数。

    戻り値: layer2_analysis/schemas/layer2_output.schema.json に準拠する辞書。
    """
    critical_errors = list(upstream_critical_errors or [])
    warning_errors = list(upstream_warning_errors or [])
    excluded_summary = list(upstream_excluded_summary or [])
    degraded_sources_list = list(degraded_sources or [])

    axis_weights = scoring_weights_config["axis_weights"]
    per_scorer_name = scoring_weights_config.get("per_scorer", "absolute_range")
    per_scorer_cls = fundamental_metrics.PER_SCORER_REGISTRY.get(
        per_scorer_name, fundamental_metrics.AbsoluteRangePERScorer
    )
    per_scorer = per_scorer_cls()
    macro_correction_config = scoring_weights_config.get("macro_sector_correction", {})

    # 1. マクロ軸・市場レジームは銘柄非依存、当日1回だけ計算する（§4）
    macro_result = macro_evaluator.score_axis(macro_series_map)
    regime_result = regime_detector.detect_regime(index_price_series)

    # 2. ニュースのnews_schema_versionを事前検証する（§3-6・Layer3詳細設計書§8-2）
    valid_news_items, invalid_news_count = _filter_valid_news_schema(
        news_items, schema_compatibility_config
    )
    if invalid_news_count:
        critical_errors.append(
            {
                "code": "SCHEMA_VERSION_ERROR",
                "message": (
                    f"{invalid_news_count}件のニュース記事でnews_schema_versionのメジャー"
                    "バージョンが不一致のため除外"
                ),
                "source_layer": "layer2",
            }
        )

    # 3. screener.py：母集団フィルタリング＋配当利回りパーセンタイル付加（§3-8）
    screening_entries = [_build_screening_entry(c) for c in candidates_raw]
    passed_entries, screener_excluded = screener.filter_universe(screening_entries, universe_config)
    excluded_summary.extend(screener_excluded)

    dividend_percentiles = screener.compute_dividend_yield_percentiles(passed_entries)
    raw_by_ticker = {c["ticker"]: c for c in candidates_raw}

    # 4. 銘柄ごとに各軸をスコア化し統合する（§3-7）。1銘柄の失敗で全体を止めない。
    scored_candidates: list = []
    for entry in passed_entries:
        ticker = entry["ticker"]
        raw = raw_by_ticker[ticker]
        try:
            candidate = _score_one_candidate(
                raw,
                macro_result,
                regime_result,
                valid_news_items,
                dividend_percentiles.get(ticker),
                axis_weights,
                per_scorer,
                macro_correction_config,
                news_decay_config,
                schema_compatibility_config,
            )
            scored_candidates.append(candidate)
        except Exception as exc:  # noqa: BLE001  1銘柄の失敗で全run停止を避ける（層別設計方針）
            logger.exception("scoring failed for ticker=%s", ticker)
            critical_errors.append(
                {
                    "code": "SCORING_FAILED",
                    "message": f"{ticker}のスコア計算中に例外発生: {exc}",
                    "source_layer": "layer2",
                }
            )
            excluded_summary.append(
                {
                    "ticker": ticker,
                    "asset_class": raw.get("asset_class", "unknown"),
                    "reason_code": "SCORING_FAILED",
                    "reason": f"スコア計算中にエラーが発生したため除外: {exc}",
                }
            )

    # 5. ranking.py：資産クラスごとの順位付け（§3-9）
    ranked = ranking.rank_candidates(scored_candidates)

    analysis_completed_at = clock()
    run_meta = scorer.build_run_meta(
        run_id=run_id,
        analysis_started_at=analysis_started_at,
        analysis_completed_at=analysis_completed_at,
        critical_errors=critical_errors,
        warning_errors=warning_errors,
        degraded_sources=degraded_sources_list,
        excluded_candidates_count=len(excluded_summary),
    )

    regime_output = {
        "current_regime": regime_result["regime"],
        "regime_reason": regime_result["reason"],
        "strategy_bias": strategy_bias,
    }

    # 6. json_builder.py：件数上限・プロンプト予算を適用し最終JSONを組み立てる（§3-10）
    candidate_limits = llm_input_config.get("candidate_limits", {})
    max_total_candidates = llm_input_config.get("max_total_candidates", len(scored_candidates) or 1)

    output, budget_warnings = json_builder.build_output(
        run_meta=run_meta,
        regime=regime_output,
        macro=macro_result,
        ranked_candidates=ranked,
        excluded_summary=excluded_summary,
        candidate_limits=candidate_limits,
        max_total_candidates=max_total_candidates,
    )
    for message in budget_warnings:
        logger.warning(message)

    output = _apply_prompt_budget(output, llm_input_config)

    # excluded_candidates_countは、json_builder段階（件数上限・プロンプト予算超過）の
    # 除外も反映した最終値に更新する。
    output["run_meta"]["data_quality"]["excluded_candidates_count"] = len(output["excluded_summary"])

    return output
