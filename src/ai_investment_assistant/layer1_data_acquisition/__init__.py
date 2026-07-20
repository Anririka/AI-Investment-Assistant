"""Layer1（データ取得層）。

詳細設計: layer1_data_acquisition_design.md（確定版）

実装状況（Phase1、段階的に拡張中）:
  models.py       正規化スキーマ（実装済み、4章）
  interfaces.py   抽象Repositoryインターフェース（実装済み、3-2）
  exceptions.py   エラー分類に対応する例外階層（実装済み、5-1）
  ratelimit.py    共通レートリミッタ（実装済み、6-2）
  fallback.py     FallbackChainRepository（実装済み、5章）
  caching.py      CachingRepositoryDecorator（実装済み、6章・7章。永続化はGoogle Drive
                  実装への差し替えを前提としたCacheStore抽象化のみ済み、実際の
                  GoogleDriveCacheStoreはPhase1後半で実装）
  factory.py      RepositoryFactory（実装済み、3-2・3-3）
  repositories/   具体Repository実装
                    jquants.py         実装済み（V2 APIキー方式）
                    alpha_vantage.py   未実装
                    twelve_data.py     未実装
                    fred.py            未実装
                    newsapi.py         未実装
                    gdelt.py           未実装
                    web_search_fallback.py  未実装
"""
