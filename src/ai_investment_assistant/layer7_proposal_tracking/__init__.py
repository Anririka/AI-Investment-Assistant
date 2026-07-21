"""Layer7（提案トラッキング層）。

layer7_proposal_tracking_design.md §1の通り、Layer7はAI判断を一切行わない純粋な
決定的Python処理であり、Layer1〜4と同様GitHub Actions上の独立したパイプラインとして
稼働する（Layer5/Layer6の実行タイミングとは非同期）。

入力はLayer6が保存したGoogle Sheets「本日の提案」シートの指定9列のみ（§5-1）。
Layer5のdecision JSON・Layer6のMarkdownレポート・`取引記録_*.csv`・Layer1〜4の出力には
一切アクセスしない（§5-2）。
"""
