"""run_daily_pipeline.pyの`_fetch_bulk_prices`（2026-07-29追加のクールダウン機能）のテスト。

run_daily_pipeline.py自体はライブ運用スクリプトのためユニットテスト対象外だが、
`_fetch_bulk_prices`はchain・sleepの両方を差し替え可能なため、
tests/scripts/test_run_monthly_backup.pyと同じ方針でこの関数単体のロジックのみを検証する。
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_daily_pipeline import (  # noqa: E402
    BULK_FETCH_COOLDOWN_SECONDS,
    BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES,
    _fetch_bulk_prices,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_investment_assistant.layer1_data_acquisition.exceptions import (  # noqa: E402
    AllSourcesFailedError,
)
from ai_investment_assistant.layer1_data_acquisition.models import (  # noqa: E402
    DataFetchMeta,
    PriceSeries,
)


class FakeChain:
    """`chain.call("get_daily_prices", ticker, ...)`をticker指定で成功/失敗させるフェイク。"""

    def __init__(self, failing_tickers: set):
        self.failing_tickers = failing_tickers
        self.call_log: list = []

    def call(self, method_name, *args, **kwargs):
        ticker = args[0]
        self.call_log.append(ticker)
        if ticker in self.failing_tickers:
            raise AllSourcesFailedError(f"rate limited: {ticker}", errors=[])
        meta = DataFetchMeta(source_used="fake", fetched_at=datetime.now(timezone.utc))
        return PriceSeries(ticker=ticker, currency="JPY", bars=(), meta=meta)


def _fake_sleep_recorder():
    calls = []

    def _sleep(seconds):
        calls.append(seconds)

    return _sleep, calls


def test_fetch_bulk_prices_all_succeed_no_cooldown():
    tickers = ["A", "B", "C"]
    chain = FakeChain(failing_tickers=set())
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(chain, tickers, "japan_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn)

    assert [c["ticker"] for c in result] == tickers
    assert sleep_calls == []


def test_fetch_bulk_prices_isolated_failures_do_not_trigger_cooldown():
    # 失敗が連続しない（間に成功が挟まる）限り、クールダウンは発動しない
    tickers = ["A", "F", "B", "F", "C", "F", "D"]
    chain = FakeChain(failing_tickers={"F"})
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(chain, tickers, "japan_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn)

    assert [c["ticker"] for c in result] == ["A", "B", "C", "D"]
    assert sleep_calls == []


def test_fetch_bulk_prices_triggers_cooldown_after_consecutive_failures():
    # 連続失敗がBULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES回に達したらクールダウンする
    n = BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES
    failing = [f"F{i}" for i in range(n)]
    tickers = failing + ["RECOVERED"]
    chain = FakeChain(failing_tickers=set(failing))
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(chain, tickers, "us_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn)

    assert sleep_calls == [BULK_FETCH_COOLDOWN_SECONDS]
    # クールダウン後は失敗カウントがリセットされ、後続の成功銘柄は正しく取得される
    assert [c["ticker"] for c in result] == ["RECOVERED"]


def test_fetch_bulk_prices_cooldown_triggers_at_most_once_per_call():
    # クールダウンしても回復しない場合、無限に待ち続けず1回だけで打ち切る
    n = BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES
    all_failing_tickers = [f"F{i}" for i in range(n * 3)]  # 閾値の3倍、全て失敗
    chain = FakeChain(failing_tickers=set(all_failing_tickers))
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(
        chain, all_failing_tickers, "japan_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn
    )

    assert result == []
    # 全銘柄失敗でも、クールダウンは高々1回のみ（際限なく待ち続けない）
    assert sleep_calls == [BULK_FETCH_COOLDOWN_SECONDS]


def test_fetch_bulk_prices_default_sleep_parameter_is_time_sleep():
    import time

    from run_daily_pipeline import _fetch_bulk_prices as fn

    assert fn.__defaults__[-1] is time.sleep
