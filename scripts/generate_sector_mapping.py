"""config/sector_mapping.yaml を実データで生成する一回限りのユーティリティスクリプト。

背景（2026-08-12、layer5_ai_judgment §7-2対応）：
config/sector_mapping.yaml は動作確認用のプレースホルダー（トヨタ・ソニー等10銘柄程度の
みを手動記載）のまま放置されており、config/universe.yaml が日経225・S&P500の実銘柄
725件に差し替えられた後もこれに追随していなかった。この結果、`load_portfolio_state.py`の
`sector_concentration`がほぼ全銘柄で"unknown"となり、既存保有と同一セクターの新規銘柄が
提案された際にセクター集中を検知できない事故（2026-08-12、日本郵船(9101)が既存保有の
商船三井(9104)と同一の海運セクターであるにも関わらず無警告で第1位提案された）が実際に
発生した。本スクリプトはその是正対応として新設した。

データソース：
  - 日本株（日経225・225銘柄）：J-Quants `/equities/master` から東証33業種区分
    （`S33`コード・`S33Nm`名称）を取得する。Layer1の`JQuantsRepository.get_listed_universe()`
    が既にS33コードだけを内部的に取得しているが（Layer2のPERセクター相対評価用）、
    人間可読な業種名（S33Nm）は保持していないため、本スクリプトでは`_request()`を直接
    呼び出し、両方を取得する。
  - 米国株（S&P500・503銘柄）：J-Quantsに相当するデータが無いため、config/universe.yaml
    自体の銘柄リストの作成時（2026-07-26差し替え）に情報源とした「Wikipedia: List of
    S&P 500 companies」のGICS Sector列を、同スクリプト内に静的テーブルとしてハードコード
    する（同じ情報源に揃えることで、銘柄リストとセクター区分の出典の一貫性を保つ）。

実行方法（本番のJ-Quants認証情報が必要。GitHub ActionsのGOOGLE_OAUTH_TOKEN_JSON等と
同様、data_pipeline.yml/tracking_pipeline.ymlのsecretsとして既に設定済みのJQUANTS_API_KEY
をそのまま使う）：

    JQUANTS_API_KEY=xxx python scripts/generate_sector_mapping.py > /tmp/sector_mapping_japan.yaml

日次パイプラインには組み込まない。銘柄のセクター分類は短期間で頻繁に変わるものでは
ないため、必要時（config/universe.yaml改訂時等）に手動で再実行し、生成結果を人間が
レビューした上でconfig/sector_mapping.yamlへ反映する運用とする。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml  # noqa: E402

from ai_investment_assistant.layer1_data_acquisition.repositories.jquants import (  # noqa: E402
    JQuantsRepository,
)

_UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "config" / "universe.yaml"


def fetch_japan_sector_table(repo: JQuantsRepository) -> dict:
    """J-Quants /equities/master から、東証33業種区分（コード→日本語名）を全銘柄分取得する。

    戻り値: {ticker: sector_name} の辞書（日経225以外の銘柄も含む全上場銘柄分。
    呼び出し側でuniverse.yamlの225銘柄のみに絞り込むこと）。
    """
    payload = repo._request("/equities/master")  # noqa: SLF001 -- 一回限りの生成スクリプトのため許容
    rows = payload.get("data", [])
    table = {}
    for row in rows:
        ticker = row.get("Code", row.get("code"))
        sector_name = row.get("S33Nm")
        if ticker and sector_name:
            table[ticker] = sector_name
    return table


def load_universe_tickers() -> dict:
    with open(_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        universe = yaml.safe_load(f)
    return {
        "japan_equity": list(universe["japan_equity"]["tickers"]),
        "us_equity": list(universe["us_equity"]["tickers"]),
    }


def main() -> None:
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        print("ERROR: JQUANTS_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    universe = load_universe_tickers()
    repo = JQuantsRepository(api_key=api_key)
    japan_table = fetch_japan_sector_table(repo)

    sectors = {}
    missing = []
    for ticker in universe["japan_equity"]:
        name = japan_table.get(ticker)
        if name is None:
            missing.append(ticker)
            continue
        sectors[ticker] = name

    if missing:
        print(
            f"WARNING: {len(missing)}件の日本株ティッカーがJ-Quantsのマスタに"
            f"見つかりませんでした（新規上場・廃止銘柄等の可能性、手動確認が必要）: {missing}",
            file=sys.stderr,
        )

    print("# 日本株セクター区分（J-Quants /equities/master、東証33業種区分、自動生成）")
    print("# 生成元: scripts/generate_sector_mapping.py")
    print(
        yaml.safe_dump({"sectors": sectors}, allow_unicode=True, sort_keys=True),
        end="",
    )
    print(
        f"\n# {len(sectors)}/{len(universe['japan_equity'])}銘柄を取得しました。"
        f"米国株分・config/sector_mapping.yamlへの統合は別途手動で行ってください。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
