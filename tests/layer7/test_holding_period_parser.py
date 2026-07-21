"""holding_period_parser.pyのテスト（layer7_proposal_tracking_design.md §8-3、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.holding_period_parser import parse_holding_period_days

UNIT_DAYS = {"日": 1, "週間": 7, "週": 7, "ヶ月": 30, "か月": 30, "カ月": 30}
FALLBACK = 90


def test_parse_holding_period_days_weeks_range_uses_max_number():
    days, status = parse_holding_period_days("2〜4週間", UNIT_DAYS, FALLBACK)
    assert days == 28
    assert status == "parsed"


def test_parse_holding_period_days_months_approximate():
    days, status = parse_holding_period_days("1ヶ月程度", UNIT_DAYS, FALLBACK)
    assert days == 30
    assert status == "parsed"


def test_parse_holding_period_days_alt_month_kanji_variants():
    for text, expected in [("2か月", 60), ("3カ月", 90)]:
        days, status = parse_holding_period_days(text, UNIT_DAYS, FALLBACK)
        assert days == expected
        assert status == "parsed"


def test_parse_holding_period_days_single_day_unit():
    days, status = parse_holding_period_days("10日", UNIT_DAYS, FALLBACK)
    assert days == 10
    assert status == "parsed"


def test_parse_holding_period_days_no_number_falls_back():
    days, status = parse_holding_period_days("しばらく保有", UNIT_DAYS, FALLBACK)
    assert days == FALLBACK
    assert status == "fallback_used"


def test_parse_holding_period_days_number_without_recognizable_unit_falls_back():
    days, status = parse_holding_period_days("3くらい", UNIT_DAYS, FALLBACK)
    assert days == FALLBACK
    assert status == "fallback_used"


def test_parse_holding_period_days_empty_string_falls_back():
    days, status = parse_holding_period_days("", UNIT_DAYS, FALLBACK)
    assert days == FALLBACK
    assert status == "fallback_used"
