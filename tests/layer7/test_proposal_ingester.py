"""proposal_ingester.pyのテスト（layer7_proposal_tracking_design.md §4手順2・§6-2、§11テスト方針）。"""

from ai_investment_assistant.layer7_proposal_tracking.proposal_ingester import (
    build_tracking_id,
    ingest_new_positions,
)

UNIT_DAYS = {"日": 1, "週間": 7, "週": 7, "ヶ月": 30, "か月": 30, "カ月": 30}
FALLBACK = 90


def _sheet_row(**overrides):
    base = {
        "run_id": "20260718-0630", "日付": "2026-07-18", "証券コード": "NVDA",
        "銘柄名": "NVIDIA Corporation", "購入価格目安": 333.74, "損切価格": 300.37,
        "利確価格": 383.80, "想定保有期間": "2〜4週間", "推奨株数": 4,
    }
    base.update(overrides)
    return base


def test_build_tracking_id_format():
    assert build_tracking_id("20260718-0630", "NVDA") == "TRK-20260718-0630-NVDA"


def test_ingest_new_positions_creates_position_preserving_values():
    new_positions, skipped, not_purchased = ingest_new_positions([_sheet_row()], [], UNIT_DAYS, FALLBACK)
    assert skipped == []
    assert not_purchased == []
    assert len(new_positions) == 1
    position = new_positions[0]
    assert position["tracking_id"] == "TRK-20260718-0630-NVDA"
    assert position["entry_price"] == 333.74
    assert position["stop_loss_price"] == 300.37
    assert position["take_profit_price"] == 383.80
    assert position["recommended_shares"] == 4
    assert position["holding_period_days_parsed"] == 28
    assert position["status"] == "active"
    assert position["latest_price"] is None


def test_ingest_new_positions_skips_existing_run_id_ticker_combo():
    existing = [{"run_id": "20260718-0630", "ticker": "NVDA"}]
    new_positions, skipped, not_purchased = ingest_new_positions([_sheet_row()], existing, UNIT_DAYS, FALLBACK)
    assert new_positions == []
    assert skipped == [("20260718-0630", "NVDA")]
    assert not_purchased == []


def test_ingest_new_positions_same_run_new_ticker_not_skipped():
    existing = [{"run_id": "20260718-0630", "ticker": "AMD"}]
    new_positions, skipped, not_purchased = ingest_new_positions([_sheet_row()], existing, UNIT_DAYS, FALLBACK)
    assert len(new_positions) == 1
    assert skipped == []
    assert not_purchased == []


def test_ingest_new_positions_infers_asset_class_from_numeric_ticker():
    row = _sheet_row(証券コード="7203", 銘柄名="トヨタ自動車")
    new_positions, _, _ = ingest_new_positions([row], [], UNIT_DAYS, FALLBACK)
    assert new_positions[0]["asset_class"] == "japan_equity"


def test_ingest_new_positions_records_fallback_parse_status():
    row = _sheet_row(想定保有期間="しばらく")
    new_positions, _, _ = ingest_new_positions([row], [], UNIT_DAYS, FALLBACK)
    assert new_positions[0]["parse_status"] == "fallback_used"
    assert new_positions[0]["holding_period_days_parsed"] == FALLBACK


def test_ingest_new_positions_coerces_string_numeric_fields_from_real_sheets_api_shape():
    """2026-07-26追加、回帰テスト：Google Sheets APIの`spreadsheets.values.get`は
    デフォルト（valueRenderOption=FORMATTED_VALUE）では数値セルも表示用の文字列
    （例："2897"、"3244.64"）として返す。実データ初回検証で、price_checker.py側の
    算術演算が`unsupported operand type(s) for -: 'float' and 'str'`で失敗する
    実例が発生した。この行のフィクスチャは、既存の`_sheet_row()`（Pythonの数値型を
    直接使っており実物のAPI形状と異なっていた）とは異なり、実際のAPIが返す文字列型
    のまま値を渡し、数値フィールドが正しくfloat/intへ変換されることを検証する。
    """
    row = _sheet_row(
        購入価格目安="333.74", 損切価格="300.37", 利確価格="383.80", 推奨株数="4",
    )
    new_positions, _, _ = ingest_new_positions([row], [], UNIT_DAYS, FALLBACK)
    position = new_positions[0]
    assert position["entry_price"] == 333.74
    assert isinstance(position["entry_price"], float)
    assert position["stop_loss_price"] == 300.37
    assert position["take_profit_price"] == 383.80
    assert position["recommended_shares"] == 4
    assert isinstance(position["recommended_shares"], int)


def test_ingest_new_positions_purchase_confirmations_excludes_not_purchased():
    # 2026-08-09追加：実運用で「3件提案されたうち1件は買わなかった」ケースが発生し、
    # 除外する手段が無かった（実害：買っていない銘柄が架空のポジションとして追跡され
    # 続ける）。purchase_confirmationsでpurchased=falseの銘柄は取り込まない。
    row = _sheet_row(証券コード="SBUX", 銘柄名="Starbucks")
    confirmations = {"SBUX": {"purchased": False}}
    new_positions, skipped, not_purchased = ingest_new_positions(
        [row], [], UNIT_DAYS, FALLBACK, purchase_confirmations=confirmations
    )
    assert new_positions == []
    assert skipped == []
    assert not_purchased == [("20260718-0630", "SBUX")]


def test_ingest_new_positions_purchase_confirmations_overrides_actual_price_and_shares():
    row = _sheet_row(証券コード="2801", 銘柄名="キッコーマン", 購入価格目安=1760.0, 推奨株数=46)
    confirmations = {"2801": {"purchased": True, "actual_entry_price": 1758.0, "actual_shares": 46}}
    new_positions, _, not_purchased = ingest_new_positions(
        [row], [], UNIT_DAYS, FALLBACK, purchase_confirmations=confirmations
    )
    assert not_purchased == []
    assert new_positions[0]["entry_price"] == 1758.0
    assert new_positions[0]["recommended_shares"] == 46
    # 損切・利確価格は提案時点の値をそのまま維持する（実際の約定価格に応じた再計算は行わない）
    assert new_positions[0]["stop_loss_price"] == 300.37


def test_ingest_new_positions_purchase_confirmations_missing_ticker_defaults_to_purchased():
    # confirmationsファイルはあるが、この銘柄のエントリが無い場合は従来通り取り込む（後方互換）。
    row = _sheet_row(証券コード="AMD")
    confirmations = {"2801": {"purchased": False}}
    new_positions, _, not_purchased = ingest_new_positions(
        [row], [], UNIT_DAYS, FALLBACK, purchase_confirmations=confirmations
    )
    assert not_purchased == []
    assert len(new_positions) == 1


def test_ingest_new_positions_no_confirmations_defaults_to_purchased_as_proposed():
    # purchase_confirmations未指定（None）の場合は、従来通り全件「提案＝約定済み」として扱う。
    new_positions, skipped, not_purchased = ingest_new_positions([_sheet_row()], [], UNIT_DAYS, FALLBACK)
    assert len(new_positions) == 1
    assert not_purchased == []
