"""Layer5のscripts配下。

layer5_ai_judgment_design.md §2の通り、ここに置くモジュールはClaude Coworkセッション
（Agent）が自身のBashツールから呼び出す補助ツール群である。選択肢B移行時にGitHub Actions
上のPythonプロセスから呼び出せるよう、各モジュールは外部I/O（Google Drive等）を薄い層に
分離し、中心的なロジックは純粋関数として実装する（テスト容易性・将来の再利用性のため）。
"""
