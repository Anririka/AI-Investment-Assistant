"""main.py（Layer3パイプライン全体）の統合テスト（layer3_news_processing_design.md §4・§13）。

「実際の記事サンプルを用いてLayer3を通しで実行し、出力StructuredNewsItem一式が
Layer2 news_scorer.pyにそのまま投入可能な形式であることを確認する」（§13の統合テスト）
に対応する。LLM呼び出しはフェイクのStructurerに差し替える。
"""

from datetime import datetime, timezone

from ai_investment_assistant.layer1_data_acquisition.caching import InMemoryCacheStore
from ai_investment_assistant.layer3_news_processing import schema
from ai_investment_assistant.layer3_news_processing.main import process_articles

QUALITY_CONFIG = {
    "min_body_length_chars": 10,
    "reject_title_only": True,
    "reject_fetch_failure": True,
    "ad_page_detection": {"enabled": True, "keyword_patterns": ["[Sponsored]"]},
}
IMPORTANCE_CONFIG = {"category_importance_floor": {"earnings": 70}, "default_floor": 0}


class FakeStructurer:
    def __init__(self):
        self.call_count = 0

    def structure(self, article, universe_tickers=None, sector_master=None):
        self.call_count += 1
        return {
            "category": "earnings",
            "affected_companies": [{"ticker": "7203", "name": "トヨタ自動車", "relevance": "primary"}],
            "affected_sectors": ["automobile"],
            "impact_direction": "positive",
            "impact_horizon": "mid_term",
            "importance": 40,  # earningsの下限70未満 -> 補正されるはず
            "confidence": 0.8,
            "confidence_reason": "決算短信を確認",
            "summary": "トヨタが好決算を発表した。",
            "llm_provider": "claude",
            "llm_model": "claude-haiku-4-5",
            "structuring_status": "success",
        }


def _article(headline="トヨタ決算発表", url="https://example.com/1", published="2026-07-19T00:00:00Z"):
    return {
        "headline": headline,
        "body": "トヨタ自動車は本日、決算を発表した。" * 3,
        "published_at": published,
        "source_url": url,
        "source_name": "TestWire",
        "source_data_origin": "gdelt",
    }


def test_full_pipeline_produces_valid_structured_items():
    structurer = FakeStructurer()
    cache_store = InMemoryCacheStore()
    now = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)

    result = process_articles(
        articles=[_article()],
        structurer=structurer,
        cache_store=cache_store,
        universe_tickers=[{"ticker": "7203", "name": "トヨタ自動車"}],
        sector_master=["automobile"],
        quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG,
        now=now,
    )

    assert len(result["structured_items"]) == 1
    item = result["structured_items"][0]
    schema.validate(item)  # Layer2にそのまま投入可能な形式であることの確認
    assert item["importance"] == 70  # ルール補正が適用されている
    assert item["importance_llm_raw"] == 40
    assert item["importance_source"] == "rule_floor_applied"
    assert structurer.call_count == 1


def test_low_quality_article_is_excluded_before_llm_call():
    structurer = FakeStructurer()
    cache_store = InMemoryCacheStore()
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)

    bad_article = {**_article(), "body": "短い"}

    result = process_articles(
        articles=[bad_article], structurer=structurer, cache_store=cache_store,
        universe_tickers=[], sector_master=[], quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG, now=now,
    )

    assert result["structured_items"] == []
    assert len(result["excluded"]) == 1
    assert structurer.call_count == 0  # 品質フィルタで弾かれ、LLM呼び出しは発生しない


def test_second_run_uses_cache_and_recomputes_age_hours():
    structurer = FakeStructurer()
    cache_store = InMemoryCacheStore()
    first_run_time = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    second_run_time = datetime(2026, 7, 21, 0, 0, 0, tzinfo=timezone.utc)  # 24時間後

    article = _article()

    first_result = process_articles(
        articles=[article], structurer=structurer, cache_store=cache_store,
        universe_tickers=[], sector_master=[], quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG, now=first_run_time,
    )
    second_result = process_articles(
        articles=[article], structurer=structurer, cache_store=cache_store,
        universe_tickers=[], sector_master=[], quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG, now=second_run_time,
    )

    assert structurer.call_count == 1  # 2回目はキャッシュから返り、LLM呼び出しは増えない
    first_age = first_result["structured_items"][0]["age_hours"]
    second_age = second_result["structured_items"][0]["age_hours"]
    assert second_age == first_age + 24  # age_hoursだけは再計算される


class FlakyStructurer:
    """1件目の記事でのみ例外を送出する（レート制限等を模したフェイク）。"""

    def __init__(self, fail_on_headline: str):
        self.fail_on_headline = fail_on_headline
        self.call_count = 0

    def structure(self, article, universe_tickers=None, sector_master=None):
        self.call_count += 1
        if article["headline"] == self.fail_on_headline:
            raise RuntimeError("429 RESOURCE_EXHAUSTED (fake rate limit)")
        return {
            "category": "earnings",
            "affected_companies": [],
            "affected_sectors": [],
            "impact_direction": "neutral",
            "impact_horizon": "short_term",
            "importance": 50,
            "confidence": 0.5,
            "confidence_reason": "テスト用",
            "summary": "テスト記事の要約。",
            "llm_provider": "gemini",
            "llm_model": "gemini-3.1-flash-lite",
            "structuring_status": "success",
        }


def test_single_article_llm_failure_does_not_abort_the_whole_run():
    """2026-07-23追加：Gemini無料枠のレート制限超過等で1記事のLLM構造化が失敗しても、
    残りの記事は正常に処理され、失敗した記事だけがexcluded（LLM_STRUCTURING_FAILED）に
    回ることを確認する（従来は例外がprocess_articles外まで伝播し、run全体が失敗していた）。
    """
    structurer = FlakyStructurer(fail_on_headline="レート制限で失敗する記事")
    cache_store = InMemoryCacheStore()
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)

    articles = [
        _article(headline="レート制限で失敗する記事", url="https://a.com/1"),
        _article(headline="正常に処理される記事", url="https://b.com/2"),
    ]

    result = process_articles(
        articles=articles, structurer=structurer, cache_store=cache_store,
        universe_tickers=[], sector_master=[], quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG, now=now,
    )

    assert len(result["structured_items"]) == 1
    assert result["structured_items"][0]["headline"] == "正常に処理される記事"
    assert len(result["excluded"]) == 1
    assert result["excluded"][0]["reason_code"] == "LLM_STRUCTURING_FAILED"
    assert result["excluded"][0]["headline"] == "レート制限で失敗する記事"


def test_duplicate_articles_are_merged_before_processing():
    structurer = FakeStructurer()
    cache_store = InMemoryCacheStore()
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)

    articles = [
        _article(headline="トヨタ決算発表", url="https://a.com/1"),
        _article(headline="トヨタ決算発表", url="https://b.com/2"),  # 見出し完全一致の転載記事
    ]

    result = process_articles(
        articles=articles, structurer=structurer, cache_store=cache_store,
        universe_tickers=[], sector_master=[], quality_filter_config=QUALITY_CONFIG,
        importance_rules_config=IMPORTANCE_CONFIG, now=now,
    )

    assert len(result["structured_items"]) == 1
    assert structurer.call_count == 1
