"""ranking.pyのテスト（layer2_analysis_design.md §3-9）。"""

from ai_investment_assistant.layer2_analysis.ranking import rank_candidates


def _candidate(ticker, asset_class, total):
    return {"ticker": ticker, "asset_class": asset_class, "composite_score": {"total": total}}


def test_ranks_descending_by_composite_score_within_asset_class():
    candidates = [
        _candidate("A", "japan_equity", 60),
        _candidate("B", "japan_equity", 90),
        _candidate("C", "japan_equity", 75),
    ]
    ranked = rank_candidates(candidates)
    by_ticker = {c["ticker"]: c["preliminary_quant_rank"] for c in ranked}
    assert by_ticker["B"] == 1
    assert by_ticker["C"] == 2
    assert by_ticker["A"] == 3


def test_ranking_is_independent_per_asset_class():
    candidates = [
        _candidate("A", "japan_equity", 60),
        _candidate("B", "us_equity", 60),
        _candidate("C", "us_equity", 95),
    ]
    ranked = rank_candidates(candidates)
    by_ticker = {c["ticker"]: c["preliminary_quant_rank"] for c in ranked}
    assert by_ticker["A"] == 1  # japan_equity内では唯一なので1位
    assert by_ticker["C"] == 1  # us_equity内の1位
    assert by_ticker["B"] == 2


def test_all_candidates_are_returned_no_truncation():
    candidates = [_candidate(str(i), "japan_equity", i) for i in range(50)]
    ranked = rank_candidates(candidates)
    assert len(ranked) == 50
