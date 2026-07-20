"""Layer1（データ取得層）。

詳細設計: layer1_data_acquisition_design.md（確定版）
実装はPhase1で行う。想定モジュール構成（設計書§3参照）:

  interfaces.py   MarketDataRepository / NewsRepository / MacroRepository 抽象クラス（§3-2）
  models.py       PriceSeries / FundamentalSnapshot / TickerInfo / RawNewsItem /
                  TimeSeries / DataFetchMeta 正規化スキーマ（§4）
  factory.py      RepositoryFactory（config/api_sources.yaml を読み込む、§3-2）
  fallback.py     FallbackChainRepository（§5）
  caching.py      CachingRepositoryDecorator（§6）
  repositories/   具体Repository実装（jquants.py, alpha_vantage.py, twelve_data.py,
                  fred.py, newsapi.py, gdelt.py, web_search_fallback.py）
"""
