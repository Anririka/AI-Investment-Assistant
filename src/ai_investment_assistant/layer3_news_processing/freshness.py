"""鮮度情報の計算・付与（layer3_news_processing_design.md §4-7）。

`published_at`から現在時刻までの経過時間を`age_hours`として計算する。
キャッシュから読み出す都度、現在時刻基準で再計算し直す（§5、鮮度情報だけはキャッシュ対象外）。
"""

from __future__ import annotations

from datetime import datetime, timezone


def compute_age_hours(published_at: datetime, now: datetime) -> float:
    """`published_at`から`now`までの経過時間を時間単位で計算する（タイムゾーンを考慮）。"""
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta = now - published_at
    return max(0.0, delta.total_seconds() / 3600.0)
