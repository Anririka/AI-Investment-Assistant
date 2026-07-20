"""RepositoryFactory（layer1_data_acquisition_design.md 3-2・3-3の確定仕様）。

config/api_sources.yamlを読み込み、データ種別ごとにフォールバックチェーン＋
キャッシュを組み立てる。新しいデータソースを追加する場合、対応する具体Repository
クラスを1つ実装し、`REPOSITORY_REGISTRY`に1行追記するだけでよく、他のコードは
変更不要（3-2確定仕様）。

各具体Repositoryクラスは`from_config(entry: dict) -> Repository`という
クラスメソッドを持つこと（APIキー等の認証情報は環境変数から自分で読む）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Union

import yaml

from .caching import CacheStore, CachingRepositoryDecorator, build_default_cache_store
from .fallback import ChainCandidate, FallbackChainRepository
from .ratelimit import RateLimiter

REPOSITORY_REGISTRY: dict[str, Callable[[dict], Any]] = {}


def _register_default_repositories() -> None:
    """実装済みの具体Repositoryを登録する。

    Phase1では段階的に実装するため、未実装のソース名（alpha_vantage/twelve_data/
    fred/newsapi/gdelt/web_search_fallback等）はここに登録されない。
    """
    try:
        from .repositories.jquants import JQuantsRepository

        REPOSITORY_REGISTRY["jquants"] = JQuantsRepository.from_config
    except ImportError:
        pass

    try:
        from .repositories.alpha_vantage import AlphaVantageRepository

        REPOSITORY_REGISTRY["alpha_vantage"] = AlphaVantageRepository.from_config
    except ImportError:
        pass

    try:
        from .repositories.twelve_data import TwelveDataRepository

        REPOSITORY_REGISTRY["twelve_data"] = TwelveDataRepository.from_config
    except ImportError:
        pass

    try:
        from .repositories.fred import FredRepository

        REPOSITORY_REGISTRY["fred"] = FredRepository.from_config
    except ImportError:
        pass

    try:
        from .repositories.newsapi import NewsApiRepository

        REPOSITORY_REGISTRY["newsapi"] = NewsApiRepository.from_config
    except ImportError:
        pass

    try:
        from .repositories.gdelt import GdeltRepository

        REPOSITORY_REGISTRY["gdelt"] = GdeltRepository.from_config
    except ImportError:
        pass


_register_default_repositories()


class UnimplementedRepositoryError(Exception):
    """config/api_sources.yamlで指定されているが、まだ実装されていない具体Repositoryを指す。"""


class RepositoryFactory:
    """`config/api_sources.yaml`からFallbackChainRepositoryを組み立てるファクトリ。"""

    def __init__(self, config: dict, cache_store: Optional[CacheStore] = None) -> None:
        self._config = config
        # 明示的に指定が無ければ、環境変数の有無でGoogle Drive実装/インメモリ実装を自動選択する
        self._cache_store = cache_store or build_default_cache_store()

    @classmethod
    def from_yaml(
        cls, path: Union[str, Path], cache_store: Optional[CacheStore] = None
    ) -> "RepositoryFactory":
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls(config, cache_store=cache_store)

    def build_chain(self, data_type: str) -> FallbackChainRepository:
        """`japan_equity`等のデータ種別に対応するFallbackChainRepositoryを組み立てる。"""
        type_config = self._config.get(data_type)
        if type_config is None:
            raise KeyError(f"'{data_type}' is not defined in api_sources.yaml")

        candidates: list[ChainCandidate] = []
        for entry in type_config["chain"]:
            name = entry["name"]
            build_repo = REPOSITORY_REGISTRY.get(name)
            if build_repo is None:
                # 未実装のソースはスキップする（実装済み候補が1つも無い場合のみ
                # build_chain呼び出し時にUnimplementedRepositoryErrorとなる）。
                continue
            repo = build_repo(entry)
            rate_limiter = None
            if "rate_limit_per_minute" in entry:
                rate_limiter = RateLimiter(entry["rate_limit_per_minute"])
            cached_repo = CachingRepositoryDecorator(repo, self._cache_store, name)
            candidates.append(
                ChainCandidate(name=name, repository=cached_repo, rate_limiter=rate_limiter)
            )

        if not candidates:
            raise UnimplementedRepositoryError(
                f"no implemented repository found in chain for '{data_type}'"
            )

        return FallbackChainRepository(candidates)
