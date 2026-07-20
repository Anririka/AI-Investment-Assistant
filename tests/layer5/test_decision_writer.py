"""decision_writer.pyのテスト（layer5_ai_judgment_design.md §3-2・§9、§12テスト方針）。"""

import pytest

from ai_investment_assistant.layer5_ai_judgment.scripts.decision_writer import (
    build_decision_document,
    compact_timestamp,
    decision_file_name,
    write_decision,
)
from ai_investment_assistant.layer5_ai_judgment.scripts.schema_validator import SchemaValidationError


def test_compact_timestamp_strips_dashes_and_colons():
    assert compact_timestamp("2026-07-18T06:34:40Z") == "20260718T063440Z"


def _valid_document():
    run_meta = {
        "run_id": "20260718-0630",
        "layer5_started_at": "2026-07-18T06:30:05Z",
        "layer5_completed_at": "2026-07-18T06:34:40Z",
        "data_quality_gate": "passed",
        "data_quality_gate_detail": {"blocking_errors_found": [], "warning_errors_found": []},
        "score_meta_ref": {"scoring_version": "1.0.0", "weight_version": "2026-07"},
    }
    proposals = [{
        "rank": 1, "asset_class": "us_equity", "ticker": "NVDA", "name": "NVIDIA Corporation",
        "overall_assessment": "buy", "recommended_shares": 4, "entry_price_basis": 333.74,
        "position_amount": 1334.96, "stop_loss_price": 300.37, "take_profit_target_pct": 15.0,
        "take_profit_price": 383.80, "expected_return_pct": 15.0, "expected_loss_pct": -10.0,
        "confidence": 78, "investment_reason": "reason", "risk_factors": "risk",
        "score_summary": {
            "technical": 84, "fundamental": 71, "supply_demand": 78, "macro": 65,
            "news": {"score": 63, "uncertainty": 35}, "regime_fit": 90, "composite": 79,
        },
    }]
    decision_log = [{"ticker": "NVDA", "decision": "adopted", "rank": 1, "reason_code": "ADOPTED_TOP_RANK"}]
    rule_enforcement_log = [{"rule": "confidence_gate", "applied": False}]
    return build_decision_document(run_meta, proposals, decision_log, rule_enforcement_log)


def test_decision_file_name_uses_layer5_completed_at():
    document = _valid_document()
    assert decision_file_name(document["run_meta"]) == "decision_20260718T063440Z.json"


def test_build_decision_document_has_four_top_level_keys():
    document = _valid_document()
    assert set(document.keys()) == {"run_meta", "proposals", "decision_log", "rule_enforcement_log"}


class FakeDriveClient:
    def __init__(self):
        self.saved = {}

    def write_decision(self, file_name, content):
        self.saved[file_name] = content
        return f"decisions/{file_name}"


def test_write_decision_saves_via_drive_client_and_returns_path():
    client = FakeDriveClient()
    document = _valid_document()
    path = write_decision(client, document)
    assert path == "decisions/decision_20260718T063440Z.json"
    assert client.saved["decision_20260718T063440Z.json"] == document


def test_write_decision_rejects_invalid_document():
    client = FakeDriveClient()
    invalid = _valid_document()
    del invalid["proposals"]
    with pytest.raises(SchemaValidationError):
        write_decision(client, invalid)
    assert client.saved == {}
