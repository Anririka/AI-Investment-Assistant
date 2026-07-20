"""重複ニュース除去（layer3_news_processing_design.md §4-4）。

1. 記事URLの正規化後のハッシュによる完全一致除去
2. 見出しの簡易類似度（Jaccard係数）が閾値超過の記事は「実質同一記事」として1件にまとめる
   （同一ニュースが複数媒体に転載されるケースへの対応）

見出しの類似度は文字n-gram（既定はbigram）ベースのJaccard係数で計算する。日本語の
見出しは英語のような単語間スペースを持たないため、空白区切りのトークン化では
（本文中に偶然スペースが入っていない限り）類似度が正しく機能しない。文字n-gramは
言語・単語境界に依存しないため、日英いずれの見出しにも同じロジックで対応できる。
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

DEFAULT_SIMILARITY_THRESHOLD = 0.8
NGRAM_SIZE = 2

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """クエリパラメータ除去・末尾スラッシュ統一等でURLを正規化する。"""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    # スキームは常にhttpsに統一し、query/fragmentは除去する
    return urlunsplit(("https", parts.netloc.lower(), path, "", ""))


def _char_ngrams(headline: str, n: int = NGRAM_SIZE) -> set:
    normalized = _WHITESPACE_RE.sub("", headline.strip().lower())
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i : i + n] for i in range(len(normalized) - n + 1)}


def _jaccard_similarity(a: str, b: str) -> float:
    ngrams_a, ngrams_b = _char_ngrams(a), _char_ngrams(b)
    if not ngrams_a and not ngrams_b:
        return 1.0
    union = ngrams_a | ngrams_b
    if not union:
        return 0.0
    return len(ngrams_a & ngrams_b) / len(union)


def deduplicate(articles: list, similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD) -> list:
    """記事リストから重複を除去する。

    `articles`の各要素は最低限`headline`・`source_url`を持つ辞書。
    完全一致（正規化URL一致）を先に除去し、その後に残った記事同士で見出しの
    Jaccard類似度が閾値以上のものを1件にまとめる（先に出現した方を残す）。
    """
    seen_urls: set = set()
    url_deduped = []
    for article in articles:
        normalized = normalize_url(article["source_url"])
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        url_deduped.append(article)

    result: list = []
    for article in url_deduped:
        is_duplicate = any(
            _jaccard_similarity(article["headline"], kept["headline"]) >= similarity_threshold
            for kept in result
        )
        if not is_duplicate:
            result.append(article)

    return result
