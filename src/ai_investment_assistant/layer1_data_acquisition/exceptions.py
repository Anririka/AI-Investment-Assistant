"""Layer1共通の例外階層（layer1_data_acquisition_design.md 5-1のエラー分類に対応）。

FallbackChainRepositoryはこれらの例外の種類によってフォールバック挙動を変える。

  - TransientError      : 同一ソースへ即時バックオフリトライ、上限超過で次候補へ
  - RateLimitError       : リトライせず即座に次候補へ
  - AuthError            : 次候補へフォールバックしつつ severity=critical でログ
  - NotFoundError        : フォールバックしない（「対象外銘柄」として記録）
  - AllSourcesFailedError: チェーン内の全Repositoryが失敗（呼び出し側は「取得不可」扱い）
"""

from __future__ import annotations


class DataSourceError(Exception):
    """すべてのデータ取得関連エラーの基底クラス。"""


class TransientError(DataSourceError):
    """タイムアウト・5xx・接続エラー等、一時的なエラー。"""


class RateLimitError(DataSourceError):
    """429やクォータ枯渇等のレート制限エラー。"""


class AuthError(DataSourceError):
    """401/403等の認証・設定エラー。run_logにseverity=criticalで記録すべき。"""


class NotFoundError(DataSourceError):
    """404等、データそのものが存在しないエラー。フォールバック対象外。"""


class AllSourcesFailedError(DataSourceError):
    """フォールバックチェーン内の全Repositoryが失敗したことを示す。"""

    def __init__(self, message: str, errors: list | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []
