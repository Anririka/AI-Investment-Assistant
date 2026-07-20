"""Layer2（分析層）。

詳細設計: layer2_analysis_design.md（確定版・Ver1.4）
配点・算出式: scoring_specification.md（確定版・Ver1.2）

実装状況（Phase2）:
  bucket.py               バケット表スコア化の共通ユーティリティ（実装済み）
  reallocation.py          欠損時の重み再配分ロジック（実装済み、scoring_specification.md 4章）
  exceptions.py            SchemaVersionError等（実装済み）
  technical_indicators.py  テクニカル軸（実装済み）
  fundamental_metrics.py   ファンダメンタル軸（実装済み、PERScorerはStrategyパターン）
  supply_demand.py         需給軸（実装済み）
  macro_evaluator.py       マクロ軸（実装済み、セクター感応度補正インターフェース込み）
  regime_detector.py       市場レジーム判定（実装済み）
  news_scorer.py           ニュース軸（実装済み、score/uncertainty分離）
  scorer.py                全軸統合・総合スコア算出（実装済み）
  screener.py              母集団フィルタリング（実装済み）
  ranking.py               順位付け（実装済み）
  json_builder.py          Layer5向け最終JSON生成（実装済み）
  schemas/layer2_output.schema.json  出力JSON Schema（実装済み、jsonschemaでvalidation）

未実装・要検討事項:
  - config/universe.yaml は動作確認用のプレースホルダー銘柄リストであり、
    本番運用前に実際の日経225/S&P500構成銘柄リストへの差し替えが必要
  - Layer3（ニュース処理層）が未実装のため、news_scorer.pyの入力(StructuredNewsItem)は
    テスト内で模擬データを用いて検証している
  - prompt_budgetのactive_provider解決は、Layer5実装まで固定値（claude）を使用
"""
