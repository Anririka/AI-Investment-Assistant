"""永続化先を抽象化するRepositoryパターン（layer4_persistence_design.md §11）。

保存系メソッドのみを定義する（読み込み系はLayer5側の責務、Layer4のRepositoryには含めない）。
現行の唯一の具体実装は`google_drive_repository.GoogleDriveRepository`。
"""
