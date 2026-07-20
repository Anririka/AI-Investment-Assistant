"""NewsStructurerの選択（layer3_news_processing_design.md §6「config/ai_provider.yamlで
使用するベンダー・モデルを指定する。コード変更なしでの切替を可能にする」）。

新しいベンダー実装を追加する場合、対応する具体クラスを1つ実装し、`STRUCTURER_REGISTRY`
に1行追記するだけでよい（Layer1のRepositoryFactory・Layer2のPERScorerと同じ、
設定ファイル切り替えのパターンを踏襲）。
"""

from __future__ import annotations

STRUCTURER_REGISTRY: dict = {}


def _register_default_structurers() -> None:
    try:
        from .llm_structurer.claude_structurer import ClaudeStructurer

        STRUCTURER_REGISTRY["claude"] = ClaudeStructurer.from_config
    except ImportError:
        pass

    try:
        from .llm_structurer.gemini_structurer import GeminiStructurer

        STRUCTURER_REGISTRY["gemini"] = GeminiStructurer.from_config
    except ImportError:
        pass


_register_default_structurers()


def build_structurer(ai_provider_config: dict):
    """`config/ai_provider.yaml`の`news_structurer.provider`に従ってNewsStructurerを組み立てる。"""
    news_cfg = ai_provider_config.get("news_structurer", {})
    provider = news_cfg.get("provider", "claude")

    factory = STRUCTURER_REGISTRY.get(provider)
    if factory is None:
        raise ValueError(
            f"Unknown news_structurer provider: '{provider}' "
            f"(registered: {list(STRUCTURER_REGISTRY.keys())})"
        )
    return factory(news_cfg)
