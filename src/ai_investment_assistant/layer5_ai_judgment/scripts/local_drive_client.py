"""ローカルファイルシステムをバックエンドとするLayer5 Drive I/Oアダプタ
（Google Drive MCPコネクタ方式への移行）。

Claude Coworkのスケジュールタスクが動くクラウドサンドボックスは、googleapis.com系
ドメインへの直接のネットワークアクセスをネットワークポリシーで遮断しているため、
`Layer5DriveClient`（google-api-python-client＋サービスアカウントによる直接API呼び出し）
はこの環境では機能しない（実地検証済み）。

これに対応するため、実際のGoogle Driveとの読み書きは、Claude Coworkセッション自身
（AIエージェント）が`mcp__Google_Drive__*`ツール（このセッションに接続済みのGoogle
Driveコネクタ、ネットワーク遮断の影響を受けない）を使って行い、その結果をこの
クラスが期待するローカルディレクトリ構成に保存しておく（詳細は
`prompts/layer5_judgment_prompt_template.md`参照）。

`Layer5DriveClient`と全く同じ公開インターフェース（`read_json`／
`read_latest_text_by_prefix`／`write_decision`）を実装することで、
`load_snapshot.py`・`load_portfolio_state.py`・`decision_writer.py`の既存ロジック
（データ品質ゲート判定・保有ポジション算出・出力契約バリデーション等）は
一切変更せずにそのまま再利用できる。ローカルディレクトリ構成：

```
{base_dir}/
├── snapshots/
│   ├── layer4_completed_YYYYMMDD.json   # エージェントがMCPで取得して保存
│   └── market_snapshot_YYYYMMDD.json     # 同上
├── 取引記録_YYYYMMDDTHHMMSSZ.csv          # 同上（base_dir直下、Driveのroot相当）
└── decisions/
    └── decision_YYYYMMDDTHHMMSSZ.json    # decision_writer.pyが書き込み、
                                            # エージェントがMCPでDriveへアップロード
```
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class LocalDriveClient:
    """Layer5DriveClientと同一の公開インターフェースを、ローカルファイルシステムに
    対して実装する（`base_dir`がGoogle Driveのroot folderに相当する）。
    """

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def _resolve_dir(self, subfolder: Optional[str]) -> Path:
        return self._base_dir / subfolder if subfolder else self._base_dir

    def read_json(self, subfolder: Optional[str], file_name: str) -> Optional[dict]:
        """指定ファイルが存在すればパースして返す。無ければNone。"""
        path = self._resolve_dir(subfolder) / file_name
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def read_latest_text_by_prefix(self, subfolder: Optional[str], name_prefix: str) -> Optional[tuple]:
        """`subfolder`内でname_prefixから始まる最新（ファイル名の降順で最大）のファイルを
        テキストとして読み込む。(file_name, text) を返す。1件も無ければNone。
        """
        directory = self._resolve_dir(subfolder)
        if not directory.exists():
            return None
        matching = sorted(
            (p.name for p in directory.iterdir() if p.is_file() and p.name.startswith(name_prefix)),
            reverse=True,
        )
        if not matching:
            return None
        latest_name = matching[0]
        with open(directory / latest_name, "r", encoding="utf-8-sig") as f:
            return latest_name, f.read()

    def write_decision(self, file_name: str, content: dict) -> str:
        """decisions/{file_name} をローカルに保存し、ローカルパスを返す。

        実際のGoogle Driveへのアップロードは、この戻り値のパスを使ってエージェントが
        `mcp__Google_Drive__create_file`で行う（このクラス自体はDriveへは書き込まない）。
        """
        decisions_dir = self._resolve_dir("decisions")
        decisions_dir.mkdir(parents=True, exist_ok=True)
        path = decisions_dir / file_name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return str(path)
