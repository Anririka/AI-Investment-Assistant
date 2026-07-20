"""Layer3（ニュース処理層）。

詳細設計: layer3_news_processing_design.md（確定版・Ver1.3）

実装状況（Phase3）:
  schema.py           StructuredNewsItemのスキーマ定義・バリデーション（実装済み、§8）
  deduplicator.py      完全一致・見出し類似度による重複除去（実装済み、§4-4）
  preprocessor.py       HTML除去・Unicode正規化・トリミング（実装済み、§4-5）
  quality_filter.py     記事品質フィルタ（実装済み、§4-1）
  freshness.py          age_hours計算（実装済み、§4-7）
  importance_rules.py   重要度のルールベース補正（実装済み、§4-2）
  llm_structurer/
    base.py             NewsStructurer抽象クラス（実装済み、§6）
    prompt_common.py     プロンプト・抽出スキーマの共有部分（実装済み、§7、ベンダー非依存）
    claude_structurer.py ClaudeStructurer（実装済み。コスト最適化のため既定では未使用、
                         provider: claudeへ戻せばすぐ使える形で維持。ライブAPIキー未検証）
    gemini_structurer.py GeminiStructurer（実装済み・既定のprovider。無料枠を利用しコストを
                         回避する構成。ライブAPIキー未検証）
    gpt_structurer.py / local_llm_structurer.py  未実装
  structurer_factory.py  config/ai_provider.yamlのprovider指定からNewsStructurerを
                         組み立てる（実装済み、§6「コード変更なしでの切替」）
  fetcher.py            Layer1 NewsRepository経由でのニュース取得（実装済み、§3・§4）
  cache_manager.py       処理済み記事のキャッシュ管理（実装済み、Layer1のCacheStoreを再利用）
  main.py                Layer3パイプラインのエントリポイント（実装済み、§4）

未実装・要検討事項:
  - GeminiStructurer・ClaudeStructurerともに実際のAPIレスポンスは未検証
    （GEMINI_API_KEY／ANTHROPIC_API_KEYがこのクラウド作業環境に共有されていないため）。
    GitHub Secretsへの登録と、ライブ実行結果の共有が必要
  - Gemini無料枠のレート制限（1日あたりの上限等）は公開ドキュメント上で流動的なため、
    実際の記事数（1日50〜150件相当）に対して十分か、稼働開始前に
    https://aistudio.google.com/rate-limit で確認することを推奨する
  - prompts/news_structuring_prompt_template.md は llm_structurer/prompt_common.py の
    build_prompt() 関数にインライン実装している（設計書は別ファイルでの一元管理を
    想定しているが、当面はこの形で運用し、必要になれば切り出す）
"""
