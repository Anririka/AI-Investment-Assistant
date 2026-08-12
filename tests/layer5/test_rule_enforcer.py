"""rule_enforcer.pyのテスト（layer5_ai_judgment_design.md §7・§7-1、§12テスト方針）。"""

from ai_investment_assistant.layer5_ai_judgment.scripts.rule_enforcer import (
    apply_confidence_gate,
    check_sector_concentration_warning,
    enforce_daily_limit,
)


def _candidate(ticker, **overrides):
    base = {"ticker": ticker, "overall_assessment": "buy", "confidence": 78,
            "preliminary_quant_rank": 1, "composite_score": 80, "rank": 1}
    base.update(overrides)
    return base


def test_apply_confidence_gate_forces_low_confidence_buy_to_hold():
    candidates = [_candidate("NVDA", confidence=40)]
    updated, log = apply_confidence_gate(candidates)
    assert updated[0]["overall_assessment"] == "hold"
    assert updated[0]["confidence_gate_forced"] is True
    assert log["applied"] is True


def test_apply_confidence_gate_leaves_high_confidence_untouched():
    candidates = [_candidate("NVDA", confidence=78)]
    updated, log = apply_confidence_gate(candidates)
    assert updated[0]["overall_assessment"] == "buy"
    assert log["applied"] is False


def test_apply_confidence_gate_ignores_non_buy_candidates():
    candidates = [_candidate("NVDA", overall_assessment="hold", confidence=10)]
    updated, log = apply_confidence_gate(candidates)
    assert updated[0]["overall_assessment"] == "hold"
    assert log["applied"] is False


def test_enforce_daily_limit_under_limit_adopts_all():
    candidates = [_candidate("A"), _candidate("B")]
    adopted, not_selected, log = enforce_daily_limit(candidates)
    assert len(adopted) == 2
    assert not_selected == []
    assert log["applied"] is False


def test_enforce_daily_limit_over_limit_prioritizes_preliminary_quant_rank():
    candidates = [
        _candidate("NVDA", preliminary_quant_rank=1, rank=2),
        _candidate("AMD", preliminary_quant_rank=2, rank=4),
        _candidate("AVGO", preliminary_quant_rank=3, rank=6),
        _candidate("TSM", preliminary_quant_rank=4, rank=1),
    ]
    adopted, not_selected, log = enforce_daily_limit(candidates)
    assert [c["ticker"] for c in adopted] == ["NVDA", "AMD", "AVGO"]
    assert [d["ticker"] for d in not_selected] == ["TSM"]
    assert not_selected[0]["reason_code"] == "DAILY_PROPOSAL_LIMIT_EXCEEDED"
    assert not_selected[0]["decision"] == "not_selected"
    assert log["applied"] is True


def test_enforce_daily_limit_tiebreaks_on_composite_score_then_confidence_then_llm_rank():
    candidates = [
        _candidate("A", preliminary_quant_rank=1, composite_score=70, confidence=60, rank=3),
        _candidate("B", preliminary_quant_rank=1, composite_score=90, confidence=60, rank=4),
        _candidate("C", preliminary_quant_rank=2, composite_score=50, confidence=99, rank=1),
        _candidate("D", preliminary_quant_rank=3, composite_score=10, confidence=10, rank=2),
    ]
    adopted, not_selected, _log = enforce_daily_limit(candidates)
    # B (rank1 tie, higher composite_score) should beat A; then C (rank2); D dropped.
    assert [c["ticker"] for c in adopted] == ["B", "A", "C"]
    assert [d["ticker"] for d in not_selected] == ["D"]


def test_enforce_daily_limit_does_not_resurrect_llm_excluded_candidates():
    # rule_enforcer only receives candidates LLM already marked "buy"; anything the LLM
    # excluded beforehand simply never reaches this function, so it can't be resurrected.
    buy_only = [_candidate("A"), _candidate("B"), _candidate("C"), _candidate("D")]
    adopted, not_selected, _log = enforce_daily_limit(buy_only)
    all_tickers = {c["ticker"] for c in adopted} | {d["ticker"] for d in not_selected}
    assert all_tickers == {"A", "B", "C", "D"}


def _position(ticker, sector):
    return {"ticker": ticker, "sector": sector}


def test_check_sector_concentration_warning_flags_overlap_with_existing_holding():
    adopted = [_candidate("9101")]
    positions = [_position("9104", "shipping")]
    sector_mapping = {"9101": "shipping", "9104": "shipping"}
    log = check_sector_concentration_warning(adopted, positions, sector_mapping)
    assert log["applied"] is True
    assert "9101" in log["detail"]
    assert "9104" in log["detail"]


def test_check_sector_concentration_warning_flags_overlap_between_same_day_adopted():
    adopted = [_candidate("9101"), _candidate("9107")]
    sector_mapping = {"9101": "shipping", "9107": "shipping"}
    log = check_sector_concentration_warning(adopted, [], sector_mapping)
    assert log["applied"] is True
    assert "9101" in log["detail"]
    assert "9107" in log["detail"]


def test_check_sector_concentration_warning_no_overlap_not_applied():
    adopted = [_candidate("4183")]
    positions = [_position("9104", "shipping")]
    sector_mapping = {"4183": "chemicals", "9104": "shipping"}
    log = check_sector_concentration_warning(adopted, positions, sector_mapping)
    assert log["applied"] is False
    assert "detail" not in log


def test_check_sector_concentration_warning_unknown_sector_never_flagged():
    # Both candidate and held position map to "unknown" (unregistered ticker); comparing
    # unknowns would be a false positive, so they must never be flagged against each other.
    adopted = [_candidate("9999")]
    positions = [_position("8888", "unknown")]
    sector_mapping = {}  # neither ticker registered -> both default to "unknown"
    log = check_sector_concentration_warning(adopted, positions, sector_mapping)
    assert log["applied"] is False


def test_check_sector_concentration_warning_does_not_mutate_or_exclude_candidates():
    adopted = [_candidate("9101"), _candidate("9107")]
    sector_mapping = {"9101": "shipping", "9107": "shipping"}
    before = [dict(c) for c in adopted]
    check_sector_concentration_warning(adopted, [], sector_mapping)
    assert adopted == before
