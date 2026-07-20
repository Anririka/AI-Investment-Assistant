"""deduplicator.pyのテスト（layer3_news_processing_design.md §4-4、§13）。"""

from ai_investment_assistant.layer3_news_processing.deduplicator import deduplicate, normalize_url


def test_normalize_url_strips_query_and_trailing_slash():
    assert normalize_url("https://example.com/news/1/?utm_source=x") == "https://example.com/news/1"
    assert normalize_url("http://Example.com/news/1") == "https://example.com/news/1"


def test_exact_duplicate_urls_are_removed():
    articles = [
        {"headline": "A社決算発表", "source_url": "https://example.com/a?utm=1"},
        {"headline": "A社決算発表（詳報）", "source_url": "https://example.com/a?utm=2"},
    ]
    result = deduplicate(articles)
    assert len(result) == 1
    assert result[0]["headline"] == "A社決算発表"


def test_similar_headlines_across_different_urls_are_merged():
    articles = [
        {"headline": "トヨタ 新型EV発表 価格は500万円から", "source_url": "https://a.com/1"},
        {"headline": "トヨタ 新型EV発表 価格500万円から", "source_url": "https://b.com/2"},
    ]
    result = deduplicate(articles, similarity_threshold=0.6)
    assert len(result) == 1


def test_distinct_headlines_are_both_kept():
    articles = [
        {"headline": "トヨタ、新型EVを発表", "source_url": "https://a.com/1"},
        {"headline": "日銀、政策金利を据え置き", "source_url": "https://b.com/2"},
    ]
    result = deduplicate(articles)
    assert len(result) == 2
