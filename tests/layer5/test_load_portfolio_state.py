"""load_portfolio_state.pyのテスト（layer5_ai_judgment_design.md §4-2、§12テスト方針）。

取引記録_*.csvの実際の列（ユーザー提供xlsxから確認済み）に準拠する：
日付, 資産クラス, 銘柄名, 証券コード, 売買種別, 株数, 約定単価, 手数料, 為替レート,
損切りライン, 利確ライン, AI提案根拠要約, AI信頼度, 保有ステータス, 実現損益, メモ
"""

import pytest

from ai_investment_assistant.layer5_ai_judgment.scripts.load_portfolio_state import (
    PortfolioStateError,
    build_portfolio_state,
    parse_trade_record_csv,
    resolve_total_capital,
    run_load_portfolio_state,
)

HEADER = (
    "日付,資産クラス,銘柄名,証券コード,売買種別,株数,約定単価,手数料,為替レート,"
    "損切りライン,利確ライン,AI提案根拠要約,AI信頼度,保有ステータス,実現損益,メモ"
)

SECTOR_MAPPING = {"7203": "automobile", "NVDA": "semiconductor"}


def _row(**overrides):
    base = {
        "日付": "2026-07-01", "資産クラス": "japan_equity", "銘柄名": "トヨタ自動車",
        "証券コード": "7203", "売買種別": "buy", "株数": "100", "約定単価": "2500",
        "手数料": "500", "為替レート": "1", "損切りライン": "2250", "利確ライン": "2875",
        "AI提案根拠要約": "test", "AI信頼度": "78", "保有ステータス": "保有中",
        "実現損益": "", "メモ": "",
    }
    base.update(overrides)
    return base


def test_parse_trade_record_csv_header_only_returns_empty_list():
    text = HEADER + "\n"
    rows = parse_trade_record_csv(text)
    assert rows == []


def test_parse_trade_record_csv_missing_required_column_raises():
    with pytest.raises(PortfolioStateError):
        parse_trade_record_csv("日付,資産クラス\n2026-07-01,japan_equity\n")


def test_resolve_total_capital_uses_test_phase_when_enabled():
    policy = {"full_scale": {"total_capital": 3000000}, "test_phase": {"enabled": True, "total_capital": 250000}}
    assert resolve_total_capital(policy) == 250000


def test_resolve_total_capital_uses_full_scale_when_test_phase_disabled():
    policy = {"full_scale": {"total_capital": 3000000}, "test_phase": {"enabled": False, "total_capital": 250000}}
    assert resolve_total_capital(policy) == 3000000


def test_resolve_total_capital_ignores_planned_dates_even_if_period_has_elapsed():
    # planned_start_date/planned_end_dateは人間向けの目安の記録用フィールドであり、
    # resolve_total_capital()はこれらを一切参照しない（期限切れでも自動でfalseに
    # ならないことを保証する。config/capital_policy.yamlのコメント参照）。
    policy = {
        "full_scale": {"total_capital": 3000000},
        "test_phase": {
            "enabled": True, "total_capital": 250000,
            "planned_start_date": "2020-01-01", "planned_end_date": "2020-02-01",
            "planned_duration_days": 30,
        },
    }
    assert resolve_total_capital(policy) == 250000


def test_build_portfolio_state_no_holdings_gives_full_available_capital():
    state = build_portfolio_state([], total_capital=250000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert state["total_invested"] == 0
    assert state["available_capital"] == 250000
    assert state["positions"] == []


def test_build_portfolio_state_only_counts_holding_status_rows():
    rows = [_row(保有ステータス="保有中"), _row(証券コード="9984", 保有ステータス="決済済み")]
    state = build_portfolio_state(rows, total_capital=3000000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert len(state["positions"]) == 1
    assert state["positions"][0]["ticker"] == "7203"


def test_build_portfolio_state_computes_invested_amount_and_available_capital():
    rows = [_row(株数="100", 約定単価="2500", 為替レート="1")]
    state = build_portfolio_state(rows, total_capital=3000000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert state["total_invested"] == 250000
    assert state["available_capital"] == 2750000


def test_build_portfolio_state_applies_fx_rate_for_us_equity():
    rows = [_row(証券コード="NVDA", 資産クラス="us_equity", 株数="10", 約定単価="333.74", 為替レート="150")]
    state = build_portfolio_state(rows, total_capital=3000000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert state["positions"][0]["invested_amount"] == pytest.approx(10 * 333.74 * 150)


def test_build_portfolio_state_sector_concentration_aggregates_by_sector():
    rows = [_row(証券コード="7203", 株数="100", 約定単価="2500"),
            _row(証券コード="7203", 株数="50", 約定単価="2500", 日付="2026-07-02")]
    state = build_portfolio_state(rows, total_capital=3000000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert state["sector_concentration"]["automobile"] == pytest.approx(150 * 2500)


def test_build_portfolio_state_unknown_ticker_maps_to_unknown_sector():
    rows = [_row(証券コード="9999")]
    state = build_portfolio_state(rows, total_capital=3000000, sector_mapping=SECTOR_MAPPING, as_of="2026-07-18T06:00:00Z")
    assert state["positions"][0]["sector"] == "unknown"


class FakeDriveClient:
    def __init__(self, latest=None):
        self._latest = latest

    def read_latest_text_by_prefix(self, subfolder, name_prefix):
        return self._latest


def test_run_load_portfolio_state_no_file_yet_returns_empty_positions():
    client = FakeDriveClient(latest=None)
    capital_policy = {"full_scale": {"total_capital": 3000000}, "test_phase": {"enabled": True, "total_capital": 250000}}
    result = run_load_portfolio_state(client, capital_policy, SECTOR_MAPPING)
    assert result["status"] == "ok"
    assert result["portfolio_state"]["positions"] == []
    assert result["portfolio_state"]["total_capital"] == 250000


def test_run_load_portfolio_state_reads_latest_csv():
    text = HEADER + "\n" + ",".join(_row().values()) + "\n"
    client = FakeDriveClient(latest=("取引記録_20260717T014126Z.csv", text))
    capital_policy = {"full_scale": {"total_capital": 3000000}, "test_phase": {"enabled": False, "total_capital": 250000}}
    result = run_load_portfolio_state(client, capital_policy, SECTOR_MAPPING)
    assert result["status"] == "ok"
    assert len(result["portfolio_state"]["positions"]) == 1


def test_run_load_portfolio_state_invalid_csv_returns_blocked():
    client = FakeDriveClient(latest=("取引記録_bad.csv", "日付,資産クラス\nx,y\n"))
    capital_policy = {"full_scale": {"total_capital": 3000000}, "test_phase": {"enabled": False, "total_capital": 250000}}
    result = run_load_portfolio_state(client, capital_policy, SECTOR_MAPPING)
    assert result["status"] == "blocked"
    assert result["reason_code"] == "PORTFOLIO_STATE_INVALID"
