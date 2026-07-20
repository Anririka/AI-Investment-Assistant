"""Layer5入出力契約のバリデーションテスト（layer5_ai_judgment_design.md §12
「選択肢B移行を見据えた契約テスト」）。"""

import pytest

from ai_investment_assistant.layer5_ai_judgment.scripts.schema_validator import (
    SchemaValidationError,
    validate_layer5_input,
    validate_layer5_output,
)


def _minimal_layer2_output():
    return {
        "run_meta": {"data_quality": {"critical_errors": [], "warning_errors": []}},
        "regime": {}, "macro": {}, "candidates": [], "excluded_summary": [],
    }


def _minimal_portfolio_state():
    return {
        "as_of": "2026-07-18T06:00:00Z", "total_capital": 250000, "total_invested": 0,
        "available_capital": 250000, "positions": [], "sector_concentration": {},
    }


def test_validate_layer5_input_accepts_valid_pair():
    validate_layer5_input(_minimal_layer2_output(), _minimal_portfolio_state())


def test_validate_layer5_input_rejects_missing_portfolio_state_field():
    invalid = _minimal_portfolio_state()
    del invalid["total_capital"]
    with pytest.raises(SchemaValidationError):
        validate_layer5_input(_minimal_layer2_output(), invalid)


def _minimal_output():
    return {
        "run_meta": {
            "run_id": "x", "layer5_started_at": "t", "layer5_completed_at": "t",
            "data_quality_gate": "passed",
            "data_quality_gate_detail": {"blocking_errors_found": [], "warning_errors_found": []},
            "score_meta_ref": {},
        },
        "proposals": [], "decision_log": [], "rule_enforcement_log": [],
    }


def test_validate_layer5_output_accepts_minimal_valid_document():
    validate_layer5_output(_minimal_output())


def test_validate_layer5_output_rejects_missing_top_level_key():
    invalid = _minimal_output()
    del invalid["decision_log"]
    with pytest.raises(SchemaValidationError):
        validate_layer5_output(invalid)


def test_validate_layer5_output_rejects_invalid_data_quality_gate_value():
    invalid = _minimal_output()
    invalid["run_meta"]["data_quality_gate"] = "unknown_value"
    with pytest.raises(SchemaValidationError):
        validate_layer5_output(invalid)
