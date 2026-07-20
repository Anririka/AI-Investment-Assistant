"""ニュース取得（layer3_news_processing_design.md §3・§4）。

Layer1が提供する`NewsRepository`（`FallbackChainRepository`でNewsAPI→GDELT→Web検索を
束ねたもの）を唯一の取得経路とする。Layer3自身はどのAPIが実際に使われたかを意識しない
（Layer1のRepositoryパターンの原則を継承、§3）。`FallbackChainRepository.last_source_used`
（Layer1側の後方互換の拡張）から`source_data_origin`を取得する。
"""

from __future__ import annotations

from datetime import date


def fetch_all(news_chain, macro_queries: list, candidate_tickers: list, since: date, until: date) -> list:
    """主要指数・マクロ全般クエリ(a)と当日候補銘柄クエリ(b)の両方を取得する（§4-2）。

    戻り値の各要素は`headline`・`body`・`published_at`・`source_url`・`source_name`・
    `source_data_origin`を持つ辞書。
    """
    articles: list = []

    if macro_queries:
        raw_items = news_chain.call("fetch_news", macro_queries, since, until)
        origin = news_chain.last_source_used
        articles.extend(_to_dicts(raw_items, origin))

    if candidate_tickers:
        raw_items = news_chain.call("fetch_news", candidate_tickers, since, until)
        origin = news_chain.last_source_used
        articles.extend(_to_dicts(raw_items, origin))

    return articles


def _to_dicts(raw_news_items, source_data_origin: str) -> list:
    """Layer1の`RawNewsItem`を、Layer3内部で使う辞書表現に変換する。"""
    return [
        {
            "headline": item.title,
            "body": item.body,
            "published_at": item.published_at,
            "source_url": item.source_url,
            "source_name": item.source_name,
            "source_data_origin": source_data_origin,
        }
        for item in raw_news_items
    ]
