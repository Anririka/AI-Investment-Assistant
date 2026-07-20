"""StructuredNewsItemのスキーマ定義・バリデーション（layer3_news_processing_design.md §8）。

Layer3自身は`news_schema_version`の互換性判定を行わない（判定はLayer2の責務、§8-2）。
ここでは現在のスキーマバージョンの出力と、フィールド形式の検証（JSON Schema）のみを行う。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import jsonschema

CURRENT_SCHEMA_VERSION = "1.0"
SUMMARY_MAX_CHARS = 80

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "structured_news_item.schema.json"


@dataclass(frozen=True)
class AffectedCompany:
    ticker: str
    name: str
    relevance: str  # "primary" | "secondary"


@dataclass(frozen=True)
class StructuredNewsItem:
    news_schema_version: str
    item_id: str
    headline: str
    source_name: str
    source_url: str
    source_data_origin: str
    published_at: str
    fetched_at: str
    age_hours: float
    category: str
    affected_companies: tuple
    affected_sectors: tuple
    impact_direction: str
    impact_horizon: str
    importance: int
    importance_llm_raw: int
    importance_source: str
    confidence: float
    confidence_reason: str
    summary: str
    llm_provider: str
    llm_model: str
    structuring_status: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["affected_companies"] = [dict(c) if isinstance(c, dict) else c.__dict__ for c in self.affected_companies]
        d["affected_sectors"] = list(self.affected_sectors)
        return d


def compute_item_id(normalized_url: str, headline: str) -> str:
    """正規化URL＋見出しのハッシュ（§8-1、キャッシュキーと同一の値）。"""
    digest = hashlib.sha256(f"{normalized_url}|{headline}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def truncate_summary(summary: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """summaryは80文字以内とする（§8確定仕様）。超過時は末尾を切り詰める。"""
    if len(summary) <= max_chars:
        return summary
    return summary[:max_chars]


def _load_schema() -> dict:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate(item_dict: dict) -> None:
    """StructuredNewsItemの辞書表現をJSON Schemaで検証する。不正な場合は例外を送出する。"""
    schema = _load_schema()
    jsonschema.validate(instance=item_dict, schema=schema)
