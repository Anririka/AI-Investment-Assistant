"""NewsStructurer抽象クラス（layer3_news_processing_design.md §6）。

`structure(article) -> dict`のシグネチャで統一する。戻り値はLLMが決定すべき部分のみ
（category／affected_companies／affected_sectors／impact_direction／impact_horizon／
importance／confidence／confidence_reason／summary／llm_provider／llm_model／
structuring_status）。item_id・published_at・age_hours等の非LLM項目はmain.py側で合成する。
"""

from __future__ import annotations

import abc


class NewsStructurer(abc.ABC):
    @abc.abstractmethod
    def structure(self, article: dict, universe_tickers: list = None, sector_master: list = None) -> dict:
        ...
