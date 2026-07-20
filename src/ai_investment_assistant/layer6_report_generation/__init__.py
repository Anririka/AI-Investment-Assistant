"""Layer6（レポート生成層）。

layer6_report_generation_design.md §0の通り、Layer6は表示専用層であり判断は一切
行わない。入力はLayer5が確定したdecision JSONオブジェクトのみ（§4）であり、それ以外の
データソース（Layer1〜4の出力、取引記録CSV等）には一切アクセスしない。

Ver1（本実装）ではLayer5と同一のClaude Coworkセッション内で継続実行する構成を採用する
（§0）が、Layer6自体のロジックは「decision JSONオブジェクトを受け取って処理する」という
契約のみに依存するため、将来の独立実行への分離時も変更を要しない。
"""
