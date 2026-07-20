"""preprocessor.pyのテスト（layer3_news_processing_design.md §4-5、§13）。"""

from ai_investment_assistant.layer3_news_processing.preprocessor import (
    normalize_whitespace,
    preprocess,
    strip_html,
    trim_body,
)


def test_strip_html_removes_script_and_style_content():
    html = "<p>本文です</p><script>alert('x')</script><style>.a{color:red}</style>続き"
    result = strip_html(html)
    assert "alert" not in result
    assert "color:red" not in result
    assert "本文です" in result
    assert "続き" in result


def test_normalize_whitespace_collapses_multiple_spaces():
    assert normalize_whitespace("a   b\n\nc\t d") == "a b c d"


def test_trim_body_leaves_short_text_untouched():
    text = "短い本文"
    assert trim_body(text, max_chars=100) == text


def test_trim_body_truncates_long_text():
    text = "あ" * 3000
    result = trim_body(text, max_chars=2000, head_chars=1500)
    assert len(result) < len(text)
    assert result.endswith("（以下省略）")


def test_preprocess_full_pipeline():
    raw = "<div>　全角スペース　と<b>タグ</b>混じりの本文です　　</div>"
    result = preprocess(raw)
    assert "<" not in result
    assert "  " not in result
