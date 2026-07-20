"""Layer1のライブ疎通確認スクリプト。

各Repositoryのユニットテスト（tests/layer1/）はモックしたレスポンスに対して行って
おり、実際のライブAPIレスポンスとは未照合の部分がある（各repositories/*.pyの
モジュールdocstring参照）。本スクリプトは実際のAPIキーを使って少数の銘柄・系列で
実データ取得を行い、フィールド名マッピングのズレを早期発見するためのものである。

Phase1完了基準（layer1_data_acquisition_design.md 9章）の1・6・7項目に対応する。
失敗した場合はエラー内容をログに出力し、そのメッセージをもとにRepository実装側の
フィールド名マッピングを調整する。

このスクリプトはユニットテストではなく、実行のたびに実際の外部APIを呼び出す
（レート制限を消費する）。CIでは手動実行のワークフロー内でのみ実行すること。
"""

from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_investment_assistant.layer1_data_acquisition.caching import InMemoryCacheStore
from ai_investment_assistant.layer1_data_acquisition.exceptions import DataSourceError
from ai_investment_assistant.layer1_data_acquisition.factory import RepositoryFactory

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "api_sources.yaml"

# ライブ確認用の少数サンプル（Phase1完了基準1「数銘柄程度」に対応）
JAPAN_TICKERS = ["7203"]  # トヨタ自動車
US_TICKERS = ["AAPL"]
FRED_SERIES = ["CPIAUCSL"]
NEWS_QUERY = ["Toyota"]

TODAY = date.today()
LOOKBACK_DAYS = 14


def _run_check(name: str, fn) -> bool:
    print(f"--- {name} ---")
    try:
        result = fn()
        print(f"[OK] {name}: {result}")
        return True
    except DataSourceError as exc:
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: unexpected error: {exc}")
        traceback.print_exc()
        return False


def main() -> int:
    # 実行内メモリキャッシュのみを使う（Google Driveへの書き込みは行わない疎通確認用途）。
    factory = RepositoryFactory.from_yaml(CONFIG_PATH, cache_store=InMemoryCacheStore())
    start = TODAY - timedelta(days=LOOKBACK_DAYS)

    results = []

    try:
        japan_chain = factory.build_chain("japan_equity")
        for ticker in JAPAN_TICKERS:
            results.append(
                _run_check(
                    f"japan_equity.get_daily_prices({ticker})",
                    lambda t=ticker: japan_chain.call("get_daily_prices", t, start, TODAY),
                )
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] japan_equity chain build: {exc}")
        results.append(False)

    try:
        us_chain = factory.build_chain("us_equity")
        for ticker in US_TICKERS:
            results.append(
                _run_check(
                    f"us_equity.get_daily_prices({ticker})",
                    lambda t=ticker: us_chain.call("get_daily_prices", t, start, TODAY),
                )
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] us_equity chain build: {exc}")
        results.append(False)

    try:
        macro_chain = factory.build_chain("macro")
        for series_id in FRED_SERIES:
            results.append(
                _run_check(
                    f"macro.get_series({series_id})",
                    lambda s=series_id: macro_chain.call("get_series", s, start, TODAY),
                )
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] macro chain build: {exc}")
        results.append(False)

    try:
        news_chain = factory.build_chain("news")
        results.append(
            _run_check(
                f"news.fetch_news({NEWS_QUERY})",
                lambda: news_chain.call("fetch_news", NEWS_QUERY, start, TODAY),
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] news chain build: {exc}")
        results.append(False)

    print("---")
    passed = sum(1 for r in results if r)
    print(f"[SUMMARY] {passed}/{len(results)} live checks passed")

    if passed < len(results):
        print(
            "[NOTE] 失敗があってもこの時点では想定内の場合がある"
            "（実レスポンスのフィールド名調整が必要な可能性、各repositories/*.pyの"
            "モジュールdocstring参照）。エラーメッセージをClaudeに共有すれば調整する。"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
