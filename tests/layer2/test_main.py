"""main.py（Layer2パイプライン全体）の統合テスト（layer2_analysis_design.md §3-7〜§3-10）。

test_schema_validation.pyが確認する「個々のモジュールを手で繋いだ場合の出力形式」を
前提に、本テストは「main.run()がその配線を正しく行うこと」と「1銘柄・1データソースの
異常が全体を止めないこと（毒薬テスト）」を確認する。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
import yaml

from ai_investment_assistant.layer1_data_acquisition.models import (
    DataFetchMeta,
    FundamentalSnapshot,
    PriceBar,
    PriceSeries,
    TimeSeries,
    TimeSeriesPoint,
)
from ai_investment_assistant.layer2_analysis import main

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SCHEMA_PATH = (
    REPO_ROOT / "src" / "ai_investment_assistant" / "layer2_analysis" / "schemas" / "layer2_output.schema.json"
)


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def universe_config():
    return _load_yaml("universe.yaml")


@pytest.fixture(scope="module")
def scoring_weights_config():
    return _load_yaml("scoring_weights.yaml")


@pytest.fixture(scope="module")
def news_decay_config():
    return _load_yaml("news_decay.yaml")


@pytest.fixture(scope="module")
def schema_compatibility_config():
    return _load_yaml("schema_compatibility.yaml")


@pytest.fixture(scope="module")
def llm_input_config():
    return _load_yaml("llm_input.yaml")


def _price_series(ticker, start_price=1000.0, days=300, volume=2_000_000):
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    bars = tuple(
        PriceBar(
            date=date(2025, 1, 1) + timedelta(days=i),
            open=start_price + i * 0.5,
            high=(start_price + i * 0.5) * 1.01,
            low=(start_price + i * 0.5) * 0.99,
            close=start_price + i * 0.5,
            volume=volume + i * 10,
        )
        for i in range(days)
    )
    return PriceSeries(ticker=ticker, currency="JPY", bars=bars, meta=meta)


def _empty_price_series(ticker):
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    return PriceSeries(ticker=ticker, currency="JPY", bars=(), meta=meta)


def _fundamentals(ticker, net_income=5e9, net_assets=1e11, dividend=10.0):
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    return FundamentalSnapshot(
        ticker=ticker, fiscal_period="2026Q1", eps=100.0, net_assets=net_assets, net_income=net_income,
        revenue=1e12, operating_income=8e10, operating_cash_flow=9e10, capital_expenditure=2e10,
        interest_bearing_debt=2e11, total_assets=5e11, dividend=dividend, meta=meta,
    )


def _macro_series_map():
    meta = DataFetchMeta(source_used="dummy", fetched_at=datetime(2026, 7, 20))
    ids = ["us_10y_yield", "fed_funds_rate", "unemployment_rate", "cpi_yoy", "ppi_yoy", "gdp_growth", "leading_index"]
    return {
        sid: TimeSeries(
            series_id=sid,
            points=(TimeSeriesPoint(date=date(2026, 5, 1), value=2.0), TimeSeriesPoint(date=date(2026, 6, 1), value=1.9)),
            meta=meta,
        )
        for sid in ids
    }


def _index_series():
    return _price_series("NIKKEI225", start_price=30000, days=300, volume=1)


def _news_item(ticker, direction="positive", schema_version="1.0", importance=80, confidence=0.9):
    return {
        "news_schema_version": schema_version,
        "item_id": f"item-{ticker}-{direction}",
        "headline": f"{ticker}の{direction}なニュース",
        "source_name": "TestWire",
        "source_url": f"https://example.com/{ticker}",
        "affected_companies": [{"ticker": ticker, "name": ticker, "relevance": "primary"}],
        "affected_sectors": [],
        "impact_direction": direction,
        "impact_horizon": "mid_term",
        "importance": importance,
        "confidence": confidence,
        "category": "product",
        "published_at": "2026-07-18T03:15:00Z",
        "age_hours": 5.0,
    }


def _base_candidate(ticker="7203", asset_class="japan_equity", market_cap=2e11):
    return {
        "ticker": ticker,
        "asset_class": asset_class,
        "name": f"{ticker} Inc.",
        "style_tags": ["growth"],
        "sector_code": "electronics",
        "price_series": _price_series(ticker),
        "fundamentals": _fundamentals(ticker),
        "market_cap": market_cap,
        "avg_volume": 2_000_000,
        "is_delayed": False,
    }


def _run_kwargs(
    candidates_raw,
    universe_config,
    scoring_weights_config,
    news_decay_config,
    schema_compatibility_config,
    llm_input_config,
    news_items=None,
):
    return dict(
        run_id="20260722-0600",
        analysis_started_at=datetime(2026, 7, 22, 6, 0, 0),
        candidates_raw=candidates_raw,
        index_price_series=_index_series(),
        macro_series_map=_macro_series_map(),
        news_items=news_items or [],
        universe_config=universe_config,
        scoring_weights_config=scoring_weights_config,
        news_decay_config=news_decay_config,
        schema_compatibility_config=schema_compatibility_config,
        llm_input_config=llm_input_config,
        strategy_bias={"japan_equity": "neutral", "us_equity": "growth_tilt"},
        clock=lambda: datetime(2026, 7, 22, 6, 5, 0),
    )


# --- happy path -------------------------------------------------------------------


def test_full_pipeline_output_validates_against_schema(
    schema, universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    candidates = [
        _base_candidate("7203", "japan_equity", market_cap=2e11),
        _base_candidate("AAPL", "us_equity", market_cap=5e10),
    ]
    news_items = [_news_item("7203")]

    output = main.run(
        **_run_kwargs(
            candidates, universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, llm_input_config, news_items=news_items,
        )
    )

    jsonschema.validate(instance=output, schema=schema)
    tickers = {c["ticker"] for c in output["candidates"]}
    assert tickers == {"7203", "AAPL"}
    assert output["run_meta"]["data_quality"]["critical_errors"] == []
    assert output["regime"]["strategy_bias"]["us_equity"] == "growth_tilt"


def test_relevant_news_only_attached_to_matching_ticker(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    candidates = [
        _base_candidate("7203", "japan_equity", market_cap=2e11),
        _base_candidate("AAPL", "us_equity", market_cap=5e10),
    ]
    news_items = [_news_item("7203")]

    output = main.run(
        **_run_kwargs(
            candidates, universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, llm_input_config, news_items=news_items,
        )
    )

    by_ticker = {c["ticker"]: c for c in output["candidates"]}
    assert len(by_ticker["7203"]["news"]["relevant_items"]) == 1
    assert by_ticker["AAPL"]["news"]["relevant_items"] == []
    assert by_ticker["AAPL"]["news"]["score"] == 50  # 該当ニュースなし＝中立


# --- screener除外（母集団フィルタ） -------------------------------------------------


def test_screener_excludes_candidate_below_min_market_cap_but_pipeline_continues(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    small_cap_candidate = _base_candidate("6861", "japan_equity", market_cap=1.0)  # 明らかに下限未満
    ok_candidate = _base_candidate("7203", "japan_equity", market_cap=2e11)

    output = main.run(
        **_run_kwargs(
            [small_cap_candidate, ok_candidate], universe_config, scoring_weights_config,
            news_decay_config, schema_compatibility_config, llm_input_config,
        )
    )

    tickers = {c["ticker"] for c in output["candidates"]}
    assert tickers == {"7203"}
    excluded_tickers = {e["ticker"]: e["reason_code"] for e in output["excluded_summary"]}
    assert excluded_tickers["6861"] == "MARKET_CAP_TOO_SMALL"


# --- 毒薬テスト：1銘柄のスコア計算失敗が全体を止めない ------------------------------


def test_poison_pill_one_candidate_scoring_failure_does_not_crash_run(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    broken = _base_candidate("6861", "japan_equity", market_cap=2e11)
    broken["price_series"] = _empty_price_series("6861")  # 価格データが空＝計算不能を誘発
    healthy = _base_candidate("7203", "japan_equity", market_cap=2e11)

    output = main.run(
        **_run_kwargs(
            [broken, healthy], universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, llm_input_config,
        )
    )

    tickers = {c["ticker"] for c in output["candidates"]}
    assert tickers == {"7203"}  # 壊れた銘柄は除外されるが、健全な銘柄は正常に処理される

    critical_codes = [e["code"] for e in output["run_meta"]["data_quality"]["critical_errors"]]
    assert "SCORING_FAILED" in critical_codes

    excluded_tickers = {e["ticker"]: e["reason_code"] for e in output["excluded_summary"]}
    assert excluded_tickers["6861"] == "SCORING_FAILED"


# --- 毒薬テスト：ニュースのnews_schema_versionメジャー不一致 -----------------------


def test_invalid_news_schema_version_is_excluded_but_pipeline_continues(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    candidates = [_base_candidate("7203", "japan_equity", market_cap=2e11)]
    news_items = [
        _news_item("7203", direction="positive", schema_version="1.0"),
        _news_item("7203", direction="negative", schema_version="2.0"),  # メジャー不一致
    ]

    output = main.run(
        **_run_kwargs(
            candidates, universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, llm_input_config, news_items=news_items,
        )
    )

    critical_codes = [e["code"] for e in output["run_meta"]["data_quality"]["critical_errors"]]
    assert "SCHEMA_VERSION_ERROR" in critical_codes

    # 不正な記事は除外されるが、正常な記事は引き続きニュース軸に反映され、
    # パイプライン全体は正常に完了する（該当銘柄も除外されない）。
    candidate = output["candidates"][0]
    assert len(candidate["news"]["relevant_items"]) == 1
    assert candidate["news"]["relevant_items"][0]["impact_direction"] == "positive"


# --- macroセクター感応度補正（Ver1はデフォルト1.0でno-op） --------------------------


def test_macro_sector_correction_default_is_noop(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    candidates = [_base_candidate("7203", "japan_equity", market_cap=2e11)]

    output = main.run(
        **_run_kwargs(
            candidates, universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, llm_input_config,
        )
    )

    candidate = output["candidates"][0]
    assert candidate["macro_axis_score_ref"] == output["macro"]["axis_score"]


# --- プロンプト予算超過時の調整 ----------------------------------------------------


def test_prompt_budget_exceeded_drops_candidates_and_records_reason(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config
):
    candidates = [
        _base_candidate("7203", "japan_equity", market_cap=2e11),
        _base_candidate("6861", "japan_equity", market_cap=2e11),
    ]
    tiny_budget_config = {
        "candidate_limits": {"japan_equity": 10, "us_equity": 10},
        "max_total_candidates": 30,
        "prompt_budget": {"claude": 10},  # 現実的にあり得ないほど小さい予算
        "active_provider": "claude",
    }

    output = main.run(
        **_run_kwargs(
            candidates, universe_config, scoring_weights_config, news_decay_config,
            schema_compatibility_config, tiny_budget_config,
        )
    )

    assert output["candidates"] == []
    reason_codes = {e["reason_code"] for e in output["excluded_summary"]}
    assert "PROMPT_BUDGET_EXCEEDED" in reason_codes
    assert output["run_meta"]["data_quality"]["excluded_candidates_count"] == len(output["excluded_summary"])


# --- upstream（Layer1/Layer3）由来のエラー・除外銘柄の引き継ぎ ---------------------


def test_upstream_errors_and_excluded_summary_are_propagated(
    universe_config, scoring_weights_config, news_decay_config, schema_compatibility_config, llm_input_config
):
    candidates = [_base_candidate("7203", "japan_equity", market_cap=2e11)]
    kwargs = _run_kwargs(
        candidates, universe_config, scoring_weights_config, news_decay_config,
        schema_compatibility_config, llm_input_config,
    )
    kwargs["upstream_critical_errors"] = [
        {"code": "SINGLE_STOCK_DATA_FAILURE", "message": "AAPL fetch failed", "source_layer": "layer1"}
    ]
    kwargs["upstream_excluded_summary"] = [
        {"ticker": "AAPL", "asset_class": "us_equity", "reason_code": "SINGLE_STOCK_DATA_FAILURE", "reason": "取得失敗"}
    ]
    kwargs["degraded_sources"] = ["jquants:price_delayed"]

    output = main.run(**kwargs)

    codes = [e["code"] for e in output["run_meta"]["data_quality"]["critical_errors"]]
    assert "SINGLE_STOCK_DATA_FAILURE" in codes
    excluded_tickers = {e["ticker"] for e in output["excluded_summary"]}
    assert "AAPL" in excluded_tickers
    assert output["run_meta"]["data_quality"]["degraded_sources"] == ["jquants:price_delayed"]
