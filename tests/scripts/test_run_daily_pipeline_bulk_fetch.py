"""run_daily_pipeline.pyの`_fetch_bulk_prices`（2026-07-29追加のクールダウン機能）のテスト。

run_daily_pipeline.py自体はライブ運用スクリプトのためユニットテスト対象外だが、
`_fetch_bulk_prices`はchain・sleepの両方を差し替え可能なため、
tests/scripts/test_run_monthly_backup.pyと同じ方針でこの関数単体のロジックのみを検証する。
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_daily_pipeline import (  # noqa: E402
    BULK_FETCH_COOLDOWN_SECONDS,
    BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES,
    BULK_FETCH_MAX_COOLDOWNS_PER_RUN,
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


class FakeChainRaisingArbitraryException:
    """特定ticker呼び出し時に、DataSourceErrorのサブクラスではない任意の例外を送出するフェイク。

    2026-08-25・26の実障害（requests.exceptions.ChunkedEncodingErrorがどの
    Repository実装のexcept節でも変換されないまま素通りし、stage1のus_equity_bulk_price
    スキャン全体がcriticalになった件）の回帰テスト用。対策②（_fetch_bulk_prices側の
    捕捉範囲拡張）が、対策①（各Repositoryでの変換）に頼らずとも単体で機能することを
    確認する。
    """

    def __init__(self, exceptions_by_ticker: dict):
        self.exceptions_by_ticker = exceptions_by_ticker
        self.call_log: list = []

    def call(self, method_name, *args, **kwargs):
        ticker = args[0]
        self.call_log.append(ticker)
        if ticker in self.exceptions_by_ticker:
            raise self.exceptions_by_ticker[ticker]
        meta = DataFetchMeta(source_used="fake", fetched_at=datetime.now(timezone.utc))
        return PriceSeries(ticker=ticker, currency="USD", bars=(), meta=meta)


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


def test_fetch_bulk_prices_cooldown_can_trigger_multiple_times_and_recover_each_time():
    # 2026-08-05修正：終盤で連続失敗が始まり、そこから実行終了まで一切回復しない
    # パターンが実運用ログで繰り返し観測されたため、クールダウンを複数回まで許可する
    # ようにした。連続失敗のブロックが複数回発生しても、それぞれクールダウン後に
    # 回復できることを検証する。
    n = BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES
    block1 = [f"F1_{i}" for i in range(n)]
    block2 = [f"F2_{i}" for i in range(n)]
    tickers = block1 + ["RECOVERED1"] + block2 + ["RECOVERED2"]
    chain = FakeChain(failing_tickers=set(block1) | set(block2))
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(
        chain, tickers, "japan_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn
    )

    assert [c["ticker"] for c in result] == ["RECOVERED1", "RECOVERED2"]
    # 2つの連続失敗ブロックそれぞれでクールダウンが発動する（1回限定ではない）
    assert sleep_calls == [BULK_FETCH_COOLDOWN_SECONDS, BULK_FETCH_COOLDOWN_SECONDS]


def test_fetch_bulk_prices_cooldown_stops_at_max_cap_when_never_recovering():
    # クールダウンしても回復し続けない場合でも、無限に待ち続けず
    # BULK_FETCH_MAX_COOLDOWNS_PER_RUN回で打ち切り、実行時間の際限ない増大を防ぐ
    n = BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES
    # 上限回数を超えるだけの連続失敗を用意する（上限×閾値より多い件数）
    all_failing_tickers = [f"F{i}" for i in range(n * (BULK_FETCH_MAX_COOLDOWNS_PER_RUN + 2))]
    chain = FakeChain(failing_tickers=set(all_failing_tickers))
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(
        chain, all_failing_tickers, "japan_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn
    )

    assert result == []
    # クールダウンはBULK_FETCH_MAX_COOLDOWNS_PER_RUN回で打ち切られる（際限なく待ち続けない）
    assert sleep_calls == [BULK_FETCH_COOLDOWN_SECONDS] * BULK_FETCH_MAX_COOLDOWNS_PER_RUN


def test_fetch_bulk_prices_default_sleep_parameter_is_time_sleep():
    import time

    from run_daily_pipeline import _fetch_bulk_prices as fn

    assert fn.__defaults__[-1] is time.sleep


def test_fetch_bulk_prices_raw_request_exception_excludes_only_that_ticker():
    # 2026-08-25・26の回帰テスト（対策②）：DataSourceErrorのサブクラスではない
    # requests.exceptions.RequestException（ChunkedEncodingError等）が1銘柄分の
    # 呼び出しで発生しても、stage1スキャン全体を落とさず、当該銘柄だけを除外して
    # 後続の銘柄の取得を継続できること。
    tickers = ["AAPL", "MSFT", "GOOG"]
    chain = FakeChainRaisingArbitraryException(
        {"MSFT": requests.exceptions.ChunkedEncodingError("Response ended prematurely")}
    )
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(chain, tickers, "us_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn)

    assert [c["ticker"] for c in result] == ["AAPL", "GOOG"]
    assert chain.call_log == tickers
    assert sleep_calls == []


def test_fetch_bulk_prices_raw_request_exceptions_also_trigger_cooldown():
    # 対策②はDataSourceError系と同じ扱い（consecutive_failuresのカウント・クールダウン）
    # に載ることも確認する。既存のクールダウン機構を迂回しないようにするため。
    n = BULK_FETCH_COOLDOWN_TRIGGER_CONSECUTIVE_FAILURES
    failing_tickers = [f"F{i}" for i in range(n)]
    tickers = failing_tickers + ["RECOVERED"]
    chain = FakeChainRaisingArbitraryException(
        {t: requests.exceptions.ChunkedEncodingError("Response ended prematurely") for t in failing_tickers}
    )
    sleep_fn, sleep_calls = _fake_sleep_recorder()

    result = _fetch_bulk_prices(chain, tickers, "us_equity", date(2026, 1, 1), date(2026, 1, 2), sleep=sleep_fn)

    assert sleep_calls == [BULK_FETCH_COOLDOWN_SECONDS]
    assert [c["ticker"] for c in result] == ["RECOVERED"]
