"""main.py（Layer8パイプライン全体）の統合テスト（layer8_self_evaluation_design.md §4・§6）。

トランザクション原則の毒薬テスト：途中のいずれかの保存が失敗すれば、
evaluation_index.jsonは更新されない（＝次回再評価される）ことを確認する。
"""

from datetime import datetime, timezone

import pytest

from ai_investment_assistant.layer8_self_evaluation import main

CONFIDENCE_THRESHOLDS = {
    "low_sample": {"max_count": 9},
    "medium_sample": {"min_count": 10, "max_count": 29},
    "normal": {"min_count": 30},
}


class FakeDriveClient:
    def __init__(self, layer7_flag=None, closed_positions=None, sheet_rows=None,
                 index_doc=None, fail_on=frozenset()):
        self._layer7_flag = layer7_flag
        self._closed_positions = closed_positions or {}
        self._sheet_rows = sheet_rows or {}
        self.evaluation_files = {}
        if index_doc is not None:
            self.evaluation_files["evaluation_index.json"] = index_doc
        self.fail_on = fail_on

    def read_latest_layer7_completed_flag(self, date_str):
        return self._layer7_flag

    def read_closed_positions(self, year_month):
        return self._closed_positions.get(year_month)

    def read_proposal_sheet_rows(self, date_str, sheet_name="本日の提案"):
        return self._sheet_rows.get(date_str)

    def read_evaluation_json(self, file_name):
        return self.evaluation_files.get(file_name)

    def write_evaluation_json(self, file_name, content):
        if file_name in self.fail_on:
            raise RuntimeError(f"write failed: {file_name}")
        self.evaluation_files[file_name] = content
        return f"evaluation/{file_name}"


def _closed_position(**overrides):
    base = {
        "tracking_id": "TRK-20260718-0630-NVDA", "run_id": "20260718-0630", "ticker": "NVDA",
        "entry_price": 333.74, "exit_price": 383.80, "recommended_shares": 4,
        "holding_days": 18, "exit_reason": "take_profit", "final_return_pct": 15.0,
        "max_unrealized_gain_pct": 16.2, "max_unrealized_loss_pct": -1.1,
    }
    base.update(overrides)
    return base


def _sheet_row(**overrides):
    base = {
        "証券コード": "NVDA", "資産クラス": "us_equity",
        "テクニカルスコア": 84, "ファンダメンタルスコア": 71, "需給スコア": 78,
        "マクロスコア": 65, "ニューススコア": 63, "ニュース不確実性": 35,
        "レジーム適合スコア": 90, "総合スコア": 79,
        "投資理由": "TECH_MA_PERFECT_ORDER_UP による良好なテクニカル。", "リスク要因": "競合激化",
    }
    base.update(overrides)
    return base


def _run(client, **overrides):
    kwargs = dict(
        drive_client=client, date_str="20260718", year_months_to_scan=["202607"],
        confidence_thresholds=CONFIDENCE_THRESHOLDS, min_recommended_sample=30,
        win_rate_diff_threshold=0.05, now=datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return main.run(**kwargs)


def test_run_skips_when_layer7_flag_missing():
    client = FakeDriveClient(layer7_flag=None)
    result = _run(client)
    assert result["status"] == "skipped"
    assert result["reason_code"] == "LAYER7_NOT_COMPLETED"


def test_run_skips_when_layer7_flag_not_completed():
    client = FakeDriveClient(layer7_flag={"completed": False})
    result = _run(client)
    assert result["status"] == "skipped"


def test_run_no_new_evaluations_when_all_already_indexed():
    client = FakeDriveClient(
        layer7_flag={"completed": True},
        closed_positions={"202607": {"positions": [_closed_position()]}},
        index_doc={"evaluated_tracking_ids": ["TRK-20260718-0630-NVDA"]},
    )
    result = _run(client)
    assert result["status"] == "no_new_evaluations"
    assert "feedback_202607.json" not in client.evaluation_files


def test_run_happy_path_generates_all_expected_files():
    client = FakeDriveClient(
        layer7_flag={"completed": True},
        closed_positions={"202607": {"positions": [_closed_position()]}},
        sheet_rows={"20260718": [_sheet_row()]},
    )
    result = _run(client)
    assert result["status"] == "ok"
    assert result["new_count"] == 1
    assert "position_evaluations_202607.json" in client.evaluation_files
    assert "segment_stats_202607.json" in client.evaluation_files
    assert "feedback_202607.json" in client.evaluation_files
    assert client.evaluation_files["evaluation_index.json"]["evaluated_tracking_ids"] == ["TRK-20260718-0630-NVDA"]

    evaluation = client.evaluation_files["position_evaluations_202607.json"]["evaluations"][0]
    assert evaluation["outcome"] == "win"
    assert evaluation["score_context_available"] is True

    feedback = client.evaluation_files["feedback_202607.json"]
    assert feedback["review_status"] == "pending_human_review"
    assert feedback["sample_size"]["total_closed_all_time"] == 1


def test_run_missing_score_context_still_evaluates_but_marks_unavailable():
    client = FakeDriveClient(
        layer7_flag={"completed": True},
        closed_positions={"202607": {"positions": [_closed_position()]}},
        sheet_rows={},  # Layer6シートが見つからない
    )
    result = _run(client)
    assert result["status"] == "ok"
    evaluation = client.evaluation_files["position_evaluations_202607.json"]["evaluations"][0]
    assert evaluation["score_context_available"] is False


def test_poison_pill_segment_stats_write_failure_prevents_index_update():
    client = FakeDriveClient(
        layer7_flag={"completed": True},
        closed_positions={"202607": {"positions": [_closed_position()]}},
        sheet_rows={"20260718": [_sheet_row()]},
        fail_on={"segment_stats_202607.json"},
    )
    result = _run(client)
    assert result["status"] == "error"
    # position_evaluationsは保存されているが、indexは更新されていない（再評価される）
    assert "position_evaluations_202607.json" in client.evaluation_files
    assert "evaluation_index.json" not in client.evaluation_files


def test_poison_pill_reevaluates_after_previous_failure():
    # 1回目：segment_stats書き込み失敗でindex未更新
    client = FakeDriveClient(
        layer7_flag={"completed": True},
        closed_positions={"202607": {"positions": [_closed_position()]}},
        sheet_rows={"20260718": [_sheet_row()]},
        fail_on={"segment_stats_202607.json"},
    )
    _run(client)
    assert "evaluation_index.json" not in client.evaluation_files

    # 2回目：同じclientから障害要因を取り除いて再実行すると、未評価のまま残っていたため
    # 再評価され、正常に完了する（二重評価は許容、§6）。
    client.fail_on = frozenset()
    result = _run(client)
    assert result["status"] == "ok"
    assert client.evaluation_files["evaluation_index.json"]["evaluated_tracking_ids"] == ["TRK-20260718-0630-NVDA"]
