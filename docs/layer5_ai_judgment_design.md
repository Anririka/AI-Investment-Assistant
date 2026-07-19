# AI判断層（Layer5）詳細設計書

作成日: 2026-07-18（Ver1.5：実装者レビューへの回答により、`recommended_shares`が0株になる場合の扱いを新設・確定。Ver1.4：全体設計書レビューへの回答により、decision JSONの保存先・命名規則を新設・確定。Ver1.3：Layer4 Ver1.1との整合のためsnapshot_pathを`snapshots/market_snapshot_YYYYMMDD.json`に統一）
前提: Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Layer3詳細設計書（確定版・Ver1.3）／Ver2設計書／スコアリング仕様書（確定版・Ver1.2）と整合。特にVer2確定事項②「LLM交換可能設計は選択肢A（Claude Cowork継続）を採用、ただし入出力インターフェースはモデル非依存で設計する」を前提とする。

---

## 0. 実行環境の前提（Layer1〜3との違い、重要）

Layer1〜3はGitHub Actions上で動く独立したPythonパイプラインとして設計した。**Layer5はこれと実行モデルが異なる**。

選択肢A採用により、Layer5は現在このやり取りを行っているような**Claude Coworkのスケジュールタスク（毎朝の定型プロンプト実行）として稼働し続ける**。つまり：

- Layer5の「コード」は、GitHub Actions上のPythonモジュール群ではなく、**①Claude Coworkに与えるプロンプトテンプレート**と、**②そのセッション内でClaudeがBash/Pythonツールを使って実行する決定的計算処理（推奨株数の算出等）**の2つで構成される。
- LLMによる推論（総合判断・投資理由・リスク説明・ニュースの解釈・ポートフォリオ提案）はセッション自体が担う。数値計算（推奨株数・損切/利確価格・リスクルールの機械的強制）は、そのセッションが自らBashツールでPythonスクリプトを実行することで行う（本書冒頭の運用ルールにあった「推奨株数は必ずコードで実行し暗算しない」という原則を、Cowork環境でもそのまま踏襲する）。
- 将来「選択肢B」（Layer5を外部Python基盤＋`AIJudge`抽象クラスへ移行）を採用する場合は、本書で定義する入出力JSONスキーマ（§4・§9）をそのまま契約として維持し、実行主体だけをClaude Coworkセッションから`ClaudeJudge`/`GPTJudge`等のAPI呼び出しクラスに置き換える（Ver2で示した移行パス）。**このため、本書のプロンプト設計・出力スキーマは意図的にモデル非依存で記述する。**

**重要な明文化（誤解防止）**：**Layer5はPythonアプリケーションではなく、AI Agent実行層である。** `scripts/*.py`はAgent（Claude Coworkセッション）が判断の過程で利用する補助ツール群であり、Layer5自身の実行主体ではない。実行主体はあくまでAIエージェント（Claude Coworkセッション）そのものであり、そのエージェントが自らの判断の一部（数値計算等）をPythonスクリプトの実行に委譲している、という構造である。したがって、全体構成を模式的に表すと以下のようになる。

```
Layer1〜4  Python Pipeline（GitHub Actions上で完結）
    ↓
Layer5     AI Agent実行層（Claude Coworkセッション。scripts/*.pyはAgentが呼ぶ補助ツール）
    ↓
Layer6     Report Generator（別途設計）
```

「結局Layer5もGitHub Actionsなのか」「ClaudeがPythonを実行するのか、PythonからClaudeを呼ぶのか」という疑問に対する答えは、**常に前者（Claude Coworkセッションが自らのBashツールでPythonスクリプトを呼ぶ）であり、後者（PythonプロセスがLLM APIを呼ぶ形）は選択肢B移行後にのみ発生する**、ということである。

---

## 1. Layer5の責務・非責務

**責務**：
- Layer2が生成した`market_snapshot_YYYYMMDD.json`（候補・スコア内訳・レジーム・マクロ・除外候補要約）の読み込み
- 現在の保有ポジション（Google Drive `取引記録_*.csv`最新スナップショット）の読み込みと、投資可能残余資金の把握
- データ品質ゲート判定（Layer2出力が欠損・重大エラーを含む場合、LLM推論を行わず「様子見」で確定させる）
- LLMによる総合判断：候補ごとの買い/売り/様子見の評価、投資理由・リスク説明の自然文生成、ニュースの`uncertainty`等を踏まえた定性的な解釈、ポートフォリオ全体の提案（集中投資回避等）
- 全候補（採用・不採用問わず）についての判断ログ生成（Ver2「AI判断ログの完全保存」要件）
- 各評価軸スコアに対する「なぜその点数か」の自然文説明生成
- **推奨株数・損切価格・利確価格の確定計算**は、LLMが暗算するのではなく、Bash/Pythonツールでスクリプトを実行して算出する（§7・§8）
- リスクルール（信頼度50未満は様子見、1日の新規提案は最大3件、1銘柄あたり投資上限33%、合計300万円上限）の最終的な機械的強制（§7）
- Layer6（レポート生成層、別途設計）・Layer4（永続化）へ渡す最終決定JSONの生成

**非責務**：
- 個別指標の計算（Layer2の責務。Layer5はLayer2が計算済みのスコア・reason_codeのみを使う）
- ニュース記事本文の解釈・構造化（Layer3の責務）
- 推奨株数・損切/利確価格の暗算（必ずコード実行、§7・§8）
- レポートの最終フォーマット・Sheets保存（Layer6の責務。Layer5は構造化された決定JSONを渡すのみ）

---

## 2. モジュール構成（選択肢Aの実態に合わせた構成）

```
layer5_ai_judgment/
├── prompts/
│   └── layer5_judgment_prompt_template.md   # Claude Coworkセッションへの指示本体（モデル非依存で記述）
├── scripts/                                  # Coworkセッションが自身のBashツールで実行するPythonヘルパー
│   ├── load_snapshot.py                       # market_snapshot_YYYYMMDD.jsonの読込・品質ゲート判定
│   ├── load_portfolio_state.py                # 取引記録_*.csvから保有ポジション・残余投資可能資金を算出
│   ├── position_sizer.py                      # 推奨株数・損切/利確価格の確定計算（§8）
│   ├── rule_enforcer.py                       # 信頼度ゲート・1日3件上限等のハードルール強制（§7）
│   └── decision_writer.py                     # 最終decision_log・提案ログのGoogle Drive書き込み
└── contracts/
    ├── layer5_input_schema.json                # Layer2 JSON＋portfolio_stateの入力契約（§4）
    └── layer5_output_schema.json               # Layer6への出力契約（決定JSON、§9）
```

**将来の選択肢B移行時の対応表**：

| 選択肢A（現行） | 選択肢B（将来） |
|---|---|
| `prompts/layer5_judgment_prompt_template.md`をClaude Coworkセッションに読ませ、セッション自体が推論する | 同じプロンプトテンプレートを`ai_judgment/claude_judge.py`（または`gpt_judge.py`等）がAPI呼び出しのメッセージとして組み立てる |
| `scripts/*.py`をCoworkセッションがBashツールで実行 | 同じ`scripts/*.py`をGitHub Actions上のPythonプロセスが呼び出す（コード自体は共通化・再利用可能） |
| 出力はCoworkセッションの応答として生成、`decision_writer.py`でDriveに保存 | `AIJudge.judge()`の戻り値として同じJSON Schemaで返る |

`scripts/`配下は最初からPythonの独立関数として実装するため、選択肢Bへの移行時もこの部分はそのまま再利用できる（Coworkが呼ぶかGitHub Actionsが呼ぶかの違いのみ）。

---

## 3. 実行フロー

1. Claude Coworkのスケジュールタスクが起動する（**完了フラグファイル方式を採用**。固定時刻オフセット方式は採用しない。§3-1参照）
2. `scripts/load_snapshot.py`をBashツールで実行し、`snapshots/layer4_completed_YYYYMMDD.json`の存在と`completed: true`を確認したうえで、当日の`market_snapshot_YYYYMMDD.json`をGoogle Driveから取得する（§3-1）
3. **データ品質ゲート**（§5）：完了フラグが規定時間までに存在しない場合、または`run_meta.data_quality`に`blocking_errors`該当のエラーが含まれる場合、この時点でLLM推論を行わず「様子見」で確定し、§9のフォーマットで理由を記録して終了する

### 3-1. Layer1〜4との実行タイミング調整（完了フラグファイル方式、確定）

固定時刻オフセット方式（例：Layer1〜4を6:00起動、Layer5を6:30起動と決め打ちする）は**採用しない**。GitHub ActionsはAPI障害・レート制限・一時的エラーによって完了時刻が変動しうるため、固定時刻ではLayer1〜4が未完了のまま不完全な`market_snapshot`をLayer5が読んでしまうリスクがある。投資判断において「最新データではなく途中状態を読む」ことは、単なる遅延よりも深刻なリスクであるため、時刻ではなく完了そのものを確認する方式を採用する。

Layer4（永続化層）は、パイプライン完了時に以下のファイルをGoogle Driveへ生成する（Layer4は本書のスコープ外だが、Layer5が依存するため契約として明記する）。

```
snapshots/
├── market_snapshot_YYYYMMDD.json
└── layer4_completed_YYYYMMDD.json
```

```json
{
  "completed": true,
  "completed_at": "2026-07-18T06:25:00Z",
  "layer_status": { "layer1": "success", "layer2": "success", "layer3": "success", "layer4": "success" },
  "snapshot_path": "snapshots/market_snapshot_20260718.json"
}
```

Layer5（Claude Coworkスケジュールタスク）は次の順序で処理する：①`layer4_completed_YYYYMMDD.json`の存在確認、②`completed: true`の確認、③`market_snapshot_YYYYMMDD.json`の読み込み、④Layer5実行。

**タイムアウト時の扱い**：規定時間（実装時に確定、例：スケジュールタスク起動から30分等）までに完了フラグが存在しない場合、LLM判断を一切実施せず、「本日はデータ準備未完了のため様子見」として`reason_code: LAYER_PIPELINE_NOT_COMPLETED`で確定・保存する。
4. `scripts/load_portfolio_state.py`をBashツールで実行し、`取引記録_*.csv`の最新スナップショットから現在の保有ポジション・銘柄別/セクター別集中度・残余投資可能資金を算出
5. LLM推論（Claude Coworkセッション自身の推論）：`layer5_judgment_prompt_template.md`の指示に従い、Layer2 JSON＋portfolio_stateを入力として、候補ごとの評価・ランキング・投資理由・リスク説明・信頼度・全候補判断ログを生成する（§6・§7）
6. `scripts/rule_enforcer.py`をBashツールで実行し、LLMの判断結果にハードルールを機械的に適用する（信頼度50未満は様子見へ強制変更、1日の新規提案が3件を超える場合は上位3件のみ採用、超過分は理由付きで不採用へ）（§7）
7. `scripts/position_sizer.py`をBashツールで実行し、最終的に採用された提案について推奨株数・損切価格・利確価格を確定計算する（§8）
8. `scripts/decision_writer.py`をBashツールで実行し、最終決定JSON・全候補の判断ログをGoogle Driveへ保存する
9. Layer6（レポート生成層）へ最終決定JSONを引き渡す

### 3-2. decision JSONの保存先・命名規則（新設・確定、全体設計書レビューへの回答）

`decisions/`フォルダ（Layer4詳細設計書§4・Layer6詳細設計書§0/§6-6で、これまでフォルダの存在のみが言及されていた）について、`scripts/decision_writer.py`が保存するdecision JSON本体のファイル名を、以下の通り新設・確定する。

```
decisions/
└── decision_YYYYMMDDTHHMMSSZ.json
```

- タイムスタンプ部分（`YYYYMMDDTHHMMSSZ`）には、本書§9出力JSONの`run_meta.layer5_completed_at`のUTC値をそのまま用いる。
- **日付のみ（`YYYYMMDD`）ではなく秒単位までのタイムスタンプを採用する理由**：Layer5（Claude Coworkスケジュールタスク）が同日中に複数回実行される可能性（手動再実行等）を考慮し、ファイル名の衝突を構造的に避けるため。
- `run_id`をファイル名に含める方式（例：`decision_{run_id}.json`）も検討したが、タイムスタンプのみで一意性の確保には十分であり、かつLayer4の`market_snapshot_YYYYMMDD_supersededTHHMMSSZ.json`（Layer4詳細設計書§7-1）と同様の「日付＋UTCタイムスタンプ」という命名慣習にファイル命名規則を揃えることを優先した。`run_id`はファイル名ではなく、ファイル内容（`run_meta.run_id`、§9参照）に保持されるため、情報が失われることはない。
- 同日再実行時も、Layer4・Layer6と同様に旧ファイルを削除・上書きせず、新しいタイムスタンプのファイルとして追加保存する（既存の「新スナップショットは新ファイル名で保存」という全体方針、Layer1詳細設計書§7-2と同一の考え方）。

---

## 4. 入力契約

Layer5は以下2つのデータソースのみを入力とする。

### 4-1. Layer2出力（`market_snapshot_YYYYMMDD.json`）

Layer2詳細設計書§5で定義したスキーマそのもの（`run_meta`／`regime`／`macro`／`candidates`／`excluded_summary`）。生の価格データ・生記事本文は一切含まれない。

### 4-2. ポートフォリオ状態（`portfolio_state`、新設・Layer5固有の入力）

`load_portfolio_state.py`が`取引記録_*.csv`の最新スナップショット（`保有ステータス`＝「保有中」の行）から算出する。

```json
{
  "as_of": "2026-07-18T06:25:00Z",
  "total_capital": 3000000,
  "total_invested": 850000,
  "available_capital": 2150000,
  "positions": [
    { "ticker": "7203", "asset_class": "japan_equity", "sector": "automobile", "invested_amount": 250000, "entry_price": 2500, "shares": 100 }
  ],
  "sector_concentration": { "automobile": 250000, "semiconductor": 600000 }
}
```

この`portfolio_state`は、Layer1のRepositoryパターンとは無関係（外部市場データではなくユーザー自身の取引記録であるため）。`load_portfolio_state.py`はGoogle Drive（`search_files`／`read_file_content`相当）を直接読む専用のローダーとして、Layer1のRepositoryとは別に実装する。

---

## 5. データ品質ゲート（確定：blocking/warning分類方式）

`critical_errors`が1件でも存在すれば無条件に様子見、という単純な設計は採用しない。理由は、例えば「1銘柄のニュース取得失敗」「一部APIタイムアウト」程度で市場全体の判断を停止すると機会損失が発生するためである。一方で「スコアリング計算失敗」「価格データ欠損」「snapshot破損」は投資判断そのものが不能なため、これらは無条件に停止すべきである。この2種類を明確に区別する。

### 5-1. `config/data_quality_policy.yaml`（新設）

```yaml
# config/data_quality_policy.yaml
blocking_errors:
  - SNAPSHOT_MISSING
  - PRICE_DATA_INVALID
  - SCORING_FAILED
  - SCHEMA_VERSION_ERROR
  - PORTFOLIO_STATE_INVALID
  - LAYER_PIPELINE_NOT_COMPLETED
warning_errors:
  - NEWS_API_FAILURE_PARTIAL
  - SINGLE_STOCK_DATA_FAILURE
  - MINOR_SOURCE_TIMEOUT
```

このリストは、Layer2詳細設計書§5で構造化した`run_meta.data_quality.critical_errors`／`warning_errors`の各エントリの`code`フィールド（`{code, message, source_layer}`）と照合される。**分類ポリシー自体はLayer5が保持し、Layer2・Layer3はコードを正しく構造化して出力するだけ**という責務分離を維持する（Layer2詳細設計書§10参照）。

### 5-2. 判定ルール

| 状況 | Layer5の動作 |
|---|---|
| 完了フラグ未到達（§3-1） / `blocking_errors`に該当するコードが1件でもある | **即座に様子見で確定**。LLM推論は実施しない。該当した`code`を理由として記録する |
| `warning_errors`に該当するコードのみが存在する（blocking無し） | **LLM判断を継続する。ただし信頼度は通常より抑制する方向で判断するようプロンプトで指示する**（無条件に様子見にはしない） |
| エラーなし | 通常通り判断する |
| `candidates`が0件（全銘柄が除外済みだがエラーは無い） | 「本日は提案なし（該当候補なし）」で確定（blocking/warningとは別の正常系） |

### 5-3. LLMへの伝達方法

`warning_errors`該当時は、プロンプトに以下のような注意喚起を含めて渡す（モデル非依存の平易な指示文）。

```
Data quality warning: 一部ニュース取得失敗あり。通常より慎重に判断してください。
```

この指示により、LLMは軽微なデータ欠損があったことを認識したうえで、通常よりやや保守的な信頼度・判断を行う（無条件のルール強制ではなく、LLMの定性判断に事実を伝えるという設計。最終的な信頼度50未満のゲートは§7の`rule_enforcer.py`が機械的に強制する）。

---

## 6. プロンプト設計方針（モデル非依存契約）

`prompts/layer5_judgment_prompt_template.md`には以下を含める。

1. **投資家プロフィール・リスクルールの明示**：投資可能資金300万円、1銘柄33%上限、損切り-10%基本、信頼度50未満は様子見、1日最大3件、断定的予測の禁止（既存ルールをそのまま踏襲）。
2. **入力データの構造説明**：Layer2 JSON（`candidates`配列、各軸の`score`／`reason`／`reason_code`／`uncertainty`(ニュースのみ)／`preliminary_quant_rank`等）と`portfolio_state`の意味をLLMに理解させる。
3. **LLMが行うべきこと**の明示：
   - 各候補について、Layer2が計算済みのスコア・reason_codeを根拠に、自然文の投資理由・リスク説明を作る（**スコアそのものを再計算・上書きしない**）
   - ニュース軸の`uncertainty`が高い候補は、その旨を投資理由・信頼度に反映する
   - `preliminary_quant_rank`を参考にしつつ、ポートフォリオ集中リスク（`portfolio_state.sector_concentration`）等を加味して最終的な推奨順位・採否を決める。ただし1日の新規提案件数が3件を超えた場合の絞り込み自体はLLMではなくPython側で行う（§7-1）ため、LLMは**全候補に対する採否判断とその理由**を出力すればよく、「3件に絞る」作業自体を意識する必要はない
   - 損切価格は「購入価格の-10%」を基本方針として明示するが、**実際の価格計算はLLMが行わず、後段の`position_sizer.py`が行う**ことを明記する
   - **利確ラインは「目標騰落率方式」を基本とする（確定）**：LLMは`take_profit_target_pct`（例：15）という数値と、その根拠（`take_profit_basis`、例：「決算成長期待と52週高値更新余地を考慮」）を出力する。実際の価格計算（購入価格×(1+目標騰落率)）はLLMが行わず`position_sizer.py`が行う（§8）。加えて任意項目として、参照価格（`reference_price_type`／`reference_price`、例：52週高値やアナリスト目標株価等、Layer2 JSON内に存在する値に限る）を補足情報として出力できる。これは利確水準の妥当性確認・レポート説明に使うのみで、価格計算そのものには使わない
   - 全候補（採用・不採用問わず）について、採否・理由・除外理由コードを含む判断ログを生成する（Ver2要件）
4. **禁止事項**：断定的な予測表現の禁止、スコアの数値そのものの再計算・改変の禁止、入力JSONに存在しない数値の創作禁止。
5. モデル固有のAPI仕様（tool use形式等）に依存しないプレーンテキストとして記述し、選択肢B移行時も同じ内容を各社API呼び出しにラップするだけで済むようにする（Layer3のプロンプト設計方針§7と同じ考え方）。

---

## 7. 決定ロジック：LLMの役割とPythonの役割の切り分け（重要）

| 項目 | 担当 | 理由 |
|---|---|---|
| 総合評価（買い/売り/様子見）の判断 | LLM | 定性的な総合判断そのもの |
| 推奨順位・ポートフォリオ集中リスクを踏まえた採否判断 | LLM | Layer2のスコアだけでは表現できない要素（ポートフォリオ全体最適）の判断 |
| 投資理由・リスク説明・ニュース解釈の自然文生成 | LLM | 自然文生成はLLMの本来の役割 |
| 各評価軸スコアの「なぜその点数か」の説明 | LLM（Layer2の`reason`/`reason_code`を根拠に生成、数値は再計算しない） | 数値はPython確定済み、説明の言語化のみLLM |
| 利確ラインの目標騰落率・根拠（どの水準を狙うか） | LLM（`take_profit_target_pct`／`take_profit_basis`を出力。実際の価格計算は`position_sizer.py`） | 「+15%程度」等の判断はLLM、価格の四則演算はPython |
| **推奨株数の計算** | **`position_sizer.py`（Python、必須）** | 元の運用ルールで「必ずコードで実行し暗算しない」と明記されている数値計算 |
| **損切価格の計算（購入価格×0.9）** | **`position_sizer.py`（Python、必須）** | 同上。LLMが暗算しない |
| **利確価格の最終計算（`take_profit_target_pct`を実際の価格に変換、許容範囲チェック含む）** | **`position_sizer.py`（Python、必須）** | LLMは目標騰落率（必須）と参照価格（任意・補足情報）を示すのみ。実際の金額計算に加え、`take_profit_policy`（5%〜50%）による範囲チェック・補正もPythonが行う（§8） |
| **信頼度50未満のゲート強制** | **`rule_enforcer.py`（Python、必須）** | LLMが誤って信頼度50未満の候補を提案してしまった場合の安全網 |
| **1日の新規提案最大3件の絞り込み** | **`rule_enforcer.py`（Python、必須。優先順位は§7-1で確定）** | LLMの出力件数が多すぎた場合の絞り込みは、モデル更新やプロンプト変更による採用銘柄のブレを避けるため、Pythonが定量指標に基づき機械的に決定する |
| **1銘柄33%上限・合計300万円上限の強制** | **`position_sizer.py`（Python、必須）** | 資金管理ルールの最終防衛線。LLMの判断に関わらず必ずこの上限内に収める |

この表の通り、**「何を買うべきか・なぜか」はLLMの判断領域、「いくら・何株買うか」は必ずPythonの決定的計算領域**、という原則を明確に分離する。`rule_enforcer.py`・`position_sizer.py`は、LLMの判断結果に対する**事後の強制レイヤー**として機能し、LLMがルールを誤って逸脱した場合でも最終出力は必ずルール準拠になるようにする（多層防御）。

### 7-1. 1日3件上限の優先順位（確定）

候補数の絞り込みは、Layer2の定量評価を優先し、LLMの提示順位に完全に寄せない。**「候補数制限はPythonルール、採用可否判断はLLM」という分離を徹底する**。

`rule_enforcer.py`は、LLMが「買い」と判断した候補のうち3件を超える場合、以下の優先順位で上位3件を機械的に選定する。

1. **Layer2 `preliminary_quant_rank`**（最優先）
2. `composite_score`（`preliminary_quant_rank`が同点の場合のタイブレーク）
3. LLMが出力した`confidence`
4. LLMが提示した推奨順位（最終的なタイブレークのみに使用）

**例外（LLM判断を尊重するケース）**：LLMが「ポートフォリオ集中リスク」「既保有銘柄との重複」等、定量スコアだけでは表現できない理由で特定候補を明示的に不採用と判断した場合、その除外判断はそのまま尊重する（`rule_enforcer.py`は「LLMが買い候補として残した集合」に対してのみ、上記優先順位で3件に絞り込む。LLMが最初から除外した候補を強制的に復活させることはしない）。

具体例：Layer2の`preliminary_quant_rank`がNVDA=1、AMD=2、AVGO=3、TSM=4で、LLMが「TSMを1位、NVDAを2位」等と独自順位を提示したとしても、3件制限時にはLLMが除外していない限り、`preliminary_quant_rank`上位のNVDA・AMD・AVGOが優先的に採用される。

---

## 8. `position_sizer.py`の算出式（既存運用ルールをそのまま踏襲）

```
1銘柄あたり投資上限額 = 投資可能資金(300万円) × 33%  ≒ 99万円
投資可能な残余資金 = portfolio_state.available_capital - 本日すでに確定した他候補への配分額

推奨株数(仮) = min( 投資上限額 ÷ 購入価格, 投資可能な残余資金 ÷ 購入価格 )
日本株の場合: 推奨株数 = floor(推奨株数(仮) / 100) × 100   # 100株単位に切り下げ
米国株・ETF等: 推奨株数 = floor(推奨株数(仮))                # 整数株に切り下げ

損切価格 = 購入価格 × (1 - 0.10)   # 基本方針。LLMが個別に変更を提言した場合のみ別値（要理由）
利確価格 = 購入価格 × (1 + take_profit_target_pct / 100)   # 確定：目標騰落率方式を基本とする
```

**利確価格の算出方式（確定）**：LLMが出力する`take_profit_target_pct`（必須）を購入価格に適用して`position_sizer.py`が計算する。LLMが任意で出力する`reference_price_type`／`reference_price`（例：52週高値等、Layer2 JSON内に存在する値）は、価格計算には使わず、算出結果の妥当性確認・レポート説明用の補足情報としてのみ保持する。参照価格方式のみを採用しない理由は、（1）銘柄ごとの値動き特性の差を吸収しにくいこと、（2）Layer2が保持する特定指標への依存が強くなりすぎること、（3）米国株・日本株・ETFで参照価格の性質が異なり統一しづらいことによる。

**`take_profit_target_pct`の許容範囲（重要・追加）**：LLMは数値を自由に生成できる立場にあるため、「LLMは判断するが資金管理ルールはPythonが守る」という本書全体の思想に基づき、`position_sizer.py`が許容範囲を機械的に強制する。

```yaml
# config/take_profit_policy.yaml
take_profit_policy:
  min_pct: 5
  max_pct: 50
  default_pct: 15
```

判定ロジック：
- `take_profit_target_pct`が`min_pct`〜`max_pct`の範囲内：LLMの値をそのまま採用する。
- 範囲外（例：LLMが45%や2%を出力）：**`position_sizer.py`が範囲内の最も近い境界値へ補正する**（例：45% → `max_pct`=50%以内なのでそのまま、60%なら50%に補正）。この補正は`rule_enforcement_log`に必ず記録し、隠蔽しない。
- 値が欠落・非数値等、構造的に無効な場合：候補全体を様子見にはせず、`default_pct`（15%）を採用したうえで、その旨を`rule_enforcement_log`に記録する（1項目の異常で提案全体を無駄にしないための扱い。ただし他の必須項目が欠落している場合は§10のエラー処理に従う）。

この範囲チェックにより、LLMが仮に不合理に大きい・小さい目標騰落率を出力しても、最終的な利確価格は常に常識的な範囲（購入価格の+5%〜+50%）に収まることが機械的に保証される。

**複数候補の同時配分**：LLMが最終的に採用した候補（最大3件）を推奨順位順に処理し、`投資可能な残余資金`を順に消費しながら逐次計算する（1件目の配分後に残余資金が減った状態で2件目を計算）。これにより、合計300万円を超える配分は構造的に発生しない。

**日本個別株の当日データ制約との関係**：Layer1詳細設計書§2-1のデータ品質ゲートにより、J-Quants Freeプランで12週遅延のデータしか取得できない日本個別株は、そもそもLayer2の`candidates`に含まれない（除外済み）。したがって`position_sizer.py`が古い価格を購入価格として使ってしまうリスクは、Layer1〜2の時点で構造的に排除されている。

**`recommended_shares`が0株になる場合の扱い（新設・確定、実装者レビューへの回答）**：残余資金が僅少な場合や、株価が高額な銘柄（1銘柄あたり投資上限額・残余資金のいずれかを購入価格が上回る場合）では、上記の算出式により`recommended_shares(仮)`を切り下げた結果、最終的な`recommended_shares`が0となることがあり得る。この場合、`position_sizer.py`は当該候補を採用候補から除外し、`decision_log`に`decision: "not_selected"`、`reason_code: "INSUFFICIENT_FUNDS_ZERO_SHARES"`として記録する（LLMによる除外ではなく、Pythonの資金管理計算による機械的な除外であることが分かるようにする）。`proposals`配列にはこの候補を含めない。この候補が消費するはずだった資金は使われないため、§8「複数候補の同時配分」で処理する後続候補の逐次計算（残余資金の消費順）には影響を与えない。0株の提案がLayer6のレポートやLayer7のトラッキング対象として実体の無いポジションのまま伝播することを、この時点で構造的に防止する。

---

## 9. 出力JSONスキーマ（Layer6への契約）

```json
{
  "run_meta": {
    "run_id": "20260718-0630",
    "layer5_started_at": "2026-07-18T06:30:05Z",
    "layer5_completed_at": "2026-07-18T06:34:40Z",
    "data_quality_gate": "passed",
    "data_quality_gate_detail": { "blocking_errors_found": [], "warning_errors_found": [] },
    "score_meta_ref": { "scoring_version": "1.0.0", "weight_version": "2026-07" }
  },
  "proposals": [
    {
      "rank": 1,
      "asset_class": "us_equity",
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "overall_assessment": "buy",
      "recommended_shares": 4,
      "entry_price_basis": 333.74,
      "position_amount": 1334.96,
      "stop_loss_price": 300.37,
      "take_profit_target_pct": 15.0,
      "take_profit_price": 383.80,
      "take_profit_basis": "決算成長期待と52週高値更新余地を考慮",
      "reference_price_type": "52_week_high",
      "reference_price": 350.0,
      "expected_return_pct": 15.0,
      "expected_loss_pct": -10.0,
      "risk_reward_ratio": 1.5,
      "holding_period": "2〜4週間",
      "confidence": 78,
      "investment_reason": "テクニカル・ファンダメンタル双方が良好（reason_code: TECH_MA_PERFECT_ORDER_UP, FUND_ROE_EXCELLENT 等）。現在のレンジ相場においても米国株はグロース優勢の局面適合。",
      "risk_factors": "ニュース軸のuncertaintyが高く、AI競合激化と製品発表というポジティブ・ネガティブ双方の材料が混在している点に留意。",
      "score_summary": {
        "technical": 84, "fundamental": 71, "supply_demand": 78, "macro": 65,
        "news": { "score": 63, "uncertainty": 35 },
        "regime_fit": 90, "composite": 79
      },
      "alternative_candidates": ["AMD (rank 4)", "AVGO (rank 6)"]
    }
  ],
  "decision_log": [
    { "ticker": "NVDA", "decision": "adopted", "rank": 1, "reason_code": "ADOPTED_TOP_RANK" },
    { "ticker": "6723", "decision": "rejected", "reason_code": "DATA_DELAYED_12W", "reason": "Layer1データ品質ゲートで除外済み（Layer2 excluded_summaryより転記）" },
    { "ticker": "AMD", "decision": "not_selected", "rank": 4, "reason_code": "DAILY_PROPOSAL_LIMIT_EXCEEDED", "reason": "LLMは買い候補として残したが、Layer2 preliminary_quant_rank(4位)を優先順位とした結果、3件制限で今回は見送り。次点候補として記録（§7-1の優先順位に基づく機械的判定であり、LLMによる除外ではない）" }
  ],
  "rule_enforcement_log": [
    { "rule": "confidence_gate", "applied": false },
    { "rule": "daily_proposal_limit", "applied": true, "detail": "LLMは4件を買い推奨としたが、§7-1の優先順位（preliminary_quant_rank→composite_score→confidence→LLM順位）に基づき上位3件に調整" }
  ]
}
```

**設計上のポイント**：
- `decision_log`には採用・不採用・除外済みを含む**全候補**が記載される（Ver2「AI判断ログの完全保存」要件）。
- `rule_enforcement_log`により、`rule_enforcer.py`／`position_sizer.py`が実際にどのハードルールを適用したか（＝LLMの出力をどう補正したか）が常に可視化される。
- `score_summary`はLayer2の`composite_score`・各軸`score`をそのまま転記したものであり、Layer5が再計算した値ではない。**フィールド名もLayer2の出力をそのまま保持し、Layer5側で改名・再構成しない**（修正済み：以前の草稿では`news_score`／`news_uncertainty`という合成キー名にしていたが、これはLayer2に存在しない名前をLayer5が作り出していることになり、「Layer5はLayer2出力を加工しない」という責務境界と矛盾するため、Layer2の実際の構造`news: {score, uncertainty}`をそのまま保持する形に修正した）。
- `take_profit_target_pct`は必須、`reference_price_type`／`reference_price`は任意の補足情報（§6・§8参照）。
- `run_meta.data_quality_gate`は`passed`（エラーなし）／`warning_continued`（`warning_errors`のみでLLM判断続行）／`blocked`（`blocking_errors`該当、様子見で確定）の3値をとる（§5参照）。

---

## 10. エラー処理・フォールバック

| 事象 | 対応 |
|---|---|
| 完了フラグファイルが規定時間までに存在しない | LLM推論を行わず「様子見」で確定。`reason_code: LAYER_PIPELINE_NOT_COMPLETED`として記録（§3-1） |
| `blocking_errors`該当のエラーが1件でもある | LLM推論を行わず即座に「様子見」で確定。該当コードを記録（§5） |
| LLM推論自体が失敗（セッションエラー等） | Layer1・Layer3と同様、`severity: critical`として記録。当日は「様子見」で確定し、原因をレポートに明記 |
| `position_sizer.py`実行時のエラー（Bashツール実行失敗等） | 当該候補の確定株数計算ができないため、その候補は「様子見（計算エラー）」に格下げする。他候補への影響は波及させない |
| `rule_enforcer.py`がハードルール違反を検知 | エラーではなく正常系。§9の`rule_enforcement_log`に記録し、補正後の値のみを最終出力とする |
| `portfolio_state`が読み込めない（取引記録ファイル破損等） | 残余投資可能資金が算出できないため、新規提案は行わず「様子見（ポートフォリオ状態不明）」とする |
| （新設・Ver1.5）`position_sizer.py`の計算結果、`recommended_shares`が0になる（資金不足・高額銘柄等） | 当該候補を`decision_log`に`not_selected`・`reason_code: INSUFFICIENT_FUNDS_ZERO_SHARES`として記録し、`proposals`には含めない（§8参照）。他候補の計算・配分順序への影響はない |

---

## 11. コスト最適化・モデル選定

- Layer5は選択肢Aのもと、Claude Coworkのスケジュールタスクとして稼働するため、Layer3のように「安価な小型モデルを個別に選定する」設計にはならない。使用モデルはそのスケジュールタスク（セッション）自体の設定に従う（Ver2確定：Claude系を採用）。
- 将来選択肢Bへ移行した場合、`config/ai_provider.yaml`の`layer5.provider`／`layer5.model`でモデルを指定する形になる（Layer3の`news_structurer`と同じ設定ファイル構造を共有する）。Layer5は最終投資判断という重い意思決定を担うため、Layer3の構造化タスクより上位のモデルを使うことが妥当（Layer3設計書§6で明記した「構造化は安価な小型モデル、最終判断はより高精度なモデル」という役割分担を維持する）。

---

## 12. テスト方針

| 対象 | テスト内容 |
|---|---|
| `load_snapshot.py` | 完了フラグ有り/無し、`completed:false`、規定時間超過のそれぞれのケースで、データ品質ゲートの判定が期待通りになること（§3-1） |
| `load_portfolio_state.py` | 取引記録CSVから保有ポジション・残余投資可能資金・セクター集中度が正しく算出されること |
| データ品質ポリシー判定 | `blocking_errors`該当時に即様子見、`warning_errors`のみの場合はLLM判断が継続しプロンプトに警告文が含まれること（§5） |
| `position_sizer.py` | 元の計算式（33%上限・残余資金・100株単位切り下げ）の既知の入力値に対する期待値照合。複数候補の逐次配分で合計が300万円を超えないこと。`take_profit_target_pct`から利確価格が正しく算出されること |
| `take_profit_policy`の範囲チェック | `min_pct`未満・`max_pct`超過の値が正しく境界値へ補正されること、値欠落時に`default_pct`が適用されること、いずれの場合も`rule_enforcement_log`に記録されること |
| `rule_enforcer.py` | 信頼度50未満の候補が確実に様子見へ変換されること、4件以上の買い推奨が§7-1の優先順位（`preliminary_quant_rank`→`composite_score`→`confidence`→LLM順位）で3件に絞られること、LLMが明示的に除外した候補は復活しないこと、絞られた候補が`not_selected`として`decision_log`に残ること |
| プロンプトテンプレートのレビューテスト | 生成されたLLM出力が「スコアの再計算をしていない」「入力JSONに存在しない数値を創作していない」ことを、サンプル入力に対する出力の後付け検証で確認 |
| 統合テスト（Layer2→Layer5） | Layer2のダミーsnapshotを一式通し、Layer5の出力JSONが§9のスキーマに準拠し、`decision_log`に全候補が含まれることをend-to-endで確認 |
| 選択肢B移行を見据えた契約テスト | `layer5_input_schema.json`／`layer5_output_schema.json`に対するJSON Schemaバリデーションが、モデルによらず一貫して通ること（将来モデル切替時の回帰防止） |

---

## 13. Ver2からの継続確認事項の再確認

- LLM交換可能設計：選択肢A（Claude Cowork継続）を採用、入出力契約はモデル非依存（本書§0・§6で反映）。
- 重みの自動調整：Layer5は行わない。自己評価層（Layer8、Ver2で設計）が別途、提案結果と実績を突き合わせて分析するのみで、Layer5自体が重みを書き換えることは無い。
- スコアの完全可視化：Layer2から受け取った`reason_code`／`score_meta`をそのまま出力JSONに保持し、Layer5独自の理由で数値を変更しない。

---

## 14. 確定事項（旧・未決事項への回答を反映）

1. **実行タイミング調整**：完了フラグファイル方式で確定。固定時刻オフセット方式は採用しない。Layer4が`layer4_completed_YYYYMMDD.json`を生成し、Layer5は存在確認→`completed:true`確認→snapshot読込→実行の順で処理する。規定時間内にフラグが無い場合は`reason_code: LAYER_PIPELINE_NOT_COMPLETED`で様子見とする（§3-1）。
2. **1日3件上限超過時の優先順位**：LLM提示順位ではなく、Python側で`preliminary_quant_rank`→`composite_score`→LLM `confidence`→LLM推奨順位、の優先順位で決定することで確定。ただしLLMがポートフォリオ集中リスクや既保有銘柄との重複を理由に明示的に除外した候補は、その判断を尊重し復活させない。「候補数制限はPythonルール、採用可否判断はLLM」という分離を徹底する（§7-1）。
3. **利確ライン方式**：「目標騰落率方式」を基本方式として確定。LLMは`take_profit_target_pct`（必須）と`take_profit_basis`を出力し、`position_sizer.py`が購入価格に適用して価格を確定する。`reference_price_type`／`reference_price`は任意の補足情報として、価格計算には使わず妥当性確認・レポート説明にのみ用いる（§6・§8）。
4. **データ品質ゲートの重大度分類**：単純な「critical_errorsあれば停止」ではなく、`config/data_quality_policy.yaml`で`blocking_errors`（即様子見：`SNAPSHOT_MISSING`、`PRICE_DATA_INVALID`、`SCORING_FAILED`、`SCHEMA_VERSION_ERROR`、`PORTFOLIO_STATE_INVALID`、`LAYER_PIPELINE_NOT_COMPLETED`）と`warning_errors`（判断継続・信頼度抑制：`NEWS_API_FAILURE_PARTIAL`、`SINGLE_STOCK_DATA_FAILURE`、`MINOR_SOURCE_TIMEOUT`）を明示的に分類することで確定（§5）。

## 15. 追加修正事項（今回のご指摘3点への対応）

1. **`score_summary`のフィールド名保持**：`news_score`／`news_uncertainty`という合成キー名を廃止し、`news: {score, uncertainty}`としてLayer2の実際の構造・命名をそのまま保持する形に修正した（§9）。Layer5がLayer2出力を加工しないという責務境界と整合させた。
2. **`take_profit_target_pct`の許容範囲**：`config/take_profit_policy.yaml`（`min_pct`5・`max_pct`50・`default_pct`15）を新設し、範囲外の値は`position_sizer.py`が境界値へ補正、欠落・無効値は`default_pct`を採用する設計に変更した（§8）。LLMが自由に数値を生成できてしまう状態を解消し、「LLMは判断する、資金管理ルールはPythonが守る」という原則を徹底した。
3. **Layer5の実行主体の明文化**：§0に「Layer5はPythonアプリケーションではなくAI Agent実行層である」ことを明記し、`scripts/*.py`はAgentが利用する補助ツール群であることを明確化した。Layer1〜4（Python Pipeline）→Layer5（AI Agent実行層）→Layer6（Report Generator）という全体構造も併記した。

## 16. 追加修正事項（全体設計書レビューへの回答、Ver1.4）

全体設計書（`docs/00_SystemArchitecture.md`）の改善提案「decision JSONの具体的なファイル命名規則が未定義」への回答として、`decisions/`フォルダに保存するdecision JSON本体のファイル名を`decision_YYYYMMDDTHHMMSSZ.json`に確定した（§3-2）。タイムスタンプはUTC・秒単位とし、同日複数回実行時の衝突を構造的に避ける。`run_id`はファイル名には含めず、ファイル内容（`run_meta.run_id`）にのみ保持する。それ以外の入出力契約・プロンプト設計・決定ロジックは一切変更していない。

## 17. 追加修正事項（実装者レビューへの回答、Ver1.5）

実装者レビューで指摘された「`position_sizer.py`の計算結果`recommended_shares`が0株になるケースの扱いが未定義」という指摘への回答として、§8末尾に取扱いルールを新設した。0株となった候補は`decision_log`に`not_selected`・`reason_code: INSUFFICIENT_FUNDS_ZERO_SHARES`として記録し、`proposals`には含めない設計とした（§10エラー処理表にも反映）。この追記は既存の`decision_log`／`rule_enforcement_log`の枠組みをそのまま用いた最小限の追記であり、責務分離・出力JSONスキーマ（`run_meta`/`proposals`/`decision_log`/`rule_enforcement_log`の4キー構造）・決定ロジックの他の部分には一切変更を加えていない。

本書はこれでVer1.5として確定とする。
