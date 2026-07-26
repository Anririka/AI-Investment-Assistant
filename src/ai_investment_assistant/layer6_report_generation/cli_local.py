"""Layer6をClaude Coworkセッション内で実行するためのCLIエントリポイント
（`local_drive_client.py`参照。Layer5の`scripts/decision_writer.py`のCLIパターンを踏襲）。

`main.py`の`run()`はライブラリ関数（decision_document・sinks・drive_clientを引数で
受け取る）であり、Layer6自体はCLIを持たない設計（layer6_report_generation_design.md
§2ではmain.pyを「エントリポイント」と呼ぶが、これは同一Coworkセッション内でBash/Python
ツールから直接呼び出される想定であり、独立CLIスクリプトの形は前提としていない）。

このモジュールは、エージェントがBashツールで
`python -m ai_investment_assistant.layer6_report_generation.cli_local <decision.jsonのパス>`
の形で呼び出せるよう、`Layer6LocalDriveClient`・`GoogleSheetsSink`・`MarkdownSink`の
組み立てのみを行う薄いラッパーである（`main.py`本体・`sinks/*.py`・`formatters/*.py`は
一切変更しない）。

標準出力には、各Sinkが実際に書き込んだローカルパス（Markdown・xlsx）と、
`reports/report_index_YYYYMM.json`のローカルパスをJSONで返す。実際のGoogle Drive
（Google Sheets自動変換含む）へのアップロードは、この結果を使ってエージェントが
`mcp__Google_Drive__create_file`で行う（`prompts/layer6_report_prompt_template.md`参照）。
"""

from __future__ import annotations

import json
import os
import sys

from . import main as layer6_main
from .local_drive_client import Layer6LocalDriveClient
from .sinks.google_sheets_sink import GoogleSheetsSink
from .sinks.markdown_sink import MarkdownSink


def run_cli() -> int:
    local_data_dir = os.environ.get("LAYER5_LOCAL_DATA_DIR")
    if not local_data_dir:
        print(json.dumps({"error": "LAYER5_LOCAL_DATA_DIR未設定"}, ensure_ascii=False))
        return 1

    input_path = sys.argv[1] if len(sys.argv) > 1 else None
    if input_path:
        with open(input_path, "r", encoding="utf-8") as f:
            decision_document = json.load(f)
    else:
        decision_document = json.load(sys.stdin)

    client = Layer6LocalDriveClient(base_dir=local_data_dir)
    sinks = [GoogleSheetsSink(client), MarkdownSink(client)]

    result = layer6_main.run(decision_document, sinks, client)

    # report_index_YYYYMM.jsonのローカルパスも併せて返す（アップロード対象のため）。
    # run_meta.layer5_completed_at（UTC）からJST日付を導出し、年月部分を取り出す。
    from .datetime_util import execution_date_jst

    try:
        date_str = execution_date_jst(decision_document["run_meta"])
        year_month = date_str[:6]
        index_path = str(client._reports_dir() / f"report_index_{year_month}.json")
        result = {**result, "report_index_local_path": index_path, "report_index_file_name": f"report_index_{year_month}.json"}
    except Exception:  # noqa: BLE001 — エラーレポート分岐等、run_metaが無い/不正なケースは無視
        pass

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "blocked") else 1


if __name__ == "__main__":
    sys.exit(run_cli())
