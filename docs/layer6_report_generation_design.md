# レポート生成層（Layer6）詳細設計書

作成日: 2026-07-18（Ver1.1：保存場所統一・入力契約簡素化・PresentationModelへの改称・市場環境セクションの正直化を反映）
前提: Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Layer3詳細設計書（確定版・Ver1.3）／Layer4詳細設計書（確定版・Ver1.1）／Layer5詳細設計書（確定版・Ver1.3）と整合。**Layer1〜5はすべて確定済みであり、本書はそれらの責務境界・入出力契約を一切変更しない。**

---

## 0. Layer6の位置付け

Layer5詳細設計書§0・Layer4詳細設計書§0で整理した全体構造を継承し、Layer6を以下のように位置付ける。

```
Layer1〜4  Python Pipeline（GitHub Actions上で完結）
    ↓
Layer5     AI Agent実行層（Claude Coworkセッション。総合判断・decision JSON生成）
    ↓
Layer6     Report Generator（表示専用層。判断は一切行わない）
    ↓
Layer7〜9  提案トラッキング／自己評価／運用成績ダッシュボード（Ver2で設計、別途詳細化）
```

**Layer6の実行モデル（確定）**：Ver1では、Layer5と同一のClaude Coworkセッション内で継続実行する構成を採用する。Layer6はAI判断を一切行わない**純粋な決定的処理**であるため、Layer5のようなAIエージェント実行層である必要はないが、Ver1では実装・運用の簡素化を優先し、Layer5がdecision JSONを確定した直後に同一セッション内でLayer6のスクリプト群をBash/Pythonツールで呼び出す（Layer5詳細設計書§3の手順8〜9の直後に接続する）。将来的にGitHub Actions等の独立ジョブへ分離可能な構造は維持する（§11のSink抽象化・§4の入力契約により、Layer6内部のロジックは実行主体が変わっても変更不要）が、**独立実行への分離自体はVer2以降の改善項目とする**。

**Layer6の入力の受け取り方（確定・重要）**：Layer6は**decision JSONオブジェクトを受け取ることのみ**を入力契約とする。このJSONがどこに保存されているか（Google Driveのパス等）は**Layer5の責務であり、Layer6は一切意識しない**（§4参照）。Ver1（同一セッション継続）ではプロセス内でオブジェクトをそのまま受け取る形になるが、これは「たまたま今の実行形態がそうなっている」というだけであり、Layer6の設計・契約としては「decision JSONオブジェクトを受け取る」という1点のみを前提とする。

**Layer5との保存責務の分担（重要）**：Layer5の`decision_writer.py`は、生のdecision JSON自体をGoogle Driveへ保存する責務を既に持つ（Layer5詳細設計書§3手順8）。**Layer6はこの生JSONの保存を重複して行わない**。Layer6が保存するのは、生JSONを人間向けに整形した後の成果物（Google Sheetsの行、Markdownファイル）のみである。

---

## 1. 責務・非責務

**責務**：
- Layer5出力JSON（decision JSON）の読込
- Google Sheetsへの保存（本日の提案・除外/不採用ログ・ルール適用ログ・履歴）
- Markdownレポート生成
- 日次サマリー生成
- 判断理由の見やすい整形
- 各候補のスコア表示
- リスク説明表示
- ルール適用結果（`rule_enforcement_log`）表示
- `decision_log`表示（採用・不採用・除外の全件）
- 履歴保存（生成したレポート自体の履歴管理）
- エラー時（データ品質ゲートで様子見確定時等）のレポート生成

**非責務**：
- AI判断（買い/売り/様子見の決定はLayer5の責務。Layer6は決定結果を表示するのみ）
- 数値計算・スコア再計算・ランキング変更・推奨株数の再計算（すべてLayer2／Layer5の責務。Layer6は値を一切変更しない）
- decision JSON自体の内容変更・上書き（Layer6が読み込んだJSONの値は、表示用に形式変換されるのみで、意味・数値は変わらない）
- decision JSON自体の生成・Google Driveへの一次保存（Layer5 `decision_writer.py`の責務。§0参照）
- データ取得（Layer1）・分析／スコアリング（Layer2）・ニュース構造化（Layer3）・永続化（Layer4）・AI判断（Layer5）の重複実施

---

## 2. モジュール構成

```
src/report_generation/
├── presentation_model.py        # Layer5 JSON → 内部の「PresentationModel（表示専用モデル）」への変換（値は一切変更しない。集計・加工ロジックの温床にならないよう「表示専用」であることが伝わる名称にした）
├── sinks/                        # 出力媒体ごとの実装（差し替え可能設計、§11）
│   ├── base.py                    # ReportSink 抽象クラス
│   ├── google_sheets_sink.py      # Google Sheets出力
│   ├── markdown_sink.py           # Markdownレポート出力
│   ├── notion_sink.py             # 【将来枠、未実装】
│   ├── pdf_sink.py                # 【将来枠、未実装】
│   ├── email_sink.py              # 【将来枠、未実装】
│   ├── slack_sink.py              # 【将来枠、未実装】
│   └── line_sink.py               # 【将来枠、未実装】
├── formatters/                    # 表示用の整形ロジック（値は変えず、文字列・表形式への変換のみ）
│   ├── candidate_formatter.py     # 候補一覧・スコア・リスク説明の整形
│   ├── decision_log_formatter.py  # decision_logの整形（§8）
│   └── rule_enforcement_formatter.py  # rule_enforcement_logの整形（§9）
├── error_report_builder.py        # データ品質ゲートblocked時・JSON異常時のレポート生成（§10）
├── history_writer.py              # 生成レポート自体の履歴保存・履歴インデックス管理
└── main.py                         # Layer6パイプラインのエントリポイント
```

---

## 3. 実行フロー

1. Layer5が`decision_writer.py`によりdecision JSONを確定・Google Driveへ保存する（Layer5詳細設計書§3手順8）。この保存先・保存方法はLayer5の責務であり、Layer6は関知しない。
2. 同一Claude Coworkセッション内で、Layer6の処理をBash/Pythonツールで呼び出す（`main.py`相当）。この時点でLayer6はdecision JSONオブジェクトを受け取る（§4）。
3. `presentation_model.py`が受け取ったdecision JSONを`PresentationModel`へ変換する。この変換は**値の参照・整形のみ**で、加工・再計算は一切行わない。
4. `run_meta.data_quality_gate`を確認する。
   - `blocked`の場合：§10のエラー時レポート生成へ分岐し、以降の通常フローは実行しない。
   - `passed`／`warning_continued`の場合：通常フローを継続する。
5. 各`ReportSink`実装（現行は`GoogleSheetsSink`・`MarkdownSink`）を順に呼び出し、同一の`PresentationModel`からそれぞれの媒体向け出力を生成・保存する。**1つのSinkの失敗が他のSinkの実行を妨げない**（§10）。
6. `history_writer.py`が、生成されたレポートのメタ情報（日付・run_id・提案件数等）を履歴インデックスに追記する。
7. 完了。

---

## 4. Layer5との入力契約

Layer6の入力は**decision JSONオブジェクト（Layer5詳細設計書§9で確定済みのスキーマ）のみ**とする。Layer6はこれ以外のデータソース（Layer1〜4の出力、`取引記録_*.csv`等）に一切アクセスしない。

### 4-1. 入力の受け渡し方（確定・責務分離を明確化）

**Layer6は「decision JSONというオブジェクトを受け取る」ことのみを契約とし、そのJSONがどこにどう保存されているか（Google Driveのパス、ファイル名等）は一切意識しない。** 保存場所・保存方法はLayer5（`decision_writer.py`）の責務であり、Layer6の設計・実装がそれに依存することはない。

- Ver1（同一Claude Coworkセッション継続、§0）では、実行環境の都合上、Layer5が生成したdecision JSONオブジェクトをプロセス内でそのまま受け取る形になる。
- 将来Layer6が独立プロセスとして分離された場合も、「どこからdecision JSONを取得してLayer6に渡すか」は呼び出し側（オーケストレーション側）の責務であり、Layer6自体のロジックは「受け取ったJSONオブジェクトを処理する」という契約のまま変更を要しない。

この整理により、Layer6の設計書に「Layer5の保存先パス」を明文化する必要が無くなり、Layer5・Layer6双方の責務がより明確に分離される。

### 4-2. 入力スキーマ（Layer5詳細設計書§9をそのまま参照）

```json
{
  "run_meta": {
    "run_id": "string",
    "layer5_started_at": "datetime",
    "layer5_completed_at": "datetime",
    "data_quality_gate": "passed | warning_continued | blocked",
    "data_quality_gate_detail": { "blocking_errors_found": [], "warning_errors_found": [] },
    "score_meta_ref": { "scoring_version": "string", "weight_version": "string" }
  },
  "proposals": [ "...(Layer5詳細設計書§9の1候補分の構造)" ],
  "decision_log": [ "...(採用/不採用/除外の全候補)" ],
  "rule_enforcement_log": [ "...(適用されたハードルールの記録)" ]
}
```

Layer6はこのJSONの**トップレベル4キー（`run_meta`／`proposals`／`decision_log`／`rule_enforcement_log`）のみを参照する**。内部の個々のフィールド（`take_profit_target_pct`、`score_summary.news.uncertainty`等）についても、値をそのまま表示用に転記するのみで、意味の解釈・再計算は一切行わない。

---

## 5. レポート生成仕様

### 5-1. 絶対原則

- **値の意味を変更しない**：数値・文字列のいずれも、Layer5が出力した値をそのまま使用する。単位変換・丸め処理（表示桁数の調整等）は「表示形式の変換」として許容するが、その場合も元の値は保持し、丸めた値だけを表示に用いる（内部データとしては原本を保持する）。
- **表示順序の並び替えは許可、値の並び替え（ランキング変更）は禁止**：例えば「`rank`昇順で表示する」「資産クラスごとにグルーピングして表示する」といった**既存フィールド値に基づく整列**は表示上の整形として許可する。一方、`rank`や`composite`スコアの値そのものを書き換えたり、Layer6独自の基準で優先順位を再計算したりすることは禁止する。この区別を明確にするため、以降「整列（許可）」と「値の変更（禁止）」を明示的に書き分ける。
- **JSONの書き換え禁止**：Layer6はdecision JSONファイル自体を上書き・追記しない（Layer5が保存した生JSONは不可侵）。Layer6が書き込むのはGoogle Sheets／Markdown等、別媒体の成果物のみ。

### 5-2. 「市場環境」セクションに関する制約（重要・要確認事項）

Ver1で想定していた「市場環境（指数・為替・金利の動き）」の物語的な説明は、**Layer5の確定出力JSON（§9）には含まれていない**。Layer5の`run_meta`は実行メタ情報とデータ品質ゲートの状態のみを持ち、Layer2が生成していたような`regime.regime_reason`や`macro.axis_score_reason`のような物語的テキストは、Layer5からLayer6へは伝播しない設計になっている（Layer5はLayer2の`market_snapshot`全体ではなく、判断結果に絞ったdecision JSONのみを出力するため）。

**確定方針（Ver1）**：`proposals[].score_summary.macro`／`score_summary.regime_fit`は、あくまで「提案候補個別の評価に使われたスコア」であり、それらを平均する等して「市場環境」であるかのように表示することは、**意味が異なる情報を市場環境として偽装することになり、かえって誤解を招く**。したがって、Ver1ではこのような集計値を「市場環境」として表示することはせず、**Markdownレポートの「市場環境」セクションには「現在のLayer5出力には市場全体情報が含まれないため省略」と明記するのみ**とする（§7-1）。存在しない・意味の異なる情報を無理に埋めるより、正直に「無い」と示す方が誠実である。豊かな市場環境の物語的説明（例：「本日は円安、NASDAQ堅調、半導体強い」等）を出力したい場合は、Layer5の出力JSONに`market_context`のような新規フィールド（regime/macroのナラティブサマリー）を追加する拡張が必要になるが、これは**Layer5詳細設計書の変更を伴うため今回のスコープ外**とし、必要になった時点でLayer5への追加を検討する（§14確定事項2）。

---

## 6. Google Sheets保存仕様

### 6-1. シート構成

Ver1の運用（`提案ログ_YYYYMMDD.csv`をGoogle Sheetsとして保存）をそのまま継承・拡張する。既存のGoogle Driveコネクタは既存ファイルの直接編集ができないため（Layer1確立当初からの制約）、**日次で新規ファイルを作成する運用を維持する**。

1シートのファイルではなく、1ファイル内に複数シート（タブ）を持たせる構成とする。

| シート名 | 内容 | 対応するdecision JSON |
|---|---|---|
| 本日の提案 | 採用された提案（最大3件） | `proposals` |
| 除外・不採用ログ | 不採用・除外された全候補 | `decision_log`（`decision != "adopted"`） |
| ルール適用ログ | ハードルールの適用記録 | `rule_enforcement_log` |
| 実行サマリー | 当日の実行メタ情報 | `run_meta` |

### 6-2. ファイル命名・日付管理

- ファイル名：`提案ログ_YYYYMMDD`（Ver1の既存命名規則をそのまま踏襲。`YYYYMMDD`はJST基準の実行日）
- 同日再実行時：Layer1詳細設計書・Layer4詳細設計書と同様、既存ファイルは上書きできないため、旧ファイルはそのまま残し新ファイルを正規のファイル名で作成する（Google Driveの`search_files`で`createdTime`が最新のものを正とする、既存の運用ルールと同一）。

### 6-3. 「本日の提案」シートの列構成

| 列名 | 対応フィールド |
|---|---|
| 日付 | （実行日、`run_meta`から導出） |
| run_id | `run_meta.run_id` |
| 推奨順位 | `proposals[].rank` |
| 資産クラス | `proposals[].asset_class` |
| 銘柄名 | `proposals[].name` |
| 証券コード | `proposals[].ticker` |
| 総合評価 | `proposals[].overall_assessment` |
| 推奨株数 | `proposals[].recommended_shares` |
| 購入価格目安 | `proposals[].entry_price_basis` |
| 投資金額 | `proposals[].position_amount` |
| 損切価格 | `proposals[].stop_loss_price` |
| 利確価格 | `proposals[].take_profit_price` |
| 利確目標騰落率(%) | `proposals[].take_profit_target_pct` |
| 想定リターン(%) | `proposals[].expected_return_pct` |
| 想定損失(%) | `proposals[].expected_loss_pct` |
| リスクリワード比 | `proposals[].risk_reward_ratio` |
| 想定保有期間 | `proposals[].holding_period` |
| 信頼度 | `proposals[].confidence` |
| 投資理由 | `proposals[].investment_reason` |
| リスク要因 | `proposals[].risk_factors` |
| テクニカルスコア | `proposals[].score_summary.technical` |
| ファンダメンタルスコア | `proposals[].score_summary.fundamental` |
| 需給スコア | `proposals[].score_summary.supply_demand` |
| マクロスコア | `proposals[].score_summary.macro` |
| ニューススコア | `proposals[].score_summary.news.score` |
| ニュース不確実性 | `proposals[].score_summary.news.uncertainty` |
| レジーム適合スコア | `proposals[].score_summary.regime_fit` |
| 総合スコア | `proposals[].score_summary.composite` |
| 代替候補 | `proposals[].alternative_candidates`（カンマ区切り文字列化） |

この列構成は、Ver2で確定した「提案ログ」拡張スキーマ（推奨順位・期待損失・リスクリワード比・代替候補・スコア内訳を含む）をそのまま満たす。

### 6-4. 「除外・不採用ログ」シートの列構成

| 列名 | 対応フィールド |
|---|---|
| 日付 | （実行日） |
| run_id | `run_meta.run_id` |
| 証券コード | `decision_log[].ticker` |
| 判定 | `decision_log[].decision`（`rejected`／`not_selected`） |
| 順位 | `decision_log[].rank`（存在する場合） |
| 理由コード | `decision_log[].reason_code` |
| 理由 | `decision_log[].reason` |

### 6-5. 「ルール適用ログ」シートの列構成

| 列名 | 対応フィールド |
|---|---|
| 日付 | （実行日） |
| run_id | `run_meta.run_id` |
| ルール名 | `rule_enforcement_log[].rule` |
| 適用有無 | `rule_enforcement_log[].applied` |
| 詳細 | `rule_enforcement_log[].detail` |

### 6-6. 履歴管理・過去比較

各日のシートは独立したファイルとして蓄積される（削除しない）ため、それ自体が履歴となる。ただし日々のファイルを都度開いて比較するのは非効率なため、Layer4詳細設計書§5-4の`history/index_YYYYMM.json`と同じ考え方で、**Layer6専用の軽量インデックス**を`reports/report_index_YYYYMM.json`として維持する。

**保存場所の修正（重要）**：当初`decisions/decision_index_YYYYMM.json`として設計していたが、`decisions/`はLayer5が出力するAI判断JSON（生データ）の置き場所であり、Layer6が生成する「レポート管理用メタデータ」とは責務が異なる。Layer6が生成・管理するインデックスは、Layer6自身の成果物置き場である`reports/`フォルダの下に置くことで、「`decisions/`＝Layer5の生JSON置き場」「`reports/`＝Layer6の成果物置き場（Markdownレポート＋そのインデックス）」という責務の対応が明確になる。Layer4の`history/`（パイプライン実行の履歴）とも責務が異なるため、あえて同じ場所には置かない。

```json
{
  "entries": [
    {
      "date": "2026-07-18",
      "run_id": "20260718-0630",
      "sheet_file": "提案ログ_20260718",
      "proposal_count": 1,
      "top_ticker": "NVDA",
      "top_composite_score": 79,
      "data_quality_gate": "passed"
    }
  ]
}
```

**最新判定表示**：「最新の判断」を参照する際は、Ver1確立当初からの運用（`search_files`で`createdTime`最大のファイルを正とする）をそのまま踏襲する。特別な「最新ポインタ」ファイルは設けない（既存運用との一貫性を優先）。

**過去比較**：`reports/report_index_YYYYMM.json`を用いることで、「直近1ヶ月の`top_composite_score`の推移」等の比較を、日次ファイルを毎回開かずに行える。

---

## 7. Markdownレポート仕様

### 7-1. 全体構成

```markdown
# AI投資アシスタント 日次レポート — {YYYY年MM月DD日}

## 市場環境
（現在のLayer5出力には市場全体情報が含まれないため省略）

## データ品質
- データ品質ゲート: {passed / warning_continued / blocked}
- {warning_continued の場合} 検知された警告: {data_quality_gate_detail.warning_errors_found の一覧}

## 本日の提案（{proposals件数}件）

### 第{rank}位：{name}（{ticker}／{asset_class}）

【総合評価】{overall_assessment}
【推奨株数】{recommended_shares}
【購入価格目安】{entry_price_basis}
【損切価格】{stop_loss_price}
【利確価格】{take_profit_price}（目標騰落率 {take_profit_target_pct}%、根拠：{take_profit_basis}）
【想定リターン】{expected_return_pct}%　【想定損失】{expected_loss_pct}%　【リスクリワード比】{risk_reward_ratio}
【想定保有期間】{holding_period}
【信頼度】{confidence}
【投資理由】
{investment_reason}
【リスク要因】
{risk_factors}
【スコア内訳】

| 評価軸 | スコア |
|---|---|
| テクニカル | {technical} |
| ファンダメンタル | {fundamental} |
| 需給 | {supply_demand} |
| マクロ | {macro} |
| ニュース | {news.score}（不確実性: {news.uncertainty}） |
| 市場レジーム適合 | {regime_fit} |
| **総合** | **{composite}** |

【代替候補】{alternative_candidates}

（`proposals`の件数分繰り返し。`proposals`が0件の場合は「本日は提案なし（該当候補なし）」と記載）

## 除外・不採用候補

| 証券コード | 判定 | 理由コード | 理由 |
|---|---|---|---|
| {ticker} | {decision} | {reason_code} | {reason} |

## ルール適用ログ

| ルール | 適用有無 | 詳細 |
|---|---|---|
| {rule} | {applied} | {detail} |

## 実行ログ

- run_id: {run_id}
- 開始時刻: {layer5_started_at}
- 終了時刻: {layer5_completed_at}
- データ品質ゲート: {data_quality_gate}
- スコアリングバージョン: {score_meta_ref.scoring_version} / 配点バージョン: {score_meta_ref.weight_version}

---
本提案は情報提供を目的としたものであり、投資成果を保証するものではありません。最終判断はご自身で行ってください。
```

### 7-2. 見出しレベル

`#`（レポートタイトル）→`##`（大セクション：市場環境／データ品質／本日の提案／除外候補／ルール適用ログ／実行ログ）→`###`（提案ごとの小見出し）の3階層に統一する。

### 7-3. ファイル命名・保存先

- ファイル名：`reports/report_YYYYMMDD.md`（新設フォルダ`reports/`。Google Driveの既存フォルダ構成に追加。同フォルダに§6-6の`report_index_YYYYMM.json`も格納する）
- 同日再実行時：Sheetsと同様、旧ファイルはそのまま残し新規ファイルを作成する。

---

## 8. decision_log表示仕様

- `decision_log`の全件を、Google Sheets「除外・不採用ログ」シートおよびMarkdownレポート「除外・不採用候補」セクションの**両方**に表示する（媒体によって内容を選別しない。Ver2「AI判断ログの完全保存」要件を表示レベルでも徹底する）。
- 表示順序：`decision`の種別（`rejected`→`not_selected`の順）、同一種別内では`rank`（存在する場合）昇順、`rank`が無い場合は`ticker`のアルファベット順とする。**これは整列であり、`decision_log`内の値そのものは変更しない**（§5-1）。
- `reason`が存在しない（`null`）場合、表内は空欄とし、「理由未記載」等の推測的な補完はしない（Layer6が独自の解釈を加えないという原則の徹底）。

---

## 9. rule_enforcement_log表示仕様

- `rule_enforcement_log`の全件を、Google Sheets「ルール適用ログ」シートおよびMarkdownレポート「ルール適用ログ」セクションの両方に表示する。
- `applied: false`のエントリも省略せず表示する（「どのルールが今回は発動しなかったか」も、Ver2の透明性要件に沿って可視化する）。
- `detail`が存在しない場合は空欄とする（§8と同じ方針）。

---

## 10. エラー処理

| 事象 | 対応 |
|---|---|
| decision JSON自体が存在しない／読み込めない | `error_report_builder.py`が最小限のエラーレポート（「本日のレポート生成に失敗しました。Layer5の出力が確認できません」）をMarkdownとして生成し、Google Sheetsへの書き込みは試行しない（表示すべきデータが無いため） |
| `run_meta.data_quality_gate` が `blocked` | 通常のレポートではなく、「本日は様子見（データ品質ゲートによりブロック）」を明記した簡易レポートを生成する。`data_quality_gate_detail.blocking_errors_found`の内容をそのまま表示する（Layer6は原因を解釈・推測しない） |
| decision JSONのトップレベルキー欠落（`proposals`等が無い） | Layer5の契約違反の可能性が高いため、`error_report_builder.py`が診断的なエラーレポートを生成し、通常のフォーマット処理は行わない（不完全なデータで見た目だけ整えたレポートを出さない） |
| Google Sheets書き込み失敗 | リトライ後、なお失敗する場合はエラーをログに記録し、**Markdown生成は独立して継続する**（1つのSinkの失敗が他のSinkをブロックしない、§3手順5） |
| Markdown書き込み失敗 | 同上（Google Sheets側は独立して継続する） |
| 両方のSinkが失敗 | `history_writer.py`が失敗自体を履歴インデックスに記録し（「本日はレポート生成に失敗」というエントリ）、次回実行時に人間が気づけるようにする |

---

## 11. モジュール交換可能設計

`ReportSink`抽象クラスを設け、以下のインターフェースに統一する（設計仕様であり実装コードではない）。

- `ReportSink.render(presentation_model) -> RenderResult`：`PresentationModel`（表示専用モデル、§2・§3参照）を受け取り、各媒体固有の出力（Sheets行、Markdown文字列等）を生成する。
- `ReportSink.save(rendered_content, destination) -> SaveResult`：生成した内容を実際の保存先（Google Drive、Notion API、PDF出力、メール送信、Slack/LINE通知等）へ送る。

現行はVer1として`GoogleSheetsSink`・`MarkdownSink`の2つを実装する（§14確定事項3）。将来のSink追加優先順位は、PDF（共有・保管用途）→Notion→Slack→メール→LINEの順とする（§14確定事項3）。追加時は`config/report_sinks.yaml`のような設定ファイルで有効化するSinkを切り替えるだけで済み、`presentation_model.py`（表示専用モデルの生成ロジック）・`formatters/`（整形ロジック）には一切変更が不要となるように設計する。

```yaml
# config/report_sinks.yaml（設計イメージ、優先順位順にコメント記載）
enabled_sinks:
  - google_sheets   # 優先度1：運用・履歴管理（Ver1実装対象）
  - markdown        # 優先度2：人が読むレポート（Ver1実装対象）
  # - pdf           # 優先度3：共有・保管用途（将来）
  # - notion        # 優先度4（将来）
  # - slack         # 優先度5（将来）
  # - email         # 優先度6（将来）
  # - line          # 優先度7（将来）
```

すべてのSinkは同一の`PresentationModel`（decision JSONを非可逆的でない形で変換した表示専用の中間表現）を入力とするため、**Sinkの追加・削除・差し替えが、他のSinkやデータ変換ロジックに影響しない**という、Layer1のRepositoryパターン・Layer5の`AIJudge`抽象化と同じ設計原則をLayer6にも適用する。

---

## 12. テスト方針

| 対象 | テスト内容 |
|---|---|
| `presentation_model.py` | Layer5出力サンプルを変換した際、全フィールドの値が変換前後で完全に一致すること（数値の丸め等、意図的な表示整形以外は値が変わらないことを確認） |
| `GoogleSheetsSink` | 各シート（本日の提案／除外・不採用ログ／ルール適用ログ／実行サマリー）の列が§6の仕様通りに生成されること |
| `MarkdownSink` | §7-1のテンプレート構成通りに出力されること、`proposals`が0件の場合に「本日は提案なし」と表示されること |
| `decision_log_formatter.py` | 全件が省略なく表示されること、整列（§8）が値を変更せず順序のみ変えていることを確認 |
| `rule_enforcement_formatter.py` | `applied: false`のエントリも省略されないこと |
| `error_report_builder.py` | JSON欠落・`blocked`ゲート・トップレベルキー欠落のそれぞれのケースで、期待通りのエラーレポートが生成されること |
| Sink独立性テスト | 一方のSink（例：Google Sheets）の書き込みを意図的に失敗させ、もう一方（Markdown）が正常に生成されることを確認 |
| 整合性テスト（Layer5→Layer6） | Layer5の出力サンプル一式を通しでLayer6に流し、Google Sheets・Markdown双方の成果物に、`proposals`・`decision_log`・`rule_enforcement_log`の全内容が過不足なく反映されていることをend-to-endで確認 |
| 値不変性の回帰テスト | ランダムに生成した複数のLayer5出力サンプルに対し、Layer6の出力に含まれる数値・文字列がすべて入力と一致すること（スコア・株数・価格等の「書き換え禁止」原則の自動検証） |

---

## 13. Layer1〜Layer5との整合性

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | Layer5詳細設計書§9のdecision JSONスキーマを、Layer6が変更・拡張していないか | 変更なし。Layer6はトップレベル4キーを参照するのみで、内部フィールドの意味・値を一切変えない（§4-2・§5-1） |
| 2 | Layer5の`decision_writer.py`が既に行う「decision JSONのGoogle Drive保存」と、Layer6の保存処理が重複していないか | 重複なし。Layer6は生JSONの保存は行わず、整形後の成果物（Sheets／Markdown）のみを保存する（§0） |
| 3 | Layer4詳細設計書との命名規則・ディレクトリ構成の整合 | 整合。`reports/`（Markdownレポート＋`report_index_YYYYMM.json`）を新設する際も、Layer4の`history/`（パイプライン実行履歴）・`contracts/`（JSON Schema）、Layer5の`decisions/`（AI判断の生JSON置き場）とは責務を分離した別フォルダとして設計した（§6-6） |
| 4 | Layer2〜Layer5で確立した「スコア・ランキングはPythonが確定し、LLMは説明のみ」という原則が、Layer6でも維持されているか | 維持されている。Layer6はLLMを一切使わない決定的処理であり、表示順序の整列以外、値の変更を一切行わない設計にした（§5-1） |
| 5 | Layer1〜Layer5の責務分離（データ取得／分析・スコアリング／ニュース構造化／永続化／AI判断）にLayer6が抵触していないか | 抵触していない。Layer6は「表示・保存」のみを行い、判断・計算のいずれも行わない |

---

## 14. 確定事項（旧・未決事項への回答を反映）

1. **Layer6の実行モデル**：Ver1ではLayer5と同一Claude Coworkセッション内で継続実行する構成を採用することで確定（§0）。Layer6はAI判断を伴わない決定的処理であるため、将来的にはGitHub Actions等の独立ジョブへ分離可能な構造（§4-1の「decision JSONオブジェクトを受け取るだけ」という契約）を維持するが、Ver1では実装・運用の簡素化を優先し、独立実行への分離自体はVer2以降の改善項目とする。
2. **市場環境データ制約**：Ver1ではLayer5の出力契約を変更せず、Layer6はLayer5から受け取った情報のみを表示することで確定（§5-2）。市場環境の物語的説明は出力せず、「現在のLayer5出力には市場全体情報が含まれないため省略」と明記する（§7-1）。必要になった時点でLayer5に`market_context`フィールドを追加する方向を将来検討する。
3. **Sinkの優先順位**：①Google Sheets（運用・履歴管理）②Markdown（人が読むレポート）③PDF（共有・保管用途）④Notion⑤Slack⑥メール⑦LINE、の順で確定（§11）。Ver1ではGoogle SheetsとMarkdownのみを実装対象とする。
4. **Google Sheetsの列構成**：Ver1では1ファイル・複数シート構成を採用し、「本日の提案」シート自体は列を分割せず1シート構成を維持することで確定（§6）。27列程度であれば運用上問題はなく、データの検索・フィルタ・CSV出力との親和性を優先する。将来「本日の提案」シートの列数が大幅に増加した場合のみ、基本情報とスコア詳細への分割を検討する。

---

## 15. 自己レビュー（Layer1〜5との責務重複／入出力契約／将来Layer7へ渡す情報）

### 15-1. Layer1〜Layer5との責務重複の確認

重複は見つからなかった。Layer6は「表示・保存」のみに徹しており、Layer1（データ取得）・Layer2（分析・スコアリング）・Layer3（ニュース構造化）・Layer4（永続化）・Layer5（AI判断）のいずれの処理も行っていない。§0で明記した通り、Layer5の`decision_writer.py`が既に行う生JSON保存とLayer6の保存処理も、対象物（生JSON vs. 整形済み成果物）が異なるため重複しない。

### 15-2. 入出力契約の確認

Layer6の入力はLayer5のdecision JSON（§9スキーマ）のみであり、これはご指示通り厳守した。ただし自己レビューの過程で、以下の**発見事項**があった。

**発見事項：「市場環境」セクションに必要な情報がLayer5出力に含まれていない**（§5-2で詳述）。当初の章立てでは「市場環境」をMarkdownレポートの主要セクションの1つとして要求されていたが、Layer5の確定済み出力JSON（§9）を精査した結果、Layer2が本来持っていた`regime.regime_reason`や`macro.axis_score_reason`のような物語的なテキスト情報は、Layer5からLayer6へは伝播しないことが判明した。

**自己修正の方針**：Layer5詳細設計書は確定済みであり、本書の指示でも「Layer1〜5の入出力契約を絶対に崩さない」と明記されているため、**Layer5の出力スキーマを本書側から変更することはしない**。代わりに、Layer6の「市場環境」セクションは「現在のLayer5出力には市場全体情報が含まれないため省略」と正直に明記する設計に修正した（§5-2・§7-1に反映済み。当初検討した`score_summary.macro`等の平均値表示は、提案候補個別の評価スコアを市場環境であるかのように偽装することになり、かえって誤解を招くため採用しなかった）。これにより、存在しないデータを推測で埋めたり、Layer6が独自にLayer2の`market_snapshot`を直接読みに行ったりする（＝入力契約違反）ことを避けている。この制約の解消（Layer5への`market_context`フィールド追加）は、§14確定事項2の通り、必要になった時点での将来検討事項として位置付けた。

### 15-3. 将来Layer7（提案トラッキング層）へ渡す情報の確認

Ver2で設計したLayer7（提案トラッキング層）は、各提案の「銘柄・エントリー価格・損切/利確ライン・想定保有期間」を記録し、後日の実勢価格と突合する機能を持つ。本書§6-3の「本日の提案」シート列構成には、`証券コード`・`購入価格目安`・`損切価格`・`利確価格`・`想定保有期間`・`run_id`・`日付`が全て含まれており、**Layer7が必要とするデータは本Layer6のGoogle Sheets出力から過不足なく取得可能**であることを確認した。したがって、Layer7の詳細設計時にLayer6側の追加修正は不要と見込まれる。

**結論**：自己レビューの結果、§5-2の「市場環境」データ制約という重要な発見があったため、その旨を設計書本文（§5-2・§7-1）に反映し、確定事項（§14-2）として明記する形で自己修正済みである。それ以外の入出力契約・責務分離・Layer7との接続については問題が見つからなかった。

**Ver1.1修正内容（今回のご指摘4点＋未決事項4点の確定）**：①`report_index_YYYYMM.json`の保存場所を`decisions/`から`reports/`へ変更（§6-6）、②Layer6の入力契約を「decision JSONオブジェクトを受け取るのみ」に簡素化し、Google Drive上の保存パスへの言及を撤去（§0・§4）、③`ReportDataModel`を`PresentationModel`へ改称し「表示専用」であることを名称からも明確化（§2・§3・§11・§12）、④「市場環境」セクションをスコア集計値の疑似サマリーから「情報が無いことを正直に明記する」方式へ変更（§5-2・§7-1）。加えて§14の4点の未決事項をすべて確定事項として反映した。

**Layer6詳細設計書 Ver1.1確定**
