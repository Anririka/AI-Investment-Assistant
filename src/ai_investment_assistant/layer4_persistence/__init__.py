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

実行状況（2026-07-22）:
  - Layer1〜4は scripts/run_daily_pipeline.py としてGitHub Actionsに組み込み済み。
  - GoogleDriveRepositoryの認証方式は、サービスアカウントJSON鍵ではなくOAuth 2.0
    ユーザー認証（GOOGLE_OAUTH_TOKEN_JSON、common/google_oauth_auth.py参照）に統一した。
    サービスアカウントは個人のGoogle Drive（マイドライブ）の保存容量を持たず、新規ファイル
    作成が403 insufficientParentPermissionsで失敗する仕様上の制約があるため。
"""
