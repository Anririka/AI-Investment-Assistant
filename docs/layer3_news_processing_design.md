# ニュース処理層（Layer3）詳細設計書

作成日: 2026-07-18（Ver1.3：Layer5との整合性確認により責務境界を精緻化）
前提: Layer1詳細設計書（確定版）／Layer2詳細設計書（確定版・Ver1.4）／Ver2設計書／スコアリング仕様書（確定版・Ver1.2）と整合
目的: 複数ニュースソースから取得した記事をLLMで構造化し、Layer2（news_scorer.py）が消費する`StructuredNewsItem`を生成する。

---

## 1. Layer3の責務・非責務

**責務**：
- ニュース取得（Layer1の`NewsRepository`経由。NewsAPI[development_only]→GDELT[production_primary]→Web検索の順）
- 重複ニュースの除去
- 記事本文の前処理
- **記事品質フィルタリング**（本文文字数不足・タイトルのみ・本文取得失敗・広告ページ等をLLM構造化前に除外。§4-1・§9参照）
- LLMによる構造化（カテゴリ分類・対象企業抽出・対象業種抽出・影響方向判定・影響期間判定・重要度算出・信頼度算出）
- **重要度のルールベース補正**（決算・M&A・FOMC等の重大イベントカテゴリに対する最低重要度の担保。§4-2参照）
- ニュース鮮度情報（`published_at`／`age_hours`）の付与
- ニュースキャッシュ管理（重複構造化の回避）
- `StructuredNewsItem`の生成とスキーマバリデーション

**非責務（Layer2以降が担う）**：
- ニュース軸スコアの数値計算（重要度×信頼度×時間減衰係数の掛け算、50点基準の加減点）は**Layer2 `news_scorer.py`の責務**。Layer3はスコアを一切算出しない。
- **銘柄単位の`uncertainty`（複数記事間の評価の割れ具合）の算出**：これは複数記事を横断して集計する処理であり**Layer2 `news_scorer.py`の責務**。Layer3は個々の記事について§8の`confidence`（情報源の一次性・公式性という記事単位の信頼度）を算出するのみで、記事横断の不確実性評価は行わない。
- 時間減衰係数そのものの適用（Layer3は`age_hours`という事実データのみを渡す。「14日超は0.1倍にする」等の評価ポリシーはLayer2側）
- **投資判断（買い・売り・様子見）、投資配分、最終的な投資推奨の信頼度（confidence）決定**：これらは**Layer5の責務**であり、Layer3では一切行わない。§8の`confidence`はあくまで「この記事がどの程度信頼できる情報源か」という記事単位の指標であり、Layer5が最終出力する投資推奨の信頼度（0-100、Ver1原則の「信頼度50未満は様子見」の対象）とは**別概念**である。両者を混同しないよう、フィールド名・使用箇所を明確に分離している。
- 銘柄選定・母集団スクリーニング（Layer2 `screener.py`の責務）
- ティッカーの正規化・銘柄マスタ管理（`config/universe.yaml`はLayer1/Layer2が管理し、Layer3は参照するのみ）

> **Layer5設計書との整合性確認により追加**：「Layer3はニュース情報の収集・構造化・不確実性評価（記事単位の情報源信頼度`confidence`の算出まで）を担当する。銘柄横断の`uncertainty`集計、投資判断（買い・売り・様子見）、投資配分、投資推奨としての信頼度決定はLayer5（および一部Layer2）の責務であり、Layer3では実施しない。」

---

## 2. モジュール構成

```
src/news_processing/
├── fetcher.py                # NewsRepository経由でのニュース取得
├── deduplicator.py           # 重複ニュース除去
├── preprocessor.py           # 記事本文の前処理（HTML除去・正規化・トリミング）
├── quality_filter.py         # 【新設】記事品質フィルタ（LLM構造化前のゴミデータ除去、§4-1）
├── freshness.py              # published_at → age_hours の計算・付与
├── llm_structurer/
│   ├── base.py                # NewsStructurer 抽象クラス
│   ├── claude_structurer.py
│   ├── gpt_structurer.py
│   ├── gemini_structurer.py
│   └── local_llm_structurer.py  # 将来のローカルLLM対応用の枠のみ
├── importance_rules.py       # 【新設】重要度のルールベース補正（§4-2）
├── cache_manager.py          # 処理済み記事のキャッシュ管理（Google Drive連携）
├── schema.py                 # StructuredNewsItemのスキーマ定義・バリデーション
└── main.py                    # Layer3パイプラインのエントリポイント
```

`prompts/news_structuring_prompt_template.md`（プロンプトの一元管理、§7参照）も本層の一部として管理する。

---

## 3. Repositoryとの接続

- Layer3は、Layer1が提供する`NewsRepository`（`FallbackChainRepository`でNewsAPI→GDELT→Web検索を束ねたもの）を**唯一の取得経路**とする。Layer3自身はどのAPIが実際に使われたかを意識しない（Layer1のRepositoryパターンの原則を継承）。
- `NewsRepository.fetch_news(query_or_tickers, since, until) -> List[RawNewsItem]`をそのまま呼び出す。戻り値には`DataFetchMeta`（`source_used`：newsapi/gdelt/web_search_fallbackのいずれか）が付随しており、Layer3はこれを`StructuredNewsItem.source_data_origin`にそのまま転記する（Ver2「使用したデータソースの保存」要件、Layer1 run_logとの整合）。
- NewsAPIが`environment: development_only`である点（Layer1確定事項）は、Layer3の実装には影響しない。Layer3はどのソースが使われたかを意識せず一律に処理する設計であるため、**本番運用でNewsAPI経由の記事がほぼ来ない**という実態はLayer1側のconfigで制御され、Layer3コードの変更は不要。

---

## 4. ニュース取得フロー

1. **取得範囲の決定**：前回実行時刻（`last_run_completed_at`、Google Driveの実行ログから取得）を`since`とする。初回実行時やログ欠落時は直近48時間をフォールバック取得範囲とする。
2. **クエリの分割**：全銘柄を毎回クエリするとAPI消費が膨大になるため、以下2種類のクエリに分ける。
   - (a) 主要指数・マクロ全般クエリ（日経平均、S&P500、FOMC、日銀等の固定キーワードセット）
   - (b) 当日のスクリーニング候補銘柄クエリ（Layer2 `screener.py`のフィルタ通過銘柄、および前日以前から追跡中の保有銘柄。Layer1詳細設計書の母集団と同期）
3. **取得**：`fetcher.py`が`NewsRepository.fetch_news()`を(a)(b)それぞれに対し呼び出す。
4. **重複除去**（`deduplicator.py`）：
   - 記事URLの正規化（クエリパラメータ除去、末尾スラッシュ統一等）後のハッシュによる完全一致除去
   - 見出しの簡易類似度（例：正規化後の文字列に対するJaccard係数等）が閾値超過の記事は「実質同一記事」として1件にまとめる（同一ニュースが複数媒体に転載されるケースへの対応）
5. **前処理**（`preprocessor.py`）：HTML/JSタグ除去、文字コード統一、極端に長い本文は先頭部分＋キーワード周辺のみへトリミング（LLM入力トークン削減、§12参照）
6. **記事品質フィルタ**（`quality_filter.py`、新設）：前処理済みの本文に対し、LLMに送る価値があるかを機械的に判定する。基準を満たさない記事はLLM構造化に進まず、ここでスキップする（§4-1）。
7. **鮮度付与**（`freshness.py`）：`published_at`から現在時刻までの経過時間を`age_hours`として計算し付与
8. **キャッシュ確認**（`cache_manager.py`）：記事の正規化ハッシュが既に処理済みであれば、LLM構造化をスキップし、キャッシュ済みの`StructuredNewsItem`を再利用する（ただし`age_hours`は現在時刻基準で再計算し直す。鮮度は日々変わる値のため、これだけはキャッシュ対象外で毎回再計算）
9. **LLM構造化**（`llm_structurer`）：品質フィルタを通過し未処理の記事のみをLLMに渡し、構造化する（§6・§7）
10. **重要度のルールベース補正**（`importance_rules.py`、新設）：LLMが算出した`importance`に対し、決算・M&A・FOMC等の重大イベントカテゴリの最低重要度を担保する補正を適用する（§4-2）。
11. **スキーマバリデーション**（`schema.py`）：`news_schema_version`に基づき出力を検証。不正な場合は§9のエラー処理へ
12. **キャッシュ登録**：新規に処理した記事のハッシュと`StructuredNewsItem`をGoogle Driveへ書き戻す
13. **Layer2への引き渡し**：同一のGitHub Actions run内であれば、プロセス内でLayer2にそのまま渡す。runを跨ぐ場合はGoogle Drive上の`snapshots/`に含めて永続化する（Layer1・Layer4の永続化方針と統一）。

### 4-1. `quality_filter.py`（記事品質フィルタ、新設・重要）

LLM構造化は記事1件あたり確実にコストが発生するため、明らかに情報価値の無い記事をLLMに送る前に機械的に除外する。これによりコスト削減だけでなく、**低品質な入力による`importance`・`confidence`のブレを未然に防ぐ**（ゴミデータに対してLLMがもっともらしい数値を返してしまうこと自体を防止する狙い）。

```yaml
# config/quality_filter.yaml
min_body_length_chars: 100    # 前処理後の本文文字数がこれ未満なら除外
reject_title_only: true       # 本文が空でタイトルのみの記事は除外
reject_fetch_failure: true    # Layer1側で本文取得に失敗した記事（RawNewsItemにbodyが無い等）は除外
ad_page_detection:
  enabled: true
  keyword_patterns: ["広告", "PR企画", "スポンサードコンテンツ", "[Sponsored]"]  # 簡易ヒューリスティック、初期実装は正規表現ベース
```

除外された記事は`StructuredNewsItem`を生成せず、`item_id`・除外理由（`reason_code`：`FILTER_BODY_TOO_SHORT`／`FILTER_TITLE_ONLY`／`FILTER_FETCH_FAILURE`／`FILTER_AD_PAGE`）のみをrun_logに記録する（Ver2「除外理由の完全保存」の趣旨をニュース処理層でも徹底し、静かに捨てない）。

### 4-2. `importance_rules.py`（重要度のルールベース補正、新設）

LLMによる`importance`算出は、同じ重大性の記事でも実行タイミングやモデルの気まぐれで日によって評価がブレるリスクがある。これを緩和するため、決算・M&A等の客観的に重大と言えるカテゴリについては、LLMの出力を上書きするのではなく**下限（フロア）を設ける補正**を適用する。

```yaml
# config/importance_rules.yaml
category_importance_floor:
  earnings: 70
  ma_deal: 70
  guidance_revision: 70
  fomc: 70
  cpi: 70
  employment_stats: 70
default_floor: 0   # 上記以外のカテゴリはLLMの算出値をそのまま使用
```

適用ロジック：`final_importance = max(llm_importance, category_importance_floor.get(category, default_floor))`。補正が発生した場合、`StructuredNewsItem`に`importance_llm_raw`（LLMの元の値）と`importance_source: "rule_floor_applied"`を記録し、補正の事実を隠蔽しない（§8参照）。

---

## 5. キャッシュ戦略

- **目的**：同一記事を複数日にわたって重複構造化しない（LLM呼び出しコストの削減が主目的。ニュース自体は日々新しく出るため、Layer1の価格データのような「無期限キャッシュがそのまま効く」構造ではない）。
- **キャッシュキー**：正規化URL＋見出し文字列のハッシュ（軽微な本文更新は別記事として扱う設計。§11で後述する再取得時の扱いにも関連）。
- **保存先**：Google Drive（Layer1確定方針「GitHubにはデータを保存しない」を継承）。`news_cache/processed_articles_index.json`（ハッシュ→`StructuredNewsItem`のマッピング）として保存し、日次でしまい込みすぎないよう、90日以上前のエントリは定期的にアーカイブ（別ファイルへ移動）する。
- **TTLの考え方**：構造化結果自体（カテゴリ・対象企業等）にはTTLを設けない（一度確定した分類は変化しないため）。**鮮度情報（`age_hours`）だけは常に再計算**し、キャッシュから読み出す都度、現在時刻基準の値に更新してからLayer2へ渡す。
- **重複排除とキャッシュの関係**：`deduplicator.py`（当日内の重複除去）と`cache_manager.py`（日をまたいだ重複構造化回避）は役割が異なる。前者は「今日取得した記事同士」の重複、後者は「過去に既に処理した記事」の重複を扱う。

---

## 6. LLM呼び出し設計

- **抽象インターフェース**：`NewsStructurer`抽象クラスを定義し、`structure(article: PreprocessedArticle) -> StructuredNewsItem`のシグネチャで統一する。具体実装として`ClaudeStructurer`／`GPTStructurer`／`GeminiStructurer`／（将来枠）`LocalLLMStructurer`を用意する。Ver2「LLM交換可能設計」で定義した`AIJudge`（Layer5）と同じ抽象化パターンを、Layer3にも一貫して適用する。
- **使用モデルの選定方針**：構造化は「狭い範囲の情報抽出」であり高度な推論を要しないため、**各社の最も安価な小型モデル**（例：Claude Haiku系、GPT-4o-mini系、Gemini Flash系）を標準採用し、コストを抑える（§12で詳述）。Layer5の最終投資判断に使う（相対的に上位の）モデルとは意図的に分離する。
- **構造化出力の強制**：各社のstructured output機能（JSON Schema準拠出力・Tool呼び出し等）を用いて`StructuredNewsItem`のスキーマに厳密準拠させる。自由文からのパースには依存しない。
- **バッチ／並列化**：複数記事をまとめて処理できる場合はバッチ化し、レイテンシとAPI呼び出し回数を削減する。
- **切替方法**：`config/ai_provider.yaml`（Layer2/Layer5と共通の設定ファイルに`news_structurer`セクションを追加する形）で使用するベンダー・モデルを指定する。コード変更なしでの切替を可能にする。

```yaml
# config/ai_provider.yaml（Layer3関連部分の追記イメージ）
news_structurer:
  provider: claude          # claude / gpt / gemini / local
  model: claude-haiku-lite  # 実際のモデルIDは実装時に確定
  batch_size: 5
```

---

## 7. プロンプト設計方針

- プロンプトは`prompts/news_structuring_prompt_template.md`として一元管理し、全ベンダー実装（`*_structurer.py`）が共通で読み込む。プロンプトの実質的な指示内容をベンダー間で共有することで、モデルを切り替えても抽出結果の一貫性を保つ。
- プロンプトに含める要素：
  1. 記事本文（前処理・トリミング済み）
  2. **対象ユニバースの制約**：当日のスクリーニング候補銘柄リスト・業種マスタを渡し、「このリストの中から該当するものだけを選ぶ」制約付き抽出にする（自由記述による銘柄名のゆらぎ・誤認識・ハルシネーションを防止）。リストに無い銘柄・業種に言及する記事は、`affected_companies`を空、`affected_sectors`のみで処理する。
  3. **カテゴリの列挙型**：決算／金利／政策／地政学／AI／半導体／企業不祥事／その他、のように固定の選択肢から選ばせる（自由記述にしない）。
  4. **影響方向・影響期間の列挙型**：`positive`/`negative`/`neutral`、`short_term`/`mid_term`/`long_term`に固定。
  5. **重要度・信頼度の採点基準の明示**：重要度は「株価・市場への影響範囲の広さ」、信頼度は「情報源の一次性・公式性（例：決算短信等の一次情報＞大手報道機関＞二次的なまとめ記事）」を基準とする旨をプロンプトに明記し、モデル間・記事間でのブレを最小化する。
- プロンプト自体はモデル固有のAPI仕様（メッセージフォーマット等）に依存しないプレーンテキストとして管理し、各`*_structurer.py`が自社のAPI呼び出し形式にラップする層を担う。

---

## 8. StructuredNewsItem JSONスキーマ

```json
{
  "news_schema_version": "1.0",
  "item_id": "sha256:9f1c2a...",
  "headline": "キオクシアHD、特許訴訟で巨額賠償の観測からストップ安",
  "source_name": "株探",
  "source_url": "https://s.kabutan.jp/news/n202607170376/",
  "source_data_origin": "gdelt",
  "published_at": "2026-07-17T06:10:00Z",
  "fetched_at": "2026-07-18T06:02:11Z",
  "age_hours": 23.9,
  "category": "corporate_legal",
  "affected_companies": [
    { "ticker": "285A", "name": "キオクシアホールディングス", "relevance": "primary" },
    { "ticker": "8035", "name": "東京エレクトロン", "relevance": "secondary" }
  ],
  "affected_sectors": ["semiconductor", "semiconductor_equipment"],
  "impact_direction": "negative",
  "impact_horizon": "short_term",
  "importance": 82,
  "importance_llm_raw": 82,
  "importance_source": "llm",
  "confidence": 0.85,
  "confidence_reason": "大手報道機関・専門ニュースサイト複数で同一内容を確認",
  "summary": "特許訴訟に関する巨額賠償の観測から、キオクシアHDがストップ安。半導体関連株全般に売り波及。",
  "llm_provider": "claude",
  "llm_model": "claude-haiku-lite",
  "structuring_status": "success"
}
```

**`summary`の文字数制限（確定）**：`summary`は**80文字以内**とする。プロンプト側で明示的に指示し、`schema.py`のバリデーションでも80文字超過時は末尾を切り詰める（トークン消費の安定化、Layer5へ渡す際のプロンプト予算＝Layer2 `json_builder.py`の`prompt_budget`との整合を取るため）。

**重要度のルールベース補正の記録（§4-2関連）**：`importance`はルール補正後の最終値、`importance_llm_raw`はLLMが算出した元の値。両者が異なる場合は`importance_source: "rule_floor_applied"`となり、`category_importance_floor`によって下限が適用されたことを示す。補正が無い場合は`importance_source: "llm"`。

### 8-1. フィールド説明・設計意図

- `news_schema_version`：Layer3が現在使用している`schema.py`のスキーマバージョンをそのまま出力する（§8-2で判定ルールの全体像を定義）。Layer3自身は互換性判定を行わない（判定はLayer2の責務）。将来スキーマにフィールドを追加する場合はマイナーバージョンを増分（例：`1.0`→`1.1`）し、既存フィールドの意味を変える・必須フィールドを削除する等の破壊的変更を行う場合のみメジャーバージョンを増分する（例：`1.0`→`2.0`）。この使い分けの徹底自体がLayer2側の後方互換ロジックが正しく機能するための前提となる。
- `item_id`：正規化URL＋見出しのハッシュ。キャッシュキーと同一の値を用いる。
- `source_data_origin`：Layer1のRepositoryチェーンで実際に使われたソース（`newsapi`/`gdelt`/`web_search_fallback`）。Ver2「使用したデータソースの保存」要件を満たす。
- `published_at`／`age_hours`：ご指示の通り、鮮度情報をLayer3が付与する。`age_hours`はキャッシュから読み出す都度、現在時刻基準で再計算する（§5）。
- `affected_companies`：配列形式とし、1記事が複数銘柄に影響する場合（例：セクター全体のニュース）に対応。`relevance`（primary/secondary）で影響の強弱を区別し、Layer2が「どの銘柄の`news`項目に含めるか」を判定する材料にする。
- `structuring_status`：`success`／`fallback_default`（§9のフォールバック発動時）／`skipped`（§9のスキップ時）のいずれか。Layer2・run_logの両方で、この記事の構造化結果がどの程度信頼できるかを判断する材料にする。
- `importance`／`importance_llm_raw`／`importance_source`：§4-2のルールベース補正の透明性を担保するための3点セット。Layer2・人間レビューの双方が「LLMの生の判断」と「ルール補正後の最終値」を区別して検証できる。

### 8-2. `news_schema_version`の互換性判定ルール（Layer2⇔Layer3の契約、★★★★★必須）

将来Layer3のスキーマが`1.0`→`1.1`→`2.0`のように拡張されていく前提で、Layer2・Layer3間の互換性判定ルールを以下の通り明確化する（判定ロジック自体の実装・保持はLayer2側。Layer2詳細設計書§3-6・§9を参照）。

- **Layer2**は、対応済みバージョン一覧`supported_schema_versions`と、受け入れ可能なメジャーバージョン`accept_major_version`を持つ（`config/schema_compatibility.yaml`）。
- **Layer3**は、`schema.py`が定義する現在のスキーマバージョンを`news_schema_version`としてそのまま出力する（Layer3はLayer2が何を`supported`としているかを意識しない）。
- **Layer2**は、受け取った`news_schema_version`について次のように判定する。
  - メジャーバージョンが`accept_major_version`と一致する場合：受け入れる。`supported_schema_versions`に完全一致する値が無くても（例：Layer3出力が`1.1`でLayer2の`supported_schema_versions`が`["1.0"]`のみの場合でも）、メジャーが一致していれば処理を継続し、未知のフィールドは無視する。
  - メジャーバージョンが不一致の場合（例：Layer3出力が`2.0`でLayer2の`accept_major_version: 1`）：**`SchemaVersionError`**として扱い、当該記事の構造化結果を破棄し、`severity: critical`でrun_logに記録する（Layer2詳細設計書§3-6参照）。

具体例：

| Layer2の`supported_schema_versions` | Layer3出力の`news_schema_version` | 判定 |
|---|---|---|
| `["1.0", "1.1"]` | `1.0` | 受理（完全一致） |
| `["1.0", "1.1"]` | `1.1` | 受理（完全一致） |
| `["1.0"]`のみ | `1.1` | 受理（メジャー一致、未知フィールドは無視） |
| `["1.0", "1.1"]` | `2.0` | `SchemaVersionError`（メジャー不一致） |

この表・判定ルールにより、Layer3側で将来マイナーバージョンを上げるだけであれば、Layer2側のconfig更新（`supported_schema_versions`への追記）は必須ではなく、任意のタイミングで追従すればよい（メジャー一致である限り処理は継続されるため）。メジャーバージョンを上げる変更（破壊的変更）を行う場合のみ、Layer2側の`accept_major_version`更新と、両層の同時デプロイが必要になる。

---

## 9. エラー処理

| 事象 | 対応 |
|---|---|
| ニュース取得自体の失敗（0件） | Layer1 Repositoryの責務でハンドリング済み。Layer3は「対象記事0件」として正常終了し、当日該当ニュース無しとして扱う（Layer2 news_scorer.pyのデフォルト50点ロジックにつながる） |
| 記事品質フィルタによる除外（§4-1） | エラーではなく正常系。`StructuredNewsItem`は生成せず、`reason_code`（`FILTER_BODY_TOO_SHORT`等）のみをrun_logに記録し、LLM構造化には進めない |
| LLM構造化のタイムアウト・5xx | §11のリトライ後、なお失敗する場合は当該記事の構造化をスキップし、`structuring_status: skipped`として記録。1記事の失敗でパイプライン全体を止めない |
| LLM出力のスキーマ違反（列挙型外の値等） | プロンプトにスキーマ違反箇所を指摘して1回再試行。それでも失敗する場合は`category: "other"`、`confidence`を大きく下げた値（例：0.2）にフォールバックし、`structuring_status: fallback_default`として記録 |
| 対象ユニバースに一致する銘柄が0件の記事 | エラーではなく正常系。`affected_companies`を空配列、`affected_sectors`またはマクロ関連フラグのみで処理継続 |
| APIキー認証エラー（LLM側） | Layer1と同様、`severity: critical`としてrun_logに記録し、当日のニュース処理を全体的に「機能低下」としてマークする（Layer5・レポートに「ニュース分析が一部/全面的に機能していない日」であることが伝わるようにする） |

---

## 10. レート制限対応

- ニュース取得APIのレート制限（NewsAPI 100/日、GDELT等）は**Layer1 Repositoryの責務**であり、Layer3はそれを意識しない。
- LLM構造化API側のレート制限（各社のRPM/TPM）は、Layer1で設計した共通の`RateLimiter`ユーティリティ（Layer1詳細設計書§6）をLayer3の`llm_structurer`にも再利用する。
- 想定記事件数（主要指数関連＋当日候補銘柄関連、合計で1日あたり概算50〜150件程度）に対し、選定したLLMベンダーのレート制限内に収まるよう、バッチサイズ・並列数を`config/ai_provider.yaml`の`batch_size`で調整する。
- 万一その日の記事件数がレート制限を大きく超える場合は、`importance`の推定に使える簡易ヒューリスティック（例：見出しのキーワードマッチ）で優先順位を付け、上位から処理し、処理しきれなかった記事は`structuring_status: skipped`として扱う（全記事を処理できないこと自体をrun_logに記録し、隠蔽しない）。

---

## 11. 再試行設計

| エラー種別 | リトライ方針 |
|---|---|
| 一時的エラー（タイムアウト、5xx） | 指数バックオフ（1秒→2秒→4秒、最大3回） |
| レート制限（429） | `Retry-After`ヘッダーがあれば従う。無ければ固定30秒待機後に1回リトライ。それでも失敗ならスキップ（§9） |
| スキーマ不整合 | プロンプトに違反箇所を追記して1回のみ再試行。それでもダメならデフォルトフォールバック（§9） |
| キャッシュ書き込み失敗（Google Drive側） | 当該runの終了時に1回だけ再試行。失敗してもパイプライン自体は正常終了とし、次回runで再取得・再構造化される（多少のコスト増を許容し、可用性を優先） |

---

## 12. コスト最適化

- **記事品質フィルタ（最重要）**：本文文字数不足・タイトルのみ・本文取得失敗・広告ページをLLM構造化前に除外する（§4-1）。コスト削減効果に加え、低品質入力による`importance`/`confidence`のブレを防ぐ副次効果がある。
- **モデル選定**：安価な小型モデルを標準採用（§6、Claudeの小型モデルを既定として確定）。
- **キャッシュ**：重複記事の再構造化を回避（§5）。
- **クエリ範囲の限定**：全銘柄ではなく、主要指数・マクロ全般＋当日のスクリーニング候補銘柄に限定（§4）。
- **本文トリミング**：前処理段階で不要な長文を削り、入力トークンを削減（§4-5）。
- **バッチ処理**：複数記事の同時処理でAPI呼び出し回数を削減（§6）。
- **コスト監視**：Layer1の`run_logger`と同様の仕組みで、LLM呼び出し回数・概算トークン消費量を記録し、Ver2の運用成績ダッシュボードと合わせて可視化する（想定を超えるコスト増加を早期に検知する）。

---

## 13. テスト方針

| 対象 | テスト内容 |
|---|---|
| `deduplicator.py` | 完全一致重複・類似見出し重複のテストケースで正しく1件にまとめられること |
| `preprocessor.py` | HTML除去・文字コード正規化・トリミングが期待通り動くこと |
| `quality_filter.py` | 本文100文字未満・タイトルのみ・本文取得失敗・広告ページのキーワードパターンのそれぞれで正しく除外されること、正常な記事が誤って除外されないこと（偽陽性のテスト） |
| `importance_rules.py` | `category_importance_floor`で定義したカテゴリでLLMの値が下限未満の場合に補正されること、下限以上の場合は補正されずLLMの値がそのまま使われること、`importance_llm_raw`/`importance_source`が正しく記録されること |
| `freshness.py` | `published_at`からの`age_hours`計算がタイムゾーンを含めて正確であること |
| `llm_structurer`（各実装） | モックLLMレスポンスを用い、スキーマ準拠の出力が得られること、スキーマ違反時のフォールバックが動くこと |
| ベンダー横断一貫性テスト | 同一記事を`ClaudeStructurer`/`GPTStructurer`/`GeminiStructurer`に通し、出力の**形式**（スキーマ準拠性）が一貫していること（内容の完全一致までは求めない） |
| `cache_manager.py` | 同一記事の2回目の処理でLLM呼び出しがスキップされること、`age_hours`のみ再計算されること |
| 統合テスト（Layer2との接続） | 実際の過去記事サンプルを用いてLayer3を通しで実行し、出力`StructuredNewsItem`一式がLayer2 `news_scorer.py`にそのまま投入可能な形式であることをend-to-endで確認 |
| `news_schema_version`互換性（§8-2） | Layer3が異なるマイナーバージョン（例：`1.1`）を出力した際、Layer2側が`supported_schema_versions`に完全一致が無くてもメジャー一致で受理すること、メジャー不一致（`2.0`）では`SchemaVersionError`になることをLayer2側と合わせて結合テストで確認 |

---

## 14. 確定事項（旧・未決事項への回答を反映）

1. **初期LLM**：Claudeの小型モデルを初期採用として確定。Layer5でもClaude系を利用する予定であり運用を統一できること、JSON出力精度が高いこと、構造化用途では十分な性能であることを理由とする。`config/ai_provider.yaml`の変更のみでGPT・Geminiへ将来切替可能な抽象化（§6）はそのまま維持する。
2. **ニュース取得範囲**：「主要指数・マクロ全般（FOMC・雇用統計・CPI等は固定クエリ）」＋「当日のスクリーニング候補銘柄」＋「保有銘柄」を対象とすることで確定（§4）。日経225/S&P500全銘柄を毎日取得対象にすると、API利用量・LLMコスト・ノイズ記事が急増するため、Layer2で先に絞り込んだ候補に対象を限定する現在の設計を維持する。
3. **利用規約**：実装前に利用規約を確認することを前提に、以下を原則として確定する：①APIから正式取得した本文のみ利用する、②Web検索フォールバックでは本文取得可否を都度確認する、③robots.txt・利用規約に反するスクレイピングは行わない、④本文全文を保存せず必要最小限（`summary`等）のみ保持する。この原則は`quality_filter.py`（§4-1、本文取得失敗時は除外）とも整合する。
4. **`affected_companies`の粒度**：初期実装では直接言及された企業のみを対象とすることで確定。サプライチェーン・親会社・子会社への波及はLLM判断の揺れが大きく誤検知が増えるため採用しない。業界全体への影響は`affected_sectors`で表現する。将来Knowledge Graph等を導入する場合のみ、二次影響の評価対象への追加を検討する。

---

## 15. Layer5との整合性確認レビュー（今回実施分）

Layer5詳細設計書作成に伴い、「Layer5を正しく動作させるために必要な最低限の修正」の観点でのみレビューを実施した。ニュース取得方法・LLMモデル選定方針・プロンプト設計思想・ニュース分類ロジック・Layer3内部処理フローは一切変更していない。

| # | 確認項目 | 結果 | 修正前 | 修正後 | 修正理由 |
|---|---|---|---|---|---|
| 1 | `news_score`フィールドの存在 | **追加不要と判断** | 存在しない | （変更なし） | `news_score`は複数記事を横断集計するLayer2 `news_scorer.py`の出力であり、記事単位で処理するLayer3が持つべき値ではない。追加すると既存の責務分離（Layer3は数値スコアを算出しない）に反するため見送り |
| 2 | `uncertainty`/`uncertainty_reason`フィールドの存在 | **追加不要と判断** | 存在しない | （変更なし） | 同上の理由で、銘柄単位の評価の割れ具合はLayer2の集計処理でしか算出できない（記事1件からは算出不能な概念）。Layer3は算出に必要な入力（記事単位の`confidence`・`importance`・`impact_direction`）を提供済み |
| 3 | `sentiment`フィールドの存在 | **追加不要と判断** | 存在しない | （変更なし） | 既存の`impact_direction`（positive/negative/neutral）が同じ役割を果たしており、別名での重複フィールドを追加するとスキーマが冗長になる。意図的に別概念（例：文章のトーンと市場影響の方向を区別したい等）であればご指示ください |
| 4 | `impact_direction`フィールドの存在 | 既に充足 | （変更なし） | （変更なし） | 既存スキーマに存在済み |
| 5 | `reason_code`フィールドの存在 | **追加不要と判断** | 記事自体には無いが`category`が存在 | （変更なし） | Layer2側が`category`から`NEWS_{category}`形式の`reason_code`を導出する設計が既に確立しており（Layer2詳細設計書§5-1の例）、Layer3側に重複したコード生成ロジックを持たせる必要はない |
| 6 | Layer3/Layer5間の責務境界の明記 | **要修正** | 責務境界の明文化が無く、`confidence`（記事単位の情報源信頼度）と投資推奨の信頼度が混同されうる書き方だった | §1に「Layer3は記事単位の情報源信頼度`confidence`までを担当し、銘柄横断の`uncertainty`集計・投資判断・投資推奨の信頼度決定はLayer5（一部Layer2）の責務」と明記 | ご提示の文言をそのまま追記すると、既存の`confidence`/`confidence_reason`フィールド（記事単位の情報源信頼度、既存設計で確立済み）が「Layer3では実施しない」対象と誤読されうるため、両者を区別する形に精緻化した |

**結論**：ご提示の6項目チェックのうち、5項目は既存設計で既に責務分離を保ったまま充足済みであり、スキーマへの追加は不要と判断した（追加すると責務分離が崩れるため、あえて追加しないことが正しい対応）。実際に追加したのは責務境界の明文化（項目6）のみで、ニュース取得方法・LLMモデル選定方針・プロンプト設計思想・ニュース分類ロジック・内部処理フローには一切手を加えていない。

本書はこれでVer1.3として確定とし、次はLayer1〜Layer5の責務分離の最終確認を行う。
