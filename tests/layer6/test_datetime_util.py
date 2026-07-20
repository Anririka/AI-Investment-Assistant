"""datetime_util.pyのテスト（layer6_report_generation_design.md §6-2、JST基準の実行日）。"""

from ai_investment_assistant.layer6_report_generation.datetime_util import execution_date_jst


def test_execution_date_jst_converts_utc_to_jst_date():
    # 2026-07-18T06:34:40Z (UTC) -> JST (+9h) = 2026-07-18 15:34:40
    run_meta = {"layer5_completed_at": "2026-07-18T06:34:40Z"}
    assert execution_date_jst(run_meta) == "20260718"


def test_execution_date_jst_crosses_date_boundary_into_next_jst_day():
    # 2026-07-18T20:00:00Z (UTC) -> JST = 2026-07-19 05:00:00 (日付が繰り上がる)
    run_meta = {"layer5_completed_at": "2026-07-18T20:00:00Z"}
    assert execution_date_jst(run_meta) == "20260719"
