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
    claude_structurer.py ClaudeStructurer（実装済み、Ver1初期採用。ライブAPIキー未検証）
    gpt_structurer.py / gemini_structurer.py / local_llm_structurer.py  未実装
  fetcher.py            Layer1 NewsRepository経由でのニュース取得（実装済み、§3・§4）
  cache_manager.py       処理済み記事のキャッシュ管理（実装済み、Layer1のCacheStoreを再利用）
  main.py                Layer3パイプラインのエントリポイント（実装済み、§4）

未実装・要検討事項:
  - ClaudeStructurerの実際のAnthropic APIレスポンスは未検証（ANTHROPIC_API_KEYが
    このクラウド作業環境に共有されていないため）。GitHub Secretsへの登録と、
    ライブ実行結果の共有が必要
  - prompts/news_structuring_prompt_template.md は claude_structurer.py の
    build_prompt() 関数にインライン実装している（設計書は別ファイルでの一元管理を
    想定しているが、Ver1はGPT/Gemini実装が無いため、切り出しは複数ベンダー実装が
    揃った時点で行う）
"""
