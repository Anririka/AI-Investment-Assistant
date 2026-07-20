"""記事品質フィルタ（layer3_news_processing_design.md §4-1、新設）。

LLM構造化前に、明らかに情報価値の無い記事を機械的に除外する。除外された記事は
`StructuredNewsItem`を生成せず、`reason_code`のみをrun_logに記録する（§9、正常系）。
"""

from __future__ import annotations

FILTER_BODY_TOO_SHORT = "FILTER_BODY_TOO_SHORT"
FILTER_TITLE_ONLY = "FILTER_TITLE_ONLY"
FILTER_FETCH_FAILURE = "FILTER_FETCH_FAILURE"
FILTER_AD_PAGE = "FILTER_AD_PAGE"


def check_article(article: dict, config: dict) -> tuple:
    """記事1件が品質フィルタを通過するか判定する。

    `article`は`headline`・`body`（前処理済み）・`fetch_failed`（任意、bool）を持つ辞書。
    戻り値: (passed: bool, reason_code: Optional[str])
    """
    if config.get("reject_fetch_failure", True) and article.get("fetch_failed"):
        return False, FILTER_FETCH_FAILURE

    body = article.get("body", "") or ""

    if config.get("reject_title_only", True) and not body.strip():
        return False, FILTER_TITLE_ONLY

    min_length = config.get("min_body_length_chars", 100)
    if len(body) < min_length:
        return False, FILTER_BODY_TOO_SHORT

    ad_config = config.get("ad_page_detection", {})
    if ad_config.get("enabled", True):
        patterns = ad_config.get("keyword_patterns", [])
        haystack = f"{article.get('headline', '')} {body}"
        if any(pattern in haystack for pattern in patterns):
            return False, FILTER_AD_PAGE

    return True, None


def filter_articles(articles: list, config: dict) -> tuple:
    """記事リストをフィルタリングする。

    戻り値: (合格した記事のリスト, 除外ログのリスト[{headline, reason_code}])
    """
    passed = []
    excluded = []
    for article in articles:
        ok, reason_code = check_article(article, config)
        if ok:
            passed.append(article)
        else:
            excluded.append({"headline": article.get("headline", ""), "reason_code": reason_code})
    return passed, excluded
