# AI投資アシスタント（AI Investment Assistant）

日々の市場データ・ニュース・マクロ指標を多角的に分析し、AIが投資候補を評価・提案し、その提案の実績を自動追跡・自己評価することで、人間のレビューを介した継続的改善を可能にする「AI投資アシスタント」システムの設計・実装リポジトリです。

単なるニュース要約ツールではなく、市場データそのものの定量分析を軸とし、LLMは定性判断・自然文説明・最終採否判断にのみ関与する市場データ分析AIシステムとして設計されています。

## 現在のステータス：Design Freeze（設計凍結）

**2026-07-19付で、全体設計書Rev.3およびLayer1〜Layer8詳細設計書はDesign Freeze状態です。**

実装者目線での最終レビュー（設計矛盾・責務分離・JSON契約・レースコンディション・データ欠損・実装不能箇所・レイヤー依存・GitHub Actions運用の8観点）を実施し、Design Freezeを妨げる重大問題が無いことを確認した上でFreezeとしています。詳細は [`DESIGN_FREEZE.md`](./DESIGN_FREEZE.md) を参照してください。

Phase0（環境構築）以降、Freeze版の設計書本文は変更しません。実装中に発見された不具合・改善の必要性は設計書の修正ではなくIssue管理で追跡し、設計そのものの変更が必要と判断された場合のみ「Rev.4」として改めてまとめます（Rev.3を直接書き換えることはしません）。

## システム構成（Layer1〜Layer8）

| レイヤー | 名称 | 主な責務 |
|---|---|---|
| Layer1 | データ取得層 | 日本株・米国株・マクロ・ニュースの生データ取得、フォールバック、正規化 |
| Layer2 | 分析層 | テクニカル/ファンダメンタル/需給/マクロ/レジーム/ニュースの6軸スコアリング、総合スコア算出、候補選定 |
| Layer3 | ニュース処理層 | ニュース取得・重複除去・品質フィルタ・LLM構造化・重要度補正 |
| Layer4 | 永続化層 | Layer2出力の非加工保存、完了フラグ生成、実行ログ・履歴インデックス管理 |
| Layer5 | AI判断層 | 完了フラグ確認、LLMによる総合投資判断、推奨株数/損切/利確の確定計算、ハードルール強制 |
| Layer6 | レポート生成層 | decision JSONの表示用整形、Google Sheets/Markdown出力 |
| Layer7 | 提案トラッキング層 | 提案の実勢価格追跡、利確/損切/期間満了判定、実績記録 |
| Layer8 | 自己評価層 | 提案実績の分析、成績集計、人間レビュー用フィードバック生成 |

（Layer9「運用成績ダッシュボード」は今回のスコープ外です。）

設計思想（数値計算とLLM判断の分離、Repository/Sink抽象化、完全なログ保存、上流層の不可侵、Google Driveへの永続化一本化 等）の詳細は [`docs/00_SystemArchitecture.md`](./docs/00_SystemArchitecture.md) を参照してください。

## ディレクトリ構成

```
AI-Investment-Assistant/
├── README.md                 本ファイル
├── DESIGN_FREEZE.md           Design Freeze記録
├── .gitignore
├── requirements.txt           （未作成：実装未着手のため。下記「今後の予定」参照）
│
├── docs/                      設計書一式（Design Freeze対象）
│   ├── 00_SystemArchitecture.md
│   ├── layer1_data_acquisition_design.md
│   ├── layer2_analysis_design.md
│   ├── layer3_news_processing_design.md
│   ├── layer4_persistence_design.md
│   ├── layer5_ai_judgment_design.md
│   ├── layer6_report_generation_design.md
│   ├── layer7_proposal_tracking_design.md
│   ├── layer8_self_evaluation_design.md
│   ├── scoring_specification.md
│   └── DESIGN_FREEZE.md
│
├── src/                        実装コード（Phase0以降に格納予定、現在は空）
├── config/                     設定ファイル（Phase0以降に格納予定、現在は空）
├── tests/                      テストコード（Phase0以降に格納予定、現在は空）
├── scripts/                    運用スクリプト（Phase0以降に格納予定、現在は空）
├── data/                       ローカルデータ（Phase0以降に格納予定、現在は空。実行結果・スナップショット等の恒久データはGoogle Driveに保存する設計のため、原則キャッシュ等の一時利用のみ）
└── .github/
    └── workflows/              GitHub Actionsワークフロー（Phase0以降に格納予定、現在は空）
```

## 今後の予定

本リポジトリは現時点で設計フェーズの成果物のみを格納しています。`docs/00_SystemArchitecture.md` §9に記載のPhaseロードマップ（Phase0: 環境構築 〜）に沿って実装を開始した時点で、`src/`・`config/`・`tests/`・`scripts/`・`.github/workflows/`への格納、および`requirements.txt`の作成を行います。
