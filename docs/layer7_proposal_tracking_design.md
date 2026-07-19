# 提案トラッキング層（Layer7）詳細設計書

作成日: 2026-07-18（Ver1.4：実装者レビューへの回答により、完了フラグの同日再実行ルール・自動判定とmanual_closeの競合優先順位・多重起動に関する前提を新設。Ver1.3：全体設計書レビューへの回答により、Layer8との実行タイミング調整として完了フラグファイル（layer7_completed_YYYYMMDD.json）を新設。Ver1.2：tracking_idをTRK-{run_id}-{ticker}形式に変更、closed_positionsを月次分割に変更）
前提: Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Layer3詳細設計書（確定版・Ver1.3）／Layer4詳細設計書（確定版・Ver1.1）／Layer5詳細設計書（確定版・Ver1.3）／Layer6詳細設計書（確定版・Ver1.1）と整合。**Layer1〜6はすべて確定済みであり、本書はそれらの責務・入出力契約・JSONスキーマ・フォルダ構成を一切変更しない。Layer7のみを設計対象とする。**

---

## 1. Layer7の位置付け

```
Layer1  データ取得（Python Pipeline／GitHub Actions）
Layer2  分析・スコアリング（同上）
Layer3  ニュース構造化（同上）
Layer4  永続化（同上）
Layer5  AI総合判断（Claude Coworkセッション、decision JSON生成）
Layer6  レポート生成（決定的処理、Google Sheets・Markdown保存）
Layer7  提案トラッキング（今回設計、決定的処理）
Layer8  自己評価（Ver2で設計予定）
Layer9  運用成績ダッシュボード（Ver2で設計予定）
```

**Layer7の実行モデル**：Layer7はAI判断を一切行わない**純粋な決定的Python処理**である。Layer5（AIエージェント）・Layer6（Layer5と同一セッション継続）とは異なり、Layer7は「保有中ポジションの価格を定期的に確認する」という、Layer5/Layer6の実行タイミングとは独立した性質の処理であるため、**Layer1〜4と同様、GitHub Actions上で独自のスケジュール（例：毎営業日の取引終了後）により実行する独立したPythonパイプライン**として設計する。Layer5のセッションが起動していない日でも、Layer7は保有中ポジションの価格確認のために単独で動作できる。

---

## 2. 責務・非責務

**責務**：
- Layer6が保存した提案履歴（Google Sheets「本日の提案」シート）の読み込み
- 保有中提案（アクティブポジション）の管理
- 定期的な市場価格の取得（アクティブポジションのみ対象）
- 利確・損切判定
- 保有終了判定（期間満了・手動終了含む）
- 実績記録（エントリー価格・決済価格・保有日数・最大含み益/損・最終損益率等）
- トラッキング履歴の保存
- Layer8（自己評価層）へ渡す評価データの生成

**非責務**：
- AI判断（買い/売り/様子見の決定はLayer5の責務。Layer7は決定を行わない）
- 銘柄選定（Layer2／Layer5の責務）
- スコア再計算（Layer2の責務）
- ランキング変更（Layer2／Layer5の責務）
- 提案内容の変更（銘柄・株数・損切/利確価格・保有期間等、Layer5が確定した値をLayer7が書き換えることは一切ない）
- Layer6成果物（Google Sheets・Markdownファイル）の書き換え：Layer7はLayer6のGoogle Sheetsを**読み取り専用**で参照するのみで、一切書き込まない
- Layer5のdecision JSONを直接参照すること：Layer7が参照するのはLayer6が生成したGoogle Sheetsのみであり、Layer5の出力JSON（Layer5詳細設計書§9）に直接アクセスすることはない

---

## 3. モジュール構成

```
src/tracking/
├── proposal_ingester.py        # Layer6 Google Sheets「本日の提案」シートから新規追跡対象を取り込む（読取専用）
├── price_checker.py            # アクティブポジションの現在価格取得（PriceCheckRepository経由）
├── holding_period_parser.py    # 「想定保有期間」文字列（例：「2〜4週間」）を日数へ変換（§8-2）
├── exit_evaluator.py           # 利確／損切／保有期間終了の判定ロジック（§8）
├── manual_close_processor.py   # manual_close_requests.json の読込・処理・削除（§8-4）
├── position_store.py           # active_positions.json / closed_positions_YYYYMM.json の読み書き
├── tracking_history_writer.py  # tracking_history_YYYYMM.json への追記
├── layer8_export_builder.py    # Layer8へ渡す評価データの生成（§13）
├── completion_flag_writer.py   # 【新設・Ver1.3】layer7_completed_YYYYMMDD.json の生成（全保存成功後の最終ステップ、§4・§6-5）
├── repository/
│   ├── base.py                   # PriceCheckRepository 抽象クラス（Layer7専用の新規コンポーネント）
│   └── price_check_repository_impl.py  # 具体実装（§7-3。Layer1の既存クライアントコードを再利用してもよいが、Layer1のクラス・契約自体は変更しない）
└── main.py                      # Layer7パイプラインのエントリポイント
```

---

## 4. 実行フロー

1. Layer7が独自スケジュールで起動する（Layer5/Layer6の実行とは非同期。例：毎営業日の取引終了後）。
2. `proposal_ingester.py`が、Layer6が保存した当日の`提案ログ_YYYYMMDD`（Google Sheets、「本日の提案」シート）を読み込む。既に`active_positions.json`に登録済みの`run_id`＋`ticker`の組み合わせはスキップし（重複取り込み防止）、未登録の行のみ新規のアクティブポジションとして追加する。**読み込んだ値（購入価格目安・損切価格・利確価格・想定保有期間・推奨株数等）は一切変更せずそのまま転記する**（§6-2）。
3. `position_store.py`が現在の`active_positions.json`（追跡中の全ポジション）を読み込む。
4. `price_checker.py`が、追跡中の全ポジションについて`PriceCheckRepository`経由で当日の市場価格（終値・高値・安値・出来高）を取得する（§7）。
5. `exit_evaluator.py`が、各ポジションについて§8の判定ルールを適用し、ステータス（`active`／`take_profit`／`stop_loss`／`holding_period_expired`）を決定する。
6. `manual_close_processor.py`が`manual_close_requests.json`を読み込み、記載された`tracking_id`があれば`manual_close`として処理する（§8-4）。手順5の自動判定と競合する場合は`manual_close`を優先する（§8-5、新設）。処理済みのリクエストはキューから削除する。
7. ステータスが`active`以外になったポジション（5・6のいずれか）は`active_positions.json`から除外し、実績情報とともに`closed_positions_YYYYMM.json`へ記録する。
8. `tracking_history_writer.py`が、当日時点の全ポジション（アクティブ・クローズ済み双方）のスナップショットを`tracking_history_YYYYMM.json`に追記する。
9. `layer8_export_builder.py`が、当日新たにクローズしたポジションについて、Layer8向けの評価データ（§13）を生成・保存する。
10. **（新設・Ver1.3）手順2〜9が全て成功した場合のみ**、`completion_flag_writer.py`が`tracking/layer7_completed_YYYYMMDD.json`を`completed: true`で生成・書き込む（§6-5参照。Layer4の完了フラグ書き込み原則（Layer4詳細設計書§3手順7・§6-2）と同じ思想を、Layer7→Layer8間のタイミング調整にも適用する）。手順2〜9のいずれかで失敗した場合、完了フラグは`completed: true`では書き込まれない（Google Drive自体への書き込みは可能であれば`completed: false`と失敗理由を記録し、Drive自体に書き込めない場合はフラグファイル自体が存在しない状態になる。Layer4詳細設計書§9のエラー処理と同じ考え方）。
11. 完了。

---

## 5. Layer6との入力契約

### 5-1. 利用してよい入力（確定・厳守）

Layer7が利用できる入力は以下のみとする。

- **Layer6 Google Sheets「本日の提案」シート**：最低限、以下の列を利用する。
  - `run_id`
  - `日付`
  - `証券コード`
  - `銘柄名`
  - `購入価格目安`
  - `損切価格`
  - `利確価格`
  - `想定保有期間`
  - `推奨株数`

  （Layer6詳細設計書§6-3で確定済みの列構成に、これらすべてが含まれることを確認済み。Layer6側の追加修正は不要。）

- **市場価格データ（Layer7が独自取得）**：追跡中ティッカーの当日終値・高値・安値・出来高のみ。取得方法は完全に抽象化し（§7）、特定のAPI実装に依存しない。

### 5-2. 利用してはいけない入力（確定・厳守）

- **Layer6 Markdownレポート**：人間閲覧用のみであり、Layer7は一切解析対象としない（自然文からの情報抽出は行わない）。
- **Layer5のdecision JSON**：Layer7は直接参照しない。Layer6を経由して整形済みの列データのみを利用する。
- **Layer6「除外・不採用ログ」シート**：追跡対象は採用された提案のみであるため、このシートはLayer7の対象外。
- **`取引記録_*.csv`**：ユーザー自身の手動取引台帳であり、Layer5が直接読む設計（Layer5詳細設計書§4-2）。Layer7はこれを読まない（§9の「手動終了」は別の仕組みで扱う。§8-4参照）。
- **Layer1〜4の出力（`market_snapshot`等）**：Layer7は一切アクセスしない。

---

## 6. 保存仕様

### 6-1. 保存先ディレクトリ

Ver2で計画されていた`tracking/`フォルダをそのまま採用する。

```
AI投資アシスタント/
└── tracking/                          【新設・Layer7管理】
    ├── active_positions.json
    ├── closed_positions_YYYYMM.json
    ├── tracking_history_YYYYMM.json
    ├── manual_close_requests.json     # 手動終了のリクエストキュー（§8-4）
    └── layer7_completed_YYYYMMDD.json # 【新設・Ver1.3】Layer8との完了フラグ（§6-5）
```

### 6-2. `active_positions.json`

```json
{
  "positions": [
    {
      "tracking_id": "TRK-20260718-0630-NVDA",
      "run_id": "20260718-0630",
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "entry_date": "2026-07-18",
      "entry_price": 333.74,
      "stop_loss_price": 300.37,
      "take_profit_price": 383.80,
      "holding_period_raw": "2〜4週間",
      "holding_period_days_parsed": 28,
      "recommended_shares": 4,
      "status": "active",
      "latest_price": { "date": "2026-07-18", "close": 333.74, "high": 335.00, "low": 330.20, "volume": 42000000 },
      "max_unrealized_gain_pct": 0.0,
      "max_unrealized_loss_pct": 0.0,
      "last_checked_at": "2026-07-18T21:05:00Z"
    }
  ]
}
```

- **`tracking_id`（修正・確定）**：`TRK-{run_id}-{ticker}`の形式で生成する（UUIDは採用しない）。`run_id`はLayer5詳細設計書§9で定義される実行ID（`YYYYMMDD-HHMMSS`まで保持する前提。1回のLayer5実行につき一意）をそのまま用いる。この形式により、人間が見て「いつの実行で・どの銘柄が」追跡対象になったかを一目で判読できると同時に、`run_id`が実行単位で一意であることに依拠して`tracking_id`の一意性を確保する（同一`run_id`内で同一`ticker`が複数回提案されることはLayer5の設計上発生しないため、衝突は起こらない）。
  - **前提の確認事項**：本設計は`run_id`が秒単位までの十分な粒度を持ち、同日中の複数回実行同士が一意に区別できることを前提とする。Layer5詳細設計書§9の`run_id`例（`"20260718-0630"`）は分単位表記であり、本書が前提とする秒単位（`HHMMSS`）表記と厳密には一致していない可能性があるため、実装時にLayer5側の`run_id`の実際の粒度を確認し、本書の前提と合致することを確認されたい（Layer5の仕様自体を変更するものではなく、既存の`run_id`値をそのまま利用する前提の確認である。§15参照）。
- `holding_period_raw`／`holding_period_days_parsed`：Layer5が出力した原文の文字列と、Layer7が解析した日数の両方を保持する（§8-2で解析ロジックを規定。Layer6・Layer5の値そのものは変更しない）。
- **`latest_price`（修正・重要）**：直近1回分の価格スナップショットのみを保持し、日次の全履歴（`price_history`配列）は`active_positions.json`には持たせない。理由：全銘柄・全期間の日次価格を`active_positions.json`に蓄積し続けると、想定運用規模（例：数百銘柄×数年）でファイルが肥大化し、読み書きの負荷・破損リスクが増大するため。**日次の時系列データは既存の`tracking_history_YYYYMM.json`（§6-4、月次分割済み）に一元化**し、`active_positions.json`は「現在のポジション状態のスナップショット」のみを保持する薄いファイルとする。これにより`active_positions.json`は追跡件数に比例するのみで、期間の長さに比例して肥大化しない（常に数十KB〜数百KB程度に収まる想定）。
- `max_unrealized_gain_pct`／`max_unrealized_loss_pct`：過去の`price_history`を遡って再計算するのではなく、**日次チェックのたびに「これまでの最大値」を逐次更新する**（当日の高値による含み益率がこれまでの`max_unrealized_gain_pct`を上回れば更新、当日の安値による含み損率がこれまでの`max_unrealized_loss_pct`を下回れば更新）。過去の価格履歴を保持しなくても、この2つの値を実行のたびに更新するだけで、日次履歴を遡らずに正しい最大値を維持できる。

### 6-3. `closed_positions_YYYYMM.json`（修正・月次分割）

**当初`closed_positions.json`という単一ファイルで設計していたが、月次分割方式（`closed_positions_YYYYMM.json`）へ変更する。** 理由：単一ファイルのまま長期運用すると、クローズ済みポジションが際限なく蓄積し続け（Layer7が長期間稼働するほど肥大化する）、`active_positions.json`と同様の肥大化・読み書き負荷の問題が生じるため。Layer4の`history/index_YYYYMM.json`・Layer6の`reports/report_index_YYYYMM.json`と同じ月次分割の方針に統一することで、ファイルサイズを一定範囲に抑えつつ、既存レイヤーとの設計の一貫性も確保する。ファイルは決済日（`exit_date`）の年月に基づいて振り分ける。

```json
{
  "positions": [
    {
      "tracking_id": "TRK-20260718-0630-NVDA",
      "run_id": "20260718-0630",
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "entry_date": "2026-07-18",
      "entry_price": 333.74,
      "exit_date": "2026-08-05",
      "exit_price": 383.80,
      "exit_reason": "take_profit",
      "holding_days": 18,
      "max_unrealized_gain_pct": 16.2,
      "max_unrealized_loss_pct": -1.1,
      "final_return_pct": 15.0,
      "recommended_shares": 4,
      "closed_at": "2026-08-05T21:05:00Z"
    }
  ]
}
```

### 6-4. `tracking_history_YYYYMM.json`

月次ファイルに分割し肥大化を防ぐ（Layer4の`history/index_YYYYMM.json`・Layer6の`reports/report_index_YYYYMM.json`と同じ月次分割方針を踏襲）。

```json
{
  "entries": [
    {
      "date": "2026-07-18",
      "tracking_id": "TRK-20260718-0630-NVDA",
      "status": "active",
      "close": 333.74,
      "unrealized_return_pct": 0.0
    }
  ]
}
```

### 6-5. `layer7_completed_YYYYMMDD.json`（完了フラグ、新設・Ver1.3、Layer8との契約の核）

全体設計書（`docs/00_SystemArchitecture.md`）のレビューで指摘された「Layer4→Layer5間の完了フラグ方式が、Layer7→Layer8間には無い」という改善提案への対応として新設する。Layer4詳細設計書§5-2の`layer4_completed_YYYYMMDD.json`と同じ設計思想（固定時刻オフセットに頼らず、完了そのものを確認する）を採用する。

```json
{
  "completed": true,
  "completed_at": "2026-07-18T21:10:00Z",
  "run_date": "2026-07-18"
}
```

失敗時（Google Drive自体への書き込みは可能な場合）：

```json
{
  "completed": false,
  "completed_at": "2026-07-18T21:12:00Z",
  "run_date": "2026-07-18",
  "failure_reason_code": "PRICE_FETCH_FAILED"
}
```

- `completed_at`は`completion_flag_writer.py`が実行された時刻（UTC）。
- `run_date`はLayer7が処理対象とした当日日付（JST基準、他レイヤーの日付基準と統一）。
- Layer8はこのファイルの存在確認・`completed:true`確認を行ってから評価処理を開始する（Layer8詳細設計書§4-3参照。Layer8側の変更内容であり、本書側の変更はフラグの生成のみ）。

**同日再実行時の扱い（新設・確定、実装者レビューへの回答）**：Layer4の`layer4_completed_YYYYMMDD.json`が「その日の最終確定状態を表し、再実行時は常に最新の完了フラグが正となる」（Layer4詳細設計書§7-1）のと同じ考え方を、本フラグにも適用する。ファイル名に時刻要素を持たないため、同日にLayer7が複数回実行された場合（失敗後の再実行等）、Google Drive上に同名ファイルが複数存在し得る。この場合、**`createdTime`が最も新しいものを正とする**（Google Driveの`search_files`で`createdTime`降順に取得し先頭を採用する。Layer6詳細設計書§6-6の「最新判定表示」と同一の考え方を踏襲する）。Layer8がこのファイルを参照する際も同じ規則に従う（Layer8詳細設計書§4-3参照）。

### 6-6. 同時実行に関する前提（新設・確定、実装者レビューへの回答）

本層が管理する`active_positions.json`・`closed_positions_YYYYMM.json`・`tracking_history_YYYYMM.json`・`manual_close_requests.json`・`layer7_completed_YYYYMMDD.json`はいずれも「読み込み→更新→書き戻し」方式（read-modify-write）で更新される。したがって、**同一実行単位（1回のLayer7ジョブ）が重複して同時に起動しないこと**を前提とする。重複起動の防止自体は本層の実装詳細ではなく、GitHub Actions側の排他制御（`concurrency`設定等）による運用面の担保とし、全体設計書§11-6を参照する。本書側の変更はこの前提を明記したのみであり、保存仕様・判定ロジックには変更を加えていない。

---

## 7. トラッキング仕様（価格取得の抽象化）

### 7-1. `PriceCheckRepository`抽象クラス

Layer1のRepositoryパターンと同じ設計原則を、**Layer7が独立して保持する新規コンポーネント**として適用する（Layer1の`RepositoryFactory`やLayer1が定義した具体クラスそのものを変更するのではなく、Layer7専用の抽象化を新設する）。

- `PriceCheckRepository.get_latest_price(ticker, asset_class) -> PriceSnapshot { date, close, high, low, volume }`

この1メソッドのみを定義し、Layer7の他モジュール（`exit_evaluator.py`等）はこのインターフェースにのみ依存する。

### 7-2. 具体実装の位置付け

現行の具体実装（`price_check_repository_impl.py`）が、内部でどのAPI（J-Quants／Alpha Vantage／Twelve Data等）を呼び出すかはLayer7の実装詳細であり、**Layer1が既に構築したデータ取得クライアント（Layer1詳細設計書§3の`JQuantsRepository`等）をコードとして再利用することは妨げない**。ただし、これはLayer1のクラス・設定・契約を変更するものではなく、あくまでLayer7側が同じクライアントコードを呼び出す（ライブラリとして利用する）だけである。Layer1の`RepositoryFactory`や`config/api_sources.yaml`への変更は一切行わない。

### 7-3. 取得頻度

Layer7は**1営業日1回**、追跡中の全アクティブポジションについて価格を取得する（Ver1時点ではザラ場中の高頻度チェックは行わない）。

---

## 8. 判定仕様

### 8-1. ステータスの種類

| ステータス | 意味 |
|---|---|
| `active` | 保有中（継続追跡） |
| `take_profit` | 利確ラインに到達し決済 |
| `stop_loss` | 損切ラインに到達し決済 |
| `holding_period_expired` | 想定保有期間を超過したため決済 |
| `manual_close` | 人間による手動終了（§8-4） |

### 8-2. 判定ルール（優先順位順、当日の高値・安値を用いて判定）

各アクティブポジションについて、当日取得した価格データ（終値・高値・安値）を用いて、以下の順序で判定する。

1. **損切判定**：当日の安値が`stop_loss_price`以下の場合 → `stop_loss`。決済価格は`stop_loss_price`とする（実際のスリッページは考慮しない簡略化であることを明記する。§15自己レビューで確認）。
2. **利確判定**：（1に該当しない場合）当日の高値が`take_profit_price`以上の場合 → `take_profit`。決済価格は`take_profit_price`とする。
3. **同日に両方の条件を満たした場合の扱い（重要）**：1営業日の値幅が損切ライン・利確ラインの両方を跨いだ場合、**損切を優先する**（リスク回避的な仮定を採用し、楽観的な結果を割り当てない）。この場合、決済価格は`stop_loss_price`、`exit_reason`は`stop_loss`とする。
4. **保有期間終了判定（境界の定義を明文化・修正）**：（1・2に該当しない場合）`entry_date`を1日目として数え、経過日数が`holding_period_days_parsed`に**到達した日**の価格判定時点で終了する。具体的には、判定基準日（`judge_date`）を`entry_date + (holding_period_days_parsed - 1)`（カレンダー日数）として算出し、当日の日付が`judge_date`**以降**であれば`holding_period_expired`とする（「超えている」ではなく「到達した」時点で終了する）。決済価格は当日の終値とする。
   - 例：`entry_date=2026-07-01`、`holding_period_days_parsed=28`の場合、`judge_date = 2026-07-01 + 27日 = 2026-07-28`。7/28時点（の価格判定後）で終了となり、7/29まで持ち越さない。
   - `judge_date`が非営業日（休場日）にあたる場合は、Layer7がその日に価格取得・判定を実行できないため、**`judge_date`以降で最初にLayer7が実行された日（＝最初に価格取得できた営業日）**に判定・終了する。
5. **上記いずれにも該当しない場合** → `active`のまま継続。

### 8-3. `holding_period_days_parsed`の算出（§6-2関連）

Layer5が出力する`holding_period`は自然文（例：「2〜4週間」「1ヶ月程度」）であり、厳密な日数ではない。Layer7は以下のルールで機械的に日数へ変換する。

```yaml
# config/holding_period_parser.yaml
unit_days:
  日: 1
  週間: 7
  週: 7
  ヶ月: 30
  か月: 30
  カ月: 30
parse_rule: "文字列内の数値をすべて抽出し、最大値を採用する。抽出した数値に対応する単位（直後に出現する単位語）を掛けて日数を算出する。例：「2〜4週間」→ 4×7 = 28日"
fallback_default_days: 90   # 数値・単位が抽出できない場合のフォールバック
```

パース失敗時（数値または単位が抽出できない場合）は、`fallback_default_days`（90日）を採用し、`holding_period_days_parsed`に`90`を設定したうえで、`parse_status: "fallback_used"`を記録する（隠蔽しない。§9のエラー処理参照）。

### 8-4. 手動終了（`manual_close`）の扱い（修正・キュー方式）

Layer7は`取引記録_*.csv`を読まない設計（§5-2）のため、ユーザーが手動でSBI証券等で売買したことを自動検知する手段を持たない。したがって`manual_close`は**Layer7の自動判定の対象外**とし、人間（または将来のGUI）が終了させたいポジションを申告する仕組みとして設計する。

**当初案からの変更点**：当初は`active_positions.json`を人間が直接編集する案としていたが、これは本番運用中のデータファイルを人手で直接編集することになり、書式ミス（カンマの欠落等）によるファイル破損のリスクが高い。そのため、**`manual_close_requests.json`という専用のリクエストキューファイル**を新設し、人間はこの小さなファイルに終了申請を追記するだけにする方式へ変更する。

```
tracking/
├── active_positions.json
├── closed_positions_YYYYMM.json
├── tracking_history_YYYYMM.json
└── manual_close_requests.json      # 【新設】手動終了のリクエストキュー
```

`manual_close_requests.json`の構造：

```json
{
  "requests": [
    {
      "tracking_id": "TRK-20260718-0630-NVDA",
      "exit_price": 350.00,
      "exit_date": "2026-08-01",
      "note": "決算前に手動で利確した"
    }
  ]
}
```

- 必須項目は`tracking_id`のみ。`exit_price`／`exit_date`が省略された場合、Layer7は次回実行時点の最新取得価格・実行日をそれぞれ採用する。`note`は任意の自由記述。
- **処理フロー**：Layer7は毎回の実行時（§4手順5の直後）に`manual_close_requests.json`を読み込み、記載された`tracking_id`が`active_positions.json`に存在すれば、`exit_reason: "manual_close"`として`closed_positions_YYYYMM.json`へ移動し、処理済みのリクエストは`manual_close_requests.json`から削除する。存在しない`tracking_id`が指定された場合はエラーとして記録し（§9）、リクエストは削除せず残す（誤って消さないため。次回実行時に再度警告される）。
- この方式により、人間（または将来のGUI）が触るファイルは「小さく」「追記するだけで済み」「Layer7が読み取った後は自動的に片付く」ものになり、`active_positions.json`本体を直接編集する必要が無くなる。将来GUIを構築する場合も、GUIはこの`manual_close_requests.json`への追記のみを行えばよく、`active_positions.json`のスキーマを意識する必要がない。

### 8-5. 自動判定とmanual_closeが競合した場合の優先順位（新設・確定、実装者レビューへの回答）

§8-2ルール3では「同日に損切・利確の両条件を満たした場合は損切優先」という、自動判定同士の競合を解決済みである。同様に、**自動判定（`exit_evaluator.py`、手順5）が既にステータスを確定させた後、`manual_close_processor.py`（手順6）が同一`tracking_id`に対する手動終了リクエストを検出した場合の優先順位**を以下の通り確定する。

- **`manual_close`を優先する**。理由：`manual_close`はユーザーが実際に行った取引の事実（例：決算前に手動で利確した）を表すのに対し、自動判定（`stop_loss`／`take_profit`／`holding_period_expired`）はLayer7が価格から機械的に推定したシミュレーション結果に過ぎない。現実の取引事実を優先すべきという原則により、手順5の自動判定結果は破棄し、`exit_reason: "manual_close"`として`closed_positions_YYYYMM.json`へ記録する。決済価格・決済日は`manual_close_requests.json`の値（省略時は§8-4既定の通り、次回実行時点の最新取得価格・実行日）を採用する。
- この優先順位は、手順7（`active_positions.json`からの除外・`closed_positions_YYYYMM.json`への記録）が実行される前、手順6の完了時点で確定させる。

---

## 9. エラー処理

| 事象 | 対応 |
|---|---|
| Layer6の「本日の提案」シートが見つからない／読み込めない | 当日の新規取り込みをスキップし、次回実行時に再試行する。既存のアクティブポジションの価格チェックは通常通り継続する |
| 特定ティッカーの価格取得失敗 | 当該ポジションの判定をスキップし`active`のまま維持する（データ欠損を理由に強制決済しない）。次回実行時に再試行する |
| `holding_period`のパース失敗 | §8-3の`fallback_default_days`を採用し、`parse_status: "fallback_used"`として記録する（隠蔽しない） |
| 同日に損切・利確の両条件を満たす | §8-2のルール3（損切優先）を適用し、その旨を`closed_positions_YYYYMM.json`の該当エントリに明記する |
| 重複取り込み（同一`run_id`＋`ticker`が既に追跡中） | エラーではなく正常系。スキップしログに記録する |
| `manual_close_requests.json`に存在しない`tracking_id`が指定されている | エラーとして記録する。当該リクエストはキューから削除せず残す（誤って握りつぶさないため）。次回実行時に再度警告される |
| `active_positions.json`／`closed_positions_YYYYMM.json`／`manual_close_requests.json`の破損・スキーマ不整合 | 当該ファイルへの書き込みを中止し、`severity: critical`として記録する。既存データを不整合なまま上書きしない |
| （新設・Ver1.3）§4手順2〜9のいずれかが失敗し、`layer7_completed_YYYYMMDD.json`が`completed:true`で書き込めない | Layer8は完了フラグ未到達として当該日の評価処理をスキップし、次回スケジュールで再試行する（Layer8詳細設計書§4-3参照）。Layer7自体の既存データは不整合なまま上書きしない |
| （新設・Ver1.4）同日に`layer7_completed_YYYYMMDD.json`が複数存在する（再実行等） | `createdTime`最大のものを正として扱う（§6-5、エラーではなく正常系） |
| （新設・Ver1.4）自動判定とmanual_closeが同一実行内で同一`tracking_id`に対し競合する | `manual_close`を優先する（§8-5、エラーではなく正常系） |

---

## 10. 将来拡張性

- `PriceCheckRepository`の抽象化により、将来価格取得APIを変更・追加してもLayer7内部（`exit_evaluator.py`・`position_store.py`等）への影響はない（§7・§15参照）。
- Ver1では1日1回の判定のみだが、将来ザラ場中の高頻度チェックが必要になった場合も、`price_checker.py`の呼び出し頻度を変えるだけで対応でき、判定ロジック自体の変更は不要。
- Layer9（運用成績ダッシュボード）は、本層が生成する`closed_positions_YYYYMM.json`・`tracking_history_YYYYMM.json`を主要な入力として利用する想定（§13・§15参照）。

---

## 11. テスト方針

| 対象 | テスト内容 |
|---|---|
| `proposal_ingester.py` | Layer6サンプルシートから正しい列のみを読み込み値を変更せず転記すること、重複取り込みが防止されること |
| `holding_period_parser.py` | 「2〜4週間」「1ヶ月程度」等の既知パターンで正しい日数に変換されること、パース不能な文字列で`fallback_default_days`が適用されること |
| `exit_evaluator.py` | 損切のみ／利確のみ／同日両方該当（損切優先）／保有期間超過／該当なし（継続）の全パターンで期待通りのステータスになること。特に`judge_date`の境界値テスト（例：`entry_date=7/1`、`holding_period_days_parsed=28`のとき`judge_date=7/28`となり、7/27では継続・7/28で終了することを確認、§8-2の修正内容） |
| `price_checker.py` | `PriceCheckRepository`をモックし、正しいフィールド（終値・高値・安値・出来高）が取得・反映されること |
| `manual_close_processor.py` | キュー内の有効な`tracking_id`が正しく`closed_positions_YYYYMM.json`へ移動しキューから削除されること、存在しない`tracking_id`がエラー記録されキューに残ること |
| `position_store.py` | 読み書きの往復テストでデータが欠落・変質しないこと。`active_positions.json`に`price_history`配列相当の日次履歴が含まれない（`latest_price`のみである）ことを確認 |
| Layer6→Layer7結合テスト | Layer6のサンプルSheetを用い、正しく`active_positions.json`が生成されることをend-to-endで確認 |
| 読み取り専用性の回帰テスト | Layer7実行前後でLayer6のGoogle Sheetsファイルの内容（ハッシュ等）が変化していないことを確認（Layer6成果物の非破壊性の検証） |
| `layer8_export_builder.py` | クローズしたポジションから§13のLayer8向けフィールドが過不足なく生成されること |

---

## 12. Layer1〜Layer6との整合性確認

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | Layer6の「本日の提案」シート列構成（Layer6詳細設計書§6-3）に、Layer7が必要とする9列がすべて存在するか | 存在する。Layer6側の追加修正は不要（§5-1） |
| 2 | Layer7がLayer6のGoogle Sheets／Markdownへ書き込みを行っていないか | 行っていない。Layer7は読み取り専用でLayer6成果物を参照する（§2非責務） |
| 3 | Layer7がLayer5のdecision JSONを直接参照していないか | 参照していない。Layer6を経由した列データのみを利用する（§5-2） |
| 4 | Layer1のRepositoryパターン（データ取得クライアント）を再利用する場合でも、Layer1の契約・設定を変更していないか | 変更していない。Layer7は独自の`PriceCheckRepository`を新設し、Layer1のコードは（再利用する場合も）ライブラリとして呼び出すのみ（§7-2） |
| 5 | Layer1〜Layer6の責務分離（データ取得／分析・スコアリング／ニュース構造化／永続化／AI判断／レポート生成）にLayer7が抵触していないか | 抵触していない。Layer7は「保有中提案の追跡・実績記録」のみを行い、判断・計算（判定ロジック以外の）・銘柄選定のいずれも行わない |

---

## 13. Layer8へ渡す情報

`layer8_export_builder.py`が、クローズしたポジションごとに以下を生成し、`closed_positions_YYYYMM.json`（§6-3）として保存する。Layer8（自己評価層）はこのファイルを入力として利用する想定。

| フィールド | 説明 |
|---|---|
| `tracking_id` | 追跡ID |
| `run_id` | 元となったLayer5の実行ID |
| `ticker` | 証券コード |
| `entry_price` | エントリー価格 |
| `exit_price` | 決済価格 |
| `holding_days` | 実際の保有日数 |
| `max_unrealized_gain_pct` | 保有期間中の最大含み益率 |
| `max_unrealized_loss_pct` | 保有期間中の最大含み損率 |
| `final_return_pct` | 最終損益率 |
| `exit_reason` | 終了理由（`take_profit`／`stop_loss`／`holding_period_expired`／`manual_close`） |

これらはVer2で計画されたLayer8「成功/失敗要因分析」（どの評価軸のスコアが的中/外れに寄与したか）に必要な「実績側」のデータを過不足なく提供する。Layer8がLayer5の`score_summary`（reason_code等）と本層の実績データを突き合わせて分析を行うことを想定する。

---

## 14. 確定事項

1. Layer7はGitHub Actions上で独立したスケジュール（Layer5/Layer6の実行タイミングとは非同期）で稼働する決定的Python処理として設計する。
2. Layer7の入力はLayer6の「本日の提案」Google Sheetsの指定9列のみとし、Markdown・Layer5 decision JSON・`取引記録_*.csv`・Layer1〜4の出力にはアクセスしない。
3. 保存先は`tracking/active_positions.json`／`closed_positions_YYYYMM.json`／`tracking_history_YYYYMM.json`／`manual_close_requests.json`とする。
4. 判定ルールは「損切優先の同日両条件判定」「保有期間の自然文パース＋フォールバック」「保有期間終了は`judge_date = entry_date + (holding_period_days_parsed - 1)`到達時点」を含め、§8で確定した通りとする。
5. **`manual_close`はキュー方式**：人間（または将来のGUI）は`manual_close_requests.json`へ`tracking_id`を追記するのみとし、`active_positions.json`本体を直接編集しない（§8-4）。
6. 価格取得は`PriceCheckRepository`という新規の抽象インターフェースで行い、Layer1の既存コードを再利用する場合もLayer1の契約・設定は変更しない。
7. **`active_positions.json`は最新価格スナップショット（`latest_price`）のみを保持し、日次の全価格履歴は`tracking_history_YYYYMM.json`に一元化する**（§6-2）。これにより`active_positions.json`の肥大化を防ぐ。
8. **（新設・Ver1.3）Layer8との実行タイミング調整として完了フラグファイル方式を採用する**：`tracking/layer7_completed_YYYYMMDD.json`を、Layer7の全保存処理成功後の最終ステップとして書き込む（§4手順10・§6-5）。Layer4→Layer5間で確立済みの完了フラグ方式と同じ思想を、Layer7→Layer8間にも統一適用する。
9. **（新設・Ver1.4）`layer7_completed_YYYYMMDD.json`の同日再実行時は`createdTime`最大のものを正とする**（§6-5）。Layer4の完了フラグと同じ考え方を踏襲する。
10. **（新設・Ver1.4）自動判定とmanual_closeが競合した場合はmanual_closeを優先する**（§8-5）。実際の取引事実を、Layer7が推定したシミュレーション結果より優先する。
11. **（新設・Ver1.4）本層が管理する各JSONファイルの更新は、同一実行単位の重複起動が発生しないことを前提とする**（§6-6）。重複起動防止自体はGitHub Actions側の運用面の担保とし、全体設計書§11-6を参照する。

---

## 15. 自己レビュー

### 15-1. Layer1〜Layer6の責務を侵害していないか

侵害していない。Layer7は「Layer6が保存した提案履歴の読み込み」「保有中提案の追跡」「実績記録」のみを行い、データ取得・分析・スコアリング・ニュース構造化・永続化・AI判断・レポート生成のいずれの処理も行っていない。

### 15-2. Layer6の成果物を書き換えていないか

書き換えていない。§2の非責務・§5-1で「読み取り専用」を明記し、§11のテスト方針に「読み取り専用性の回帰テスト」を設けることで、実装段階でもこの原則が破られないことを検証可能にした。

### 15-3. Layer5のdecision JSONを直接参照していないか

参照していない。§5-2で明示的に禁止し、Layer7が利用できるのはLayer6を経由した「本日の提案」シートの列データのみとした。

### 15-4. Layer8が必要な情報を十分保持できるか

保持できる。ご指定のフィールド（エントリー価格・決済価格・保有日数・最大含み益/損・最終損益率・終了理由・run_id・ticker）をすべて§13で定義し、`closed_positions_YYYYMM.json`に格納する設計とした。

### 15-5. 将来Layer9で利用できる設計になっているか

なっている。`closed_positions_YYYYMM.json`（実績の集計元データ）・`tracking_history_YYYYMM.json`（時系列データ）は、Ver2で計画されている運用成績ダッシュボード（勝率・平均利益/損失・Profit Factor・最大ドローダウン・シャープレシオ等の算出）に必要な生データをすべて含む形にした（§10・§13）。

### 15-6. 入出力契約が曖昧になっていないか

当初、「保有期間終了」の判定において、Layer5が出力する`holding_period`が自然文（「2〜4週間」等）であり厳密な日数ではないことが、設計の過程で明らかになった。これを曖昧なまま「期間を見て判断する」としてしまうと実装者が迷うため、§8-3で機械的なパースルール（数値抽出・単位換算・最大値採用）とフォールバック値（90日）を具体的に定義し、パース失敗時も`parse_status`で状態を明示することで、曖昧さを排除した。また「同日に損切・利確の両方の条件を満たす」という境界ケースも、当初は未定義だったため§8-2ルール3で「損切優先」を明文化した。これらはいずれも本文（§8）に反映済みである。

### 15-7. 将来APIを変更してもLayer7内部へ影響しない設計になっているか

なっている。`PriceCheckRepository`という単一メソッドの抽象インターフェースを新設し、`exit_evaluator.py`等の判定ロジックはこのインターフェースにのみ依存する設計とした（§7）。将来価格取得APIを変更しても、影響範囲は具体実装（`price_check_repository_impl.py`）内に閉じる。

**結論**：自己レビューの過程で、§8-2（同日両条件該当時の優先順位）と§8-3（保有期間の自然文パース）という2点の曖昧さを発見し、本文へ具体的なルールとして反映済みである。それ以外の確認項目（責務侵害・成果物書き換え・decision JSON直接参照・Layer8/Layer9との接続・API変更耐性）については問題が見つからなかった。

**Ver1.1修正内容（3点への対応）**：①保有期間終了の判定境界を「超えている」から「`judge_date = entry_date + (holding_period_days_parsed - 1)`に到達した時点」へ明確化し、直感的な期待（例：28日保有なら28日目に終了）と一致させた（§8-2）。②`active_positions.json`から日次の`price_history`配列を廃止し、直近1回分の`latest_price`のみを保持する設計に変更、時系列データは既存の`tracking_history_YYYYMM.json`に一元化してファイル肥大化を防いだ（§6-2）。③`manual_close`を、`active_positions.json`の直接編集から、`manual_close_requests.json`という専用キューファイルへの追記方式に変更し、ファイル破損リスクを低減するとともに将来のGUI連携も見据えた設計にした（§8-4）。

**Ver1.2修正内容（今回のご指摘2点への対応）**：①`tracking_id`の生成方式をUUIDではなく`TRK-{run_id}-{ticker}`という人間判読可能な形式に変更した（§6-2）。この一意性は`run_id`が実行単位で一意であることに依拠するため、Layer5の`run_id`が想定する粒度（`YYYYMMDD-HHMMSS`）を持つことを前提とし、実装時の確認事項として明記した。②`closed_positions.json`（単一ファイル）を`closed_positions_YYYYMM.json`（月次分割）へ変更し、Layer4・Layer6の月次分割方針と統一するとともに長期運用時のファイル肥大化を防止した（§6-3）。

### 15-8. Layer8との実行タイミング調整（今回の修正点・Ver1.3）

全体設計書（`docs/00_SystemArchitecture.md`）のレビューにおいて、「Layer4→Layer5間は完了フラグファイル方式でタイミング調整を行っているが、Layer7→Layer8間には同等の機構が無い」という改善提案が挙げられた。これを受け、Layer7の全保存処理（§4手順2〜9）が成功した場合のみ`tracking/layer7_completed_YYYYMMDD.json`を書き込む設計に変更した（§4手順10、§6-5）。Layer8はこのフラグの存在・`completed:true`を確認してから評価処理を開始する（Layer8詳細設計書側の変更）。これによりLayer7→Layer8間のタイミング調整も、Layer4→Layer5間と同じ「固定時刻オフセットに頼らず完了そのものを確認する」原則に統一された。

**Ver1.3修正内容（全体設計書レビューへの回答）**：Layer8との実行タイミング調整のため、完了フラグファイル`tracking/layer7_completed_YYYYMMDD.json`を新設した（§4手順10、§6-1、§6-5、§14確定事項8）。既存の判定ロジック・保存仕様・入出力契約には一切変更を加えていない。

### 15-9. 実装者レビューへの回答（今回の修正点・Ver1.4）

実装者レビューで指摘された3点（①`layer7_completed_YYYYMMDD.json`の同日再実行時のルール欠如、②自動判定とmanual_closeの競合時の優先順位未定義、③多重起動に対する排他制御の前提欠如）に対応した。①はLayer4の完了フラグと同じ「`createdTime`最大を正とする」ルールを追記（§6-5）、②は「manual_closeは実際の取引事実を表すため自動判定より優先する」というルールを新設（§8-5）、③は同一実行単位の重複起動が発生しない前提を明記し、防止自体はGitHub Actions側の運用面（全体設計書§11-6）に委ねる形で整理した（§6-6）。いずれも既存の保存仕様・判定ロジック・JSONスキーマを変更せず、確定済みパターン（完了フラグの再実行ルール、優先順位ルールの体系）を同種のケースへ延長する最小限の追記に留めている。

**Ver1.4修正内容（実装者レビューへの回答）**：`layer7_completed_YYYYMMDD.json`の同日再実行ルール（§6-5）、自動判定とmanual_closeの優先順位（§8-5）、同時実行に関する前提（§6-6）を新設した。既存の保存仕様・判定ロジック・入出力契約には一切変更を加えていない。

**Layer7詳細設計書 Ver1.4確定**
