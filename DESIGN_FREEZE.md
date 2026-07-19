# AI投資アシスタント Design Freeze 記録

## Design Freeze日

**2026-07-19**

全体設計書Rev.3、および前提とするLayer1〜Layer8詳細設計書について、実装者目線での最終レビュー（設計矛盾・責務分離・JSON契約・レースコンディション・データ欠損・実装不能箇所・レイヤー依存・GitHub Actions運用の8観点）を実施し、Design Freezeを妨げる重大問題が無いことを確認した上で、本日付でDesign Freezeとする。

---

## 対象文書一覧（Design Freeze版）

| レイヤー | 文書 | 版 |
|---|---|---|
| 全体設計書 | `docs/00_SystemArchitecture.md` | **Rev.3** |
| Layer1（データ取得層） | `layer1_data_acquisition_design.md` | 確定版 |
| Layer2（分析層） | `layer2_analysis_design.md` | Ver1.4確定 |
| Layer3（ニュース処理層） | `layer3_news_processing_design.md` | Ver1.3確定 |
| Layer4（永続化層） | `layer4_persistence_design.md` | Ver1.1確定 |
| Layer5（AI判断層） | `layer5_ai_judgment_design.md` | **Ver1.5確定** |
| Layer6（レポート生成層） | `layer6_report_generation_design.md` | Ver1.1確定 |
| Layer7（提案トラッキング層） | `layer7_proposal_tracking_design.md` | **Ver1.4確定** |
| Layer8（自己評価層） | `layer8_self_evaluation_design.md` | **Ver1.4確定** |

（companion文書として`scoring_specification.md`（Ver1.2確定、Layer2の配点・算出式の別紙）も本Freezeの対象範囲に含む。）

---

## Design Freeze時点で残っているKnown Issue

| # | Issue | 内容 | 現在の扱い |
|---|---|---|---|
| 1 | Layer8 フルリカルクモード未設計 | Layer8詳細設計書§1・§13確定事項1で「増分モード」と並ぶ機能として名称のみ確定しているが、起動方法・`evaluation_index.json`との関係・トランザクション原則との整合は未設計。 | 増分モードによる日次運用（Phase0〜Phase9）をブロックしないため、今回のFreeze対象からは意図的に除外。**将来、実際にこのモードを使用する段階（スコアリングロジック変更時の再集計等）になった時点で、Layer8詳細設計書に設計を追加する。** |

Design Freeze時点で、上記1件以外に残存する重大な設計欠陥・矛盾は無い。

---

## Phase0以降の変更管理ルール

1. **Phase0（環境構築）以降、本Freeze版の設計書本文は変更しない。** 実装中に発見された不具合・改善の必要性は、設計書の修正ではなく、Issue管理（課題管理表・Issueトラッカー等）で個別に記録・追跡する。
2. Issueが「設計そのものの欠陥（責務分離・JSON契約・レイヤー依存等、Freeze対象の確認観点に抵触するもの）」と判明した場合のみ、設計変更のプロセスに戻す。単なる実装上のバグ・パラメータ調整（タイムアウト値等）は設計変更として扱わない。
3. **設計変更が必要と判断された場合は、個別のパッチ的修正を行わず、全体設計書および該当レイヤー詳細設計書を「Rev.4」として改めてまとめて管理する。** Rev.3の内容を直接書き換えることはしない。
4. 上記Known Issue（Layer8フルリカルクモード）の設計追加も、実施時点でRev.4（または該当レイヤーのバージョン単独更新）として記録する。

---

**本書をもって、全体設計書Rev.3およびLayer1〜Layer8詳細設計書（上記版）をDesign Freezeとする。**
