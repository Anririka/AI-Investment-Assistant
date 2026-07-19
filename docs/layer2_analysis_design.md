# 分析層（Layer2）詳細設計書

作成日: 2026-07-18（Ver1.4：Layer5との整合性確認により責務境界明記・critical_errors形式を補強）
前提: Layer1詳細設計書（確定版）／Ver2設計書で確定した6軸評価（テクニカル・ファンダメンタル・ニュース・マクロ・需給・市場レジーム）＋総合
関連文書: 「スコアリング仕様書」（配点・算出式は本書ではなく別紙に定義。本書はモジュール構成・データフロー・JSONスキーマ・テスト方針を定義する）

---

## 1. Layer2の責務と非責務

**責務**：Layer1から受け取った正規化データ（PriceSeries／FundamentalSnapshot／TimeSeries／RawNewsItem＋Layer3が構造化したニュース要約）をもとに、
- テクニカル指標・ファンダメンタル指標・需給指標の計算
- マクロ環境の評価
- 市場レジーム判定
- ニュース構造化データのスコア化
- 上記6軸のスコアと総合スコアの算出（配点はスコアリング仕様書に従う）
- 銘柄スクリーニング（母集団フィルタリング）と、Layer5に渡す最終JSONの組み立て

まで、**全て数値計算として完結させる**。

**非責務（LLMがやること・Layer2ではやらないこと）**：
- 投資判断（買い/売り/様子見）そのもの
- 自然文でのリスク説明・投資理由の作成
- ニュース記事本文の解釈（これはLayer3の責務。Layer2はLayer3が既に構造化した結果を受け取るのみ）
- 不採用理由の物語的な説明（理由コードは付与するが、文章化はLayer5）

---

## 2. モジュール構成（v1.1：責務分割を反映）

```
src/analysis/
├── technical_indicators.py   # テクニカル軸：指標計算＋サブスコア化
├── fundamental_metrics.py    # ファンダメンタル軸：指標計算＋サブスコア化（PERScorerはStrategyパターン化）
├── supply_demand.py          # 需給軸：出来高系指標の計算＋サブスコア化
├── macro_evaluator.py        # マクロ軸：FRED系列の評価＋サブスコア化（セクター感応度補正インターフェース含む）
├── regime_detector.py        # 市場レジーム判定＋レジーム適合スコア化
├── news_scorer.py            # ニュース軸：Layer3構造化結果の重み付け集計
├── scorer.py                 # 全軸のスコアを集約し、総合スコア・欠損時再配分を行う統合モジュール
├── screener.py                # 【責務縮小】母集団のフィルタリングのみ
├── ranking.py                 # 【新設】スコア順の並び替え・順位付け
└── json_builder.py            # 【新設】Layer5へ渡す最終JSONの生成（件数制限の適用含む）
```

各モジュールは「入力：正規化データ」「出力：軸別のサブスコア配列＋軸スコア」という共通の型で統一し、`scorer.py`だけがそれらを横断的に集約する。**個々のモジュールは他モジュールの実装を知らない**（疎結合）。

> **ご質問②（screener.pyの責務分割）への回答**：ご提案に賛成です。現行の`screener.py`は「母集団フィルタ」「ランキング」「JSON組み立て」という性質の異なる3つの処理を1ファイルに抱えており、単一責任の原則（SRP）に反していました。特に「将来ランキングアルゴリズムを変更する（例：スコア以外の要素を加味した並び替えに変える）」「Layer5のJSON仕様を変更する（例：選択肢Bへの移行に伴うスキーマ変更）」は、それぞれ独立に発生しうる変更であり、1ファイルに同居させたままだと修正時の影響範囲の見極めが難しくなります。分割によって、母集団フィルタ条件の変更・ランキングロジックの変更・JSON出力仕様の変更が互いに影響しなくなり、テストも単位ごとに書けるため、保守性の観点で明確にメリットがあると判断し、この方針を採用します。

---

## 3. 各モジュールの入力・出力・データフロー

### 3-1. `technical_indicators.py`（テクニカル軸）

- **入力**：`PriceSeries`（Layer1・Repository経由。最低200日分の日次OHLCVが必要、200MA計算のため）
- **算出指標**：5MA/25MA/75MA/200MA、RSI(14)、MACD/Signal/Histogram、ADX(14)、ATR(14)、ボリンジャーバンド（±1σ/±2σ）、VWAP、52週高値・安値
- **出力**：各指標の実測値（`raw_value`）＋スコアリング仕様書のバケット表に基づくサブスコア（0-100）＋採点理由文字列（例："RSI=52.3、健全な上昇トレンド帯（45-60）に該当"）
- **欠損時の扱い**：Layer1からPriceSeriesが200日分未満しか取得できない場合（新規上場銘柄等）、200MAは算出不能として欠損マークを付け、他のテクニカル指標のみでスコア化（重み再配分は`scorer.py`が実施）

### 3-2. `fundamental_metrics.py`（ファンダメンタル軸）

- **入力**：`FundamentalSnapshot`（EPS・純資産・当期純利益・売上高・営業利益・営業CF・設備投資・有利子負債・総資産・配当金等の生数値）
- **算出指標**：PER、PBR、ROE、ROA、EPS成長率（前年同期比）、売上成長率、営業利益率、営業CF・FCF水準、FCF成長率、自己資本比率、配当利回り（＋ユニバース内順位）
- **出力**：技術指標軸と同様の形式（raw_value／score／reason）
- **欠損時の扱い**：Layer1詳細設計書§2-4/§8で明記した通り、自己資本比率・FCF成長率はJ-Quants Freeプランでは取得できない可能性が高い。取得できない場合は当該サブ指標を欠損としてマークし、`scorer.py`が同一軸内の他指標へ比例配分する。
- **配当利回り順位の算出**：`screener.py`（母集団フィルタリング後）が母集団全体の配当利回り分布からパーセンタイルを計算し、各候補の生データに付加してから`fundamental_metrics.py`に渡す。本モジュールはその付加済みパーセンタイル値をスコア化するのみとし、順位計算そのものは行わない（責務分割後のデータフローは§3-8参照）。
- **PERのスコアリング方式（Strategyパターン）**：PERは業種によって適正水準が大きく異なるため、`PERScorer`という抽象インターフェースを設け、複数の実装を切り替え可能にする。
  - `AbsoluteRangePERScorer`（Ver1で採用・デフォルト）：スコアリング仕様書§3-2の絶対レンジ表をそのまま適用する、最もシンプルな実装。
  - `SectorRelativePERScorer`（将来拡張用、Ver1では未実装）：母集団内の同業種銘柄のPER中央値・標準偏差から偏差値を算出してスコア化する実装。インターフェースの型（入力：対象銘柄のPERと業種コード、母集団の業種別統計／出力：0-100スコア）のみを今回定義し、実装はしない。
  - 使用する実装は`config/scoring_weights.yaml`（または新設する`config/analysis_strategy.yaml`）で`per_scorer: absolute_range`のように指定し、将来`sector_relative`に切り替える際は設定変更のみで済むようにする。

### 3-3. `supply_demand.py`（需給軸）

- **入力**：`PriceSeries`の出来高列（過去25日分以上）、（取得できれば）信用残高データ
- **算出指標**：出来高急増率（当日出来高／過去20日平均出来高）、出来高移動平均乖離率（5日平均÷25日平均）、信用倍率（信用買い残÷信用売り残、J-Quants Standard以上でのみ取得可）
- **出力**：同上フォーマット
- **欠損時の扱い**：信用倍率はJ-Quants Freeプランでは常時欠損。`scorer.py`が需給軸内の残り2指標（出来高急増率・出来高移動平均乖離率）で100%を按分する。

### 3-4. `macro_evaluator.py`（マクロ軸）

- **入力**：`TimeSeries`（FRED経由：米10年国債利回り、FF金利、失業率、CPI、PPI、GDP、景気先行指数）
- **算出指標**：各系列の「水準」および「直近の変化方向」の評価
- **出力**：各指標のサブスコア＋マクロ軸スコア。**この軸は銘柄非依存（当日1回だけ計算し、全銘柄・全資産クラス共通で使い回す）**という点が他の軸と異なる。
- **セクター感応度補正（インターフェースのみ実装、Ver1ではデフォルト無効）**：`macro_evaluator.py`は、銘柄のスタイルタグ（グロース/バリュー/ディフェンシブ/高配当等）ごとに補正係数（`sector_sensitivity_factor`）を適用できるインターフェースを持つ。
  - 計算式：`candidate_macro_score = clamp(base_macro_axis_score × sector_sensitivity_factor[style_tag], 0, 100)`
  - Ver1では`config/scoring_weights.yaml`内の`macro_sector_correction`にすべてのスタイルタグに対し係数`1.0`（補正なし）を設定し、全銘柄が共通のマクロ軸スコアを使う。
  - 将来、十分な実績データ（Ver2で設計した自己評価ログ）が蓄積された段階で、この係数を人間レビューのうえ調整する（例：金利上昇局面のグロース株に`0.9`を設定する等）。**係数の自動学習は行わない**（Ver2で確定した「重み自動調整は不採用」の方針と整合させる）。
  - このインターフェースを最初から用意しておくことで、将来の拡張時に`macro_evaluator.py`本体のロジック変更は不要となり、configの係数変更のみで対応できる。

### 3-5. `regime_detector.py`（市場レジーム）

- **入力**：日経平均・TOPIX・S&P500等の指数レベルの`PriceSeries`
- **処理**：200日線との乖離とADX(14)を組み合わせたルールベース判定で「上昇相場」「下降相場」「レンジ相場」のいずれかを判定（判定ロジックの詳細はスコアリング仕様書に記載）
- **出力**：
  - `regime`（3値のいずれか）
  - 資産クラスごとの推奨スタイルバイアス（`config/risk_rules.yaml`のレジーム→戦略マッピングを参照。例：下降相場→ディフェンシブ/債券ETF/高配当、上昇相場→グロース/半導体/AI関連）
  - 個別銘柄ごとの「レジーム適合スコア」（銘柄のスタイルタグと現在のレジームの整合性を採点。§3-6参照）
- **銘柄非依存部分（regime自体の判定）は当日1回のみ計算**し、適合スコアの算出のみ銘柄ごとに行う。

### 3-6. `news_scorer.py`（ニュース軸）

- **入力**：Layer3（ニュース処理層）が既に構造化した`StructuredNewsItem`（カテゴリ／対象企業／対象業種／影響方向／影響期間／情報源／信頼度／重要度／`published_at`／`age_hours`／`news_schema_version`を含む。生記事本文は受け取らない）
- **処理**：対象銘柄・対象業種に関連するニュース項目を抽出し、`重要度 × 信頼度 × 影響方向（符号） × 時間減衰係数`を各記事ごとに算出する。
  - **時間減衰係数**：Layer3が付与した`age_hours`をもとに、`config/news_decay.yaml`（新設）で定義された係数を適用する（ハードコードせず、将来のニュース運用戦略変更をconfig変更のみで反映できるようにする）。

    ```yaml
    # config/news_decay.yaml
    decay_curve:
      - { within_hours: 24, factor: 1.0 }
      - { within_hours: 72, factor: 0.8 }
      - { within_hours: 168, factor: 0.6 }
      - { within_hours: 336, factor: 0.3 }
      - { within_hours: null, factor: 0.1 }   # 336時間（14日）超はこの係数
    ```

- **`score`と`uncertainty`の分離（重要）**：単純に全記事の寄与度を合計して50点基準に加減点するだけだと、例えば「非常にポジティブな記事」と「非常にネガティブな記事」が同時に存在する場合、寄与度が相殺されて見かけ上は50点（中立）になってしまい、「実際には重大なニュースが2件ある」という状況が消えてしまう。この問題を避けるため、`news_scorer.py`は**`score`（中心傾向）と`uncertainty`（評価の割れ具合）を分離して出力する**。
  - `score`：从来通り、寄与度の合計を50点基準で正規化した値（0-100）
  - `uncertainty`：ポジティブ方向の総寄与量とネガティブ方向の総寄与量の打ち消し合いの大きさを0-100で表す値。計算式：

    ```
    positive_mass = Σ(寄与度 > 0 の記事の寄与度)
    negative_mass = Σ(|寄与度| : 寄与度 < 0 の記事)
    total_mass = positive_mass + negative_mass
    uncertainty = total_mass > 0 ? 100 × 2 × min(positive_mass, negative_mass) / total_mass : 0
    ```
    全記事が同じ方向（相殺なし）ならuncertainty=0、ポジティブとネガティブが同じ大きさで拮抗していればuncertainty=100に近づく。
  - この`uncertainty`はスコア計算式（総合スコアの加重平均）には織り込まない。**Layer5が「このニュース評価は割れている」ことを自然文の説明・リスク要因の記述に反映するための追加シグナル**として渡す（Ver2「スコアの完全可視化」の趣旨を拡張し、単一の数値に丸め込めない不確実性そのものを可視化する）。
- **出力**：ニュース軸`score`／`uncertainty`＋寄与した記事一覧（見出し・情報源・公開時刻・経過時間・時間減衰係数・個別寄与度）を採点理由として保持
- **該当ニュースが無い銘柄**：`score`=50（中立）、`uncertainty`=0をデフォルトとし、「本日該当ニュースなし」と明記する
- **`news_schema_version`の扱い（後方互換設計、必須）**：`news_scorer.py`は受け取った`StructuredNewsItem`の`news_schema_version`を、単純な完全一致ではなく**メジャーバージョン単位の後方互換ルール**で検証する。
  - Layer2は対応済みバージョン一覧`supported_schema_versions`と、受け入れ可能な`accept_major_version`を`config/schema_compatibility.yaml`（新設）として保持する。

    ```yaml
    # config/schema_compatibility.yaml
    news_schema:
      supported_schema_versions: ["1.0", "1.1"]
      accept_major_version: 1
    ```

  - 判定ルール：受け取った`news_schema_version`のメジャーバージョン（`.`区切りの先頭）が`accept_major_version`と一致すれば受け入れる。マイナーバージョンの差分（例：Layer3が`1.1`を出力し、Layer2の`supported_schema_versions`が`1.0`しか知らない場合でも、メジャーが一致していれば受け入れる）は、**未知のフィールドを無視して処理を継続する**（追加フィールドは無視、必須フィールドの欠落は§9のエラー処理で個別に扱う）。
  - メジャーバージョンが不一致（例：Layer3が`2.0`を出力し、Layer2が`accept_major_version: 1`のまま）の場合のみ、`SchemaVersionError`として扱い、当該記事（または当日のニュース処理全体）を「互換性エラー」として`run_log`に`severity: critical`で記録する。この場合は無理に処理を継続せず、Layer5には「ニュース分析が機能していない日」であることが伝わるようにする（Layer1詳細設計書§5-2の重大エラー分類と同じ扱い）。
  - まとめ：Layer2は`supported_schema_versions`を持つ。Layer3は`news_schema_version`を出力する。Layer2は「一致または互換バージョン（メジャー一致）」のみ受け入れ、未知のメジャーバージョンなら`SchemaVersionError`とする。

### 3-7. `scorer.py`（統合）

- **入力**：3-1〜3-6の各モジュールが返すサブスコア群（軸ごと）
- **処理**：
  1. 各軸内で欠損サブ指標があれば、残りのサブ指標へ配点を比例配分する（欠損時再配分ルールはスコアリング仕様書§4で規定）
  2. 軸別スコア（0-100）を算出
  3. `config/scoring_weights.yaml`の軸別配点に従い、総合スコア（0-100）を加重平均で算出
  4. 各軸・各サブ指標のスコアと採点理由を`ScoreBreakdown`スキーマにまとめる
- **出力**：銘柄1件分の`ScoreBreakdown`（§5のJSONスキーマ内`scores`フィールドに対応）

### 3-8. `screener.py`（母集団フィルタリングのみ、責務縮小）

- **入力**：`config/universe.yaml`（日経225/S&P500構成銘柄マスタ、時価総額・出来高の下限条件）
- **処理**：
  1. 母集団を時価総額・出来高条件でフィルタリング
  2. フィルタ後の母集団全体の分布統計（配当利回りパーセンタイル等、ユニバース全体を見ないと算出できない値）を計算し、各候補の生データに付加する
  3. データ品質ゲート（Layer1の`is_delayed`等）により対象外となる銘柄をここで除外し、理由コードを付与する
- **出力**：フィルタ・統計付加済みの候補リスト（`scorer.py`への入力となる）＋除外銘柄と理由コードのリスト
- **他モジュールとの関係**：`scorer.py`は本モジュールの出力を受け取ってスコアリングを行う。ランキング・JSON組み立ての処理は一切持たない。

### 3-9. `ranking.py`（スコア順・順位付け、新設）

- **入力**：`scorer.py`が算出した全候補（母集団フィルタを通過した全件）の`ScoreBreakdown`
- **処理**：
  1. 資産クラスごとに総合スコアの降順で並び替え、`preliminary_quant_rank`を付与
  2. 将来的にスコア以外の要素（ポートフォリオ集中制約等）を加味した並び替えロジックに拡張する場合も、変更範囲はこのファイルに閉じる
- **出力**：資産クラスごとに順位付けされた**全候補**のリスト（この時点ではまだ件数の絞り込みは行わない。全候補の順位情報はGoogle Driveの`decision_log`に完全保存するため）

### 3-10. `json_builder.py`（Layer5へ渡すJSON生成、新設）

- **入力**：`ranking.py`が出力した順位付け済み全候補、`regime_detector.py`／`macro_evaluator.py`の当日共通データ、`screener.py`の除外銘柄リスト
- **処理**：
  1. `config/llm_input.yaml`で定義された資産クラスごとの件数上限に従い、上位候補のみを抽出する（§3-10-1参照）
  2. 除外候補・件数超過により今回は非採用となった候補を`excluded_summary`として要約する
  3. §5のJSONスキーマに沿って最終的なJSONを組み立てる
- **出力**：Layer5に渡す最終JSON（§5）。**母集団全件の生データはここでは渡さず、上限件数分のみを含める**（プロンプト肥大化・コスト増を避けるため）。順位付け済み全候補の完全なデータはGoogle Drive上の`decision_log`に別途保存し、LLMへの入力JSONには含めない。

#### 3-10-1. `config/llm_input.yaml`（新設：LLMへ渡す候補件数の設定）

```yaml
# config/llm_input.yaml
candidate_limits:
  japan_equity: 10
  us_equity: 10
  etf: 5
  bond: 3
  gold: 3
  other: 3
max_total_candidates: 30   # 上記合計の目安上限（超過時は資産クラスごとの上限を優先し、超過分は警告ログに記録）

prompt_budget:              # 【新設】LLMベンダーごとに異なるトークン制約・コストに対応
  claude: 12000
  gpt: 8000
  gemini: 10000
active_provider_ref: "config/ai_provider.yaml#layer5.provider"   # 現在Layer5が使用中のプロバイダを参照し、対応するbudgetを採用
```

この値は将来的な調整を見込み、コード変更なしで`json_builder.py`が参照する設定ファイルとして独立させる。

**`prompt_budget`の扱い**：`json_builder.py`は`candidate_limits`による資産クラスごとの件数制限を適用した後、組み立てたJSON全体の概算トークン数を見積もり（簡易的には文字数÷4等の概算、または各社トークナイザーライブラリを利用）、現在Layer5が使用しているプロバイダの`prompt_budget`を超える場合はさらに調整を行う。調整の優先順位は次の通り：①各候補の`sub_scores`の`reason`文字列を短縮（`reason_code`は残すため情報は失われない）、②総合スコアが低い候補から順に除外し`excluded_summary`へ移す。どちらの調整を行ったかはrun_logに記録し、Ver2「スコアの完全可視化」の趣旨に沿って隠蔽しない。

---

## 4. Repositoryとの接続方法

- Layer2の各モジュールは、Layer1が提供する`RepositoryFactory`経由でのみデータを取得する。**Layer2はどのAPIが使われたかを一切意識しない**（Layer1詳細設計書§3のRepositoryパターンの原則を継承）。
- ただし、取得したデータに付随する`DataFetchMeta`（`is_delayed`、`source_used`等）は、Layer2の各モジュールが「このデータは信頼して指標計算に使ってよいか」を判断する材料として参照する。特に日本個別株で`is_delayed=true`（12週遅延データ）の場合、`technical_indicators.py`は指標計算自体を実行せず、「データ品質ゲートにより対象外」として`screener.py`に伝播する（Layer1詳細設計書§2-1の方針をLayer2側で受ける形）。
- `macro_evaluator.py`・`regime_detector.py`はマクロ・指数データという「銘柄非依存」のデータを扱うため、個別銘柄用のRepositoryとは別に、それぞれ`MacroRepository`・指数用の`MarketDataRepository`インスタンスを1回だけ呼び出す（銘柄数分のループの外側で実行し、無駄な重複呼び出しを避ける）。

---

## 5. Layer5に渡すJSONスキーマ（STEP4）

Layer2の最終出力であり、Layer5（AI判断層）の唯一の入力契約。**Ver2「LLM交換可能設計（選択肢A採用、ただし入出力契約はモデル非依存）」の方針に基づき、このスキーマは特定のAIベンダーに依存しない、純粋なデータ契約として設計する。**

**責務境界の明記（Layer5設計書との整合性確認により追加）**：Layer2は各評価軸スコア・`reason_code`・`composite_score`を確定生成する。**Layer5はこれらの値を変更・再計算せず**、投資判断理由生成および総合判断に利用する。Layer5が行うのは、これらの確定済みスコアを根拠とした自然文の説明生成と、ポートフォリオ全体を踏まえた採否・優先順位の判断であり、スコアの数値そのものを書き換えることはない（Layer5詳細設計書§7参照）。

### 5-1. トップレベル構造

```json
{
  "run_meta": {
    "run_id": "20260718-0600",
    "analysis_started_at": "2026-07-18T06:00:12Z",
    "analysis_completed_at": "2026-07-18T06:07:45Z",
    "score_meta": {
      "scoring_version": "1.0.0",
      "weight_version": "2026-07"
    },
    "data_quality": {
      "critical_errors": [],
      "warning_errors": [],
      "degraded_sources": ["jquants:price_delayed"],
      "excluded_candidates_count": 3
    }
  },
  "regime": {
    "current_regime": "range",
    "regime_reason": "日経平均が200日線±3%で推移、ADX(14)=18と方向感が弱い",
    "strategy_bias": {
      "japan_equity": "neutral",
      "us_equity": "growth_tilt",
      "bond": "neutral"
    }
  },
  "macro": {
    "as_of": "2026-07-17",
    "series": {
      "us_10y_yield": { "value": 4.55, "change_1m": -0.05, "score": 70 },
      "fed_funds_rate": { "value": 4.25, "trend": "hold_expected", "score": 60 },
      "unemployment_rate": { "value": 4.1, "change_1m": 0.0, "score": 60 },
      "cpi_yoy": { "value": 2.8, "trend": "decelerating", "score": 75 },
      "ppi_yoy": { "value": 2.1, "trend": "flat", "score": 60 },
      "gdp_growth": { "value": 2.3, "vs_consensus": "in_line", "score": 60 },
      "leading_index": { "value": 101.2, "trend": "up", "score": 70 }
    },
    "axis_score": 65,
    "axis_score_reason": "金利は横ばい〜やや低下、インフレは鈍化基調で総じて中立〜やや良好"
  },
  "candidates": [
    {
      "asset_class": "us_equity",
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "style_tags": ["growth", "semiconductor", "ai"],
      "preliminary_quant_rank": 1,
      "data_quality": { "is_delayed": false, "missing_fields": ["fcf_growth_rate"] },
      "technical": {
        "raw": { "rsi14": 52.3, "macd": 1.2, "macd_signal": 0.9, "adx14": 27.5, "atr14": 8.1, "ma_alignment": "perfect_up", "bb_position": "+1sigma", "vwap_diff_pct": 1.8, "week52_position": "near_high" },
        "sub_scores": [
          { "indicator": "MA", "reason_code": "TECH_PERFECT_ORDER_UP", "score": 95, "weight_in_axis": 0.25, "reason": "5>25>75>200のパーフェクトオーダー、株価は5MA上" },
          { "indicator": "RSI", "reason_code": "TECH_RSI_HEALTHY", "score": 90, "weight_in_axis": 0.15, "reason": "RSI=52.3、45-60の健全な上昇トレンド帯" }
        ],
        "axis_score": 84,
        "axis_score_reason": "トレンド・モメンタムともに良好、過熱感は限定的"
      },
      "fundamental": {
        "raw": { "per": 42.1, "pbr": 18.3, "roe": 0.68, "roa": 0.35, "eps_growth_yoy": 0.45, "sales_growth_yoy": 0.38, "operating_margin": 0.55, "fcf": 28000000000, "fcf_growth_rate": null, "equity_ratio": 0.72, "dividend_yield_rank_pct": 0.9 },
        "sub_scores": [ "...(同形式)" ],
        "axis_score": 71,
        "axis_score_reason": "高PERだが高ROE・高成長で正当化される水準。FCF成長率は欠損のため他指標へ再配分"
      },
      "supply_demand": {
        "raw": { "volume_surge_ratio": 2.4, "volume_ma_deviation_pct": 0.32, "margin_ratio": null },
        "sub_scores": [ "..." ],
        "axis_score": 78,
        "axis_score_reason": "出来高急増率2.4倍、関心の高まりを示唆。信用倍率は米国株のため対象外"
      },
      "news": {
        "relevant_items": [
          { "news_schema_version": "1.0", "reason_code": "NEWS_PRODUCT", "headline": "NVIDIA、新型AIチップ発表", "source": "Reuters", "category": "product", "impact_direction": "positive", "impact_horizon": "mid_term", "confidence": 0.8, "importance": 75, "published_at": "2026-07-18T03:15:00Z", "age_hours": 5.3, "time_decay_factor": 1.0, "contribution": 60.0 }
        ],
        "score": 63,
        "uncertainty": 0,
        "axis_score_reason": "ポジティブな製品ニュース1件、重要度中程度、公開5.3時間後で減衰係数1.0を適用。相殺する逆方向の記事なしのためuncertainty=0"
      },
      "macro_axis_score_ref": 65,
      "regime_fit": {
        "score": 90,
        "reason": "現在のレジーム(レンジ、米国株はグロース優勢)とグロース/半導体タグが合致"
      },
      "composite_score": {
        "total": 79,
        "breakdown_weights": { "technical": 25, "fundamental": 25, "supply_demand": 15, "macro": 15, "news": 10, "regime": 10 },
        "calculation_note": "各軸スコア（newsは`score`フィールドを使用、`uncertainty`は計算に含めない）×配点の加重平均。欠損指標は同軸内で比例配分済み",
        "score_meta": {
          "scoring_version": "1.0.0",
          "weight_version": "2026-07"
        }
      }
    }
  ],
  "excluded_summary": [
    { "ticker": "6723", "asset_class": "japan_equity", "reason_code": "DATA_DELAYED_12W", "reason": "J-Quants Freeプランの12週遅延によりデータ品質ゲートで除外" }
  ]
}
```

### 5-2. 設計上のポイント

- **すべての`score`には`reason`（自然文）と`reason_code`（機械可読コード）の両方が併記される**（Ver2「スコアの完全可視化」要件の拡張）。`reason`はLLMが自然文説明を作る際の根拠、`reason_code`はLayer5・人間・将来のバックテスト分析ツールが「同じ理由コードの提案がどれだけあったか」等を機械的に検索・集計するために使う。命名規則は`{軸}_{指標}_{状態}`（例：`TECH_RSI_HEALTHY`、`TECH_PERFECT_ORDER_UP`、`NEWS_PRODUCT`）とし、コード一覧はスコアリング仕様書の各バケット表に列として追加済み。
- **ニュース軸は`score`と`uncertainty`を分離して持つ**（§3-6参照）。ポジティブ・ネガティブ双方の重要ニュースが同時に存在する「評価が割れている」状態を、単一スコアへの丸め込みで消してしまわないようにするための設計。
- **`score_meta`（`scoring_version`／`weight_version`）を`run_meta`および各候補の`composite_score`双方に持たせる**（重要）。将来、配点や算出式（スコアリング仕様書）を変更した際、過去の提案データと現在の提案データのスコアを単純比較できなくなる問題を防ぐため。`weight_version`は`config/scoring_weights.yaml`等の数値パラメータの版、`scoring_version`はスコア算出ロジック・計算式そのものの版（バケット構成の追加変更等）を表し、両者は独立にインクリメントされる。バックテスト（Ver2で前倒しした基盤）は、この2つのバージョンが一致するデータ同士でのみ「同じ物差し」として比較する。
- **`preliminary_quant_rank`はLayer2が算出した参考順位であり、LLMの最終推奨順位と一致するとは限らない**（LLMはポートフォリオ集中リスクや損切りルールとの整合性等、定量スコアだけでは表現しきれない要素を加味して最終順位を決める余地を残す。ただし、その判断も本JSON内の情報のみに基づく）。
- **`excluded_summary`はLLMにも要約レベルで渡し**、「本日除外された候補とその理由」を最終レポートに含められるようにする（Ver2「不採用候補・除外理由の保存」要件を、Layer5の入力段階から満たす）。
- **`critical_errors`／`warning_errors`のエントリ形式（Layer5設計書との整合性確認により追加）**：Layer5がエラー種別ごとに「即様子見」か「警告として継続」かを判定できるよう（Layer5詳細設計書§5）、各エントリは`{ "code": "...", "message": "...", "source_layer": "layer1|layer2|layer3" }`の形式で記録する。`code`にはLayer1・Layer3を含む全層で共通の語彙（例：`SNAPSHOT_MISSING`、`PRICE_DATA_INVALID`、`SCORING_FAILED`、`SCHEMA_VERSION_ERROR`、`NEWS_API_FAILURE_PARTIAL`、`SINGLE_STOCK_DATA_FAILURE`、`MINOR_SOURCE_TIMEOUT`等）を用いる。この語彙自体の「どれが即停止でどれが継続可か」というポリシーはLayer5側が`config/data_quality_policy.yaml`として保持し（Layer5詳細設計書§5参照）、Layer2は判定を行わずコードを正しく記録するだけに留める（責務分離を維持）。例：`"critical_errors": [{ "code": "SCORING_FAILED", "message": "scorer.pyでの需給軸計算中に例外発生", "source_layer": "layer2" }]`。
- **プロンプトのトークン予算（`prompt_budget`）を超える場合の調整**は§3-10-1で規定した優先順位（reason短縮→低スコア候補の除外）に従う。
- モデル非依存性：本スキーマはJSON Schemaとして厳密に定義し（Phase1実装時にJSON Schemaファイルを作成）、将来Layer5を選択肢B（外部LLM）に切り替える場合も、この入力契約と出力契約（決定JSON）を変更する必要がないようにする。

---

## 6. テスト方針

| 対象 | テスト内容 |
|---|---|
| 各指標計算関数（`technical_indicators.py`等） | 既知の価格系列に対する手計算済みの期待値（RSI・MACD等）とのユニットテスト照合 |
| バケットスコア化ロジック | 境界値テスト（例：RSI=29.99と30.00で異なるスコアバケットに入ることの確認、スコアリング仕様書の境界定義通りに動くこと） |
| 欠損時再配分ロジック | 意図的に1〜複数のサブ指標を欠損させ、軸内の残りサブ指標へ正しく比例配分されること、配点合計が常に100%になることを確認 |
| `regime_detector.py` | 人工的に作成した「明確な上昇トレンド」「明確な下降トレンド」「レンジ」のダミー指数データを入力し、意図通りの3値判定になることを確認 |
| `news_scorer.py` | ポジティブ/ネガティブ/中立の記事を混在させたテストケースで、`score`が符号通りに動くこと、該当ニュース無しの場合に`score=50`／`uncertainty=0`のデフォルトになることを確認。特に「強いポジティブ1件＋強いネガティブ1件」のケースで`score≈50`かつ`uncertainty`が高い値になることを確認（本節の主眼） |
| `config/news_decay.yaml`の反映 | `age_hours`の境界値（24h/72h/168h/336h前後）で正しい減衰係数が適用されること、config変更のみで係数が変わりコード変更が不要なことを確認 |
| `reason_code`の一意性・網羅性 | スコアリング仕様書で定義された全バケットに対応する`reason_code`が漏れなく存在すること |
| `score_meta`の伝播 | `run_meta.score_meta`と各候補`composite_score.score_meta`が同一run内で常に一致すること |
| `news_schema_version`の後方互換判定 | メジャー一致・マイナー差分ありのケース（例：`supported_schema_versions: ["1.0"]`に対し`1.1`を受信）で正常受理・未知フィールド無視となること、メジャー不一致（例：`2.0`受信）で`SchemaVersionError`となり`severity: critical`でログされること |
| `scorer.py`（統合） | 軸別配点の合計が`scoring_weights.yaml`の定義通りになること、全軸が正常な場合と一部軸が欠損データを含む場合の両方で総合スコアが破綻しないこと |
| `screener.py` | 母集団フィルタ条件（時価総額・出来高）が正しく適用されること、除外銘柄に正しい`reason_code`が付与されること |
| `ranking.py` | 総合スコア降順で正しく順位付けされること、母集団全件が（件数を絞らずに）出力されること |
| `json_builder.py` | `config/llm_input.yaml`の件数上限が資産クラスごとに正しく適用されること、上限超過分が`excluded_summary`に正しく記録されること、合計30件を超えた場合に警告ログが出ること |
| JSONスキーマ全体 | Layer1のダミー出力一式を通しでLayer2に流し、§5のJSON Schemaに対してvalidation（jsonschema等のライブラリでの形式検証）が通ること |

---

## 7. 確定事項（旧・未決定事項への回答を反映）

1. **マクロ軸のセクター感応度補正**：Ver1ではデフォルト無効（補正係数1.0、全銘柄共通スコア）で確定。インターフェースのみ実装し、将来の人間レビューによる係数調整に備える（§3-4）。
2. **LLMへ渡す候補件数**：日本株10件・米国株10件・ETF5件・債券/金/その他各3件（合計30件目安）で確定。`config/llm_input.yaml`で管理する（§3-10-1）。
3. **PERの業種補正**：Ver1は絶対レンジ方式で確定。`PERScorer`をStrategyパターン化し、将来`SectorRelativePERScorer`へ切り替え可能な構造とする（§3-2）。
4. **`screener.py`の責務分割**：`screener.py`（母集団フィルタ）／`ranking.py`（順位付け）／`json_builder.py`（JSON生成）の3モジュールに分割する方針で確定（§2、§3-8〜3-10）。

## 8. 追加修正事項（今回のご指摘5点への対応）

1. **ニュースのscore/uncertainty分離**：`news_scorer.py`の出力を`score`（中心傾向）と`uncertainty`（評価の割れ具合）に分離する設計に変更（§3-6）。強いポジティブ記事と強いネガティブ記事が相殺されて中立点に丸め込まれる問題を回避し、Layer5が「評価が割れている」ことを判断できるようにした。
2. **時間減衰係数のconfig化**：`config/news_decay.yaml`を新設し、時間減衰の閾値・係数をコード外で管理できるようにした（§3-6）。
3. **`prompt_budget`の追加**：`config/llm_input.yaml`にLLMベンダーごとのトークン予算（`prompt_budget`）を追加し、`json_builder.py`が候補件数の上限に加えてトークン予算でも調整できるようにした（§3-10-1）。
4. **`reason_code`の追加**：全サブスコア・ニュース項目に機械可読な`reason_code`を付与し、`reason`（自然文）と併記する設計に変更した（§5-1、§5-2）。命名規則・コード一覧はスコアリング仕様書側に定義する。
5. **`score_meta`（バージョン管理）の追加**：`scoring_version`／`weight_version`を`run_meta`と各候補の`composite_score`に持たせ、将来の配点変更後もバックテストで「同じ物差し」のデータのみを比較できるようにした（§5-1、§5-2）。

## 9. 追加修正事項（news_schema_versionの後方互換設計、★★★★★必須）

`news_schema_version`の検証ロジックを、完全一致方式から**メジャーバージョン単位の後方互換方式**に変更した（§3-6）。`config/schema_compatibility.yaml`で`supported_schema_versions`（対応済みバージョン一覧）と`accept_major_version`（受け入れ可能なメジャーバージョン）を管理し、メジャーバージョンが一致すればマイナー差分（未知フィールド）を無視して受け入れ、メジャーバージョン不一致の場合のみ`SchemaVersionError`として重大エラー扱いにする設計に統一した。この方針はLayer3設計書側の説明とも整合させている（Layer3側の該当箇所を参照）。

## 10. Layer5との整合性確認レビュー（今回実施分）

Layer5詳細設計書作成に伴い、「Layer5を正しく動作させるために必要な最低限の修正」の観点でのみレビューを実施した。スコアリングロジック・重み・特徴量計算方法・候補抽出ロジック・評価式・Layer2の責務範囲は一切変更していない。

| # | 確認項目 | 結果 | 修正前 | 修正後 | 修正理由 |
|---|---|---|---|---|---|
| 1 | `candidates[].ticker`/`name`/`asset_class`/`composite_score`の存在 | 既に充足 | （変更なし） | （変更なし） | 既存スキーマに全て存在済みのため修正不要 |
| 2 | 各評価軸`score`の存在（technical/fundamental/supply_demand/macro/news/regime） | 既に充足（キー名は軸ごとに`axis_score`/`score`と異なるが、Layer5側は既にこの命名を前提に設計済み） | （変更なし） | （変更なし） | Layer5詳細設計書§9の出力例は既存のキー名（`axis_score`、`news.score`、`regime_fit.score`）をそのまま参照しており支障がない。命名統一は既存アーキテクチャの変更に当たるため今回は見送り |
| 3 | 各評価軸`reason`の存在 | 既に充足 | （変更なし） | （変更なし） | `axis_score_reason`／`regime_fit.reason`として全軸に存在済み |
| 4 | `reason_code`の存在 | 既に充足（サブ指標単位） | （変更なし） | （変更なし） | 各`sub_scores`要素に`reason_code`が付与済みで、Layer5はここから根拠を参照可能 |
| 5 | `preliminary_quant_rank`の存在 | 既に充足 | （変更なし） | （変更なし） | 既存スキーマに存在済み |
| 6 | `news_score`/`news_uncertainty`相当の存在 | 既に充足 | （変更なし） | （変更なし） | `candidates[].news.score`／`candidates[].news.uncertainty`として存在済み |
| 7 | `run_meta.data_quality`/`critical_errors`の存在 | 既に充足 | （変更なし） | （変更なし） | 既存スキーマに存在済み |
| 8 | `score_meta.scoring_version`/`weight_version`の存在 | 既に充足 | （変更なし） | （変更なし） | `run_meta.score_meta`・各候補`composite_score.score_meta`双方に存在済み |
| 9 | Layer2/Layer5間の責務境界の明記 | **要追加** | 責務境界の明文化が無かった | §5冒頭に「Layer2はスコア・reason_code・composite_scoreを確定生成し、Layer5はこれらを変更・再計算せず利用する」を追記 | Layer5が数値を再計算しないことを両設計書で相互に確認できるようにするため |
| 10 | `critical_errors`のエントリ形式 | **要追加** | 配列の要素形式が未定義（文字列か構造体か不明瞭） | `{code, message, source_layer}`の構造化形式に確定し、`warning_errors`配列も追加 | Layer5が新設した`data_quality_policy`（blocking/warning分類）が、コードによる機械的な分類を前提とするため、Layer2側でコードを明確に構造化して出力する必要があった |

**結論**：Layer5が必要とする情報の大部分は既存のLayer2設計で既に充足していた。追加が必要だったのは「責務境界の明文化」と「エラーエントリの構造化」の2点のみであり、スコアリングロジックやモジュール構成、責務分離には一切手を加えていない。

本書はこれでVer1.4として確定とし、次はLayer5（AI判断層）の詳細設計に進む。
