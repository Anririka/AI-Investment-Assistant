"""presentation_model.pyのテスト（layer6_report_generation_design.md §5-1・§12
「値不変性の回帰テスト」）。"""

import copy

from ai_investment_assistant.layer6_report_generation.presentation_model import build_presentation_model
from .sample_data import sample_decision_document


def test_build_presentation_model_preserves_all_values():
    document = sample_decision_document()
    original = copy.deepcopy(document)
    model = build_presentation_model(document)

    # 入力オブジェクト自体は変更されていないこと
    assert document == original

    # run_meta/decision_log/rule_enforcement_logの値は完全に一致すること
    assert model["run_meta"] == original["run_meta"]
    assert model["decision_log"] == original["decision_log"]
    assert model["rule_enforcement_log"] == original["rule_enforcement_log"]

    # proposalsは値集合として一致すること（順序のみ変わりうる）
    assert sorted(model["proposals"], key=lambda p: p["ticker"]) == sorted(
        original["proposals"], key=lambda p: p["ticker"]
    )


def test_build_presentation_model_sorts_proposals_by_rank_ascending():
    document = sample_decision_document()  # AMD(rank2), NVDA(rank1) の順で格納されている
    model = build_presentation_model(document)
    ranks = [p["rank"] for p in model["proposals"]]
    assert ranks == sorted(ranks)
    assert model["proposals"][0]["ticker"] == "NVDA"


def test_build_presentation_model_handles_zero_proposals():
    document = sample_decision_document(gate="blocked")
    model = build_presentation_model(document)
    assert model["proposals"] == []
