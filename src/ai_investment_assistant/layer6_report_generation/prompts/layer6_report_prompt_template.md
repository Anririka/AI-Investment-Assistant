# Layer6 レポート生成層 実行手順テンプレート

本テンプレートは `layer6_report_generation_design.md` §0・§3の確定仕様と、
`layer5_ai_judgment/prompts/layer5_judgment_prompt_template.md` §6-0で確立された
「Google Drive MCPコネクタ方式」を踏襲する。2026-07-26、Layer5に続きLayer6の
実データ初回検証を行い、本テンプレートの内容で最後まで実行できることを確認済み
（`local_drive_client.py`・`cli_local.py`のdocstring参照）。

**重要（2026-07-26、2回の実地検証を経て確定した制約）**：当初は「本日の提案」を
.xlsx（4タブ）として組み立て、アップロード時にGoogle Sheets形式へ自動変換させる
方式を想定していたが、(1) このコネクタは.xlsx→Sheetsの自動変換アップロードに対応
しておらず、(2) `disableConversionToGoogleType=true`で.xlsxのまま保存する代替策も、
1万文字を超えるbase64文字列をエージェントがテキストとして正確に再現できず、
アップロード後にzip破損（"CORRUPTED"エラー）を起こすことが実地検証で判明した。
そのため**タブごとに1つのCSVファイルとして書き出し、CSV→Google Sheets自動変換で
個別のネイティブSheetsファイルとしてアップロードする方式**に変更した（§2-3参照。
CSVはテキストのため`textContent`経由でアップロードでき、base64を経由しないため
上記の破損リスクが構造的に発生しない）。

## 0. あなたの役割

Layer6はLayer5と異なり、AI判断（LLM推論）を一切行わない**純粋な決定的処理**である
（layer6_report_generation_design.md §1「非責務」参照）。あなたの役割は、Layer5が
確定したdecision JSONを受け取り、Bash/PythonツールでLayer6のロジックを呼び出し、
その結果（Markdownレポート・「本日の提案」CSV群・レポート履歴インデックス）を
`mcp__Google_Drive__*`ツールでGoogle Driveへ保存することのみであり、値の解釈・
再計算・判断は一切行わない。

Layer6はLayer5と同一のClaude Coworkセッション内で、Layer5の手順完了（decision JSON
のGoogle Driveアップロード、layer5_judgment_prompt_template.md §6-4）の直後に接続する
（§0）。

## 1. 前提

- 環境変数 `LAYER5_LOCAL_DATA_DIR` がLayer5の手順で既に設定済みであること（同じ
  ディレクトリをLayer6もそのまま使う。`Layer6LocalDriveClient`はこの配下に`reports/`
  を作成する）。
- Layer5が確定したdecision JSONオブジェクト（layer5_judgment_prompt_template.md §6-3
  手順6で組み立てたもの。ローカルパスは `decision_writer.py` の標準出力の`local_path`）
  が手元にあること。

## 2. 実行手順

### 2-1. 既存の`report_index_YYYYMM.json`の取得（あれば）

1. `mcp__Google_Drive__search_files`で
   `parentId = '$LAYER5_DRIVE_ROOT_FOLDER_ID' and title = 'reports'` を検索する。
   見つからない場合（初回実行）は、`mcp__Google_Drive__create_file`
   （`mimeType`相当として`contentMimeType`に`application/vnd.google-apps.folder`を指定）
   で`reports`フォルダを新規作成し、そのidを使う。
2. `reports`フォルダのid配下で、当日の**JST日付**（`{today}`、YYYYMMDD）から年月部分
   （`{year_month}`、YYYYMM）を求め、
   `parentId = '<reportsフォルダid>' and title = 'report_index_{year_month}.json'`
   を検索する。見つかった場合は`mcp__Google_Drive__download_file_content`で内容を
   取得し、Writeツールで`$LAYER5_LOCAL_DATA_DIR/reports/report_index_{year_month}.json`
   として保存する（見つからない場合はそのまま次へ進む。`Layer6LocalDriveClient`が
   「未検出」として新規作成扱いで正しく処理する）。複数見つかった場合は
   `createdTime`が最大のものを正とする（Layer1/4/5と同じ既存運用）。

### 2-2. Layer6本体の実行

```
python -m ai_investment_assistant.layer6_report_generation.cli_local <decision.jsonのファイルパス>
```

標準出力にJSONで以下が返る：

```json
{
  "status": "ok",
  "sink_results": {
    "google_sheets": {
      "本日の提案": "/path/to/reports/提案ログ_YYYYMMDD/本日の提案.csv",
      "除外・不採用ログ": "/path/to/reports/提案ログ_YYYYMMDD/除外・不採用ログ.csv",
      "ルール適用ログ": "/path/to/reports/提案ログ_YYYYMMDD/ルール適用ログ.csv",
      "実行サマリー": "/path/to/reports/提案ログ_YYYYMMDD/実行サマリー.csv"
    },
    "markdown": "/path/to/reports/report_YYYYMMDD.md"
  },
  "sink_errors": {},
  "report_index_local_path": "/path/to/reports/report_index_YYYYMM.json",
  "report_index_file_name": "report_index_YYYYMM.json"
}
```

`status`が`"blocked"`（データ品質ゲートblocked）や`"error"`（decision JSON欠落・契約
違反）の場合、`sink_results`には`markdown`のみが含まれる（§10のエラー処理。この場合、
2-3の「本日の提案」アップロード手順はスキップし、Markdownのみアップロードする）。

### 2-3. Google Driveへのアップロード

1. **Markdownレポート**：2-2の`sink_results.markdown`のローカルファイルを読み、
   `mcp__Google_Drive__create_file`で`parentId`に`reports`フォルダid、`title`に
   `report_YYYYMMDD.md`（ローカルファイル名と同じ）、`textContent`にファイル内容、
   `contentMimeType`に`text/markdown`、`disableConversionToGoogleType`にtrueを指定して
   アップロードする。
2. **「本日の提案」（4ファイル、`status`が`"ok"`の場合のみ）**：`sink_results.
   google_sheets`は`{シート名: ローカルCSVパス}`の辞書。**この4件それぞれについて**、
   Readツールでローカルの.csv内容を読み、`mcp__Google_Drive__create_file`で
   `parentId`に`reports`フォルダid、`title`に`提案ログ_YYYYMMDD_{シート名}`
   （例：`提案ログ_20260726_本日の提案`。拡張子は付けない＝Sheets変換後のネイティブ
   ファイルとして保存する）、`textContent`にCSV内容（読んだテキストをそのまま）、
   `contentMimeType`に`text/csv`を指定してアップロードする。**`disableConversionToGoogleType`
   は指定しないこと**（デフォルトのconvert=trueのままにし、Google Sheetsへ自動変換
   させる）。

   **重要（アップロード方法についての厳守事項）**：この2-3手順2は、必ず「Readツールで
   ローカルCSVファイルの内容を読み、その内容をそのまま`textContent`に渡す」という
   手順で行うこと。CSVはUTF-8テキストであり`textContent`（base64を経由しない）で
   問題なくアップロードできる。**絶対に`base64Content`は使わないこと**（xlsx等の
   バイナリをbase64文字列としてエージェントが手作業でツール引数に書き起こすと、
   1万文字を超える場合に文字の取り違えが発生し、アップロード後のファイルが破損する
   ことが2026-07-26の実地検証で確認されている。詳細は`local_drive_client.py`
   モジュールdocstring参照）。
3. **レポート履歴インデックス**：2-2の`report_index_local_path`のローカルファイルを
   読み、`mcp__Google_Drive__create_file`で`parentId`に`reports`フォルダid、`title`に
   `report_index_YYYYMM.json`（2-1で使った`{year_month}`と同じ）、`textContent`に
   ファイル内容、`contentMimeType`に`application/json`、`disableConversionToGoogleType`
   にtrueを指定してアップロードする（既存ファイルへの上書き更新はコネクタでは行えない
   ため、常に新規作成し`createdTime`最大のものを正とする。`local_drive_client.py`
   モジュールdocstring参照）。

### 2-4. アップロード後の確認（推奨）

特に2-3手順2でアップロードしたファイルについては、`mcp__Google_Drive__
read_file_content`で内容を読み返し、行数・列数・値が期待通りであることを確認する
ことを強く推奨する（2026-07-26に実際にこの確認によってbase64経由アップロードの
破損が発覚した経緯があるため）。

## 3. 既知の制約・今後の課題

- 「本日の提案」はdesign書§6-1が想定する「1ファイル・4タブ」ではなく、**4つの
  独立したネイティブGoogle Sheetsファイル**（`提案ログ_YYYYMMDD_{シート名}`）として
  保存される（§2-3参照。CSV→Sheets変換は個別ファイルとしてのみ動作するため）。
- `report_index_YYYYMM.json`は「既存ファイルへの追記更新」ではなく「その時点の
  完全な累積内容を持つ新規ファイル」として月内に複数回作成されうる（Layer1/4/5の
  既存運用と同じ「`createdTime`最大が正」というルールに従う限り、実質的な内容は
  同じ）。
- 過去の実行（2026-07-26の1回目の実地検証）で、破損した.xlsxファイル
  （`提案ログ_20260726.xlsx`、および検証用の`test_upload.xlsx`・`test_minimal.xlsx`）
  がreportsフォルダに残存している場合がある。Drive MCPコネクタには削除機能が無いため、
  発見した場合はユーザーに手動削除を依頼すること。
