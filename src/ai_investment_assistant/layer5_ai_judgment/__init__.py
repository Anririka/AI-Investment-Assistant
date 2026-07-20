"""Layer5（AI判断層）。

layer5_ai_judgment_design.md §0で明文化されている通り、Layer5はPythonアプリケーション
ではなく「AI Agent実行層」である。実行主体はClaude Coworkスケジュールタスク（LLMの
推論そのもの）であり、`scripts/`配下のモジュールはそのAgentがBash/Pythonツールで呼び出す
補助的な決定的計算処理（推奨株数の確定計算・ハードルールの機械的強制等）を提供するに
過ぎない。`prompts/layer5_judgment_prompt_template.md`がAgentへの指示本体であり、
`contracts/`配下がLayer2との入力契約・Layer6への出力契約を定義する。

将来「選択肢B」（外部Python基盤＋AIJudge抽象クラス）へ移行する場合も、`scripts/`配下は
そのまま再利用できるよう、最初から独立したPython関数として実装している（§2参照）。
"""
