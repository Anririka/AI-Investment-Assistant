"""json_builder.pyのテスト（layer2_analysis_design.md §3-10）。"""

from ai_investment_assistant.layer2_analysis.json_builder import (
    build_output,
    drop_lowest_scoring_candidates,
    shorten_reasons_for_budget,
)

CANDIDATE_LIMITS = {"japan_equity": 2, "us_equity": 1}


def _candidate(ticker, asset_class, rank, total=50):
    return {
        "ticker": ticker, "asset_class": asset_class, "preliminary_quant_rank": rank,
        "composite_score": {"total": total},
        "technical": {"sub_scores": [{"reason": "x" * 100}]},
        "fundamental": {"sub_scores": []},
        "supply_demand": {"sub_scores": []},
    }


def test_candidate_limit_applied_per_asset_class():
    candidates = [
        _candidate("A", "japan_equity", 1), _candidate("B", "japan_equity", 2), _candidate("C", "japan_equity", 3),
        _candidate("D", "us_equity", 1), _candidate("E", "us_equity", 2),
    ]
    output, warnings = build_output(
        run_meta={}, regime={}, macro={}, ranked_candidates=candidates, excluded_summary=[],
        candidate_limits=CANDIDATE_LIMITS, max_total_candidates=30,
    )
    selected_tickers = {c["ticker"] for c in output["candidates"]}
    assert selected_tickers == {"A", "B", "D"}


def test_excess_candidates_recorded_in_excluded_summary():
    candidates = [_candidate("A", "japan_equity", 1), _candidate("B", "japan_equity", 2), _candidate("C", "japan_equity", 3)]
    output, warnings = build_output(
        run_meta={}, regime={}, macro={}, ranked_candidates=candidates, excluded_summary=[],
        candidate_limits=CANDIDATE_LIMITS, max_total_candidates=30,
    )
    excluded_tickers = {e["ticker"] for e in output["excluded_summary"]}
    assert excluded_tickers == {"C"}
    assert output["excluded_summary"][0]["reason_code"] == "CANDIDATE_LIMIT_EXCEEDED"


def test_warning_emitted_when_total_exceeds_max():
    candidates = [_candidate(f"T{i}", "japan_equity", i + 1) for i in range(2)]
    output, warnings = build_output(
        run_meta={}, regime={}, macro={}, ranked_candidates=candidates, excluded_summary=[],
        candidate_limits={"japan_equity": 2}, max_total_candidates=1,
    )
    assert len(warnings) == 1


def test_shorten_reasons_truncates_long_strings():
    output = {"candidates": [_candidate("A", "japan_equity", 1)]}
    shortened = shorten_reasons_for_budget(output, max_reason_chars=10)
    assert shortened["candidates"][0]["technical"]["sub_scores"][0]["reason"].endswith("...")
    assert len(shortened["candidates"][0]["technical"]["sub_scores"][0]["reason"]) == 13  # 10 + "..."


def test_drop_lowest_scoring_candidates_removes_and_records():
    output = {
        "candidates": [
            {"ticker": "LOW", "asset_class": "japan_equity", "composite_score": {"total": 20}},
            {"ticker": "HIGH", "asset_class": "japan_equity", "composite_score": {"total": 90}},
        ],
        "excluded_summary": [],
    }
    result = drop_lowest_scoring_candidates(output, count=1)
    remaining_tickers = {c["ticker"] for c in result["candidates"]}
    assert remaining_tickers == {"HIGH"}
    assert result["excluded_summary"][0]["reason_code"] == "PROMPT_BUDGET_EXCEEDED"
