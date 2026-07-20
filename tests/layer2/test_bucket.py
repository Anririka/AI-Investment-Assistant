"""bucket.pyの境界値テスト（scoring_specification.md §2の[a,b)方式）。"""

import pytest

from ai_investment_assistant.layer2_analysis.bucket import Bucket, score_from_buckets

RSI_LIKE_BUCKETS = [
    Bucket(None, 20, 40, "A", "深い売られすぎ"),
    Bucket(20, 30, 60, "B", "売られすぎ"),
    Bucket(30, 45, 75, "C", "調整局面"),
    Bucket(45, 60, 90, "D", "健全"),
    Bucket(60, None, 70, "E", "過熱"),
]


def test_lower_bound_is_inclusive():
    # 30.00は[30, 45)バケット（C）に入る。29.99は[20,30)バケット（B）
    assert score_from_buckets(30.0, RSI_LIKE_BUCKETS).reason_code == "C"
    assert score_from_buckets(29.99, RSI_LIKE_BUCKETS).reason_code == "B"


def test_upper_bound_is_exclusive():
    assert score_from_buckets(44.99, RSI_LIKE_BUCKETS).reason_code == "C"
    assert score_from_buckets(45.0, RSI_LIKE_BUCKETS).reason_code == "D"


def test_open_ended_lower_and_upper_buckets():
    assert score_from_buckets(-100, RSI_LIKE_BUCKETS).reason_code == "A"
    assert score_from_buckets(1000, RSI_LIKE_BUCKETS).reason_code == "E"


def test_raises_when_no_bucket_matches():
    incomplete = [Bucket(0, 10, 50, "X", "x")]
    with pytest.raises(ValueError):
        score_from_buckets(50, incomplete)
