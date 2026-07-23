"""Layer3パイプラインのエントリポイント（layer3_news_processing_design.md §4）。

取得→重複除去→前処理→品質フィルタ→鮮度付与→キャッシュ確認→LLM構造化→
重要度のルールベース補正→スキーマバリデーション→キャッシュ登録、の順で処理する。
"""

from __future__ import annotations

from datetime import datetime

from . import deduplicator, freshness, importance_rules, preprocessor, quality_filter, schema
from .cache_manager import get_cached, store_cached


def process_articles(
    articles: list,
    structurer,
    cache_store,
    universe_tickers: list,
    sector_master: list,
    quality_filter_config: dict,
    importance_rules_config: dict,
    now: datetime,
    similarity_threshold: float = deduplicator.DEFAULT_SIMILARITY_THRESHOLD,
) -> dict:
    """記事リストをLayer3パイプラインに通し、`StructuredNewsItem`一式を組み立てる（§4）。

    `articles`は`fetcher.fetch_all`が返す辞書のリスト（headline/body/published_at/
    source_url/source_name/source_data_originを持つ）。
    戻り値: {"structured_items": [dict, ...], "excluded": [{"headline", "reason_code"}, ...]}
    """
    deduped = deduplicator.deduplicate(articles, similarity_threshold=similarity_threshold)

    excluded_log: list = []
    quality_passed = []
    for article in deduped:
        raw_body = article.get("body") or ""
        preprocessed_body = preprocessor.preprocess(raw_body)
        candidate = {
            **article,
            "body": preprocessed_body,
            "fetch_failed": not bool(raw_body),
        }
        ok, reason_code = quality_filter.check_article(candidate, quality_filter_config)
        if ok:
            quality_passed.append(candidate)
        else:
            excluded_log.append({"headline": article.get("headline", ""), "reason_code": reason_code})

    structured_items: list = []
    for article in quality_passed:
        normalized_url = deduplicator.normalize_url(article["source_url"])
        item_id = schema.compute_item_id(normalized_url, article["headline"])

        cached = get_cached(cache_store, item_id)
        if cached is not None:
            # 構造化結果自体はキャッシュから再利用するが、age_hoursだけは
            # 現在時刻基準で再計算し直す（§5）。
            published_at = _parse_datetime(cached["published_at"])
            cached = {**cached, "age_hours": freshness.compute_age_hours(published_at, now)}
            structured_items.append(cached)
            continue

        try:
            structured_item = _structure_one(
                article, item_id, structurer, universe_tickers, sector_master,
                importance_rules_config, now,
            )
            schema.validate(structured_item)
        except Exception as exc:  # noqa: BLE001
            # 2026-07-23追加：LLM構造化（Gemini無料枠のレート制限等）が1記事だけ
            # 失敗しても、Layer1のSINGLE_STOCK_DATA_FAILUREと同様に当該記事のみ除外し、
            # 残りの記事の処理を継続する（従来は例外がここで捕捉されず、run_daily_pipeline.py
            # まで伝播して news pipeline 全体が失敗扱いになっていた。2026-07-23の
            # ライブ実行でGemini無料枠のレート制限超過により発覚）。
            excluded_log.append({
                "headline": article.get("headline", ""),
                "reason_code": "LLM_STRUCTURING_FAILED",
                "error_detail": str(exc),
            })
            continue

        store_cached(cache_store, item_id, structured_item)
        structured_items.append(structured_item)

    return {"structured_items": structured_items, "excluded": excluded_log}


def _structure_one(
    article: dict,
    item_id: str,
    structurer,
    universe_tickers: list,
    sector_master: list,
    importance_rules_config: dict,
    now: datetime,
) -> dict:
    """1記事をLLM構造化し、非LLM項目（item_id・鮮度・重要度補正）を合成する（§4-9〜4-10）。"""
    llm_result = structurer.structure(article, universe_tickers=universe_tickers, sector_master=sector_master)

    published_at = _parse_datetime(article["published_at"])
    age_hours = freshness.compute_age_hours(published_at, now)

    importance_result = importance_rules.apply_importance_floor(
        llm_result["importance"], llm_result["category"], importance_rules_config
    )

    return {
        "news_schema_version": schema.CURRENT_SCHEMA_VERSION,
        "item_id": item_id,
        "headline": article["headline"],
        "source_name": article.get("source_name", ""),
        "source_url": article["source_url"],
        "source_data_origin": article.get("source_data_origin", "unknown"),
        "published_at": article["published_at"] if isinstance(article["published_at"], str) else article["published_at"].isoformat(),
        "fetched_at": now.isoformat(),
        "age_hours": age_hours,
        "category": llm_result["category"],
        "affected_companies": llm_result["affected_companies"],
        "affected_sectors": llm_result["affected_sectors"],
        "impact_direction": llm_result["impact_direction"],
        "impact_horizon": llm_result["impact_horizon"],
        "importance": importance_result["importance"],
        "importance_llm_raw": importance_result["importance_llm_raw"],
        "importance_source": importance_result["importance_source"],
        "confidence": llm_result["confidence"],
        "confidence_reason": llm_result["confidence_reason"],
        "summary": schema.truncate_summary(llm_result["summary"]),
        "llm_provider": llm_result["llm_provider"],
        "llm_model": llm_result["llm_model"],
        "structuring_status": llm_result["structuring_status"],
    }


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
