# スコアリング仕様書（Layer2付属）

作成日: 2026-07-18（Ver1.2：reason_code・スコアversion管理・ニュースscore/uncertainty分離・時間減衰のconfig化を反映）
位置づけ: 分析層（Layer2）詳細設計書の付属文書。`config/scoring_weights.yaml`の設計内容と、各指標のスコア算出式（バケット表）を定義する。
共通ルール: 全スコアは0〜100点。各軸内のサブ指標配点合計は必ず100%になるよう設計し、データ欠損時は欠損分を残りのサブ指標へ比例配分する（§4）。ここで定義する配点・閾値は**初期値**であり、Ver2で採用した「人間レビューによる重み調整」プロセスを通じて将来調整されることを前提とする（自動調整は行わない）。

**バージョン管理（重要）**：本仕様書の配点・算出式は`weight_version`（数値パラメータの版）と`scoring_version`（算出ロジック・計算式構造の版）の2つで管理する。これらはLayer2が出力するJSONの`run_meta.score_meta`／各候補`composite_score.score_meta`にそのまま転記され、将来の配点変更後も過去データとの単純比較を誤って行わないようにする（Layer2詳細設計書§7参照）。本書時点の版は`scoring_version: "1.0.0"`／`weight_version: "2026-07"`とする。

---

## 1. 軸別配点（`config/scoring_weights.yaml` トップレベル）

6軸＋総合の構成。軸別配点の合計は100。

| 評価軸 | 配点 | 設計意図 |
|---|---|---|
| テクニカル | 25 | 市場データ分析AIの中核。価格・出来高パターンを重視 |
| ファンダメンタル | 25 | テクニカルと並ぶ中核。企業の実質的な価値・収益性を重視 |
| 需給 | 15 | 出来高急増等、短期的な資金流入/流出の兆候 |
| マクロ | 15 | 金利・インフレ等、市場全体への外部環境の影響 |
| ニュース | 10 | 意図的に最も低い配点。「ニュース要約AI」からの脱却という今回のリファクタリング方針を反映し、ニュースは補助情報に留める |
| 市場レジーム | 10 | 現在の相場局面とのスタイル適合度 |
| **総合** | **100** | 上記6軸の加重平均 |

```yaml
# config/scoring_weights.yaml（設計イメージ）
scoring_version: "1.0.0"
weight_version: "2026-07"

axis_weights:
  technical: 25
  fundamental: 25
  supply_demand: 15
  macro: 15
  news: 10
  regime: 10

technical:
  MA: 25
  MACD: 20
  RSI: 15
  ADX: 10
  ATR: 10
  BollingerBands: 10
  VWAP: 5
  Week52HighLow: 5

fundamental:
  ROE: 15
  PER: 15
  EPSGrowth: 15
  SalesGrowth: 10
  OperatingMargin: 10
  PBR: 10
  FCFLevel: 5
  FCFGrowth: 5
  EquityRatio: 5
  DividendYieldRank: 5
  ROA: 5

supply_demand:
  VolumeSurgeRatio: 45
  VolumeMADeviation: 35
  MarginRatio: 20   # J-Quants Freeでは常時欠損 → 欠損時は残り2項目で100%按分

macro:
  US10YYield: 20
  FedFundsRate: 20
  UnemploymentRate: 15
  CPI: 15
  PPI: 10
  GDP: 10
  LeadingIndex: 10

news:
  method: "weighted_sentiment_aggregation_with_uncertainty"   # §3-5参照。score/uncertaintyを分離出力
  decay_config_ref: "config/news_decay.yaml"                    # §3-5参照。時間減衰係数は別configで管理

regime:
  method: "rule_based_lookup"                # バケット表ではなくルールベース判定（§3-6参照）
```

各サブ軸の配点合計（technical=100、fundamental=100、supply_demand=100、macro=100）が保たれていることをユニットテストで検証する（Layer2設計書§6参照）。

---

## 2. スコア算出の共通ルール

- 各指標の実測値（`raw_value`）を、以下のバケット表に照らして0-100点に変換する。
- バケット境界は「以上・未満」で定義し、境界値の扱いは**下限側を含む（closed-open, `[a, b)`）**方式に統一する（実装時の曖昧さ回避）。
- 各指標のスコアには、実測値を埋め込んだ採点理由テンプレート文（`reason`）と、機械可読な`reason_code`を必ずセットで生成する。`reason`はLayer5が自然文説明を作る根拠、`reason_code`はLayer5・人間・将来のバックテスト分析ツールが機械的に検索・集計するための識別子。
- **`reason_code`命名規則**：`{軸プレフィックス}_{指標}_{状態}`の形式に統一する。軸プレフィックスは`TECH`（テクニカル）／`FUND`（ファンダメンタル）／`SUPD`（需給）／`MACRO`／`NEWS`／`REGIME`の6種。以下の各表に`reason_code`列として定義する。

---

## 3. 指標別スコア算出式（バケット表）

### 3-1. テクニカル軸

**RSI(14)** — 高いほど良いわけではなく、健全な上昇トレンド帯を最高点とする設計

| RSI範囲 | スコア | reason_code | 意味 |
|---|---|---|---|
| 〜20未満 | 40 | `TECH_RSI_DEEP_OVERSOLD` | 深い売られすぎ。反発期待はあるが下落継続リスクも高い |
| 20〜30未満 | 60 | `TECH_RSI_OVERSOLD` | 売られすぎ、反発期待 |
| 30〜45未満 | 75 | `TECH_RSI_PULLBACK` | 調整局面、押し目買いゾーン |
| 45〜60未満 | 90 | `TECH_RSI_HEALTHY` | 健全な上昇トレンド（最高スコア） |
| 60〜70未満 | 70 | `TECH_RSI_WARM` | やや過熱 |
| 70〜80未満 | 45 | `TECH_RSI_OVERBOUGHT` | 過熱、反落リスク |
| 80以上 | 25 | `TECH_RSI_EXTREME_OVERBOUGHT` | 極度の過熱 |

**MACD**（MACD線・シグナル線・ヒストグラムの関係で判定）

| 状態 | スコア | reason_code |
|---|---|---|
| ゴールデンクロス直後（ヒストグラムが負→正に転換） | 90 | `TECH_MACD_GOLDEN_CROSS` |
| MACD>Signalかつヒストグラム拡大中 | 85 | `TECH_MACD_BULLISH_EXPANDING` |
| MACD>Signalだがヒストグラム縮小中 | 60 | `TECH_MACD_BULLISH_FADING` |
| MACD<Signalだがヒストグラム縮小中（下落モメンタム減速） | 55 | `TECH_MACD_BEARISH_FADING` |
| デッドクロス直後 | 20 | `TECH_MACD_DEAD_CROSS` |
| MACD<Signalかつヒストグラム拡大中（下落加速） | 15 | `TECH_MACD_BEARISH_EXPANDING` |

**MA（5/25/75/200の並び）**

| 状態 | スコア | reason_code |
|---|---|---|
| パーフェクトオーダー上昇（5>25>75>200、株価が5MA上） | 95 | `TECH_MA_PERFECT_ORDER_UP` |
| 概ね上昇配列（一部逆転あり） | 75 | `TECH_MA_MOSTLY_UP` |
| もみ合い（MA収束・交錯） | 50 | `TECH_MA_CONVERGING` |
| 概ね下降配列 | 30 | `TECH_MA_MOSTLY_DOWN` |
| パーフェクトオーダー下降（5<25<75<200） | 10 | `TECH_MA_PERFECT_ORDER_DOWN` |

**ADX(14)**（トレンドの「強さ」。方向はMAで判断）

| ADX範囲 | スコア | reason_code |
|---|---|---|
| 〜20未満 | 40 | `TECH_ADX_NO_TREND` |
| 20〜25未満 | 55 | `TECH_ADX_WEAK_TREND` |
| 25〜40未満 | 80 | `TECH_ADX_STRONG_TREND` |
| 40以上 | 65 | `TECH_ADX_OVERHEATED_TREND` |

**ATR(14)**（直近20日平均ATRとの比で評価。ボラティリティの急拡大は減点）

| 直近ATR ÷ 20日平均ATR | スコア | reason_code |
|---|---|---|
| 1.5倍超 | 40 | `TECH_ATR_SPIKE` |
| 1.0〜1.5倍 | 65 | `TECH_ATR_ELEVATED` |
| 0.7〜1.0倍 | 85 | `TECH_ATR_NORMAL` |
| 0.7倍未満 | 60 | `TECH_ATR_COMPRESSED` |

**ボリンジャーバンド**（±2σに対する株価位置）

| 位置 | スコア | reason_code |
|---|---|---|
| -2σ超え下抜け | 35 | `TECH_BB_BREAK_LOWER` |
| -2σ〜-1σ | 75 | `TECH_BB_LOWER_ZONE` |
| -1σ〜+1σ | 65 | `TECH_BB_MID_ZONE` |
| +1σ〜+2σ | 80 | `TECH_BB_UPPER_ZONE` |
| +2σ超（バンドウォーク） | 55 | `TECH_BB_WALK_UPPER` |

**VWAP**

| 状態 | スコア | reason_code |
|---|---|---|
| 株価>VWAPで乖離拡大中 | 80 | `TECH_VWAP_ABOVE_EXPANDING` |
| 株価≈VWAP | 60 | `TECH_VWAP_NEUTRAL` |
| 株価<VWAP | 35 | `TECH_VWAP_BELOW` |

**52週高値・安値**

| 状態 | スコア | reason_code |
|---|---|---|
| 52週高値更新中 | 85 | `TECH_52W_NEW_HIGH` |
| 高値から-5%以内 | 75 | `TECH_52W_NEAR_HIGH` |
| 高値から-5〜-20% | 60 | `TECH_52W_MID_RANGE_FROM_HIGH` |
| 安値から+20%以内 | 50 | `TECH_52W_NEAR_LOW` |
| 52週安値更新中 | 20 | `TECH_52W_NEW_LOW` |

### 3-2. ファンダメンタル軸

**PER**（初期実装は絶対レンジ方式。将来的に業種内偏差値化を検討、`PERScorer`はStrategyパターン）

| PER | スコア | reason_code |
|---|---|---|
| 〜10未満 | 85 | `FUND_PER_CHEAP` |
| 10〜15未満 | 80 | `FUND_PER_LOW` |
| 15〜20未満 | 70 | `FUND_PER_MODERATE` |
| 20〜30未満 | 55 | `FUND_PER_ELEVATED` |
| 30〜50未満 | 40 | `FUND_PER_HIGH` |
| 50以上／赤字で算出不能 | 20 | `FUND_PER_EXTREME_OR_NA` |

**PBR**

| PBR | スコア | reason_code |
|---|---|---|
| 〜1.0未満 | 85 | `FUND_PBR_BELOW_BOOK` |
| 1.0〜1.5未満 | 75 | `FUND_PBR_LOW` |
| 1.5〜2.5未満 | 60 | `FUND_PBR_MODERATE` |
| 2.5〜4.0未満 | 45 | `FUND_PBR_HIGH` |
| 4.0以上 | 30 | `FUND_PBR_EXTREME` |

**ROE**

| ROE | スコア | reason_code |
|---|---|---|
| 15%以上 | 90 | `FUND_ROE_EXCELLENT` |
| 10〜15%未満 | 75 | `FUND_ROE_GOOD` |
| 5〜10%未満 | 55 | `FUND_ROE_MODERATE` |
| 0〜5%未満 | 35 | `FUND_ROE_WEAK` |
| マイナス | 15 | `FUND_ROE_NEGATIVE` |

**ROA**

| ROA | スコア | reason_code |
|---|---|---|
| 8%以上 | 85 | `FUND_ROA_EXCELLENT` |
| 5〜8%未満 | 70 | `FUND_ROA_GOOD` |
| 2〜5%未満 | 50 | `FUND_ROA_MODERATE` |
| 0〜2%未満 | 35 | `FUND_ROA_WEAK` |
| マイナス | 15 | `FUND_ROA_NEGATIVE` |

**EPS成長率（前年同期比）**

| 成長率 | スコア | reason_code |
|---|---|---|
| 30%以上 | 95 | `FUND_EPS_GROWTH_HIGH` |
| 15〜30%未満 | 80 | `FUND_EPS_GROWTH_GOOD` |
| 5〜15%未満 | 65 | `FUND_EPS_GROWTH_MODERATE` |
| 0〜5%未満 | 50 | `FUND_EPS_GROWTH_FLAT` |
| マイナス | 25 | `FUND_EPS_GROWTH_NEGATIVE` |

**売上成長率**

| 成長率 | スコア | reason_code |
|---|---|---|
| 20%以上 | 90 | `FUND_SALES_GROWTH_HIGH` |
| 10〜20%未満 | 75 | `FUND_SALES_GROWTH_GOOD` |
| 3〜10%未満 | 60 | `FUND_SALES_GROWTH_MODERATE` |
| 0〜3%未満 | 45 | `FUND_SALES_GROWTH_FLAT` |
| マイナス | 25 | `FUND_SALES_GROWTH_NEGATIVE` |

**営業利益率**

| 利益率 | スコア | reason_code |
|---|---|---|
| 20%以上 | 90 | `FUND_OPM_EXCELLENT` |
| 10〜20%未満 | 75 | `FUND_OPM_GOOD` |
| 5〜10%未満 | 55 | `FUND_OPM_MODERATE` |
| 0〜5%未満 | 35 | `FUND_OPM_WEAK` |
| マイナス | 15 | `FUND_OPM_NEGATIVE` |

**営業CF・FCF水準**

| 状態 | スコア | reason_code |
|---|---|---|
| FCFプラスかつ前期比増加 | 85 | `FUND_FCF_POSITIVE_GROWING` |
| FCFプラスだが前期比減少 | 65 | `FUND_FCF_POSITIVE_SHRINKING` |
| FCFマイナスだが営業CFはプラス（投資先行） | 50 | `FUND_FCF_NEGATIVE_INVESTING` |
| 営業CFもマイナス | 20 | `FUND_OCF_NEGATIVE` |

**FCF成長率**（取得可能な場合のみ。取得不可時は欠損として按分）

| 成長率 | スコア | reason_code |
|---|---|---|
| 20%以上 | 90 | `FUND_FCF_GROWTH_HIGH` |
| 10〜20%未満 | 75 | `FUND_FCF_GROWTH_GOOD` |
| 0〜10%未満 | 60 | `FUND_FCF_GROWTH_MODERATE` |
| マイナス | 30 | `FUND_FCF_GROWTH_NEGATIVE` |

**自己資本比率**

| 比率 | スコア | reason_code |
|---|---|---|
| 60%以上 | 85 | `FUND_EQUITY_RATIO_STRONG` |
| 40〜60%未満 | 70 | `FUND_EQUITY_RATIO_GOOD` |
| 20〜40%未満 | 50 | `FUND_EQUITY_RATIO_MODERATE` |
| 20%未満 | 30 | `FUND_EQUITY_RATIO_WEAK` |

**配当利回り順位**（`screener.py`が確定した母集団内パーセンタイル）

| 順位 | スコア | reason_code |
|---|---|---|
| 上位10%以内 | 90 | `FUND_DIV_YIELD_TOP10` |
| 上位10〜30% | 75 | `FUND_DIV_YIELD_TOP30` |
| 中位30〜70% | 55 | `FUND_DIV_YIELD_MID` |
| 下位30% | 40 | `FUND_DIV_YIELD_BOTTOM30` |
| 無配 | 30 | `FUND_DIV_YIELD_NONE` |

### 3-3. 需給軸

**出来高急増率（当日出来高 ÷ 過去20日平均出来高）**

| 倍率 | スコア | reason_code |
|---|---|---|
| 3倍以上 | 90 | `SUPD_VOL_SURGE_EXTREME` |
| 2〜3倍 | 80 | `SUPD_VOL_SURGE_HIGH` |
| 1.5〜2倍 | 65 | `SUPD_VOL_SURGE_MODERATE` |
| 0.8〜1.5倍 | 55 | `SUPD_VOL_SURGE_NORMAL` |
| 0.8倍未満 | 40 | `SUPD_VOL_SURGE_LOW` |

**出来高移動平均乖離率（5日平均 ÷ 25日平均）**

| 乖離 | スコア | reason_code |
|---|---|---|
| +50%以上 | 85 | `SUPD_VOL_MA_DEV_HIGH` |
| +20〜+50% | 70 | `SUPD_VOL_MA_DEV_MODERATE` |
| -20〜+20% | 55 | `SUPD_VOL_MA_DEV_NEUTRAL` |
| -20%以下 | 40 | `SUPD_VOL_MA_DEV_LOW` |

**信用倍率（信用買い残 ÷ 信用売り残。J-Quants Standard以上のみ取得可、Freeでは欠損）**

| 倍率 | スコア | reason_code |
|---|---|---|
| 1倍未満 | 80 | `SUPD_MARGIN_RATIO_SHORT_HEAVY` |
| 1〜3倍 | 60 | `SUPD_MARGIN_RATIO_NEUTRAL` |
| 3〜6倍 | 40 | `SUPD_MARGIN_RATIO_LONG_HEAVY` |
| 6倍超 | 25 | `SUPD_MARGIN_RATIO_EXTREME_LONG` |

### 3-4. マクロ軸（銘柄非依存、当日1回算出）

| 指標 | 判定基準 | スコア例 | reason_code例 |
|---|---|---|---|
| 米10年国債利回り | 低下／横ばい／上昇 | 80／60／35 | `MACRO_US10Y_FALLING`／`MACRO_US10Y_FLAT`／`MACRO_US10Y_RISING` |
| FF金利 | 利下げ優勢／据え置き優勢／利上げ優勢 | 80／60／30 | `MACRO_FFR_CUT_EXPECTED`／`MACRO_FFR_HOLD_EXPECTED`／`MACRO_FFR_HIKE_EXPECTED` |
| 失業率 | 改善／横ばい／悪化 | 70／60／40 | `MACRO_UNRATE_IMPROVING`／`MACRO_UNRATE_FLAT`／`MACRO_UNRATE_WORSENING` |
| CPI/PPI | 鈍化／予想通り／加速 | 80／60／30 | `MACRO_INFLATION_DECELERATING`／`MACRO_INFLATION_INLINE`／`MACRO_INFLATION_ACCELERATING` |
| GDP | 上回る／並み／下回る | 80／60／30 | `MACRO_GDP_BEAT`／`MACRO_GDP_INLINE`／`MACRO_GDP_MISS` |
| 景気先行指数 | 上昇／横ばい／低下 | 75／55／35 | `MACRO_LEI_RISING`／`MACRO_LEI_FLAT`／`MACRO_LEI_FALLING` |

マクロ軸スコア＝上記6指標の配点加重平均（§1のmacro配点表参照）。

### 3-5. ニュース軸（score／uncertaintyの分離出力）

対象銘柄・対象業種に関連する当日のニュース項目それぞれについて、以下の式で個別記事の寄与度を算出する。

```
記事の寄与度 = 重要度(0-100) × 信頼度(0-1) × 方向性係数 × 時間減衰係数
方向性係数: positive=+1, neutral=0, negative=-1
```

**時間減衰係数**：`config/news_decay.yaml`（新設、Layer3が付与する`age_hours`を用いてLayer2側で適用）で管理する。ハードコードせず、将来の運用変更をconfig変更のみで反映できるようにする。

```yaml
# config/news_decay.yaml（初期値）
decay_curve:
  - { within_hours: 24, factor: 1.0, reason_code: "NEWS_DECAY_FRESH" }
  - { within_hours: 72, factor: 0.8, reason_code: "NEWS_DECAY_RECENT" }
  - { within_hours: 168, factor: 0.6, reason_code: "NEWS_DECAY_WEEK_OLD" }
  - { within_hours: 336, factor: 0.3, reason_code: "NEWS_DECAY_TWO_WEEKS_OLD" }
  - { within_hours: null, factor: 0.1, reason_code: "NEWS_DECAY_STALE" }
```

**`score`（中心傾向）と`uncertainty`（評価の割れ具合）の算出（重要・変更点）**：

```
positive_mass = Σ(寄与度 > 0 の記事の寄与度)
negative_mass = Σ(|寄与度| : 寄与度 < 0 の記事)
total_mass = positive_mass + negative_mass

score = 50 + normalize(positive_mass - negative_mass)   # 0-100にクリップ
uncertainty = total_mass > 0 ? 100 × 2 × min(positive_mass, negative_mass) / total_mass : 0

該当記事が無い場合: score=50（中立）、uncertainty=0 固定
```

**設計上の理由**：
1. **時間減衰**：ニュースは時間経過とともに市場への織り込みが進み価値が減衰するため、`age_hours`（Layer3が事実として付与）をもとにLayer2側でこの減衰率という「評価ポリシー」を適用する。データの事実と評価の分離により、減衰カーブの調整もconfig変更のみで完結する。
2. **score/uncertaintyの分離**：単純平均だけだと、強いポジティブ記事と強いネガティブ記事が同時にある場合に相殺され「中立」と誤認されてしまう（実際には重大なニュースが複数存在する状態）。`uncertainty`を別出力することで、全記事が同方向（相殺なし）ならuncertainty=0、ポジティブ・ネガティブが拮抗していればuncertainty=100に近づく。Layer5はこの`uncertainty`が高い場合、投資判断の自然文説明や信頼度（confidence）の記述に「評価が割れている」旨を反映できる。`uncertainty`は総合スコアの計算式には組み込まない（あくまでLLMの定性判断のための追加シグナル）。
3. `reason_code`：各記事の寄与にはLayer3が付与した`category`をベースにした`NEWS_{CATEGORY}`形式のコードを付与する（例：`NEWS_EARNINGS`、`NEWS_PRODUCT`、`NEWS_GEOPOLITICAL`、`NEWS_SEMICONDUCTOR`）。

正規化方法（`normalize`）：寄与度合計を記事件数・母数で調整しつつ、極端な値に張り付かないよう`tanh`等の飽和関数でクリップする（実装詳細はPhase実装時に確定）。

### 3-6. 市場レジーム軸（ルールベース判定）

**レジーム判定自体**（銘柄非依存）：

| 条件 | 判定 | reason_code |
|---|---|---|
| 指数が200日線より上、かつADX(14)≧25で上向き | 上昇相場 | `REGIME_UPTREND` |
| 指数が200日線より下、かつADX(14)≧25で下向き | 下降相場 | `REGIME_DOWNTREND` |
| 上記いずれにも該当しない | レンジ相場 | `REGIME_RANGE` |

**個別銘柄のレジーム適合スコア**：

| レジーム | 銘柄スタイルタグ | スコア | reason_code |
|---|---|---|---|
| 上昇相場 | グロース／半導体／AI関連 | 90 | `REGIME_FIT_UPTREND_GROWTH` |
| 上昇相場 | ディフェンシブ／高配当／債券 | 40 | `REGIME_FIT_UPTREND_DEFENSIVE_MISMATCH` |
| 下降相場 | ディフェンシブ／高配当／債券ETF | 90 | `REGIME_FIT_DOWNTREND_DEFENSIVE` |
| 下降相場 | グロース／半導体 | 30 | `REGIME_FIT_DOWNTREND_GROWTH_MISMATCH` |
| レンジ相場 | （スタイル問わず） | 60 | `REGIME_FIT_RANGE_NEUTRAL` |

---

## 4. 欠損時の重み再配分ルール（共通仕様）

1. あるサブ指標が取得不可（欠損）の場合、そのサブ指標の配点を0点として扱うのではなく、**同一軸内の他の取得済みサブ指標へ、元の配点比率を保ったまま比例配分する**。
   - 例：需給軸で信用倍率（配点20）が欠損した場合、残る出来高急増率（45）・出来高移動平均乖離率（35）の比率（45:35）を保ったまま、20点を按分する（出来高急増率に約11.25点追加→56.25、出来高移動平均乖離率に約8.75点追加→43.75）。
2. 軸全体が完全に欠損する場合（例：ニュースが1件も無い）は、その軸はデフォルト中立スコア（50点）を採用し、`axis_score_reason`と`reason_code`（例：`{AXIS}_NO_DATA_NEUTRAL`）に「データなしのため中立扱い」と明記する。
3. 再配分が発生した場合は必ず`reason`／`reason_code`（例：`{指標}_REALLOCATED`）にその旨（どの指標が欠損し、どう按分したか）を記録し、Layer5・人間レビューの双方が後から検証できるようにする（Ver2「スコアの完全可視化」要件）。

---

## 5. 総合スコアの算出

```
総合スコア = Σ( 軸スコア[i] × 軸配点[i] / 100 )   for i in {technical, fundamental, supply_demand, macro, news, regime}
```

軸配点は`config/scoring_weights.yaml`の`axis_weights`に従う（初期値は§1参照）。ニュース軸は`score`フィールド（`uncertainty`は含めない）を用いる。この計算は`scorer.py`が実行し、LLM（Layer5）には計算済みの総合スコアと内訳のみが渡される。LLMは総合スコアを再計算せず、その根拠を自然文で説明する役割に徹する。

**バージョンの付与**：この計算結果には必ず、計算時点の`scoring_version`／`weight_version`（本書冒頭参照）が`score_meta`として付与される（Layer2詳細設計書§5参照）。将来これらの版が変わった場合、異なる版のスコアを単純比較しないことをバックテスト・自己評価ロジック（Ver2で前倒しした基盤）側でも徹底する。
