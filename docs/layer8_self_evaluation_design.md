# 自己評価層（Layer8）詳細設計書

作成日: 2026-07-18（Ver1.4：実装者レビューへの回答により、layer7_completed_YYYYMMDD.jsonの同日再実行時の参照ルール・多重起動に関する前提を追加。Ver1.3：全体設計書レビューへの回答により、Layer7完了フラグ（layer7_completed_YYYYMMDD.json）の確認ステップを追加。Ver1.2：evaluation_index.jsonの更新タイミング（トランザクション原則）を追加。Ver1.1：増分判定方法・シート検索方法・feedback生成条件・Profit Factorのゼロ除算・confidence基準を確定、Layer9関連を削除）
前提: Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Layer3詳細設計書（確定版・Ver1.3）／Layer4詳細設計書（確定版・Ver1.1）／Layer5詳細設計書（確定版・Ver1.3）／Layer6詳細設計書（確定版・Ver1.1）／Layer7詳細設計書（確定版・Ver1.2）と整合。**Layer1〜7はすべて確定済みであり、本書はそれらの責務・入出力契約・JSONスキーマ・フォルダ構成を一切変更しない。Layer8のみを新規設計対象とする。**

---

## 1. Layer8の位置付け

```
Layer1  データ取得
Layer2  分析・スコアリング
Layer3  ニュース構造化
Layer4  永続化
Layer5  AI総合判断（decision JSON生成）
Layer6  レポート生成（Google Sheets・Markdown）
Layer7  提案トラッキング（保有中提案の追跡・実績記録）
Layer8  自己評価（今回設計、決定的Python処理）
```

（Layer9「運用成績ダッシュボード」は今回のスコープ外とする。Layer8はLayer9を前提とした設計・出力を行わない。）

**Layer8はAIによる新たな投資判断を行う層ではない。** 過去の提案結果（Layer7が記録した実績）を分析し、AI改善のための評価データ・フィードバックを生成する、**決定的Python処理のみで構成される層**である。Layer5・Layer6・Layer7と同様、LLMは一切呼び出さない。

**実行モデル**：Layer8は「過去の蓄積結果を分析する」性質上、Layer1〜4のような日次バッチではなく、**Layer7完了後に続けて実行される独立したスケジュールジョブ**（GitHub Actions等）として設計する。日次実行では「その日新たにクローズしたポジション」を差分的に取り込み評価する増分モードを基本とし、加えて「過去全期間を再計算する」フルリカルクモード（統計ロジック自体を変更した際の再集計等に使用）も提供する。

---

## 2. 責務・非責務

**責務**：
- Layer7が生成した`closed_positions_YYYYMM.json`の読込
- Layer6のGoogle Sheets「本日の提案」シートに含まれる`score_summary`・`investment_reason`等との突き合わせ（§5で詳述。Layer5の生JSONは直接参照しない）
- 提案成功／失敗要因の分析
- 評価データの生成
- AI改善用フィードバックJSON（`feedback_YYYYMM.json`）の生成

**非責務**：
- AI判断（新たな投資推奨は一切行わない）
- 銘柄選定・スクリーニング（Layer2／Layer5の責務）
- スコアの再計算（Layer2が確定したスコアを分析対象として参照するのみで、値を書き換えない）
- ランキング変更（Layer2／Layer5の責務）
- **重みの自動調整**：Ver2で確定した方針（「重みの自動調整は実装しない。自己評価ログのみ保存し、重み変更は人間がレビューして設定ファイルを更新する」）をそのまま継承する。Layer8はあくまで「調整の提案」を人間向けに生成するのみで、`config/scoring_weights.yaml`等への自動反映は一切行わない。
- Layer5〜7の成果物（decision JSON、Google Sheets、Markdown、`active_positions.json`／`closed_positions_YYYYMM.json`／`manual_close_requests.json`）の書き換え：Layer8はこれらすべてを**読み取り専用**で参照する

---

## 3. モジュール構成

```
src/self_evaluation/
├── closed_position_loader.py     # Layer7のclosed_positions_YYYYMM.jsonの読込
├── evaluation_index.py           # evaluation_index.json（評価済みtracking_idの横断インデックス）の読み書き・増分判定（§4-1）
├── score_context_loader.py       # Layer6 Google Sheets「本日の提案」からscore_summary/investment_reason等を取得（§5）
├── reason_code_extractor.py      # investment_reasonからreason_codeパターンを抽出（ベストエフォート、§7-4）
├── outcome_analyzer.py           # 勝率・平均利益率/損失率・Profit Factor等の算出（§7-1）
├── segment_analyzer.py           # reason_code別／score帯別／資産クラス別／保有期間別の成績集計（§7-2〜7-5）
├── feedback_builder.py           # AI改善用feedback_YYYYMM.jsonの生成（§8。新規評価0件の場合は生成しない）
├── evaluation_store.py           # 評価データの読み書き（§6）
└── main.py                        # Layer8パイプラインのエントリポイント
```

---

## 4. 実行フロー

1. Layer8が独自スケジュールで起動する（Layer7完了後を想定。増分モードが基本）。
2. **（新設・Ver1.3）`tracking/layer7_completed_YYYYMMDD.json`の存在確認・`completed:true`確認**（§4-3参照）。フラグが規定時間内に存在しない、または`completed:false`の場合、以降のステップ（3以降）は一切実行せず、実行ログにその旨を記録して終了する（次回スケジュールで再試行）。
3. `closed_position_loader.py`が、当該期間（および必要に応じ複数期間）の`closed_positions_YYYYMM.json`を読み込む。
4. `evaluation_index.py`が`evaluation/evaluation_index.json`（§4-1）を読み込み、既に評価済みの`tracking_id`集合と突き合わせて、**未評価のクローズ済みポジションのみ**を特定する（月をまたいだ横断判定。§4-1で仕組みを確定）。
5. 未評価ポジションが0件の場合、ステップ6以降（スコア取得・分析・feedback生成）はすべてスキップし、実行ログにその旨を記録して終了する（§4-2、feedback生成条件の修正）。
6. `score_context_loader.py`が、未評価ポジションそれぞれについて`run_id`から対象シート名を直接導出し（§5-2の修正内容）、該当する1シートのみを読み込んで`score_summary`・`investment_reason`・`risk_factors`・`資産クラス`を取得する。
7. `reason_code_extractor.py`が`investment_reason`文字列から、reason_code命名規則（`TECH_`／`FUND_`／`SUPD_`／`MACRO_`／`NEWS_`／`REGIME_`で始まる大文字スネークケース文字列）に一致する部分文字列を正規表現で抽出する（ベストエフォート。§7-4で限界を明記）。
8. `outcome_analyzer.py`が各ポジションの勝敗判定・損益率・金額損益（Profit Factorのゼロ除算処理含む、§7-1）を算出する。
9. `segment_analyzer.py`が、reason_code別・score帯別・資産クラス別・保有期間別に成績を集計する（§7-2〜7-6、confidence基準は§7-1で確定）。
10. `evaluation_store.py`が個別ポジション評価・集計結果を`evaluation/`フォルダへ保存し、`evaluation_index.json`に今回処理した`tracking_id`を追加する（§6）。
11. `feedback_builder.py`が`feedback_YYYYMM.json`を生成する（§8。ステップ5で0件と判定された場合は本ステップ自体を実行しない）。
12. 完了。

### 4-1. 増分モードの判定方法（修正・確定）

`position_evaluations_YYYYMM.json`は月次分割されるため、「過去に評価済みかどうか」を月をまたいで判定する必要がある。**`evaluation/evaluation_index.json`という、全期間を横断する軽量インデックスを新設し、これを唯一の判定根拠とする**（各月の`position_evaluations_YYYYMM.json`を毎回横断検索することはしない）。

```json
{
  "evaluated_tracking_ids": [
    "TRK-20260718-0630-NVDA",
    "TRK-20260701-0630-7203"
  ]
}
```

`closed_position_loader.py`は、Layer7の`closed_positions_YYYYMM.json`から得た`tracking_id`のうち、この`evaluated_tracking_ids`に**含まれていないもの**を「未評価」として特定する。評価完了後、`evaluation_store.py`が処理済みの`tracking_id`をこのインデックスへ追記する（Layer4の`history/index_YYYYMM.json`等と同様、軽量インデックスによる高速な差分判定というパターンを踏襲する）。

### 4-2. feedback生成条件（修正・確定）

未評価のクローズ済みポジションが**0件**の実行では、`feedback_YYYYMM.json`の生成・更新を行わない（既存のfeedbackファイルもそのまま保持し、空の内容で上書きしない）。これにより、動きの無い日に`sample_size=0`のfeedbackファイルが量産されることを防ぐ。新規評価が1件以上ある場合のみ、該当月の`feedback_YYYYMM.json`を再生成する。

### 4-3. `layer7_completed_YYYYMMDD.json`の確認（新設・Ver1.3、全体設計書レビューへの回答）

全体設計書（`docs/00_SystemArchitecture.md`）のレビューで、「Layer4→Layer5間は完了フラグファイル方式でタイミング調整を行っているが、Layer7→Layer8間には同等の機構が無い」という改善提案が挙げられたことを受け、Layer7詳細設計書Ver1.3で新設された`tracking/layer7_completed_YYYYMMDD.json`（Layer7詳細設計書§6-5）を、Layer8が起動直後に確認する設計に変更する。

```json
{
  "completed": true,
  "completed_at": "2026-07-18T21:10:00Z",
  "run_date": "2026-07-18"
}
```

判定ルール：

| 状況 | Layer8の動作 |
|---|---|
| フラグファイルが規定時間内に存在しない | 当該実行の評価処理（§4手順3以降）を一切行わず、実行ログに`reason_code: LAYER7_NOT_COMPLETED`を記録して終了する（次回スケジュールで再試行） |
| フラグファイルが存在するが`completed:false` | 同上（`failure_reason_code`があれば併せて記録する） |
| フラグファイルが存在し`completed:true` | 通常通り§4手順3以降を実行する |

この確認は、Layer5がLayer4の完了フラグを確認する設計（Layer5詳細設計書§3-1・§5）と同じ思想であり、固定時刻オフセットに頼らず「Layer7が本当に完了したか」を機械的に確認することで、Layer7未完了の状態でLayer8が不完全な`closed_positions_YYYYMM.json`を読みに行くリスクを構造的に防止する。

**同日再実行時の参照ルール（新設・確定、実装者レビューへの回答）**：`layer7_completed_YYYYMMDD.json`はファイル名に時刻要素を持たないため、同日にLayer7が複数回実行された場合、Google Drive上に同名ファイルが複数存在し得る（Layer7詳細設計書§6-5）。この場合、Layer8は**`createdTime`が最も新しいものを正として参照する**（Layer4の完了フラグ、Layer6の「最新判定表示」と同一の考え方。Layer6詳細設計書§6-6参照）。

---

## 5. Layer7との入出力契約

### 5-1. 主入力：Layer7の成果物

Layer8の主たる入力は、Layer7が生成する`tracking/closed_positions_YYYYMM.json`（Layer7詳細設計書§6-3・§13で確定済み）である。Layer8が利用するフィールドは、`tracking_id`／`run_id`／`ticker`／`entry_price`／`exit_price`／`holding_days`／`max_unrealized_gain_pct`／`max_unrealized_loss_pct`／`final_return_pct`／`exit_reason`／`recommended_shares`。

### 5-2. 副入力：Layer6のGoogle Sheets（必要性の説明・重要）

**Layer7の`closed_positions_YYYYMM.json`自体には、スコア情報（`score_summary`）や投資理由（`investment_reason`）が一切含まれていない**（Layer7詳細設計書§6-3を参照。Layer7は価格・損益の追跡に特化しており、スコア情報を保持しない設計になっている）。したがって、ご指示にある「Layer5のreason_code・score_summary等と突き合わせる」を実現するには、Layer7の出力だけでは不十分であり、**Layer6が保存したGoogle Sheets「本日の提案」シート（Layer6詳細設計書§6-3で確定済み）を、`run_id`＋`ticker`をキーに追加で参照する**必要がある。

- Layer8はLayer6のGoogle Sheetsから、`score_summary`相当の列（テクニカルスコア／ファンダメンタルスコア／需給スコア／マクロスコア／ニューススコア／ニューススコア不確実性／レジーム適合スコア／総合スコア）、`投資理由`（`investment_reason`）、`リスク要因`（`risk_factors`）、`資産クラス`を取得する。
- **検索方法（修正・確定、実装効率上重要）**：Google Drive上には`提案ログ_YYYYMMDD`が日次で大量に蓄積されるため、毎回全シートを検索する設計にはしない。**`run_id`（例：`20260718-0630`）の先頭8桁（`YYYYMMDD`）から、対象ファイル名`提案ログ_YYYYMMDD`を一意に導出し、そのファイルのみを名前指定で取得する**。取得したファイル内で該当`ticker`の行を1回だけ検索する（ファイル横断検索は発生しない）。これにより検索コストは常に「1ファイル分」に固定され、蓄積されたファイル数に比例して遅くならない。
- **Layer8はLayer5の生decision JSONを直接参照しない**（Layer7が確立した「Layer5には直接アクセスせずLayer6経由で参照する」という設計原則を、Layer8でも踏襲する）。
- Layer8はLayer6のMarkdownレポートを解析対象にしない（Layer7と同様、人間閲覧用ファイルは非対象とする）。
- Layer8は`取引記録_*.csv`、Layer1〜4の出力（`market_snapshot`等）には一切アクセスしない。

### 5-3. 参照の失敗時

該当する`run_id`＋`ticker`の組み合わせがLayer6のGoogle Sheetsに見つからない場合（例：シートが手動で削除された等）、そのポジションは損益等の基本統計（勝敗・損益率）には含めるが、スコア関連の分析（reason_code別・score帯別集計）からは除外する（§9）。

---

## 6. 保存仕様

Ver2で計画されていた`evaluation/`フォルダを採用し、Layer4・Layer6・Layer7で確立した月次分割方針をそのまま踏襲する。

```
AI投資アシスタント/
└── evaluation/                              【新設・Layer8管理】
    ├── evaluation_index.json                  # 評価済みtracking_idの横断インデックス（§4-1）
    ├── position_evaluations_YYYYMM.json      # 個別ポジションの評価詳細
    ├── segment_stats_YYYYMM.json              # reason_code別/score帯別/資産クラス別/保有期間別集計
    └── feedback_YYYYMM.json                   # AI改善用フィードバック（人間レビュー用。新規評価が無い月は生成しない）
```

**保存順序とトランザクション原則（重要・追加）**：`position_evaluations_YYYYMM.json`・`segment_stats_YYYYMM.json`・`feedback_YYYYMM.json`・`evaluation_index.json`は、**1つのトランザクションとして扱い、すべて保存できて初めて完了とみなす**。特に`evaluation_index.json`の更新は、他の3ファイルの保存が全て成功した後の**最終ステップ**として実行する。

- 途中で失敗した場合（例：`position_evaluations_YYYYMM.json`は保存できたが、その後の処理で異常終了した場合）、**`evaluation_index.json`は更新しない**。これにより、次回実行時は当該`tracking_id`が「未評価」のままとなり、再評価が行われる（`position_evaluations_YYYYMM.json`への重複書き込みが起こり得るため、`evaluation_store.py`は書き込み時に同一`tracking_id`の既存エントリを検出したら上書きする形にし、単純な追記による重複レコード化を避ける）。
- 逆に、`evaluation_index.json`だけが誤って更新され、実体データ（`position_evaluations_YYYYMM.json`等）が保存されていない、という状態は起こらない（`evaluation_index.json`の更新を必ず最後にすることで構造的に防止する）。
- この順序により、「二重評価」（実害は軽微：再評価されるだけ）は起こり得ても、「未評価なのに評価済み扱いになり永久に評価されない」という、より深刻な事故は起こらない設計とする。

**同時実行に関する前提（新設・確定、実装者レビューへの回答）**：上記のトランザクション原則は、Layer8の**単一の実行プロセスが処理途中で異常終了するケース**（クラッシュ耐性）を対象としたものであり、**Layer8のジョブそのものが重複して同時に起動するケース**（例：手動再実行とスケジュール実行の重複）までは対象としない。`evaluation_index.json`・`position_evaluations_YYYYMM.json`等はいずれも読み込み→更新→書き戻し方式（read-modify-write）であるため、同一実行単位の重複起動が発生しないことを前提とする。重複起動の防止自体は本層の実装詳細ではなく、GitHub Actions側の排他制御（`concurrency`設定等）による運用面の担保とし、全体設計書§11-6を参照する。

### 6-1. `position_evaluations_YYYYMM.json`

```json
{
  "evaluations": [
    {
      "tracking_id": "TRK-20260718-0630-NVDA",
      "run_id": "20260718-0630",
      "ticker": "NVDA",
      "entry_price": 333.74,
      "exit_price": 383.80,
      "recommended_shares": 4,
      "holding_days": 18,
      "exit_reason": "take_profit",
      "final_return_pct": 15.0,
      "pnl_amount": 200.24,
      "outcome": "win",
      "max_unrealized_gain_pct": 16.2,
      "max_unrealized_loss_pct": -1.1,
      "score_summary": { "technical": 84, "fundamental": 71, "supply_demand": 78, "macro": 65, "news_score": 63, "news_uncertainty": 35, "regime_fit": 90, "composite": 79 },
      "extracted_reason_codes": ["TECH_MA_PERFECT_ORDER_UP", "FUND_ROE_EXCELLENT"],
      "reason_code_extraction_status": "success",
      "asset_class": "us_equity",
      "score_context_available": true
    }
  ]
}
```

---

## 7. 評価ロジック

### 7-1. 勝敗判定・基本統計

- **勝敗判定**：`final_return_pct > 0`を`win`、`final_return_pct <= 0`を`loss`とする（`exit_reason`ではなく実際の損益率の符号で判定する。`holding_period_expired`でもプラスであれば`win`として扱う）。
- **金額損益（`pnl_amount`）**：`(exit_price - entry_price) × recommended_shares`
- **勝率**：`win`件数 ÷ 全クローズ件数
- **平均利益率**：`win`となったポジションの`final_return_pct`の平均
- **平均損失率**：`loss`となったポジションの`final_return_pct`の平均
- **Profit Factor（ゼロ除算の扱いを確定）**：`total_gain = Σ(pnl_amountがプラスのポジションの合計)`、`total_loss = |Σ(pnl_amountがマイナスのポジションの合計)|`として、以下のルールで算出する。

  | 条件 | Profit Factorの値 | 備考 |
  |---|---|---|
  | `total_loss > 0`（通常ケース） | `total_gain ÷ total_loss` | 通常の算出式 |
  | `total_gain > 0` かつ `total_loss == 0`（全勝） | `null` | `"profit_factor_note": "全勝のため算出不能（損失0）"`を併記する。`Infinity`はJSONの標準的な値ではないため採用しない |
  | `total_gain == 0` かつ `total_loss > 0`（全敗） | `0.0` | 利益が無いため0とする |
  | `total_gain == 0` かつ `total_loss == 0`（クローズ件数0） | `null` | `"profit_factor_note": "クローズ済みポジションが無いため算出不能"`を併記する |

- **利確率**：`exit_reason == "take_profit"`の件数 ÷ 全クローズ件数
- **損切率**：`exit_reason == "stop_loss"`の件数 ÷ 全クローズ件数
- **最大含み益／最大含み損（集計）**：全ポジションの`max_unrealized_gain_pct`／`max_unrealized_loss_pct`の平均値・最大値・最小値を集計する（Layer7が個別ポジション単位で既に算出済みの値をそのまま集約するのみで、Layer8が再計算するものではない）

### 7-1-2. `confidence`（信頼度ラベル）の判定基準（修正・確定）

セグメント集計（reason_code別・score帯別等）に付与する`confidence`ラベルは、サンプル数（該当セグメントのクローズ件数）に応じて以下の基準で機械的に決定する。設定値は`config/feedback_thresholds.yaml`として切り出し、将来調整可能にする（§10）。

```yaml
# config/feedback_thresholds.yaml
confidence_thresholds:
  low_sample: { max_count: 9 }        # 0〜9件
  medium_sample: { min_count: 10, max_count: 29 }   # 10〜29件
  normal: { min_count: 30 }            # 30件以上
```

| サンプル数 | `confidence`値 |
|---|---|
| 0〜9件 | `low_sample` |
| 10〜29件 | `medium_sample` |
| 30件以上 | `normal` |

### 7-2. reason_code別成績

`extracted_reason_codes`に含まれる各コードについて、そのコードが付与されたポジション群の勝率・平均損益率を集計する（1ポジションが複数コードを持つ場合は、該当する全コードの集計対象に含める、いわゆる多重集計）。

### 7-3. score帯別成績

各評価軸（`technical`／`fundamental`／`supply_demand`／`macro`／`news_score`／`regime_fit`／`composite`）について、スコアを固定バケット（`0-59`／`60-69`／`70-79`／`80-89`／`90-100`）に分類し、バケットごとの勝率・平均損益率を集計する。

### 7-4. reason_code抽出の限界（重要・自己レビュー §14で詳述）

`investment_reason`は元来Layer5が生成する**自然文**であり、reason_codeの言及は必須フォーマットではない（Layer5詳細設計書§6のプロンプト設計では、reason_codeを根拠として言及することを促してはいるが、厳密な構造化出力ではない）。したがって、正規表現による抽出は**ベストエフォートであり、100%の網羅性・正確性を保証しない**。抽出できなかった場合は`extracted_reason_codes: []`、`reason_code_extraction_status: "no_match"`として記録し、無理に推測しない。この限界を踏まえ、reason_code別成績は「参考情報」として扱い、score帯別成績（§7-3、数値ベースで確実に算出可能）をより信頼性の高い分析軸として優先する。

### 7-5. 資産クラス別成績（「セクター別成績」に relate する制約・重要）

ご要望の「セクター別成績」について、**Layer5の`proposals`・Layer6のGoogle Sheetsのいずれにも、業種・セクター（半導体・自動車等）や`style_tags`（グロース／バリュー等）に相当する列・フィールドが含まれていない**ことを確認した（Layer2の`candidates[].style_tags`は、Layer5・Layer6の確定済み出力には引き継がれていない）。そのため、Layer8が実際に利用できる最も細かいカテゴリ変数は**`資産クラス`（`japan_equity`／`us_equity`／`etf`／`bond`／`gold`／`other`）のみ**である。

**確定方針**：Ver1では「セクター別成績」を「資産クラス別成績」に読み替えて実装し、業種・スタイルレベルの粒度での分析は行わない（存在しないデータを無理に推測しない。Layer6詳細設計書§5-2で確立した「情報が無い場合は正直に明記する」という設計原則をLayer8でも踏襲する）。将来、業種・スタイル分析が必要になった場合は、Layer2の`style_tags`をLayer5・Layer6の出力スキーマへ追加で伝播させる拡張が必要になるが、これは**Layer5・Layer6詳細設計書の変更を伴うため今回のスコープ外**とし、§14の自己レビューおよび次回のLayer5/6改訂検討事項として明記する。

### 7-6. 保有期間別成績

Layer7の`holding_days`を用い、固定バケット（`〜7日`／`8〜14日`／`15〜30日`／`31日超`）に分類して勝率・平均損益率を集計する（Layer7の実測値をそのまま利用するため、抽出の限界やデータ欠落の問題は発生しない）。

---

## 8. AIフィードバック生成仕様

`feedback_YYYYMM.json`は、Ver2で確定した「重みの自動調整は行わず、人間レビュー用の提案書を生成する」という方針をそのまま実装したものである。

```json
{
  "period": "2026-07",
  "generated_at": "2026-08-01T06:00:00Z",
  "sample_size": {
    "total_closed_this_period": 4,
    "total_closed_all_time": 15,
    "min_recommended_sample_for_confidence": 30,
    "sufficient_for_reliable_analysis": false
  },
  "overall_stats": { "win_rate": 0.53, "avg_win_pct": 12.1, "avg_loss_pct": -8.5, "profit_factor": 1.8, "profit_factor_note": null, "take_profit_rate": 0.4, "stop_loss_rate": 0.13 },
  "reason_code_performance": [
    { "reason_code": "TECH_RSI_HEALTHY", "count": 8, "win_rate": 0.625, "avg_return_pct": 9.2, "confidence": "low_sample" }
  ],
  "score_band_performance": [
    { "axis": "composite", "band": "70-79", "count": 5, "win_rate": 0.6, "avg_return_pct": 7.1, "confidence": "low_sample" }
  ],
  "_confidence_scale_note": "confidenceは0〜9件=low_sample、10〜29件=medium_sample、30件以上=normal（§7-1-2）",
  "asset_class_performance": [
    { "asset_class": "us_equity", "count": 10, "win_rate": 0.5, "avg_return_pct": 5.3 }
  ],
  "holding_period_performance": [
    { "band": "15〜30日", "count": 6, "win_rate": 0.67, "avg_return_pct": 8.0 }
  ],
  "weight_adjustment_suggestions": [
    {
      "target_config": "config/scoring_weights.yaml#technical.RSI",
      "current_weight": 15,
      "observation": "TECH_RSI_HEALTHYが付与された提案の勝率(62.5%)が全体平均(53%)を上回っている",
      "suggested_direction": "increase",
      "confidence": "low（サンプル数8件、統計的有意性は未検証）",
      "requires_human_review": true
    }
  ],
  "review_status": "pending_human_review"
}
```

**設計原則**：
- `weight_adjustment_suggestions`は**あくまで「提案」であり、`config/scoring_weights.yaml`等への自動反映は一切行わない**（Ver2の確定方針を厳守）。
- サンプル数に応じた`confidence`ラベル（`low_sample`／`medium_sample`／`normal`、§7-1-2の基準）を必ず付与し、あたかも統計的に確実であるかのような誤解を与えないようにする。
- `review_status`は常に`"pending_human_review"`で始まり、人間がレビューした後の状態遷移（例：`"reviewed_no_action"`／`"reviewed_applied"`）は、Layer8の外側（人間の運用フロー、または将来のUI）で管理する。Layer8自身がこのステータスを`"applied"`に自動遷移させることはない。

---

## 9. エラー処理

| 事象 | 対応 |
|---|---|
| `closed_positions_YYYYMM.json`が見つからない／空 | 当該期間の評価をスキップし、次回実行時に再試行する |
| Layer6のGoogle Sheetsが見つからない（該当`run_id`＋`ticker`に対応するシートが無い） | `score_context_available: false`として記録し、基本統計（勝敗・損益率）には含めるが、reason_code別・score帯別の集計対象からは除外する（§5-3） |
| `investment_reason`からreason_codeが抽出できない | `extracted_reason_codes: []`、`reason_code_extraction_status: "no_match"`として記録し、無理に推測しない（§7-4） |
| セグメント（reason_code／score帯／資産クラス／保有期間）のサンプル数が少ない | 集計自体は表示するが、§7-1-2の基準（0〜9件=`low_sample`、10〜29件=`medium_sample`、30件以上=`normal`）に従い`confidence`を必ず付与する。数値を隠さず、信頼性の注記のみ行う |
| Profit Factorの分母が0（全勝または全敗、クローズ0件） | §7-1の表に従い`null`または`0.0`とし、`profit_factor_note`にその理由を明記する（`Infinity`は使用しない） |
| `evaluation_store`への書き込み失敗 | リトライ後、なお失敗する場合は`severity: critical`として記録し、既存データを不整合なまま上書きしない |
| 重複評価（同一`tracking_id`が既に評価済み） | エラーではなく正常系。スキップする |
| （新設・Ver1.3）`tracking/layer7_completed_YYYYMMDD.json`が規定時間内に存在しない、または`completed:false` | 当該実行の評価処理を一切行わず、`reason_code: LAYER7_NOT_COMPLETED`を記録して終了する（§4-3、次回スケジュールで再試行） |
| （新設・Ver1.4）同日に`layer7_completed_YYYYMMDD.json`が複数存在する（Layer7の再実行等） | `createdTime`最大のものを正として扱う（§4-3、エラーではなく正常系） |

---

## 10. 将来拡張性

- reason_codeの抽出（§7-4）は正規表現によるベストエフォートであるが、将来Layer5・Layer6の出力スキーマに構造化された`cited_reason_codes`フィールドが追加された場合、`reason_code_extractor.py`はまずその構造化フィールドの有無を確認し、存在すればそちらを優先して利用し、存在しない過去データについてのみ現行のテキスト抽出にフォールバックする設計に拡張できる。
- セクター／スタイル分析（§7-5）も同様に、将来Layer5・Layer6が`style_tags`を出力するようになった場合、`segment_analyzer.py`に新しい集計軸を追加するだけで対応でき、既存の資産クラス別集計ロジックへの影響はない。
- `feedback_builder.py`が生成する`weight_adjustment_suggestions`のロジック自体（どの程度の勝率差があれば提案するか等の閾値）は、`config/feedback_thresholds.yaml`内に`confidence_thresholds`（§7-1-2）と並ぶ形で追加設定できるようにし、将来調整可能にする。

---

## 11. テスト方針

| 対象 | テスト内容 |
|---|---|
| `evaluation_index.py` | 過去に評価済みの`tracking_id`が月をまたいでも正しく除外されること（月次ファイルを横断検索せず、インデックスのみで判定できていることを確認） |
| `closed_position_loader.py` | 未評価ポジションのみを正しく特定すること、重複評価が発生しないこと |
| `score_context_loader.py` | `run_id`から正しいシート名（`提案ログ_YYYYMMDD`）が導出されること、全シート検索が発生しないこと（呼び出し回数の検証）、該当シートが無い場合に`score_context_available: false`となること |
| `reason_code_extractor.py` | 既知のreason_code命名パターンを含む文章から正しく抽出できること、パターンを含まない文章で`no_match`となること（誤検出・過検出双方のテスト） |
| `outcome_analyzer.py` | 既知の損益データに対し、勝敗判定・Profit Factor等が期待通りの値になること（境界値：`final_return_pct == 0`、全勝(`total_loss=0`)・全敗(`total_gain=0`)・クローズ0件のケースを含む） |
| `segment_analyzer.py` | 各バケット境界値（例：score=59/60、69/70）で正しく分類されること、サンプル数の境界（9/10件、29/30件）で`confidence`が正しく切り替わること |
| `feedback_builder.py` | `weight_adjustment_suggestions`が生成されても`config`ファイルへの書き込みが一切発生しないこと（自動適用禁止の回帰テスト）。新規評価0件の場合に`feedback_YYYYMM.json`が生成・更新されないこと |
| 読み取り専用性の回帰テスト | Layer8実行前後でLayer6・Layer7の成果物ファイルの内容が変化していないことを確認 |
| 統合テスト（Layer7→Layer8） | Layer7のサンプル`closed_positions_YYYYMM.json`とLayer6のサンプルシートを用い、`position_evaluations_YYYYMM.json`・`feedback_YYYYMM.json`がend-to-endで正しく生成されることを確認 |

---

## 12. Layer1〜Layer7との整合性確認

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | Layer7の`closed_positions_YYYYMM.json`スキーマ（Layer7詳細設計書§6-3）をLayer8が変更していないか | 変更していない。読み取り専用で参照するのみ |
| 2 | Layer6のGoogle Sheetsをスコア情報取得のために追加参照する設計が、Layer6の責務・スキーマを変更していないか | 変更していない。Layer6が既に確定済みの列（Layer6詳細設計書§6-3）を読み取るのみで、新しい列の追加をLayer6へ要求しない |
| 3 | Layer5のdecision JSONを直接参照していないか | 参照していない。Layer7が確立した「Layer5には直接アクセスせずLayer6経由」という原則をLayer8でも踏襲した（§5-2） |
| 4 | Ver2で確定した「重みの自動調整は行わない」方針にLayer8が抵触していないか | 抵触していない。`feedback_builder.py`が生成するのは人間レビュー用の提案のみで、config自動反映は一切行わない（§8） |
| 5 | Layer1〜Layer7の責務分離にLayer8が抵触していないか | 抵触していない。Layer8は「過去実績の分析・評価データ生成」のみを行い、データ取得・分析・スコアリング・ニュース構造化・永続化・AI判断・レポート生成・トラッキングのいずれも行わない |

---

**（旧「13. Layer9へ渡す情報」章は、Layer9「運用成績ダッシュボード」が今回のスコープ外となったため削除した。Layer8は`position_evaluations_YYYYMM.json`・`segment_stats_YYYYMM.json`を`evaluation/`フォルダに保存するのみとし、Layer9向けの専用エクスポート形式は今回設計しない。将来Layer9を設計する際は、これら既存の保存済みファイルを入力として利用できるかを別途検討する。）**

---

## 13. 確定事項

1. Layer8はLayer7完了後に続けて実行される独立したスケジュールジョブとして設計し、増分モード（新規クローズ分のみ評価）とフルリカルクモード（全期間再集計）の両方を提供する。
2. 主入力はLayer7の`closed_positions_YYYYMM.json`、副入力としてLayer6のGoogle Sheets「本日の提案」シート（`score_summary`／`investment_reason`等）を`run_id`＋`ticker`で結合して利用する。Layer5のdecision JSON・Layer6のMarkdown・`取引記録_*.csv`・Layer1〜4の出力にはアクセスしない。
3. 保存先は`evaluation/evaluation_index.json`／`position_evaluations_YYYYMM.json`／`segment_stats_YYYYMM.json`／`feedback_YYYYMM.json`とし、月次分割方針を踏襲する。Layer9向けの専用エクスポートは今回設計しない。
4. 増分判定は`evaluation_index.json`（評価済み`tracking_id`の横断インデックス）を唯一の判定根拠とし、月次ファイルを毎回横断検索しない（§4-1）。
5. `score_context_loader.py`は`run_id`からシート名（`提案ログ_YYYYMMDD`）を直接導出し、該当1ファイルのみを読み込む（全シート検索は行わない、§5-2）。
6. 新規評価対象が0件の実行では`feedback_YYYYMM.json`を生成・更新しない（§4-2）。
7. 勝敗判定は`final_return_pct`の符号で行う（`exit_reason`ではない）。Profit Factorは金額損益ベースで算出し、分母0（全勝／クローズ0件）の場合は`null`、全敗の場合は`0.0`とする（§7-1）。
8. セグメントの`confidence`は、0〜9件=`low_sample`、10〜29件=`medium_sample`、30件以上=`normal`という基準で機械的に決定する（§7-1-2）。
9. 「セクター別成績」は、Layer5・Layer6の確定済み出力にセクター／スタイル情報が存在しないため、Ver1では「資産クラス別成績」として実装する。
10. reason_code別成績は、`investment_reason`からの正規表現ベストエフォート抽出に基づく参考情報として扱い、抽出の限界を明記する。
11. `feedback_YYYYMM.json`の重み調整提案は、常に人間レビュー待ちの提案として生成し、`config/scoring_weights.yaml`等への自動反映は一切行わない。
12. **（新設・Ver1.3）Layer7との実行タイミング調整として完了フラグファイル方式を採用する**：`tracking/layer7_completed_YYYYMMDD.json`の存在・`completed:true`を確認してから評価処理を開始する（§4手順2、§4-3）。Layer4→Layer5間で確立済みの完了フラグ方式と同じ思想である。
13. **（新設・Ver1.4）`layer7_completed_YYYYMMDD.json`が同日に複数存在する場合は`createdTime`最大のものを正とする**（§4-3）。
14. **（新設・Ver1.4）本層が管理する各JSONファイルの更新は、同一実行単位の重複起動が発生しないことを前提とする**（§6）。重複起動防止自体はGitHub Actions側の運用面の担保とし、全体設計書§11-6を参照する。

---

## 14. 自己レビュー

### 14-1. Layer1〜Layer7の責務を侵害していないか

侵害していない。Layer8は「過去実績の分析・評価データ生成」のみを行い、他レイヤーの処理を重複して行っていない。

### 14-2. Layer5〜7の成果物を書き換えていないか

書き換えていない。すべて読み取り専用で参照し、§11に読み取り専用性の回帰テストを設けた。

### 14-3. Layer5のdecision JSONを直接参照していないか

参照していない。§5-2で明示的に「Layer7が確立した『Layer5には直接アクセスせずLayer6経由』という原則をLayer8でも踏襲する」と定めた。

### 14-4. 発見事項：スコア情報がLayer7の出力に含まれていない

自己レビューの過程で、Layer7の`closed_positions_YYYYMM.json`（確定済み）には`score_summary`・`investment_reason`が一切含まれていないことが判明した。ご指示の「Layer5のreason_code・score_summary等と突き合わせる」を実現するには、Layer7の出力だけでは不十分であったため、**Layer6のGoogle Sheetsを副入力として追加する**設計に修正した（§5-2）。これはLayer6・Layer7いずれのスキーマも変更しない形での解決であり、責務分離を保ったまま対応できている。

### 14-5. 発見事項：reason_codeが構造化データとして存在しない

Layer5の`investment_reason`は自然文であり、reason_codeの構造化出力（例：`cited_reason_codes: [...]`のような専用フィールド）は現在の確定済みスキーマに存在しない。そのため、reason_code別成績は正規表現によるベストエフォート抽出に依拠せざるを得ず、100%の網羅性は保証できない（§7-4）。この限界を設計書に明記し、より信頼性の高いscore帯別成績を優先分析軸とする方針とした。

### 14-6. 発見事項：セクター／スタイル情報が存在しない

ご要望の「セクター別成績」についても、Layer5・Layer6の確定済み出力に業種・スタイル情報が存在しないことが判明した。Ver1では「資産クラス別成績」に読み替えて実装し、この制約を明記した（§7-5）。将来Layer2の`style_tags`をLayer5・Layer6の出力スキーマに伝播させる拡張を推奨するが、これは今回のスコープ外である。

### 14-7. 増分モードの判定方法は曖昧でないか（今回の修正点）

当初「`evaluation_store`にまだ評価記録が無いポジションを特定する」とだけ記述しており、月次分割された`position_evaluations_YYYYMM.json`を月をまたいでどう検索するかが未定義だった。`evaluation_index.json`という全期間横断の軽量インデックスを新設することで解消した（§4-1）。

### 14-8. 入出力契約が曖昧になっていないか

§5-2でLayer6を副入力とする理由・検索方法（`run_id`からのファイル名直接導出）を明記し、§7-4・§7-5でデータの限界（reason_code抽出のベストエフォート性、セクター情報の不在）を具体的に記述することで、当初曖昧になりかねなかった箇所を明確化した。

### 14-9. 将来APIを変更してもLayer8内部へ影響しない設計になっているか

なっている。Layer8は外部APIを直接呼び出さない（Layer7が既に取得した価格データとLayer6のスコアデータを読むのみ）ため、外部APIの変更による影響を直接受けない。将来Layer5・Layer6の出力スキーマが拡張された場合の対応方針も§10で明記した。

**結論**：自己レビューの過程で、当初案から4点の改善（スコア情報の副入力の必要性、reason_code抽出のベストエフォート性、セクター情報の不在、増分モード判定方法の具体化）を反映した。加えて今回のご指摘5点（増分判定・シート検索方法・feedback生成条件・Profit Factorのゼロ除算・confidence基準）をすべて本文へ反映し、Layer9関連の内容は削除した。さらにVer1.2にて、evaluation_index.jsonの更新タイミングに関するトランザクション原則（§6）を追加し、途中失敗時の「未評価なのに評価済み扱い」という重大な事故を構造的に防止する設計とした。Layer5・Layer6・Layer7の確定済み仕様は一切変更していない。

### 14-10. evaluation_index.jsonの更新タイミング(今回の修正点・Ver1.2)

当初案では`position_evaluations_YYYYMM.json`等のデータファイルと`evaluation_index.json`の保存順序・失敗時の扱いが未定義だった。ご指摘の通り、「データ保存成功→index更新失敗」なら軽微な二重評価で済むが、「index更新成功→データ保存失敗」だと「評価済みとして扱われるが実データが存在しない」という、事後的に検出困難な重大なデータ欠損事故になり得る。これを受け、§6に「保存順序とトランザクション原則」を追加し、`evaluation_index.json`の更新を必ず最後（4ファイル中の最終ステップ）に実行する設計とした。これにより起こり得る事故を「二重評価（軽微・再評価で自然回復）」のみに限定し、「評価済み扱いなのに永久に評価されない」という事故を構造的に排除した。

### 14-11. Layer7との実行タイミング調整（今回の修正点・Ver1.3）

全体設計書（`docs/00_SystemArchitecture.md`）のレビューにおいて、「Layer7→Layer8間には、Layer4→Layer5間の完了フラグ方式に相当する明示的なタイミング調整機構が無い」という改善提案が挙げられた。これを受け、Layer7詳細設計書Ver1.3で新設された`tracking/layer7_completed_YYYYMMDD.json`（Layer7詳細設計書§6-5）を、Layer8が起動直後に確認する設計に変更した（§4手順2、§4-3）。フラグ未到達・`completed:false`の場合は評価処理を一切行わず次回再試行する。これによりLayer7未完了の状態でLayer8が不完全な実績データを読みに行くリスクを構造的に排除した。

**Ver1.3修正内容（全体設計書レビューへの回答）**：Layer7との実行タイミング調整のため、`tracking/layer7_completed_YYYYMMDD.json`の確認ステップを新設した（§4手順2、§4-3、§9、§13確定事項12）。評価ロジック・保存仕様・入出力契約には一切変更を加えていない。

### 14-12. 実装者レビューへの回答（今回の修正点・Ver1.4）

実装者レビューで指摘された2点（①`layer7_completed_YYYYMMDD.json`の同日再実行時の参照ルール欠如、②多重起動に対する排他制御の前提欠如）に対応した。①はLayer7・Layer4と同じ「`createdTime`最大を正とする」ルールを追記（§4-3）、②は同一実行単位の重複起動が発生しない前提を明記し、防止自体はGitHub Actions側の運用面（全体設計書§11-6）に委ねる形で整理した（§6）。なお、同じレビューで指摘された「フルリカルクモードの詳細設計」については、今回は見送り、全体設計書側の改善提案（今後の課題）としてのみ記録し、本書の内容は変更していない。上記2点の追記は、Ver1.2で確立したトランザクション原則（単一プロセスのクラッシュ耐性）を補完するものであり、既存の評価ロジック・保存仕様・入出力契約には一切変更を加えていない。

**Ver1.4修正内容（実装者レビューへの回答）**：`layer7_completed_YYYYMMDD.json`の同日再実行時の参照ルール（§4-3）、同時実行に関する前提（§6）を新設した。フルリカルクモードの詳細設計は今回対応しない。

**Layer8詳細設計書 Ver1.4確定**
