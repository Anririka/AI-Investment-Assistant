"""FallbackChainRepositoryのテスト（layer1_data_acquisition_design.md 5章の挙動を検証）。"""

import pytest

from ai_investment_assistant.layer1_data_acquisition.exceptions import (
    AllSourcesFailedError,
    AuthError,
    NotFoundError,
    RateLimitError,
    TransientError,
)
from ai_investment_assistant.layer1_data_acquisition.fallback import ChainCandidate, FallbackChainRepository


class FakeRepo:
    """呼び出し回数を記録し、あらかじめ指定した振る舞い（例外 or 戻り値）を返すテスト用Repository。"""

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.call_count = 0

    def get_daily_prices(self, *args, **kwargs):
        self.call_count += 1
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _no_sleep(seconds: float) -> None:
    pass  # テストでは実時間を待たない


def test_fallback_to_next_candidate_on_transient_error_after_retries():
    first = FakeRepo([TransientError("timeout")] * 4)  # 3回リトライしてもまだ失敗
    second = FakeRepo(["ok-from-second"])
    chain = FallbackChainRepository(
        [ChainCandidate("first", first), ChainCandidate("second", second)],
        sleep=_no_sleep,
    )

    result = chain.call("get_daily_prices", "7203")

    assert result == "ok-from-second"
    assert first.call_count == 4  # 初回+3リトライ
    assert second.call_count == 1


def test_transient_error_recovers_within_retry_budget():
    first = FakeRepo([TransientError("timeout"), "ok-after-one-retry"])
    chain = FallbackChainRepository([ChainCandidate("first", first)], sleep=_no_sleep)

    result = chain.call("get_daily_prices", "7203")

    assert result == "ok-after-one-retry"
    assert first.call_count == 2


def test_rate_limit_switches_immediately_without_retry():
    first = FakeRepo([RateLimitError("429")])
    second = FakeRepo(["ok-from-second"])
    chain = FallbackChainRepository(
        [ChainCandidate("first", first), ChainCandidate("second", second)],
        sleep=_no_sleep,
    )

    result = chain.call("get_daily_prices", "7203")

    assert result == "ok-from-second"
    assert first.call_count == 1  # リトライせず即座に次候補へ


def test_auth_error_switches_to_next_candidate():
    first = FakeRepo([AuthError("401")])
    second = FakeRepo(["ok-from-second"])
    chain = FallbackChainRepository(
        [ChainCandidate("first", first), ChainCandidate("second", second)],
        sleep=_no_sleep,
    )

    result = chain.call("get_daily_prices", "7203")

    assert result == "ok-from-second"


def test_not_found_error_does_not_fallback():
    first = FakeRepo([NotFoundError("no such ticker")])
    second = FakeRepo(["should-not-be-called"])
    chain = FallbackChainRepository(
        [ChainCandidate("first", first), ChainCandidate("second", second)],
        sleep=_no_sleep,
    )

    with pytest.raises(NotFoundError):
        chain.call("get_daily_prices", "9999")

    assert second.call_count == 0


def test_all_candidates_failing_raises_all_sources_failed_error():
    first = FakeRepo([RateLimitError("429")])
    second = FakeRepo([AuthError("401")])
    chain = FallbackChainRepository(
        [ChainCandidate("first", first), ChainCandidate("second", second)],
        sleep=_no_sleep,
    )

    with pytest.raises(AllSourcesFailedError) as exc_info:
        chain.call("get_daily_prices", "7203")

    assert len(exc_info.value.errors) == 2
