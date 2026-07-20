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
                    jquants.py         実装済み（V2 APIキー方式、日本株）
                    alpha_vantage.py   実装済み（米国株、決算・EPS等の補完用途に限定）
                    twelve_data.py     実装済み（米国株、広範スクリーニングの主力）
                    fred.py            実装済み（マクロ指標）
                    newsapi.py         実装済み（開発・検証用途限定、本番主力はGDELT）
                    gdelt.py           実装済み（本番主力、APIキー不要）
                    web_search_fallback.py  未実装（採用する検索手段が未決定のため保留）

未実装・要検討事項:
  - GoogleDriveCacheStore（本番の永続キャッシュ実装、現状はInMemoryCacheStoreのみ）
  - web_search_fallback.py（どの検索APIを使うか未決定）
  - 各具体Repositoryのレスポンスフィールド名は、ライブAPIでの疎通確認前の
    二次情報ベースの実装であり、実行結果を見ての微調整を要する可能性がある
"""
