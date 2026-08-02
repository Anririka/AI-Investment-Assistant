"""run_daily_pipeline.pyの`_fetch_market_candidates`（2026-08-02追加の`price_chain`分離）のテスト。

背景：米国株のus_equityチェーン（先頭候補alpha_vantage）の`get_daily_prices`は、無料/Basic
プランではoutputsize=fullパラメータが使えず常に失敗する実装上のバグがあった（実運用ログで
判明）。結果的にTwelve Dataへ毎回フォールバックしており実害は無かったが、無駄な待ち時間が
発生していた。`price_chain`を明示的に渡すことで、get_daily_pricesだけを別チェーン
（Twelve Data単独のus_equity_bulk_price）に向け、get_fundamentalsは従来通り
alpha_vantage優先のchainに残す。
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_daily_pipeline import _fetch_market_candidates  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_investment_assistant.layer1_data_acquisition.models import (  # noqa: E402
    DataFetchMeta,
    FundamentalSnapshot,
    PriceSeries,
)


class FakeChain:
    """`chain.call(method_name, *args)`のみを公開する、実物のFallbackChainRepositoryを模したフェイク。

    `label`はどのチェーンに向けて呼ばれたかをテストで判別するためのマーカー。
    """

    def __init__(self, label: str):
        self.label = label
        self.last_source_used = label
        self.calls: list = []

    def call(self, method_name, *args, **kwargs):
        self.calls.append(method_name)
        if method_name == "get_listed_universe":
            return []
        if method_name == "get_daily_prices":
            meta = DataFetchMeta(source_used=self.label, fetched_at=datetime.now(timezone.utc))
            return PriceSeries(ticker=args[0], currency="USD", bars=(), meta=meta)
        if method_name == "get_fundamentals":
            meta = DataFetchMeta(source_used=self.label, fetched_at=datetime.now(timezone.utc))
            return FundamentalSnapshot(
                ticker=args[0], fiscal_period="2026Q1", eps=1.0, net_assets=None, net_income=None,
                revenue=None, operating_income=None, operating_cash_flow=None, capital_expenditure=None,
                interest_bearing_debt=None, total_assets=None, dividend=None, meta=meta, market_cap=100.0,
            )
        raise AssertionError(f"unexpected method_name={method_name}")


def test_price_chain_used_for_get_daily_prices_when_provided():
    fundamentals_chain = FakeChain("alpha_vantage_chain")
    price_chain = FakeChain("twelve_data_bulk_chain")

    _fetch_market_candidates(
        fundamentals_chain, ["AAPL"], "us_equity", date(2026, 1, 1), date(2026, 1, 2),
        warning_errors=[], excluded_summary=[], degraded_sources=set(),
        price_chain=price_chain,
    )

    assert "get_daily_prices" in price_chain.calls
    assert "get_daily_prices" not in fundamentals_chain.calls
    assert "get_fundamentals" in fundamentals_chain.calls
    assert "get_fundamentals" not in price_chain.calls


def test_chain_used_for_both_when_price_chain_omitted():
    # japan_equity等、price_chain未指定の資産クラス向けの後方互換
    chain = FakeChain("japan_equity_chain")

    _fetch_market_candidates(
        chain, ["7203"], "japan_equity", date(2026, 1, 1), date(2026, 1, 2),
        warning_errors=[], excluded_summary=[], degraded_sources=set(),
    )

    assert "get_daily_prices" in chain.calls
    assert "get_fundamentals" in chain.calls


def test_candidate_built_correctly_with_split_chains():
    fundamentals_chain = FakeChain("alpha_vantage_chain")
    price_chain = FakeChain("twelve_data_bulk_chain")

    result = _fetch_market_candidates(
        fundamentals_chain, ["AAPL"], "us_equity", date(2026, 1, 1), date(2026, 1, 2),
        warning_errors=[], excluded_summary=[], degraded_sources=set(),
        price_chain=price_chain,
    )

    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["price_series"].meta.source_used == "twelve_data_bulk_chain"
    assert result[0]["fundamentals"].meta.source_used == "alpha_vantage_chain"
