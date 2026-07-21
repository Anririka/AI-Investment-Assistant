"""feedback_builder.pyのテスト（layer8_self_evaluation_design.md §8、§11テスト方針）。

自動適用禁止の回帰テストを含む：weight_adjustment_suggestionsが生成されても
configファイルへの書き込みは一切発生しないこと（本モジュールがファイルI/Oを
一切行わない純粋関数のみで構成されていること自体がその保証となる）。
"""

import inspect

from ai_investment_assistant.layer8_self_evaluation import feedback_builder
from ai_investment_assistant.layer8_self_evaluation.feedback_builder import (
    build_feedback,
    build_sample_size,
    build_weight_adjustment_suggestions,
    should_generate_feedback,
)


def test_should_generate_feedback_false_when_zero():
    assert should_generate_feedback(0) is False


def test_should_generate_feedback_true_when_positive():
    assert should_generate_feedback(1) is True


def test_build_sample_size_flags_insufficient_when_below_minimum():
    sample = build_sample_size(total_closed_this_period=4, total_closed_all_time=15, min_recommended_sample=30)
    assert sample["sufficient_for_reliable_analysis"] is False


def test_build_sample_size_flags_sufficient_when_at_minimum():
    sample = build_sample_size(total_closed_this_period=4, total_closed_all_time=30, min_recommended_sample=30)
    assert sample["sufficient_for_reliable_analysis"] is True


def test_build_weight_adjustment_suggestions_generates_increase_for_outperforming_code():
    reason_code_performance = [{"reason_code": "TECH_RSI_HEALTHY", "count": 8, "win_rate": 0.625,
                                 "avg_return_pct": 9.2, "confidence": "low_sample"}]
    suggestions = build_weight_adjustment_suggestions(reason_code_performance, overall_win_rate=0.53,
                                                        win_rate_diff_threshold=0.05)
    assert len(suggestions) == 1
    assert suggestions[0]["suggested_direction"] == "increase"
    assert suggestions[0]["requires_human_review"] is True
    assert suggestions[0]["target_config"] == "config/scoring_weights.yaml#technical.RSI"


def test_build_weight_adjustment_suggestions_generates_decrease_for_underperforming_code():
    reason_code_performance = [{"reason_code": "FUND_PER_HIGH", "count": 12, "win_rate": 0.2,
                                 "avg_return_pct": -3.0, "confidence": "medium_sample"}]
    suggestions = build_weight_adjustment_suggestions(reason_code_performance, overall_win_rate=0.53,
                                                        win_rate_diff_threshold=0.05)
    assert suggestions[0]["suggested_direction"] == "decrease"


def test_build_weight_adjustment_suggestions_skips_when_diff_below_threshold():
    reason_code_performance = [{"reason_code": "TECH_RSI_HEALTHY", "count": 8, "win_rate": 0.55,
                                 "avg_return_pct": 9.2, "confidence": "low_sample"}]
    suggestions = build_weight_adjustment_suggestions(reason_code_performance, overall_win_rate=0.53,
                                                        win_rate_diff_threshold=0.05)
    assert suggestions == []


def test_build_weight_adjustment_suggestions_empty_when_overall_win_rate_none():
    suggestions = build_weight_adjustment_suggestions(
        [{"reason_code": "TECH_A", "count": 1, "win_rate": 1.0, "avg_return_pct": 1.0, "confidence": "low_sample"}],
        overall_win_rate=None, win_rate_diff_threshold=0.05,
    )
    assert suggestions == []


def test_build_feedback_review_status_always_pending():
    feedback = build_feedback(
        period="2026-07", generated_at="2026-08-01T06:00:00Z",
        total_closed_this_period=4, total_closed_all_time=15, min_recommended_sample=30,
        overall_stats={"win_rate": 0.53, "avg_win_pct": 12.1, "avg_loss_pct": -8.5, "profit_factor": 1.8,
                       "profit_factor_note": None, "take_profit_rate": 0.4, "stop_loss_rate": 0.13},
        reason_code_performance=[], score_band_performance=[], asset_class_performance=[],
        holding_period_performance=[], win_rate_diff_threshold=0.05,
    )
    assert feedback["review_status"] == "pending_human_review"
    assert feedback["sample_size"]["total_closed_this_period"] == 4


def test_feedback_builder_module_performs_no_file_or_config_io():
    # 自動適用禁止の回帰テスト：モジュール内にopen/write系のファイルI/O呼び出しが
    # 一切含まれていないことをソースレベルで確認する。
    source = inspect.getsource(feedback_builder)
    assert "open(" not in source
    assert ".write(" not in source
    assert "yaml.dump" not in source
