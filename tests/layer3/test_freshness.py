"""freshness.pyのテスト（layer3_news_processing_design.md §4-7、§13）。

`published_at`からの`age_hours`計算がタイムゾーンを含めて正確であることを確認する。
"""

from datetime import datetime, timedelta, timezone

from ai_investment_assistant.layer3_news_processing.freshness import compute_age_hours


def test_age_hours_basic_utc():
    published = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 7, 20, 5, 0, 0, tzinfo=timezone.utc)
    assert compute_age_hours(published, now) == 5.0


def test_age_hours_handles_naive_datetimes_as_utc():
    published = datetime(2026, 7, 20, 0, 0, 0)
    now = datetime(2026, 7, 20, 3, 0, 0)
    assert compute_age_hours(published, now) == 3.0


def test_age_hours_across_timezones():
    published = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone(timedelta(hours=9)))  # JST
    now = datetime(2026, 7, 19, 20, 0, 0, tzinfo=timezone.utc)  # = 2026-07-20 05:00 JST
    assert compute_age_hours(published, now) == 5.0


def test_age_hours_never_negative():
    published = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc)  # publishedより前（時計ズレ想定）
    assert compute_age_hours(published, now) == 0.0
