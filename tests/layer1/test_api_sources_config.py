"""config/api_sources.yaml自体の整合性テスト（2026-07-26追加）。

背景：config/universe.yamlをS&P500全構成銘柄（503件）に差し替えたことで、Twelve Data
（Basicプラン、公式サイトで確認した実際の上限は8クレジット/分・800/日）への呼び出しが
1日数件から500件超に急増した。ところが元の設定はrate_limit_per_dayのみを記載しており、
rate_limit_per_minuteが無かったため、RepositoryFactory.build_chain（factory.py）が
RateLimiterを組み込まず、実際の分あたり上限を守らずに全リクエストを送ってしまう状態に
なっていた（プレースホルダー5銘柄の頃は問題が表面化しなかった）。

本テストは、実際のconfig/api_sources.yamlファイルを読み込み、twelve_dataを使う
各チェーンでrate_limit_per_minuteが明示されていることを保証する回帰テスト。
"""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "api_sources.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_all_twelve_data_chain_entries_declare_rate_limit_per_minute():
    config = _load_config()

    twelve_data_entries = []
    for data_type, type_config in config.items():
        for entry in type_config.get("chain", []):
            if entry.get("name") == "twelve_data":
                twelve_data_entries.append((data_type, entry))

    assert twelve_data_entries, "config/api_sources.yamlにtwelve_dataのチェーンエントリが見つからない"

    for data_type, entry in twelve_data_entries:
        assert "rate_limit_per_minute" in entry, (
            f"{data_type}チェーンのtwelve_dataにrate_limit_per_minuteが未設定。"
            "rate_limit_per_dayのみではRateLimiterが組み込まれず、Basicプランの実際の"
            "分あたり上限（8/分）を守らずに大量リクエストを送ってしまう（factory.py参照）。"
        )
        assert entry["rate_limit_per_minute"] > 0


def test_us_equity_bulk_price_chain_uses_twelve_data_only():
    """第1段階（stage1_screener）用チェーンがAlpha Vantageの予約枠を消費しないことを保証する。"""
    config = _load_config()
    chain_names = [entry["name"] for entry in config["us_equity_bulk_price"]["chain"]]
    assert "alpha_vantage" not in chain_names
    assert "twelve_data" in chain_names
