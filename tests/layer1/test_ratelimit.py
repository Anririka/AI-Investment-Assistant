"""RateLimiterのテスト（fake clock/sleepで実時間を使わずに検証する）。"""

from ai_investment_assistant.layer1_data_acquisition.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_waits_when_called_too_soon():
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    limiter = RateLimiter(rate_limit_per_minute=60, clock=clock, sleep=fake_sleep)  # 1req/sec

    limiter.acquire()  # 1回目：待たない
    assert sleeps == []

    clock.now += 0.2  # 0.2秒しか経っていない状態で2回目
    limiter.acquire()
    assert sleeps == [0.8]  # 残り0.8秒待つはず


def test_rate_limiter_does_not_wait_if_interval_already_elapsed():
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    limiter = RateLimiter(rate_limit_per_minute=60, clock=clock, sleep=fake_sleep)

    limiter.acquire()
    clock.now += 2.0  # 十分に間隔が空いている
    limiter.acquire()
    assert sleeps == []


def test_rate_limiter_rejects_non_positive_rate():
    import pytest

    with pytest.raises(ValueError):
        RateLimiter(rate_limit_per_minute=0)
