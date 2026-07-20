"""Layer4（永続化層）。

詳細設計: layer4_persistence_design.md（確定版・Ver1.1）

実装状況（Phase4）:
  schema_validator.py      market_snapshotのトップレベル形式検証（実装済み、§3・§8）
  snapshot_writer.py        market_snapshot_YYYYMMDD.jsonの非加工保存（実装済み、§5-1）
  completion_flag_writer.py  layer4_completed_YYYYMMDD.jsonの生成（実装済み、§5-2）
  execution_logger.py        execution_log_YYYYMMDD.jsonの生成（実装済み、§5-3）
  history_indexer.py         history/index_YYYYMM.jsonの更新（実装済み、§5-4）
  repository/
    base.py                  PersistenceRepository抽象クラス（実装済み、保存系メソッドのみ、§11）
    google_drive_repository.py  GoogleDriveRepository（実装済み、現行唯一の具体実装）
  main.py                     書き込み順序を固定したパイプライン全体（実装済み、§3・§6-2）

書き込み順序（Layer5との契約の核、§6-2）:
  market_snapshot → execution_log → history index → completion flag
  全て成功した場合のみcompleted:trueを書く。1つでも失敗すれば書かない（毒薬テスト、§9）。

未実装・要検討事項:
  - GoogleDriveRepositoryの実際のGoogle Drive APIレスポンスは未検証（このクラウド
    作業環境にGOOGLE_DRIVE_SERVICE_ACCOUNT_JSON等は共有されているが、Layer4の実行
    自体はまだGitHub Actionsパイプラインに組み込まれていない。Layer5実装後、
    Layer1〜4を通しで実行するタイミングでライブ検証する）
"""
