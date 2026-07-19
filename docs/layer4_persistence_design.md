# 永続化層（Layer4）詳細設計書

作成日: 2026-07-18（Ver1.1：historyファイル名統一・saved_files整合性・snapshot_path統一・Repository保存専用化を反映）
前提: Ver2全体設計書（確定版）／Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Layer3詳細設計書（確定版・Ver1.3）／Layer5詳細設計書（確定版・Ver1.2）と整合。**Layer5は確定済みのため、Layer5が前提とする仕様（特に`layer4_completed_YYYYMMDD.json`の構造とLayer5の読み込み順序）は本書側が合わせる。Layer5側を変更することは一切行わない。**

---

## 0. 実行環境の前提

Layer5詳細設計書§0で整理した全体構造の通り、Layer4はLayer1〜3と同じ実行モデルに属する。

```
Layer1〜4  Python Pipeline（GitHub Actions上、同一runの最終ステップとしてLayer4が動く）
    ↓
Layer5     AI Agent実行層（Claude Coworkセッション。Layer4が生成したファイルをGoogle Driveから読む）
    ↓
Layer6     Report Generator（別途設計）
```

Layer4はAIエージェントでもLLM呼び出しでもなく、**純粋な決定的Python処理**である。Layer1（データ取得）→Layer2（分析・スコアリング、Layer3のニュース構造化結果を内部で利用）→Layer4（永続化）という順で同一GitHub Actions run内で実行され、Layer4はLayer2が生成した最終JSON（`json_builder.py`の戻り値）をメモリ上でそのまま受け取る（Google Driveを経由した往復は発生しない）。Layer4が書き込んだ結果を、後続の別プロセスであるLayer5（Claude Coworkセッション）がGoogle Drive経由で読みに来る、という構造である。

---

## 1. Layer4の責務・非責務

**責務**：
- Layer1〜3の成果物（Layer2の最終出力JSON、および各層の実行メタ情報）の保存
- `market_snapshot_YYYYMMDD.json`の生成（Layer2出力の**非加工**保存）
- `layer4_completed_YYYYMMDD.json`（完了フラグ）の生成
- 実行ログ・履歴・実行結果の保存
- Google Driveへの保存
- JSON Schemaの維持（`market_snapshot`／`layer4_completed`／`execution_log`の形式定義とバリデーション）
- 将来の履歴参照を可能にするインデックスの維持

**非責務**：
- スコア計算（Layer2の責務。Layer4は計算を一切行わない）
- ニュース解析（Layer3の責務）
- AI判断（Layer5の責務）
- レポート生成（Layer6の責務）
- ポートフォリオ（`取引記録_*.csv`）の管理：これはLayer1〜3の成果物ではなくユーザー自身の取引台帳であり、Layer5が直接読み込む（Layer5詳細設計書§4-2）。Layer4は関与しない。
- Layer2が生成した`run_meta.data_quality`の内容を書き換えること：Layer4はLayer2の判断結果をそのまま転記するのみで、独自にエラー分類を追加・変更しない（Layer2詳細設計書§10で確立した責務分離を継承）。

---

## 2. モジュール構成

```
src/persistence/
├── snapshot_writer.py         # market_snapshot_YYYYMMDD.json の書き込み（Layer2出力を非加工で保存）
├── completion_flag_writer.py  # layer4_completed_YYYYMMDD.json の生成（全保存成功後の最終ステップ）
├── execution_logger.py        # execution_log_YYYYMMDD.json の生成（開始/終了時刻・保存件数・エラー/警告一覧等）
├── history_indexer.py         # history/ 配下の軽量インデックス更新（過去実行の高速参照用）
├── drive_client.py            # Google Drive書き込みの共通ラッパー（Layer1のRepositoryパターンの思想を継承）
├── repository/                # 【将来拡張】永続化先を抽象化するRepositoryパターン（§11）
│   ├── base.py                  # PersistenceRepository 抽象クラス（保存系メソッドのみ。読み込み系は含めない）
│   └── google_drive_repository.py  # 現行の具体実装
├── schema/
│   ├── market_snapshot.schema.json
│   ├── layer4_completed.schema.json
│   └── execution_log.schema.json
└── main.py                     # Layer4パイプラインのエントリポイント（Layer1〜3完了後に呼ばれる）
```

---

## 3. 実行フロー

1. 同一GitHub Actions run内で、Layer1（データ取得）→Layer2（分析・スコアリング。内部でLayer3のニュース構造化結果を利用）が完了し、Layer2の`json_builder.py`が最終JSONを生成する。
2. Layer4（`main.py`）が起動し、Layer2の最終出力JSONをメモリ上でそのまま受け取る。
3. **Schemaバリデーション**：`market_snapshot.schema.json`に対して、トップレベルの必須キー（`run_meta`／`regime`／`macro`／`candidates`／`excluded_summary`）の存在のみを検証する（**内部の詳細な妥当性—スコアの範囲や配点の整合性等—はLayer2の責務でありLayer4は検証しない**。あくまで「保存可能な形をしているか」という形式チェックに限定する）。不正な場合は§9のエラー処理へ進み、以降のステップは実行しない。
4. `snapshot_writer.py`が`snapshots/market_snapshot_YYYYMMDD.json`としてGoogle Driveへ書き込む（内容は一切加工しない）。
5. `execution_logger.py`が、Layer1〜3それぞれの実行メタ情報（成功/失敗・使用ソース・所要時間等、Layer1の`run_logger`が収集済みのもの）を集約し、`logs/execution_log_YYYYMMDD.json`として書き込む。
6. `history_indexer.py`が`history/index_YYYYMM.json`（実行月の月次ファイル）に当日のサマリレコード（日付・run_id・ステータス・候補件数・エラー件数等）を追記する。
7. **手順4〜6が全て成功した場合のみ**、`completion_flag_writer.py`が`snapshots/layer4_completed_YYYYMMDD.json`を`completed: true`で生成・書き込む（§7・§8）。
8. 手順3〜6のいずれかで失敗した場合、完了フラグは`completed: true`では書き込まれない（§7-2・§9参照。Google Drive自体に書き込めた場合は`completed: false`で失敗詳細を記録し、Drive自体に書き込めない場合は完了フラグファイル自体が存在しない状態になる）。

---

## 4. 保存ディレクトリ構成

既存のGoogle Drive「AI投資アシスタント」フォルダ（Ver2で確立済み）を拡張する形とし、新しい命名体系を別途作らない。

```
AI投資アシスタント/
├── config/                              # 既存（Layer1〜5共通のconfig類）
├── snapshots/                           # 既存。Layer4が書き込む主要成果物
│   ├── market_snapshot_YYYYMMDD.json
│   ├── market_snapshot_YYYYMMDD_supersededTHHMMSSZ.json   # 同日再実行時の旧版（§7-1参照）
│   └── layer4_completed_YYYYMMDD.json
├── logs/                                # 既存。Layer4が書き込む実行ログ
│   └── execution_log_YYYYMMDD.json
├── history/                             # 【新設・Layer4管理】日次サマリの軽量インデックス
│   └── index_YYYYMM.json                # 月次ファイルに分割し肥大化を防ぐ
├── contracts/                           # 【新設・Layer4管理】JSON Schema定義一式
│   ├── market_snapshot.schema.json
│   ├── layer4_completed.schema.json
│   └── execution_log.schema.json
├── decisions/                           # 既存。Layer5が書き込む（Layer4は関与しない）
├── tracking/                            # 既存。Ver2バックテスト基盤（Layer4は関与しない）
├── evaluation/                          # 既存。Ver2自己評価層（Layer4は関与しない）
├── dashboard/                           # 既存。Ver2運用成績ダッシュボード（Layer4は関与しない）
├── 取引記録_YYYYMMDDTHHMMSSZ.csv          # 既存。ユーザーの取引台帳（Layer4は関与しない）
└── 提案ログ_YYYYMMDD.csv                  # 既存
```

**`portfolio/`フォルダを新設しない理由**：`取引記録_*.csv`はLayer1〜3の成果物ではなくユーザー自身の取引台帳であり、Layer5が直接読み込む設計が既に確定している（Layer5詳細設計書§4-2）。Layer4が管理すると責務境界（「Layer1〜3の成果物を保存」）を超えてしまうため、あえて含めない。

---

## 5. 保存ファイル仕様

### 5-1. `market_snapshot_YYYYMMDD.json`

Layer2の`json_builder.py`が生成した最終出力そのもの。**Layer4は一切加工しない**（キーの追加・削除・改名・値の変換のいずれも行わない）。Layer2詳細設計書§5で定義されたスキーマ（`run_meta`／`regime`／`macro`／`candidates`／`excluded_summary`）がそのまま保存される。UTF-8、可読性のためインデント付きで保存する。

### 5-2. `layer4_completed_YYYYMMDD.json`（完了フラグ、Layer5との契約の核）

Layer5詳細設計書§3-1で定義された構造を**そのまま**採用する（変更しない）。

```json
{
  "completed": true,
  "completed_at": "2026-07-18T06:25:00Z",
  "layer_status": {
    "layer1": "success",
    "layer2": "success",
    "layer3": "success",
    "layer4": "success"
  },
  "snapshot_path": "snapshots/market_snapshot_20260718.json"
}
```

失敗時（Google Drive自体への書き込みは可能な場合）：

```json
{
  "completed": false,
  "completed_at": "2026-07-18T06:28:00Z",
  "layer_status": {
    "layer1": "success",
    "layer2": "success",
    "layer3": "failed",
    "layer4": "not_started"
  },
  "snapshot_path": null,
  "failure_reason_code": "SCORING_FAILED"
}
```

### 5-3. `execution_log_YYYYMMDD.json`

以下を必ず含める（ご指定の必須項目に対応）。

**`saved_files`の整合性について（重要）**：書き込み順序は「market_snapshot→execution_log→history index→completion flag」に固定されている（§6-2）。この順序上、`execution_log`が生成される時点では、`history index`と`layer4_completed`はまだ書き込まれていない。したがって`saved_files`には、**この`execution_log`自身が生成される時点で既に保存済みの成果物のみ**を含める（現時点では`market_snapshot`のみ）。`execution_log`自身・`history index`・`layer4_completed`は、Layer4の内部管理ファイル（成果物そのものではなく、成果物の保存を記録・確定させるための付随ファイル）であり、あえて`saved_files`には含めない。これらのファイルは書き込み時点が未確定である以上に書き込みパス自体は決定的（日付から一意に定まる）であるため、「これから書き込まれる予定のパス」として`related_files_planned`に分離して記録し、「保存済み」を意味する`saved_files`と明確に区別する。

```json
{
  "run_id": "20260718-0600",
  "schema_version": "1.0",
  "started_at": "2026-07-18T06:00:00Z",
  "completed_at": "2026-07-18T06:25:00Z",
  "saved_files": [
    "snapshots/market_snapshot_20260718.json"
  ],
  "saved_count": 1,
  "save_destination": "google_drive:AI投資アシスタント",
  "related_files_planned": {
    "history_index": "history/index_202607.json",
    "completion_flag": "snapshots/layer4_completed_20260718.json"
  },
  "errors": [],
  "warnings": [
    { "code": "MINOR_SOURCE_TIMEOUT", "message": "GDELT応答が1回タイムアウトしリトライで成功", "source_layer": "layer3" }
  ]
}
```

### 5-4. `history/index_YYYYMM.json`

過去実行を毎回`market_snapshot`全文を開かずに参照できるようにするための軽量インデックス。

```json
{
  "entries": [
    {
      "date": "2026-07-18",
      "run_id": "20260718-0600",
      "status": "completed",
      "candidate_count": 27,
      "blocking_errors_count": 0,
      "warning_errors_count": 1,
      "snapshot_path": "snapshots/market_snapshot_20260718.json"
    }
  ]
}
```

---

## 6. 入出力契約（Layer5との契約、最重要）

### 6-1. Layer4への入力

- Layer2の最終出力JSON（同一プロセス内でメモリ上から受け取る。Google Drive経由の読み込みは発生しない）
- Layer1・Layer3それぞれの実行メタ情報（成功/失敗・使用ソース・所要時間、Layer1の`run_logger`が既に収集済みのものを集約するのみで、Layer4が新たに収集し直すことはしない）

### 6-2. Layer4からの出力（＝Layer5への入力契約）

Layer5詳細設計書§3-1は、以下の順序で読み込むことを前提として**既に確定**している。

1. `snapshots/layer4_completed_YYYYMMDD.json`の存在確認
2. `completed: true`の確認
3. `snapshots/market_snapshot_YYYYMMDD.json`の読み込み
4. Layer5実行

Layer4はこの契約を満たすため、**書き込み順序を厳密に固定する**：`market_snapshot`→`execution_log`→`history index`の全てが成功して初めて、最後に`layer4_completed`を書く。**完了フラグを先に書いてsnapshotを後から書く、という順序は絶対に行わない**（Layer5がフラグの存在だけを見てsnapshotをまだ存在しない状態で読みに行ってしまうレースコンディションを防ぐため）。

### 6-3. 責務分離の明記

Layer4はLayer2が生成したデータの**運搬・保存**のみを行う。スコアの計算・ニュースの解釈・投資判断のいずれも行わない。Layer5がLayer4の出力を読む際、Layer4を経由したことによってLayer2の判断内容が変質していないことが保証される（そのためにも§5-1の「非加工保存」原則が重要）。

---

## 7. Google Drive保存仕様

### 7-1. ファイル命名規則・上書き方針

- ファイル名は`{種別}_{YYYYMMDD}.json`（`YYYYMMDD`はJST基準の実行日）で統一する。
- **同日再実行時の扱い**：同名ファイルが既に存在する場合、新規書き込みの前に既存ファイルを`market_snapshot_YYYYMMDD_superseded{現在時刻のUTCタイムスタンプ}Z.json`のようにリネームしてから新しい内容を正規の名前で書き込む（既存のGoogle Driveコネクタは上書き更新ができないため、Layer1確立当初からの「新スナップショットは新ファイル名で保存」という運用と整合する形。旧版は削除せず、監査・比較のために残す）。
- `layer4_completed_YYYYMMDD.json`も同様の考え方で扱うが、こちらは「その日の最終確定状態」を表すものなので、再実行時は常に最新の完了フラグが正となる。

### 7-2. 履歴を残すもの・日付管理

- `market_snapshot`・`execution_log`・`history/index`は削除せず蓄積し続ける（Layer1詳細設計書§7-3で確立した「バックテスト用データレイク」としての性質をLayer4がそのまま体現する）。
- 日付はJST基準の実行日で統一し、Layer1〜5全体を通して同一の日付基準を用いる。

---

## 8. JSON Schema

### 8-1. `market_snapshot.schema.json`（トップレベル形式のみを検証。内部詳細はLayer2の責務）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "market_snapshot",
  "type": "object",
  "required": ["run_meta", "regime", "macro", "candidates", "excluded_summary"],
  "properties": {
    "run_meta": { "type": "object" },
    "regime": { "type": "object" },
    "macro": { "type": "object" },
    "candidates": { "type": "array" },
    "excluded_summary": { "type": "array" }
  }
}
```

### 8-2. `layer4_completed.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "layer4_completed",
  "type": "object",
  "required": ["completed", "completed_at", "layer_status"],
  "properties": {
    "completed": { "type": "boolean" },
    "completed_at": { "type": "string", "format": "date-time" },
    "layer_status": {
      "type": "object",
      "required": ["layer1", "layer2", "layer3", "layer4"],
      "properties": {
        "layer1": { "enum": ["success", "failed", "not_started"] },
        "layer2": { "enum": ["success", "failed", "not_started"] },
        "layer3": { "enum": ["success", "failed", "not_started"] },
        "layer4": { "enum": ["success", "failed", "not_started"] }
      }
    },
    "snapshot_path": { "type": ["string", "null"] },
    "failure_reason_code": { "type": "string" }
  }
}
```

### 8-3. `execution_log.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "execution_log",
  "type": "object",
  "required": ["run_id", "schema_version", "started_at", "completed_at", "saved_files", "saved_count", "save_destination", "errors", "warnings"],
  "properties": {
    "run_id": { "type": "string" },
    "schema_version": { "type": "string" },
    "started_at": { "type": "string", "format": "date-time" },
    "completed_at": { "type": "string", "format": "date-time" },
    "saved_files": { "type": "array", "items": { "type": "string" } },
    "saved_count": { "type": "integer" },
    "save_destination": { "type": "string" },
    "related_files_planned": { "type": "object" },
    "errors": { "type": "array" },
    "warnings": { "type": "array" }
  }
}
```

`related_files_planned`は必須項目ではない（任意項目）。`saved_files`との違いは§5-3を参照。

---

## 9. エラー処理

| 事象 | 対応 |
|---|---|
| Google Drive保存失敗（一時的エラー） | Layer1の`RateLimiter`／バックオフ方針（Layer1詳細設計書§6）を再利用してリトライ。それでも失敗する場合は完了フラグを`completed:true`では書かない |
| JSON保存失敗（シリアライズエラー等） | Layer2の契約違反の可能性が高いため`SNAPSHOT_SCHEMA_INVALID`として`execution_log`に記録し、完了フラグを書かない |
| Schema不一致（§8-1のトップレベルキー欠落） | 同上。`market_snapshot`は保存せず（または`_invalid`サフィックス付きで保存し調査可能にする）、完了フラグは書かない |
| Google Driveのフォルダ不存在 | 既存のVer2フォルダ構成を前提とするため通常発生しないが、念のためフォルダ作成を試行し、作成した場合は`warnings`に記録する |
| 権限エラー | `severity: critical`として記録し、完了フラグを書かない。監視・アラートの対象とする |
| 途中失敗（`market_snapshot`は保存できたが`execution_log`保存に失敗等） | **全ステップ（§3の手順4〜6）が成功して初めて完了フラグを書く**という全体不可分の原則により、一部でも失敗すれば完了フラグは書かれない。Layer5からは「未完了」として扱われ、安全側に倒れる |
| 途中保存の再実行 | GitHub Actionsの再実行機能でLayer1〜4を再実行すればよい。§7-1の命名規則（旧版のsuperseded化）により、再実行の結果が正しく最新版として扱われる |

---

## 10. テスト方針

| 対象 | テスト内容 |
|---|---|
| `snapshot_writer.py` | Layer2の出力サンプルを渡した際、保存後のJSONが入力と完全に一致すること（キーの追加・削除・改名が一切発生しないことをバイト単位に近い精度で確認） |
| `completion_flag_writer.py` | §3手順4〜6が全て成功した場合のみ`completed:true`が書かれること、いずれか1つでも失敗した場合は`completed:true`が書かれない（「毒薬テスト」で全パターンを網羅） |
| Schemaバリデーション | 正常な`market_snapshot`／トップレベルキー欠落のケース双方で、期待通りの判定になること |
| 同日再実行（上書き）動作 | 同日の再実行で旧ファイルが`superseded`名で退避され、新ファイルが正規名で保存されること |
| Google Drive障害シミュレーション | 保存API呼び出し失敗をモックし、リトライ後もなお失敗する場合に完了フラグが書かれないことを確認 |
| Layer5との結合テスト | Layer4が書き込んだ`market_snapshot`＋`layer4_completed`のペアを、Layer5の`load_snapshot.py`がそのまま正しく読み込めることをend-to-endで確認（Layer4→Layer5境界の往復テスト） |
| `history_indexer.py` | 複数日分の実行後、`index_YYYYMM.json`に正しい件数・内容のレコードが蓄積されること |

---

## 11. 将来の拡張性

現行はGoogle Driveのみを永続化先とするが、将来SQLite／PostgreSQL／S3／Azure Blob等へ拡張できるよう、Layer1のRepositoryパターン（Layer1詳細設計書§3）と同じ考え方を適用する。**Layer4は保存専用の層であるため、Repositoryにも保存系メソッドのみを持たせ、読み込み系メソッドは一切含めない**（読み込みはLayer5の責務であり、Layer4のRepositoryに依存させない。§13レビューの⑤を参照）。

- `PersistenceRepository`抽象クラス（`save_snapshot()`／`save_completion_flag()`／`save_execution_log()`／`save_history_index()`の**保存系メソッドのみ**を定義）を設け、`GoogleDriveRepository`を現行の唯一の具体実装とする。`load_snapshot()`や`list_history()`のような読み込み系メソッドは、本Repositoryには含めない。
- 将来`S3Repository`や`PostgresRepository`を追加する場合、`config/persistence_backend.yaml`のようなconfigで切り替えるだけで済み、Layer1〜3・Layer5の契約（ファイルパス・JSON構造）には一切影響しない。
- **将来、永続化先を変更する場合の読み込み側対応について**：Layer5は現状「Google Drive上のファイル」を`load_snapshot.py`／`load_portfolio_state.py`で直接読む設計（Layer5詳細設計書§4-1・§4-2）であり、Layer4のRepositoryには依存していない。したがって永続化先を変更する場合、読み込み側に対応する`Repository`（またはそれに相当する読み込みロジック）が必要になったとしても、それは**Layer5側で実装するものとし、Layer4のRepositoryの責務には含めない**。この整理により、Layer4のRepositoryは常に「保存専用」を維持できる。

---

## 12. 確定事項

1. 保存先はGoogle Drive「AI投資アシスタント」フォルダに一本化し、`history/`・`contracts/`を新設。`portfolio/`は責務境界の観点から新設しない。
2. `market_snapshot_YYYYMMDD.json`はLayer2出力を非加工で保存する。
3. `layer4_completed_YYYYMMDD.json`はLayer5詳細設計書§3-1の構造をそのまま採用し、変更しない。書き込み順序は「market_snapshot→execution_log→history index→completion flag」の順に固定する。
4. `execution_log_YYYYMMDD.json`にはrun_id・schema_version・開始/終了時刻・保存件数・保存ファイル一覧・エラー一覧・警告一覧・保存先を含める。
5. 同日再実行時は旧ファイルを`superseded`名で退避し、新ファイルを正規名で保存する。
6. 永続化先の抽象化はRepositoryパターンで将来対応可能とし、現行はGoogle Drive実装のみ提供する。**Repositoryは保存系メソッド（`save_snapshot`／`save_completion_flag`／`save_execution_log`／`save_history_index`）のみを持ち、読み込み系メソッドは含めない。将来読み込み側の抽象化が必要になった場合はLayer5側で実装する（§11）。**
7. **historyインデックスのファイル名は`history/index_YYYYMM.json`に統一する**（本文中に混在していた`index.json`表記は`index_YYYYMM.json`に統一済み）。
8. **`layer4_completed`の`snapshot_path`は`snapshots/market_snapshot_YYYYMMDD.json`（`snapshots/`プレフィックス付き）に統一する**（§5-2の例を修正済み）。
9. **`execution_log`の`saved_files`は、当該ログ生成時点で既に保存済みのファイルのみを含める**（現時点では`market_snapshot`のみ）。`execution_log`自身・`history index`・`layer4_completed`は書き込み順序上まだ存在しないため含めず、その予定パスは`related_files_planned`として別フィールドに分離する（§5-3）。書き込み順序（market_snapshot→execution_log→history index→completion flag）自体は変更しない。

---

## 13. Layer1〜Layer5との整合性レビュー

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | Layer5が期待する`layer4_completed_YYYYMMDD.json`の構造（`completed`/`completed_at`/`layer_status`/`snapshot_path`）と完全一致しているか | 一致（§5-2で同一構造を採用） |
| 2 | Layer5が期待する読み込み順序（完了フラグ確認→snapshot読み込み）とLayer4の書き込み順序が矛盾しないか | 矛盾なし（§6-2で書き込み順序を明示的に固定） |
| 3 | Layer2詳細設計書§5で確定した`market_snapshot`のスキーマ（`run_meta`/`regime`/`macro`/`candidates`/`excluded_summary`）をLayer4が変更していないか | 変更なし（§5-1で非加工保存を原則化） |
| 4 | Layer2詳細設計書§10で追加した`critical_errors`/`warning_errors`の`{code, message, source_layer}`構造を、Layer4が壊していないか | 壊していない（Layer4は`run_meta.data_quality`の内容を書き換えず、Layer4自身の失敗はexecution_logと完了フラグの欠落・`completed:false`でのみ表現する設計とした） |
| 5 | Layer3詳細設計書との間で、ニュース関連データの取り扱いに矛盾がないか | 矛盾なし。Layer4はLayer3の出力を直接扱わず、Layer2に統合された後の`market_snapshot`のみを扱う |
| 6 | Layer1詳細設計書§7（キャッシュ・永続化方針）との整合 | 整合。Google Drive一本化・GitHubには保存しないという方針を継承 |
| 7 | Layer1〜Layer5の責務分離が維持されているか（データ取得／分析・スコアリング／ニュース構造化／永続化／AI判断の5層が、それぞれ他層の仕事を行っていないか） | 維持されている。Layer4は「運搬・保存」のみを行い、計算・解釈・判断のいずれも行わない設計にした |

**結論**：不足点・矛盾点は見つからなかった。Layer5が前提とする仕様（特に完了フラグの構造・読み込み順序）は一切変更していない。

**Ver1.1修正内容（今回の4点、いずれもLayer5との入出力契約は変更なし）**：①`history`インデックスのファイル名を`history/index_YYYYMM.json`に統一、②`execution_log.saved_files`の整合性を修正（生成時点で未保存のファイルを含めないよう`related_files_planned`に分離、書き込み順序は維持）、③`snapshot_path`を`snapshots/market_snapshot_YYYYMMDD.json`に統一、④Repositoryを保存系メソッドのみに限定（読み込み系はLayer5側の責務として明記）。

**Layer4詳細設計書 Ver1.1確定**
