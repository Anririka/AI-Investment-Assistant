"""記事本文の前処理（layer3_news_processing_design.md §4-5）。

HTML/JSタグ除去、文字コード統一、極端に長い本文は先頭部分＋キーワード周辺のみへ
トリミングする（LLM入力トークン削減）。
"""

from __future__ import annotations

import re
import unicodedata

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_MAX_BODY_CHARS = 2000
DEFAULT_HEAD_CHARS = 1500


def strip_html(text: str) -> str:
    """script/styleタグを中身ごと除去し、残りのHTMLタグを除去する。"""
    without_scripts = _TAG_RE.sub(" ", text)
    without_tags = _HTML_TAG_RE.sub(" ", without_scripts)
    return without_tags


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_unicode(text: str) -> str:
    """文字コードの正規化（NFKC、全角/半角統一等）。"""
    return unicodedata.normalize("NFKC", text)


def trim_body(text: str, max_chars: int = DEFAULT_MAX_BODY_CHARS, head_chars: int = DEFAULT_HEAD_CHARS) -> str:
    """極端に長い本文を先頭部分のみへトリミングする（§4-5、LLM入力トークン削減）。

    Ver1では「先頭部分＋キーワード周辺」のうち、キーワード抽出ロジックは未実装のため
    先頭部分のみのトリミングとする（設計書は将来のキーワード周辺抽出を想定しているが、
    具体的なキーワード抽出方式は本書で規定されていないため、Ver1は単純な先頭トリミング
    で確定する）。
    """
    if len(text) <= max_chars:
        return text
    return text[:head_chars].rstrip() + "…（以下省略）"


def preprocess(raw_body: str) -> str:
    """本文前処理のパイプライン全体（HTML除去→Unicode正規化→空白正規化→トリミング）。"""
    text = strip_html(raw_body)
    text = normalize_unicode(text)
    text = normalize_whitespace(text)
    text = trim_body(text)
    return text
