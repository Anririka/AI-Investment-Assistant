"""error_report_builder.pyのテスト（layer6_report_generation_design.md §10）。"""

from ai_investment_assistant.layer6_report_generation.error_report_builder import (
    build_blocked_report,
    build_missing_decision_report,
    build_schema_violation_report,
)
from .sample_data import sample_decision_document


def test_build_missing_decision_report_mentions_failure():
    text = build_missing_decision_report()
    assert "Layer5の出力が確認できません" in text


def test_build_blocked_report_shows_blocking_errors():
    document = sample_decision_document(gate="blocked")
    text = build_blocked_report(document)
    assert "様子見" in text
    assert "LAYER_PIPELINE_NOT_COMPLETED" in text


def test_build_schema_violation_report_includes_details():
    text = build_schema_violation_report("'proposals' is a required property")
    assert "契約違反" in text
    assert "'proposals' is a required property" in text
