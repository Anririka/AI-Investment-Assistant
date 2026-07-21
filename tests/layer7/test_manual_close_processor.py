"""manual_close_processor.pyのテスト（layer7_proposal_tracking_design.md §8-4、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.manual_close_processor import process_manual_close_requests


def _position(tracking_id="TRK-1", **overrides):
    base = {"tracking_id": tracking_id, "ticker": "NVDA",
            "latest_price": {"close": 350.0}}
    base.update(overrides)
    return base


def test_process_manual_close_requests_moves_matching_position_to_closed():
    active = [_position()]
    requests = [{"tracking_id": "TRK-1", "exit_price": 360.0, "exit_date": "2026-08-01", "note": "手動利確"}]
    result = process_manual_close_requests(active, requests, default_exit_date="2026-08-02")
    assert len(result["closed"]) == 1
    position, exit_price, exit_date, note = result["closed"][0]
    assert exit_price == 360.0
    assert exit_date == "2026-08-01"
    assert note == "手動利確"
    assert result["remaining_requests"] == []
    assert result["errors"] == []


def test_process_manual_close_requests_defaults_exit_price_to_latest_close_when_omitted():
    active = [_position()]
    requests = [{"tracking_id": "TRK-1"}]
    result = process_manual_close_requests(active, requests, default_exit_date="2026-08-02")
    _position_out, exit_price, exit_date, _note = result["closed"][0]
    assert exit_price == 350.0
    assert exit_date == "2026-08-02"


def test_process_manual_close_requests_unknown_tracking_id_recorded_as_error_and_kept():
    active = [_position()]
    requests = [{"tracking_id": "TRK-UNKNOWN"}]
    result = process_manual_close_requests(active, requests, default_exit_date="2026-08-02")
    assert result["closed"] == []
    assert result["remaining_requests"] == [{"tracking_id": "TRK-UNKNOWN"}]
    assert result["errors"][0]["tracking_id"] == "TRK-UNKNOWN"


def test_process_manual_close_requests_processed_requests_removed_from_queue():
    active = [_position()]
    requests = [{"tracking_id": "TRK-1"}, {"tracking_id": "TRK-UNKNOWN"}]
    result = process_manual_close_requests(active, requests, default_exit_date="2026-08-02")
    assert len(result["closed"]) == 1
    assert result["remaining_requests"] == [{"tracking_id": "TRK-UNKNOWN"}]
