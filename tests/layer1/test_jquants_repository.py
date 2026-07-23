"""JQuantsRepositoryのテスト（requests.getをモックし、V2 APIキー方式を検証する）。

get_daily_pricesのレスポンス形式は、GitHub Actions上でのライブ疎通確認
（2026-07-20、トヨタ自動車7203、config: plan=light）で得られた実際のレスポンスを
そのまま反映している（test_get_daily_prices_parses_real_jquants_v2_response参照）。
それ以外のメソッド（get_fundamentals等）はまだライブ検証できていない想定ベースの形。
"""

from datetime import date
from unittest.mock import patch

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    TransientError,
)
from ai_investment_assistant.layer1_data_acquisition.repositories.jquants import JQuantsRepository


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


def test_missing_api_key_raises_auth_error():
    with pytest.raises(AuthError):
        JQuantsRepository(api_key="")


def test_from_config_reads_env_var(monkeypatch):
    monkeypatch.setenv("JQUANTS_API_KEY", "test-key")
    repo = JQuantsRepository.from_config({"plan": "light", "price_delay_weeks": 0})
    assert repo.plan == "light"
    assert repo.is_delayed is False
    assert repo.delay_reason is None


def test_free_plan_sets_delay_flag():
    repo = JQuantsRepository(api_key="k", plan="free", price_delay_weeks=12)
    assert repo.is_delayed is True
    assert "12" in repo.delay_reason


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_daily_prices_parses_normalized_series(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            # ライブ疎通確認（scripts/layer1_live_check.py）で確認した実際のV2レスポンス形式
            "data": [
                {
                    "Date": "2026-07-16", "Code": "72030",
                    "O": 100.0, "H": 105.0, "L": 98.0, "C": 103.0, "Vo": 1_000_000.0, "Va": 103_000_000.0,
                    "UL": "0", "LL": "0", "AdjFactor": 1.0,
                    "AdjO": 100.0, "AdjH": 105.0, "AdjL": 98.0, "AdjC": 103.0, "AdjVo": 1_000_000.0,
                },
                {
                    "Date": "2026-07-17", "Code": "72030",
                    "O": 103.0, "H": 108.0, "L": 101.0, "C": 106.0, "Vo": 1_200_000.0, "Va": 127_200_000.0,
                    "UL": "0", "LL": "0", "AdjFactor": 1.0,
                    "AdjO": 103.0, "AdjH": 108.0, "AdjL": 101.0, "AdjC": 106.0, "AdjVo": 1_200_000.0,
                },
            ]
        },
    )
    repo = JQuantsRepository(api_key="k", plan="light", price_delay_weeks=0)

    series = repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))

    assert series.ticker == "7203"
    assert series.currency == "JPY"
    assert len(series.bars) == 2
    assert series.bars[0].close == 103.0
    assert series.meta.source_used == "jquants"
    assert series.meta.is_delayed is False


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_daily_prices_parses_real_jquants_v2_response(mock_get):
    """2026-07-20のGitHub Actionsライブ疎通確認で実際に返ってきたレスポンスの抜粋（トヨタ自動車7203）。

    このテストが失敗する場合、J-Quants側がレスポンス形式を変更した可能性があるため、
    再度ライブ確認のうえフィールド名マッピングを見直すこと。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "data": [
                {
                    "Date": "2026-07-06", "Code": "72030",
                    "O": 2855.0, "H": 2923.0, "L": 2839.0, "C": 2923.0,
                    "UL": "0", "LL": "0", "Vo": 26728000.0, "Va": 77519359100.0, "AdjFactor": 1.0,
                    "AdjO": 2855.0, "AdjH": 2923.0, "AdjL": 2839.0, "AdjC": 2923.0, "AdjVo": 26728000.0,
                },
                {
                    "Date": "2026-07-07", "Code": "72030",
                    "O": 2950.0, "H": 2980.0, "L": 2925.0, "C": 2946.0,
                    "UL": "0", "LL": "0", "Vo": 36408300.0, "Va": 107398051750.0, "AdjFactor": 1.0,
                    "AdjO": 2950.0, "AdjH": 2980.0, "AdjL": 2925.0, "AdjC": 2946.0, "AdjVo": 36408300.0,
                },
            ]
        },
    )
    repo = JQuantsRepository(api_key="k", plan="light", price_delay_weeks=0)

    series = repo.get_daily_prices("7203", date(2026, 7, 6), date(2026, 7, 7))

    assert len(series.bars) == 2
    assert series.bars[0].date == date(2026, 7, 6)
    assert series.bars[0].open == 2855.0
    assert series.bars[0].close == 2923.0
    assert series.bars[0].volume == 26728000
    assert series.bars[1].close == 2946.0

    called_headers = mock_get.call_args.kwargs["headers"]
    assert called_headers == {"x-api-key": "k"}


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_index_daily_prices_calls_indices_endpoint_and_parses_short_field_names(mock_get):
    """2026-07-24追加：市場レジーム判定の基準指数を日経平均株価（J-Quantsでは未提供）から
    TOPIX（指数コード"0000"）へ切り替えた際に新設したメソッドの回帰テスト。
    `/indices/bars/daily`を正しく叩き、get_daily_pricesと同じ短縮フィールド名
    （O/H/L/C）を優先的にマッピングすること。出来高の概念が無いためvolumeは常に0。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "data": [
                {"Date": "2026-07-16", "Code": "0000", "O": 2800.0, "H": 2820.0, "L": 2790.0, "C": 2810.0},
                {"Date": "2026-07-17", "Code": "0000", "O": 2810.0, "H": 2830.0, "L": 2805.0, "C": 2825.0},
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    series = repo.get_index_daily_prices("0000", date(2026, 7, 16), date(2026, 7, 17))

    called_path = mock_get.call_args.args[0]
    assert called_path == "https://api.jquants.com/v2/indices/bars/daily"
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["code"] == "0000"
    assert len(series.bars) == 2
    assert series.bars[0].close == 2810.0
    assert series.bars[1].close == 2825.0
    assert series.bars[0].volume == 0


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_index_daily_prices_falls_back_to_long_field_names(mock_get):
    """短縮形（O/H/L/C）が無い場合、正式名（Open/High/Low/Close）でも取れること。"""
    mock_get.return_value = FakeResponse(
        200,
        {"data": [{"Date": "2026-07-16", "Open": 2800.0, "High": 2820.0, "Low": 2790.0, "Close": 2810.0}]},
    )
    repo = JQuantsRepository(api_key="k")

    series = repo.get_index_daily_prices("0000", date(2026, 7, 16), date(2026, 7, 16))

    assert len(series.bars) == 1
    assert series.bars[0].close == 2810.0


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_index_daily_prices_missing_fields_skips_row_and_logs(mock_get, caplog):
    """想定したいずれのフィールド名も見つからない行は、クラッシュせずスキップし、
    診断のため実際の行データのキー一覧を警告ログに残す。
    """
    mock_get.return_value = FakeResponse(200, {"data": [{"Date": "2026-07-16", "unexpected": 1}]})
    repo = JQuantsRepository(api_key="k")

    with caplog.at_level("WARNING"):
        series = repo.get_index_daily_prices("0000", date(2026, 7, 16), date(2026, 7, 16))

    assert series.bars == ()
    assert any("unexpected" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "status_code,expected_exception",
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, TransientError),
        (503, TransientError),
    ],
)
@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_error_status_codes_map_to_expected_exceptions(mock_get, status_code, expected_exception):
    mock_get.return_value = FakeResponse(status_code, text="error detail")
    repo = JQuantsRepository(api_key="k")

    with pytest.raises(expected_exception):
        repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_fundamentals_calls_fins_summary_endpoint_and_parses_fields(mock_get):
    """2026-07-22のライブ実行で判明した誤りの回帰テスト：`/fins/summary`を正しく叩き、
    実際のフィールド名（DiscDate/CurPerType/Sales/OP/NP/EPS/TA/Eq/CFO/DivAnn）を
    FundamentalSnapshotへ正しくマッピングすること。トップレベルキーは`data`を優先する
    （2026-07-23追加：get_listed_universeと同じくJ-Quants V2共通の命名パターンのため）。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "data": [
                {
                    "DiscDate": "2026-05-10", "CurPerType": "FY", "Sales": 45_000_000_000_000.0,
                    "OP": 5_000_000_000_000.0, "NP": 4_500_000_000_000.0, "EPS": 350.5,
                    "TA": 70_000_000_000_000.0, "Eq": 30_000_000_000_000.0,
                    "CFO": 6_000_000_000_000.0, "DivAnn": 90.0,
                }
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    fundamentals = repo.get_fundamentals("7203")

    called_path = mock_get.call_args.args[0]
    assert called_path == "https://api.jquants.com/v2/fins/summary"
    assert fundamentals.fiscal_period == "FY"
    assert fundamentals.revenue == 45_000_000_000_000.0
    assert fundamentals.operating_income == 5_000_000_000_000.0
    assert fundamentals.net_income == 4_500_000_000_000.0
    assert fundamentals.eps == 350.5
    assert fundamentals.total_assets == 70_000_000_000_000.0
    assert fundamentals.net_assets == 30_000_000_000_000.0
    assert fundamentals.operating_cash_flow == 6_000_000_000_000.0
    assert fundamentals.dividend == 90.0
    # 公式ドキュメントでフィールド名が確認できなかった項目は、推測で埋めずNoneのまま
    assert fundamentals.capital_expenditure is None
    assert fundamentals.interest_bearing_debt is None


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_fundamentals_coerces_string_numeric_fields_to_float(mock_get):
    """2026-07-23のライブ実行で判明した回帰テスト：J-QuantsがNP/EPS等の数値項目を
    JSON文字列（例："4500000000000"）で返す場合があり、これがそのままFundamentalSnapshotに
    渡ると、呼び出し側（_estimate_market_cap等）でのfloat演算が
    `TypeError: unsupported operand type(s) for /: 'str' and 'str'`で落ちる原因になっていた。
    文字列で来てもfloatへ変換されることを確認する。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "data": [
                {
                    "CurPerType": "FY", "Sales": "45000000000000", "OP": "5000000000000",
                    "NP": "4500000000000", "EPS": "350.5", "TA": "70000000000000",
                    "Eq": "30000000000000", "CFO": "6000000000000", "DivAnn": "90",
                }
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    fundamentals = repo.get_fundamentals("7203")

    assert fundamentals.net_income == 4_500_000_000_000.0
    assert isinstance(fundamentals.net_income, float)
    assert fundamentals.eps == 350.5
    assert isinstance(fundamentals.eps, float)


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_fundamentals_still_supports_legacy_fins_summary_key(mock_get):
    """`data`キーが無い場合、後方互換として`fins_summary`キーも引き続き読めること。"""
    mock_get.return_value = FakeResponse(
        200, {"fins_summary": [{"CurPerType": "FY", "EPS": 100.0}]}
    )
    repo = JQuantsRepository(api_key="k")

    fundamentals = repo.get_fundamentals("7203")

    assert fundamentals.eps == 100.0


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_fundamentals_handles_empty_response(mock_get):
    mock_get.return_value = FakeResponse(200, {"data": []})
    repo = JQuantsRepository(api_key="k")

    fundamentals = repo.get_fundamentals("7203")

    assert fundamentals.ticker == "7203"
    assert fundamentals.eps is None


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_fundamentals_missing_known_keys_logs_diagnostic(mock_get, caplog):
    """想定したいずれのキー（data/fins_summary/summary）も見つからない場合、診断のため
    実際のトップレベルキー一覧を警告ログに残す（2026-07-23追加）。
    """
    mock_get.return_value = FakeResponse(200, {"unexpected_key": []})
    repo = JQuantsRepository(api_key="k")

    with caplog.at_level("WARNING"):
        fundamentals = repo.get_fundamentals("7203")

    assert fundamentals.eps is None
    assert any("unexpected_key" in record.message for record in caplog.records)


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_listed_universe_parses_real_field_names(mock_get):
    """2026-07-23のライブ実行で判明した回帰テスト（2回に分けて発覚）：
    1回目：行ごとのフィールド名がcode/name/sector_code/marketでは0件しか取得できなかった
    →Code/CoName/S33/Mktに修正。
    2回目：トップレベルのキーが'equities'ではなく'data'だった（診断ログで確認）→修正。
    market_capに対応するフィールドは確認できていないためNoneのまま。
    """
    mock_get.return_value = FakeResponse(
        200,
        {
            "data": [
                {"Code": "72030", "CoName": "トヨタ自動車", "S33": "3700", "Mkt": "プライム"}
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    universe = repo.get_listed_universe()

    assert len(universe) == 1
    assert universe[0].ticker == "72030"
    assert universe[0].name == "トヨタ自動車"
    assert universe[0].sector_code == "3700"
    assert universe[0].market == "プライム"
    assert universe[0].market_cap is None


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_listed_universe_missing_data_key_returns_empty_and_logs(mock_get, caplog):
    """想定した'data'キーがレスポンスに無い場合、例外にはせず空リストを返し、
    診断のため実際のトップレベルキー一覧を警告ログに残す（2026-07-23追加）。
    """
    mock_get.return_value = FakeResponse(200, {"unexpected_key": []})
    repo = JQuantsRepository(api_key="k")

    with caplog.at_level("WARNING"):
        universe = repo.get_listed_universe()

    assert universe == []
    assert any("unexpected_key" in record.message for record in caplog.records)


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_trading_calendar_filters_non_trading_days(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {
            "calendar": [
                {"date": "2026-07-17", "is_trading_day": True},
                {"date": "2026-07-18", "is_trading_day": False},
            ]
        },
    )
    repo = JQuantsRepository(api_key="k")

    calendar = repo.get_trading_calendar()

    assert calendar == [date(2026, 7, 17)]


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_get_earnings_calendar_parses_events(mock_get):
    mock_get.return_value = FakeResponse(
        200,
        {"events": [{"code": "7203", "date": "2026-08-05", "is_confirmed": True}]},
    )
    repo = JQuantsRepository(api_key="k")

    events = repo.get_earnings_calendar()

    assert len(events) == 1
    assert events[0].ticker == "7203"
    assert events[0].is_confirmed is True


@patch("ai_investment_assistant.layer1_data_acquisition.repositories.jquants.requests.get")
def test_connection_error_raises_transient_error(mock_get):
    import requests

    mock_get.side_effect = requests.ConnectionError("boom")
    repo = JQuantsRepository(api_key="k")

    with pytest.raises(TransientError):
        repo.get_daily_prices("7203", date(2026, 7, 16), date(2026, 7, 17))
