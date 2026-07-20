"""Layer2共通の例外（layer2_analysis_design.md §3-6・§5-2）。"""

from __future__ import annotations


class SchemaVersionError(Exception):
    """Layer3が出力したnews_schema_versionのメジャーバージョンが、Layer2の
    accept_major_versionと一致しない場合に送出する（§3-6）。severity: criticalとして
    run_logに記録すべきエラー。
    """


class ScoringFailedError(Exception):
    """軸スコア計算中に想定外の例外が発生したことを示す（critical_errors用、reason_code:
    SCORING_FAILED）。
    """
