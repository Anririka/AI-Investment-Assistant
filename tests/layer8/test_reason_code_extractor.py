"""reason_code_extractor.pyのテスト（layer8_self_evaluation_design.md §7-4、§11テスト方針）。"""

from ai_investment_assistant.layer8_self_evaluation.reason_code_extractor import extract_reason_codes


def test_extract_reason_codes_finds_known_patterns():
    text = "テクニカル・ファンダメンタル双方が良好（reason_code: TECH_MA_PERFECT_ORDER_UP, FUND_ROE_EXCELLENT 等）。"
    codes, status = extract_reason_codes(text)
    assert codes == ["TECH_MA_PERFECT_ORDER_UP", "FUND_ROE_EXCELLENT"]
    assert status == "success"


def test_extract_reason_codes_deduplicates_repeated_codes():
    text = "TECH_RSI_HEALTHY を根拠とする。TECH_RSI_HEALTHY は継続。"
    codes, status = extract_reason_codes(text)
    assert codes == ["TECH_RSI_HEALTHY"]
    assert status == "success"


def test_extract_reason_codes_no_match_for_plain_text():
    codes, status = extract_reason_codes("特に根拠は明示されていない自然文の説明。")
    assert codes == []
    assert status == "no_match"


def test_extract_reason_codes_none_input_is_no_match():
    codes, status = extract_reason_codes(None)
    assert codes == []
    assert status == "no_match"


def test_extract_reason_codes_does_not_false_positive_on_unrelated_uppercase():
    # NEWS/TECH等のプレフィックスを持たない大文字文字列は誤検出しない
    codes, status = extract_reason_codes("AI社は好調。USD高が影響。")
    assert codes == []
    assert status == "no_match"


def test_extract_reason_codes_supports_all_known_prefixes():
    text = "SUPD_VOLUME_SURGE MACRO_RATE_CUT_EXPECTED NEWS_POSITIVE_EARNINGS REGIME_TREND_ALIGNED"
    codes, status = extract_reason_codes(text)
    assert set(codes) == {
        "SUPD_VOLUME_SURGE", "MACRO_RATE_CUT_EXPECTED", "NEWS_POSITIVE_EARNINGS", "REGIME_TREND_ALIGNED",
    }
    assert status == "success"
