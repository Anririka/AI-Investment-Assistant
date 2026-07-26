"""ローカルファイルシステムをバックエンドとするLayer6 Drive/Sheets I/Oアダプタ
（Google Drive MCPコネクタ方式への移行。Layer5の`local_drive_client.py`と同じ考え方）。

Claude Coworkのスケジュールタスクが動くクラウドサンドボックスは、googleapis.com系
ドメインへの直接のネットワークアクセスをネットワークポリシーで遮断しているため、
`Layer6DriveClient`（google-api-python-client＋OAuthユーザー認証による直接API呼び出し。
Drive API・Sheets APIの両方を使用）はこの環境では機能しない（Layer5詳細設計書§0・
`layer5_ai_judgment/scripts/local_drive_client.py`のdocstringで実地検証済みの制約と同一）。

これに対応するため、実際のGoogle Drive・Google Sheetsとの読み書きは、Claude Cowork
セッション自身（AIエージェント）が`mcp__Google_Drive__*`ツール（このセッションに
接続済みのGoogle Driveコネクタ、ネットワーク遮断の影響を受けない）を使って行い、
その結果をこのクラスが期待するローカルディレクトリ構成に保存しておく（詳細は
`prompts/layer6_report_prompt_template.md`参照）。

重要な設計判断（Google Sheetsの代替手段。2026-07-26、2回の実地検証を経て確定）：

1回目の検証：Google Drive MCPコネクタには、Sheets API相当の「既存スプレッドシートの
特定タブへ値を書き込む」機能が無い（`mcp__Google_Drive__create_file`はファイル新規作成
のみ）ため、「本日の提案」ファイル（4タブ構成、layer6_report_generation_design.md
§6-1）をローカルで.xlsx（openpyxl、1タブ=1ワークシート）として組み立て、アップロード時
にGoogle Sheets形式へ自動変換させる方式を試みた。しかしこのコネクタは.xlsx→Google
Sheetsの自動変換アップロード自体に対応しておらず（"Invalid conversion requested"）、
やむなく`disableConversionToGoogleType=true`で.xlsxのまま保存する方式に変更した。

2回目の検証（重大な問題）：.xlsxのまま保存したファイルをユーザーがDrive上で開いたところ、
"CORRUPTED: ... zlib.error: invalid distance too far back"というzip破損エラーで開けない
ことが判明した。原因を調査した結果、Driveにアップロード後のファイルをダウンロードして
ローカル原本とチェックサムを比較したところ不一致だった（ファイルサイズは一致）。すなわち、
エージェント（Claude）が`mcp__Google_Drive__create_file`の`base64Content`引数へ.xlsxの
base64文字列（1万文字超）をテキストとして書き起こす過程で、1バイト以上の取り違えが発生し
ていたと判明した。長大なbase64文字列をエージェントの出力テキストとして正確に再現し続ける
ことは信頼できないため、**バイナリファイル（.xlsx等）をbase64経由でアップロードする方式
そのものを廃止**した。

代わりに、「本日の提案」の4タブ（本日の提案／除外・不採用ログ／ルール適用ログ／
実行サマリー）を、**タブごとに1つのCSVファイル（UTF-8プレーンテキスト）**として
ローカルに書き出す方式に変更した。CSVはテキストであり、`mcp__Google_Drive__create_file`
の`textContent`（base64を経由しない）でアップロードできるため、上記の取り違えリスクが
構造的に発生しない。かつCSV→Google Sheets自動変換（`disableConversionToGoogleType`を
指定しない、デフォルトのconvert=true）はこのコネクタで正常に動作することを実地検証済み
（アップロード直後に`read_file_content`で内容を確認し、意図通りの表として変換されている
ことを確認した）。

この結果、design書§6-1が想定する「1ファイル・4タブ」ではなく「4ファイル（それぞれが
1タブ相当のネイティブGoogle Sheets）」という構成になる（既知の制約・変更点として
`prompts/layer6_report_prompt_template.md`にも明記）。Markdownレポート・
`report_index_YYYYMM.json`（いずれもテキストで`textContent`アップロード）はこの問題の
影響を受けないため、方式変更は不要である。

いずれの方式でも、`main.py`・`sinks/*.py`・`formatters/*.py`・`history_writer.py`は一切
変更せず、`Layer6DriveClient`と同一の公開インターフェースを実装するだけで再利用できる
（Layer5と同じ「Repository抽象化のおかげで実行環境の差し替えがロジック非破壊で行える」
という設計原則を踏襲）。

`report_index_YYYYMM.json`について：実APIの`Layer6DriveClient.write_report_index_entry`は
「既存ファイルを読み込んで追記した内容で同一ファイルを更新（update）」するが、Drive MCP
コネクタには当該ファイルへの上書き更新機能が無い（作成のみ）。そのため、Layer1・Layer4・
Layer5が既に採用している「同名でも新規ファイルとして作成し、`createdTime`最大のものを
正とする」運用を踏襲する：エージェントは実行前に既存の`report_index_YYYYMM.json`を
（存在すれば）ダウンロードしてこのローカルディレクトリに配置しておき、このクラスが
その内容を読み込んで新エントリを追記した「完全な最新版」をローカルに書き出す。エージェントは
その内容で（同名の）新規ファイルをDriveへアップロードする。月内の1日ごとに1ファイルずつ
蓄積されるが、常に最新版が全エントリの累積を含む「完全版」であるため、実質的に同じ内容に
アクセスできる。

ローカルディレクトリ構成：

```
{base_dir}/
└── reports/
    ├── report_index_YYYYMM.json          # エージェントが実行前にMCPで取得して配置（あれば）
    ├── report_YYYYMMDD.md                 # MarkdownSinkが書き込み、エージェントがMCPでアップロード
    └── 提案ログ_YYYYMMDD/                  # GoogleSheetsSinkが書き込むCSV群（4ファイル、
        ├── 本日の提案.csv                    # タブごとに1ファイル）。エージェントが各CSVを
        ├── 除外・不採用ログ.csv               # mcp__Google_Drive__create_fileで個別に
        ├── ルール適用ログ.csv                 # アップロードし、それぞれ独立したネイティブ
        └── 実行サマリー.csv                   # Google Sheetsファイルとして変換保存される
```
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Optional


class Layer6LocalDriveClient:
    """Layer6DriveClientと同一の公開インターフェースを、ローカルファイルシステムに
    対して実装する（`base_dir`がGoogle Driveのroot folderに相当する。Layer5の
    LocalDriveClientと同じ`base_dir`を共有してよい＝同一Coworkセッションの
    `$LAYER5_LOCAL_DATA_DIR`をそのまま使い回せる）。
    """

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def _reports_dir(self) -> Path:
        d = self._base_dir / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- Markdownレポート ---------------------------------------------------------

    def write_markdown_report(self, file_name: str, text: str) -> str:
        """reports/{file_name} へMarkdownをローカル保存し、ローカルパスを返す。

        実際のGoogle Driveへのアップロードは、この戻り値のパスを使ってエージェントが
        `mcp__Google_Drive__create_file`（`textContent`、contentMimeType=
        "text/markdown"、disableConversionToGoogleType=true）で行う。テキストの
        `textContent`経由（base64を経由しない）のため、大きなバイナリのbase64転記で
        発生した破損リスク（モジュールdocstring参照）は生じない。
        """
        path = self._reports_dir() / file_name
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return str(path)

    # --- 「本日の提案」スプレッドシート（タブごとにCSV→Drive側でSheets自動変換） -----------

    def write_proposal_spreadsheet(self, file_name: str, sheets_data: dict) -> dict:
        """`sheets_data`（{シート名: [[ヘッダー行], [データ行], ...]}）を、シートごとに
        1つのCSV（UTF-8, `\\r\\n`改行のRFC4180準拠）としてローカルの
        `reports/{file_name}/`配下に書き出す（§6-1〜§6-5の4タブ相当）。

        戻り値は`{シート名: ローカルCSVパス}`の辞書（`Layer6DriveClient`本来の戻り値の
        型（str）とは異なるが、`main.py`はこの戻り値をそのまま`sink_results["google_sheets"]`
        へ格納するのみで型を検査しないため、呼び出し側のロジックは変更不要。CLIの標準出力
        ではこの辞書がJSONとしてそのまま出力される）。

        実際のGoogle Driveへのアップロードは、返された各CSVパスを使ってエージェントが
        `mcp__Google_Drive__create_file`（`textContent`、contentMimeType="text/csv"、
        `disableConversionToGoogleType`は**指定しない**＝デフォルトのconvert=trueのまま）
        で、シートごとに個別のファイルとしてアップロードする。これにより、シートごとに
        独立したネイティブGoogle Sheetsファイルとして保存される（CSV→Sheets変換は
        2026-07-26に実地検証済み。`textContent`経由のためbase64転記の破損リスクも無い。
        モジュールdocstring参照）。
        """
        base = self._reports_dir() / file_name
        base.mkdir(parents=True, exist_ok=True)

        paths = {}
        for sheet_name, rows in sheets_data.items():
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\r\n")
            for row in rows:
                writer.writerow(["" if v is None else v for v in row])

            csv_path = base / f"{sheet_name}.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                f.write(buf.getvalue())
            paths[sheet_name] = str(csv_path)

        return paths

    # --- レポート履歴インデックス ----------------------------------------------------

    def read_report_index(self, year_month: str) -> Optional[dict]:
        """reports/report_index_{year_month}.json をローカルから読み込む。

        実際のGoogle Drive上の最新版を参照するには、呼び出し側（Coworkエージェント）が
        事前に`mcp__Google_Drive__search_files`（`createdTime`最大のものを正とする既存
        運用）＋`download_file_content`でこのローカルパスに配置しておく必要がある
        （配置されていなければNoneを返し、新規作成として扱われる）。
        """
        path = self._reports_dir() / f"report_index_{year_month}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_report_index_entry(self, year_month: str, entry: dict) -> str:
        """reports/report_index_{year_month}.json に`entry`を追記した「完全版」を
        ローカルへ書き出し、ローカルパスを返す（§6-6）。

        実際のGoogle Driveへの反映は、エージェントがこの戻り値のパスの内容で
        （同名の）新規ファイルを`mcp__Google_Drive__create_file`（`textContent`経由）に
        よりアップロードする（既存ファイルの上書き更新はDrive MCPコネクタでは行えない
        ため、Layer1/4/5と同じ「新規作成＋createdTime最大が正」の運用を踏襲する。
        モジュールdocstring参照）。
        """
        existing = self.read_report_index(year_month) or {"entries": []}
        existing["entries"].append(entry)

        path = self._reports_dir() / f"report_index_{year_month}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return str(path)
