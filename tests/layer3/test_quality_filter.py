"""quality_filter.pyのテスト（layer3_news_processing_design.md §4-1、§13）。

本文100文字未満・タイトルのみ・本文取得失敗・広告ページのそれぞれで正しく除外されること、
正常な記事が誤って除外されないこと（偽陽性のテスト）を確認する。
"""

from ai_investment_assistant.layer3_news_processing.quality_filter import (
    FILTER_AD_PAGE,
    FILTER_BODY_TOO_SHORT,
    FILTER_FETCH_FAILURE,
    FILTER_TITLE_ONLY,
    check_article,
    filter_articles,
)

CONFIG = {
    "min_body_length_chars": 100,
    "reject_title_only": True,
    "reject_fetch_failure": True,
    "ad_page_detection": {"enabled": True, "keyword_patterns": ["広告", "[Sponsored]"]},
}


def test_body_too_short_is_rejected():
    article = {"headline": "h", "body": "短い本文"}
    ok, reason = check_article(article, CONFIG)
    assert ok is False
    assert reason == FILTER_BODY_TOO_SHORT


def test_title_only_is_rejected():
    article = {"headline": "h", "body": ""}
    ok, reason = check_article(article, CONFIG)
    assert ok is False
    assert reason == FILTER_TITLE_ONLY


def test_fetch_failure_is_rejected():
    article = {"headline": "h", "body": "x" * 200, "fetch_failed": True}
    ok, reason = check_article(article, CONFIG)
    assert ok is False
    assert reason == FILTER_FETCH_FAILURE


def test_ad_page_keyword_is_rejected():
    article = {"headline": "h", "body": "本文" * 60 + "[Sponsored]"}
    ok, reason = check_article(article, CONFIG)
    assert ok is False
    assert reason == FILTER_AD_PAGE


def test_normal_article_passes_without_false_positive():
    article = {"headline": "決算発表", "body": "本文です。" * 30}
    ok, reason = check_article(article, CONFIG)
    assert ok is True
    assert reason is None


def test_filter_articles_separates_passed_and_excluded():
    articles = [
        {"headline": "good", "body": "本文です。" * 30},
        {"headline": "bad", "body": "短い"},
    ]
    passed, excluded = filter_articles(articles, CONFIG)
    assert len(passed) == 1
    assert len(excluded) == 1
    assert excluded[0]["reason_code"] == FILTER_BODY_TOO_SHORT
