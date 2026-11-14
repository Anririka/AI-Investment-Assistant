"""FinancialModelingPrepRepositoryのテスト（requests.getをモックして検証する）。"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.fmp import (
    FinancialModelingPrepRepository,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        FinancialModelingPrepRepository(api_key="")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_get_fundamentals_parses_statements_and_profile(mock_get):
    def fake_get(url, params=None, timeout=None):
        if "income-statement" in url:
            return FakeResponse(200, [{"date": "2026-06-30", "eps": "6.5", "netIncome": "2.3e10", "revenue": "9.0e10", "operatingIncome": "3.0e10"}])
        if "balance-sheet-statement" in url:
            return FakeResponse(200, [{"totalStockholdersEquity": "6.0e10", "totalDebt": "1.0e10", "totalAssets": "3.5e11"}])
        if "cash-flow-statement" in url:
            return FakeResponse(200, [{"operatingCashFlow": "2.8e10", "capitalExpenditure": "-1.0e10"}])
        if "profile" in url:
            return FakeResponse(200, [{"lastDiv": "0.96", "mktCap": "2.9e12"}])
        raise AssertionError(f"unexpected path for url={url}")

    mock_get.side_effect = fake_get
    repo = FinancialModelingPrepRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    assert snapshot.ticker == "AAPL"
    assert snapshot.fiscal_period == "2026-06-30"
    assert snapshot.eps == 6.5
    assert snapshot.net_income == 2.3e10
    assert snapshot.revenue == 9.0e10
    assert snapshot.operating_income == 3.0e10
    assert snapshot.net_assets == 6.0e10
    assert snapshot.interest_bearing_debt == 1.0e10
    assert snapshot.total_assets == 3.5e11
    assert snapshot.operating_cash_flow == 2.8e10
    assert snapshot.capital_expenditure == -1.0e10
    assert snapshot.dividend == 0.96
    assert snapshot.market_cap == 2.9e12
    assert snapshot.meta.source_used == "fmp"


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_requests_use_stable_path_with_symbol_as_query_param(mock_get):
    # 2026-11-14追加：旧/api/v3/{path}/{ticker}（pathセグメント）ではなく、
    # 新しい/stable/{path}?symbol={ticker}（クエリパラメータ）で呼んでいることを
    # 固定する回帰テスト（実運用でlegacyエンドポイント扱いの403を受けて発覚した不具合）。
    mock_get.return_value = FakeResponse(200, [])
    repo = FinancialModelingPrepRepository(api_key="k")

    repo.get_fundamentals("AAPL")

    called_urls = [call.args[0] for call in mock_get.call_args_list]
    called_params = [call.kwargs.get("params", {}) for call in mock_get.call_args_list]
    assert all("/stable/" in url for url in called_urls)
    assert all("/api/v3/" not in url for url in called_urls)
    assert all("AAPL" not in url for url in called_urls), "ticker must not be in the URL path"
    assert all(params.get("symbol") == "AAPL" for params in called_params)


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_get_fundamentals_parses_real_stable_income_statement_response(mock_get):
    # 2026-11-14追加：実際にFMPの/stable/income-statement?symbol=AAPLを叩いて
    # 得られた本物のレスポンス（フィールド名確認用）をそのまま使う回帰テスト。
    real_income_statement_sample = [
        {
            "date": "2026-09-26",
            "symbol": "AAPL",
            "fiscalYear": "2026",
            "period": "FY",
            "revenue": 478834000000,
            "operatingIncome": 158063000000,
            "netIncome": 132175000000,
            "eps": 9.01,
        },
        {
            "date": "2025-09-27",
            "symbol": "AAPL",
            "fiscalYear": "2025",
            "period": "FY",
            "revenue": 416161000000,
            "operatingIncome": 133050000000,
            "netIncome": 112010000000,
            "eps": 7.49,
        },
    ]

    def fake_get(url, params=None, timeout=None):
        if "income-statement" in url:
            return FakeResponse(200, real_income_statement_sample)
        return FakeResponse(200, [])

    mock_get.side_effect = fake_get
    repo = FinancialModelingPrepRepository(api_key="k")

    snapshot = repo.get_fundamentals("AAPL")

    # _latestは先頭要素（最新の決算）を使う
    assert snapshot.fiscal_period == "2026-09-26"
    assert snapshot.revenue == 478834000000
    assert snapshot.operating_income == 158063000000
    assert snapshot.net_income == 132175000000
    assert snapshot.eps == 9.01


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_get_fundamentals_missing_statements_defaults_to_none(mock_get):
    def fake_get(url, params=None, timeout=None):
        if "profile" in url:
            return FakeResponse(200, [])
        return FakeResponse(200, [])

    mock_get.side_effect = fake_get
    repo = FinancialModelingPrepRepository(api_key="k")

    snapshot = repo.get_fundamentals("UNKNOWNTICKER")

    assert snapshot.eps is None
    assert snapshot.net_income is None
    assert snapshot.market_cap is None
    assert snapshot.fiscal_period == ""


@pytest.mark.parametrize(
    "code,expected_exception",
    [(401, AuthError), (403, AuthError)],
)
@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_status_error_code_maps_to_exceptions(mock_get, code, expected_exception):
    mock_get.return_value = FakeResponse(code, {}, text="error")
    repo = FinancialModelingPrepRepository(api_key="k")

    with pytest.raises(expected_exception):
        repo.get_fundamentals("AAPL")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_error_message_with_limit_wording_raises_rate_limit_error(mock_get):
    mock_get.return_value = FakeResponse(
        200, {"Error Message": "Limit Reach . Please upgrade your plan or visit our documentation"}
    )
    repo = FinancialModelingPrepRepository(api_key="k")

    with pytest.raises(RateLimitError):
        repo.get_fundamentals("AAPL")


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.fmp.requests.get")
def test_error_message_without_limit_wording_raises_not_found(mock_get):
    mock_get.return_value = FakeResponse(200, {"Error Message": "Invalid ticker symbol"})
    repo = FinancialModelingPrepRepository(api_key="k")

    with pytest.raises(NotFoundError):
        repo.get_fundamentals("AAPL")


def test_unsupported_methods_raise_not_implemented():
    repo = FinancialModelingPrepRepository(api_key="k")

    with pytest.raises(NotImplementedError):
        repo.get_daily_prices("AAPL", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(NotImplementedError):
        repo.get_listed_universe()
    with pytest.raises(NotImplementedError):
        repo.get_trading_calendar()
    with pytest.raises(NotImplementedError):
        repo.get_earnings_calendar()
