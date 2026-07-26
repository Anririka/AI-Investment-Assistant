"""Layer6LocalDriveClientのテスト（local_drive_client.py）。

2026-07-26の実地検証で、「本日の提案」を.xlsx(base64)としてアップロードする方式が
zip破損を起こすことが判明し、タブごとのCSV書き出しに変更した経緯を回帰的に検証する
（local_drive_client.pyモジュールdocstring参照）。
"""

import csv
import json

from ai_investment_assistant.layer6_report_generation.local_drive_client import Layer6LocalDriveClient


def test_write_markdown_report_writes_utf8_text(tmp_path):
    client = Layer6LocalDriveClient(base_dir=str(tmp_path))
    path = client.write_markdown_report("report_20260726.md", "# タイトル\n本文")

    with open(path, "r", encoding="utf-8") as f:
        assert f.read() == "# タイトル\n本文"


def test_write_proposal_spreadsheet_creates_one_csv_per_sheet(tmp_path):
    client = Layer6LocalDriveClient(base_dir=str(tmp_path))
    sheets_data = {
        "本日の提案": [["日付", "証券コード"], ["20260726", "7203"]],
        "実行サマリー": [["日付"], ["20260726"]],
    }

    result = client.write_proposal_spreadsheet("提案ログ_20260726", sheets_data)

    assert set(result.keys()) == {"本日の提案", "実行サマリー"}
    for sheet_name, path in result.items():
        assert path.endswith(f"{sheet_name}.csv")
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        assert rows == sheets_data[sheet_name]


def test_write_proposal_spreadsheet_preserves_long_japanese_text_without_corruption(tmp_path):
    """base64/xlsx経由で発生したbyte単位の破損リスクが、CSV/textContent経由では
    構造的に発生しないことを確認する回帰テスト。長い日本語テキストを含む値が
    往復（書き込み→読み込み）で完全に一致することを検証する。
    """
    long_reason = "RSIは53.1で健全な範囲、株価はVWAPを上回り乖離が拡大中。" * 5
    client = Layer6LocalDriveClient(base_dir=str(tmp_path))
    sheets_data = {"本日の提案": [["投資理由"], [long_reason]]}

    result = client.write_proposal_spreadsheet("提案ログ_20260726", sheets_data)
    with open(result["本日の提案"], "r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))

    assert rows[1][0] == long_reason


def test_write_report_index_entry_appends_to_existing(tmp_path):
    client = Layer6LocalDriveClient(base_dir=str(tmp_path))
    client.write_report_index_entry("202607", {"date": "20260725", "run_id": "a"})
    path = client.write_report_index_entry("202607", {"date": "20260726", "run_id": "b"})

    with open(path, "r", encoding="utf-8") as f:
        content = json.load(f)
    assert [e["run_id"] for e in content["entries"]] == ["a", "b"]


def test_read_report_index_returns_none_when_missing(tmp_path):
    client = Layer6LocalDriveClient(base_dir=str(tmp_path))
    assert client.read_report_index("202607") is None
