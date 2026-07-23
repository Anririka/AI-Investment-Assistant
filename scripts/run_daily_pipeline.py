"""Layer1〜4（データ取得〜永続化）を実データで通しで実行する本番パイプライン。

.github/workflows/data_pipeline.yml のコメントにあった
「Layer1〜4を実際に通しで実行する本番ステップは、Layer5の実装が固まった時点で追加する」
に対応するスクリプト。Layer5が確定したため、ここでLayer1→Layer3→Layer2→Layer4を
実データで一気通貫に実行する。

実行内容（layer1_data_acquisition_design.md／layer2_analysis_design.md／
layer3_news_processing_design.md／layer4_persistence_design.md 各§0・§3系）：
  1. RepositoryFactory（Layer1）を組み立て、config/universe.yamlの銘柄について
     日次株価・ファンダメンタル・銘柄マスタ・マクロ系列・ニュースを取得する。
  2. Layer3（news_processing.main.process_articles）でニュースを構造化する。
  3. Layer2（layer2_analysis.main.run）でスコアリング・スクリーニング・ランキング・
     最終JSON組み立てを行う。
  4. Layer4（layer4_persistence.main.run）でGoogle Driveへ永続化する。

1銘柄・1データソースの障害で全体を止めない設計（layer1_data_acquisition_design.md §5、
data_quality_policy.yamlのwarning_errors語彙）。個別ティッカーの取得失敗は
`SINGLE_STOCK_DATA_FAILURE`としてwarning_errorsに記録し、当該銘柄をexcluded_summaryへ
回して処理を継続する。

本スクリプトはユニットテスト対象外（phase0_smoke_test.py・layer1_live_check.pyと同様、
実際の外部API・Google Driveを呼び出すライブ運用スクリプトのため）。GitHub Actionsの
手動実行（workflow_dispatch）で検証する。

未解決の設計ギャップ（本スクリプト実装時に判明。既存モジュールの契約は変更していない。
値は暫定のフォールバックとして扱い、上位の人間レビューに委ねる）：

  1. 【市場レジーム判定用の指数ティッカー】regime_detector.detect_regime()は日経平均等の
     指数PriceSeriesを要求するが、config/api_sources.yaml・config/universe.yamlの
     いずれにも指数ティッカーの定義が無い。config/universe.yamlの個別銘柄プレースホルダー
     と同様の位置づけで、下記`NIKKEI225_INDEX_TICKER`を暫定プレースホルダーとして置き、
     取得失敗時は「レンジ相場」にフォールバックする（クラッシュはさせない）。実際の
     J-Quants指数コードの確認が必要。
  2. 【銘柄スタイルタグの管理場所が未整備】regime_detector.score_fit()・
     macro_evaluator.apply_sector_sensitivity()はいずれも銘柄の`style_tags`
     （growth/defensive/high_dividend等）を要求するが、それを管理するconfigファイルが
     リポジトリ内に存在しない（config/sector_mapping.yamlは業種コードのみ）。本スクリプトは
     暫定的に全銘柄`style_tags=[]`として扱う（レジーム適合スコア・マクロ感応度補正は
     中立値にフォールバックする）。
  3. 【前年同期比の算出に必要な過去データが取得不能】fundamental_metrics.score_axis()は
     EPS/売上/FCF成長率のためprior_year_eps/revenue/fcfを受け取れるが、Layer1の
     `MarketDataRepository.get_fundamentals(ticker)`は単一時点のスナップショットのみを
     返す契約であり、過去期のスナップショットを取得する手段が設計書に定義されていない。
     本スクリプトはこれらを常にNoneとして渡す（該当サブ指標はscoring_specification.md §4の
     欠損時再配分ルールにより自動的に他指標へ按分される）。
  4. 【config/risk_rules.yamlが未整備】layer2_analysis_design.md §3-5がregime→戦略バイアス
     （strategy_bias）の参照先として挙げるconfig/risk_rules.yamlが本リポジトリに存在しない。
     本スクリプトは暫定的に全資産クラス"neutral"を返す。
  5. 【market_capが日本株・米国株とも常時取得不能だった問題（2026-07-23対応）】
     J-Quants（無料〜Lightプラン）の`/equities/master`、Alpha Vantage/Twelve Dataの
     `get_listed_universe()`はいずれも時価総額を直接は返さない（2026-07-23のライブ実行で
     確認、全候補がMARKET_CAP_TOO_SMALLで除外されていた）。Layer1の各Repositoryは
     Design-Frozenのため、TickerInfo/FundamentalSnapshotのフィールド自体は追加せず、
     本スクリプト側（`_estimate_market_cap`）で、既に取得済みのファンダメンタル
     （純利益・EPS）と直近終値から時価総額を近似する暫定策で対応した：
         発行済株式数 ≈ 純利益 ÷ EPS
         時価総額 ≈ 発行済株式数 × 直近終値
     info.market_cap（Repositoryが直接返す値）が取得できた場合はそちらを優先する。
     あくまで直近決算時点のEPSを使った近似値であり、発行済株式数の変動（自己株買い等）
     や、EPSが古い期のものである場合には実際の時価総額とズレが生じ得る。より正確な値が
     必要になった場合は、真の時価総額を提供するデータソースへの切り替えを検討すること。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from ai_investment_assistant.layer1_data_acquisition.caching import build_default_cache_store
from ai_investment_assistant.layer1_data_acquisition.exceptions import DataSourceError
from ai_investment_assistant.layer1_data_acquisition.factory import RepositoryFactory
from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer2_analysis import main as layer2_main
from ai_investment_assistant.layer3_news_processing import fetcher as layer3_fetcher
from ai_investment_assistant.layer3_news_processing import main as layer3_main
from ai_investment_assistant.layer3_news_processing.structurer_factory import build_structurer
from ai_investment_assistant.layer4_persistence import main as layer4_main
from ai_investment_assistant.layer4_persistence.repository.google_drive_repository import GoogleDriveRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_daily_pipeline")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
JST = timezone(timedelta(hours=9))

PRICE_LOOKBACK_DAYS = 400  # 200MA計算に必要な200営業日分を安全に確保する
MACRO_LOOKBACK_DAYS = 900  # 月次・四半期系列でも十分な点数を確保する
NEWS_LOOKBACK_DAYS = 2  # 前回runからの差分取得が本来の設計だが、本スクリプトでは簡易に直近48hとする

# ギャップ1：指数ティッカーのプレースホルダー（要確認、config/universe.yamlの
# 「プレースホルダー、要更新」と同じ位置づけ）
NIKKEI225_INDEX_TICKER = "998407"

# マクロ系列ID（layer2_analysis.macro_evaluatorの内部キー）→ FRED系列ID
# （layer1_data_acquisition_design.md §2-3のマッピング表どおり）
FRED_SERIES_MAP = {
    "us_10y_yield": "DGS10",
    "fed_funds_rate": "FEDFUNDS",
    "unemployment_rate": "UNRATE",
    "cpi_yoy": "CPIAUCSL",
    "ppi_yoy": "PPIACO",
    "gdp_growth": "GDP",
    "leading_index": "USSLIND",
}

# ニュース取得(a)：主要指数・マクロ全般の固定クエリ（layer3_news_processing_design.md §4）
MACRO_NEWS_QUERIES = ["Nikkei 225", "S&P 500", "FOMC", "Bank of Japan", "CPI inflation"]


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def _empty_price_series(ticker: str, reason: str) -> PriceSeries:
    """指数取得に失敗した場合のフォールバック（レンジ相場に倒す、単一フラットバー）。"""
    meta = DataFetchMeta(source_used="fallback", fetched_at=datetime.now(timezone.utc), success=False, error_detail=reason)
    bar = PriceBar(date=date.today(), open=100.0, high=100.0, low=100.0, close=100.0, volume=0)
    return PriceSeries(ticker=ticker, currency="JPY", bars=(bar,), meta=meta)


def _estimate_market_cap(fundamentals, price_series: PriceSeries, ticker: str = "") -> "float | None":
    """時価総額を、既に取得済みのファンダメンタル・株価から近似する（2026-07-23追加）。

    J-Quants（無料〜Lightプラン）・Alpha Vantage/Twelve DataのいずれもTickerInfo経由では
    時価総額を直接返さない（ギャップ5、本ファイル冒頭docstring参照）。Layer1の各Repository
    はDesign-Frozenのためフィールド追加はせず、本スクリプト側で以下の近似式を使う：

        発行済株式数 ≈ 純利益 ÷ EPS
        時価総額 ≈ 発行済株式数 × 直近終値

    純利益・EPSのいずれかが欠損、EPS=0、または株価データが空の場合はNoneを返す
    （screener.py側でmin_market_cap未満として扱われ除外される、これは既存の仕様どおり）。

    診断ログ（2026-07-23追加）：2026-07-23のライブ実行で、この近似計算を追加した後も
    全銘柄がMARKET_CAP_TOO_SMALLで除外され続けたため、具体的にどのフィールドが
    欠損していたのかを切り分けるために追加した（fundamentals自体が未確認のレスポンス
    形状に依存しているため、net_income/epsが実際には取得できていない可能性がある）。
    """
    if fundamentals is None:
        logger.warning("_estimate_market_cap(%s): fundamentals is None", ticker)
        return None
    if fundamentals.net_income is None or not fundamentals.eps:
        logger.warning(
            "_estimate_market_cap(%s): missing net_income or eps (net_income=%s, eps=%s)",
            ticker, fundamentals.net_income, fundamentals.eps,
        )
        return None
    if not price_series.bars:
        logger.warning("_estimate_market_cap(%s): price_series has no bars", ticker)
        return None
    shares_outstanding = fundamentals.net_income / fundamentals.eps
    latest_close = price_series.bars[-1].close
    return shares_outstanding * latest_close


def _fetch_market_candidates(
    chain,
    tickers: list,
    asset_class: str,
    start: date,
    end: date,
    warning_errors: list,
    excluded_summary: list,
    degraded_sources: set,
) -> list:
    """1市場分の候補データを取得する。1銘柄の失敗は当該銘柄のみ除外して継続する。"""
    candidates: list = []

    try:
        listed_universe = list(chain.call("get_listed_universe"))
    except DataSourceError as exc:
        logger.warning("get_listed_universe failed for %s: %s", asset_class, exc)
        warning_errors.append(
            {"code": "MINOR_SOURCE_TIMEOUT", "message": f"{asset_class} get_listed_universe failed: {exc}", "source_layer": "layer1"}
        )
        listed_universe = []

    # ticker_infosは生のticker（例："72030"）と、末尾の1桁（チェックディジット的な
    # 付加数字、J-Quantsの5桁コード表記でよく見られる慣習）を除いた4桁形式
    # （例："7203"）の両方をキーとして登録する（2026-07-23追加）。config/universe.yaml
    # 側は4桁ティッカーで管理しているため、get_listed_universeが5桁形式で返す場合でも
    # 一致するようにするための防御的な正規化（get_daily_pricesのレスポンスで
    # "Code":"72030"だった前例あり、他方の対応が確認できるまでの暫定措置）。
    ticker_infos: dict = {}
    for info in listed_universe:
        ticker_infos[info.ticker] = info
        if len(info.ticker) == 5 and info.ticker.isdigit() and info.ticker.endswith("0"):
            ticker_infos.setdefault(info.ticker[:4], info)

    if tickers and not ticker_infos:
        logger.warning(
            "get_listed_universe returned no entries for %s (tickers=%s)", asset_class, tickers
        )
    elif tickers:
        unmatched = [t for t in tickers if t not in ticker_infos]
        if unmatched:
            sample_keys = list(ticker_infos.keys())[:10]
            logger.warning(
                "get_listed_universe: %d/%d tickers unmatched for %s (unmatched=%s, "
                "ticker_infos keys sample=%s) -- config/universe.yamlのticker形式と "
                "get_listed_universeの返すticker形式が不一致の可能性あり",
                len(unmatched), len(tickers), asset_class, unmatched, sample_keys,
            )

    for ticker in tickers:
        try:
            price_series = chain.call("get_daily_prices", ticker, start, end)
            if price_series.meta.is_delayed:
                degraded_sources.add(f"{chain.last_source_used}:price_delayed")

            fundamentals = chain.call("get_fundamentals", ticker)

            info = ticker_infos.get(ticker)
            market_cap = info.market_cap if info else None
            if market_cap is None:
                market_cap = _estimate_market_cap(fundamentals, price_series, ticker=ticker)
            candidates.append(
                {
                    "ticker": ticker,
                    "asset_class": asset_class,
                    "name": info.name if info else ticker,
                    "style_tags": [],  # ギャップ2：style_tagsの管理configが未整備のため暫定的に空
                    "sector_code": info.sector_code if info else None,
                    "price_series": price_series,
                    "fundamentals": fundamentals,
                    "market_cap": market_cap,
                    "is_delayed": price_series.meta.is_delayed,
                    "margin_ratio": None,  # J-Quants Light/Freeでは常時欠損（scorer側で按分される）
                    "prior_year_eps": None,  # ギャップ3：前年同期データの取得手段が未整備
                    "prior_year_revenue": None,
                    "prior_year_fcf": None,
                }
            )
        except DataSourceError as exc:
            logger.warning("data fetch failed for %s (%s): %s", ticker, asset_class, exc)
            warning_errors.append(
                {
                    "code": "SINGLE_STOCK_DATA_FAILURE",
                    "message": f"{ticker}のデータ取得に失敗: {exc}",
                    "source_layer": "layer1",
                }
            )
            excluded_summary.append(
                {
                    "ticker": ticker,
                    "asset_class": asset_class,
                    "reason_code": "SINGLE_STOCK_DATA_FAILURE",
                    "reason": f"データ取得に失敗したため当日の候補から除外: {exc}",
                }
            )

    return candidates


def _fetch_macro_series_map(macro_chain, start: date, end: date, warning_errors: list) -> dict:
    series_map = {}
    for internal_id, fred_id in FRED_SERIES_MAP.items():
        try:
            series_map[internal_id] = macro_chain.call("get_series", fred_id, start, end)
        except DataSourceError as exc:
            logger.warning("macro series fetch failed for %s (%s): %s", internal_id, fred_id, exc)
            warning_errors.append(
                {
                    "code": "MINOR_SOURCE_TIMEOUT",
                    "message": f"マクロ系列{internal_id}({fred_id})の取得に失敗: {exc}",
                    "source_layer": "layer1",
                }
            )
    return series_map


def _fetch_index_series(japan_chain, start: date, end: date, critical_errors: list) -> PriceSeries:
    try:
        return japan_chain.call("get_daily_prices", NIKKEI225_INDEX_TICKER, start, end)
    except DataSourceError as exc:
        logger.error("index series fetch failed, falling back to range regime: %s", exc)
        critical_errors.append(
            {
                "code": "PRICE_DATA_INVALID",
                "message": f"市場レジーム判定用の指数（{NIKKEI225_INDEX_TICKER}）取得に失敗: {exc}",
                "source_layer": "layer1",
            }
        )
        return _empty_price_series(NIKKEI225_INDEX_TICKER, str(exc))


def main() -> int:
    started_at = datetime.now(timezone.utc)
    now_jst = _now_jst()
    date_str = now_jst.strftime("%Y%m%d")
    year_month = now_jst.strftime("%Y%m")
    run_id = now_jst.strftime("%Y%m%d-%H%M")

    logger.info("=== run_daily_pipeline start (run_id=%s) ===", run_id)

    api_sources_config = _load_yaml("api_sources.yaml")
    universe_config = _load_yaml("universe.yaml")
    scoring_weights_config = _load_yaml("scoring_weights.yaml")
    news_decay_config = _load_yaml("news_decay.yaml")
    schema_compatibility_config = _load_yaml("schema_compatibility.yaml")
    llm_input_config = _load_yaml("llm_input.yaml")
    quality_filter_config = _load_yaml("quality_filter.yaml")
    importance_rules_config = _load_yaml("importance_rules.yaml")
    ai_provider_config = _load_yaml("ai_provider.yaml")
    sector_mapping_config = _load_yaml("sector_mapping.yaml")

    cache_store = build_default_cache_store()
    factory = RepositoryFactory(api_sources_config, cache_store=cache_store)

    critical_errors: list = []
    warning_errors: list = []
    excluded_summary: list = []
    degraded_sources: set = set()

    price_start = date.today() - timedelta(days=PRICE_LOOKBACK_DAYS)
    price_end = date.today()
    macro_start = date.today() - timedelta(days=MACRO_LOOKBACK_DAYS)

    candidates_raw: list = []

    # --- 日本株 ---------------------------------------------------------------
    try:
        japan_chain = factory.build_chain("japan_equity")
        japan_tickers = universe_config.get("japan_equity", {}).get("tickers", [])
        candidates_raw.extend(
            _fetch_market_candidates(
                japan_chain, japan_tickers, "japan_equity", price_start, price_end,
                warning_errors, excluded_summary, degraded_sources,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("japan_equity chain build failed")
        critical_errors.append({"code": "SNAPSHOT_MISSING", "message": f"japan_equity chain構築に失敗: {exc}", "source_layer": "layer1"})
        japan_chain = None

    # --- 米国株 -----------------------------------------------------------------
    try:
        us_chain = factory.build_chain("us_equity")
        us_tickers = universe_config.get("us_equity", {}).get("tickers", [])
        candidates_raw.extend(
            _fetch_market_candidates(
                us_chain, us_tickers, "us_equity", price_start, price_end,
                warning_errors, excluded_summary, degraded_sources,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("us_equity chain build failed")
        critical_errors.append({"code": "SNAPSHOT_MISSING", "message": f"us_equity chain構築に失敗: {exc}", "source_layer": "layer1"})

    # --- マクロ（銘柄非依存、当日1回） -------------------------------------------
    try:
        macro_chain = factory.build_chain("macro")
        macro_series_map = _fetch_macro_series_map(macro_chain, macro_start, price_end, warning_errors)
    except Exception as exc:  # noqa: BLE001
        logger.exception("macro chain build failed")
        critical_errors.append({"code": "SNAPSHOT_MISSING", "message": f"macro chain構築に失敗: {exc}", "source_layer": "layer1"})
        macro_series_map = {}

    # --- 市場レジーム判定用の指数 -------------------------------------------------
    if japan_chain is not None:
        index_price_series = _fetch_index_series(japan_chain, price_start, price_end, critical_errors)
    else:
        index_price_series = _empty_price_series(NIKKEI225_INDEX_TICKER, "japan_equity chain unavailable")

    # --- ニュース（Layer1取得 → Layer3構造化） ------------------------------------
    structured_news_items: list = []
    try:
        news_chain = factory.build_chain("news")
        since = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
        until = datetime.now(timezone.utc)
        candidate_tickers = [c["ticker"] for c in candidates_raw]

        articles = layer3_fetcher.fetch_all(news_chain, MACRO_NEWS_QUERIES, candidate_tickers, since, until)

        structurer = build_structurer(ai_provider_config)
        # prompt_common.build_prompt()は{"ticker":..., "name":...}の辞書リストを期待する
        # （2026-07-22のライブ実行で判明した回帰：素のticker文字列リストを渡すと
        # `t['ticker']`アクセスでTypeErrorになる、tests/layer3/test_main.py参照）。
        universe_tickers = [{"ticker": c["ticker"], "name": c.get("name", c["ticker"])} for c in candidates_raw]
        sector_master = sorted(set(sector_mapping_config.get("sectors", {}).values()))

        result = layer3_main.process_articles(
            articles=articles,
            structurer=structurer,
            cache_store=cache_store,
            universe_tickers=universe_tickers,
            sector_master=sector_master,
            quality_filter_config=quality_filter_config,
            importance_rules_config=importance_rules_config,
            now=datetime.now(timezone.utc),
        )
        structured_news_items = result["structured_items"]
        if result["excluded"]:
            logger.info("layer3 quality filter excluded %d articles", len(result["excluded"]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("news pipeline (layer1 fetch + layer3 structuring) failed")
        warning_errors.append(
            {"code": "NEWS_API_FAILURE_PARTIAL", "message": f"ニュース取得・構造化に失敗: {exc}", "source_layer": "layer3"}
        )

    # --- Layer2（分析・スコアリング） --------------------------------------------
    # ギャップ4：config/risk_rules.yamlが未整備のため、全資産クラスneutralで暫定対応
    strategy_bias = {asset_class: "neutral" for asset_class in universe_config.keys()}

    layer2_output = layer2_main.run(
        run_id=run_id,
        analysis_started_at=started_at,
        candidates_raw=candidates_raw,
        index_price_series=index_price_series,
        macro_series_map=macro_series_map,
        news_items=structured_news_items,
        universe_config=universe_config,
        scoring_weights_config=scoring_weights_config,
        news_decay_config=news_decay_config,
        schema_compatibility_config=schema_compatibility_config,
        llm_input_config=llm_input_config,
        strategy_bias=strategy_bias,
        upstream_critical_errors=critical_errors,
        upstream_warning_errors=warning_errors,
        upstream_excluded_summary=excluded_summary,
        degraded_sources=sorted(degraded_sources),
    )

    logger.info(
        "layer2 output: %d candidates, %d critical_errors, %d warning_errors",
        len(layer2_output["candidates"]),
        len(layer2_output["run_meta"]["data_quality"]["critical_errors"]),
        len(layer2_output["run_meta"]["data_quality"]["warning_errors"]),
    )

    # --- Layer4（永続化） ---------------------------------------------------------
    oauth_token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not oauth_token_json or not folder_id:
        logger.error(
            "GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_DRIVE_FOLDER_ID not set; "
            "cannot persist layer2_output to Google Drive."
        )
        return 1

    repository = GoogleDriveRepository(oauth_token_json, folder_id)
    layer_status = {
        "layer1": "success" if not any(e["source_layer"] == "layer1" for e in critical_errors) else "failed",
        "layer2": "success",
        "layer3": "success" if not any(e.get("source_layer") == "layer3" for e in critical_errors) else "failed",
    }

    result = layer4_main.run(
        repository=repository,
        date_str=date_str,
        year_month=year_month,
        run_id=run_id,
        layer2_output=layer2_output,
        layer_status=layer_status,
        started_at=started_at,
    )

    if result.get("completed"):
        logger.info("=== run_daily_pipeline completed successfully: %s ===", result.get("snapshot_path"))
        return 0

    logger.error("=== run_daily_pipeline FAILED at layer4: %s ===", result)
    return 1


if __name__ == "__main__":
    sys.exit(main())
