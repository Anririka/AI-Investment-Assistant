"""Layer8（自己評価層）。

layer8_self_evaluation_design.md §1・§2の通り、Layer8はAIによる新たな投資判断を
一切行わない、決定的Python処理のみで構成される層である。過去の提案結果（Layer7が
記録した実績）を分析し、AI改善のための評価データ・フィードバック（人間レビュー用の
提案）を生成する。重みの自動調整（`config/scoring_weights.yaml`等への自動反映）は
一切行わない（Ver2確定方針の継承）。

主入力はLayer7の`tracking/closed_positions_YYYYMM.json`、副入力はLayer6の
Google Sheets「本日の提案」シート（`run_id`＋`ticker`で結合）。Layer5のdecision JSON・
Layer6のMarkdown・`取引記録_*.csv`・Layer1〜4の出力にはアクセスしない（§5-2）。
"""
