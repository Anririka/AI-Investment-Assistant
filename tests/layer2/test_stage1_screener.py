"""stage1_screener.pyのテスト（2026-07-26追加、項目6の第1段階スクリーニング）。"""

from datetime import date, datetime, timedelta

from ai_investment_assistant.layer1_data_acquisition.models import DataFetchMeta, PriceBar, PriceSeries
from ai_investment_assistant.layer2_analysis import stage1_screener


def _make_series(ticker, closes, volume=2_000_000, base_date=date(2025, 1, 1)):
    bars = tuple(
        PriceBar(
            date=base_date + timedelta(days=i),
            open=c, high=c * 1.01, low=c * 0.99, close=c, volume=volume,
        )
        for i, c in enumerate(closes)
    )
    meta = DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 26))
    return PriceSeries(ticker=ticker, currency="JPY", bars=bars, meta=meta)


def _uptrend_closes(n=300, start=1000.0, step=1.0):
    return [start + i * step for i in range(n)]


def _flat_closes(n=300, value=1000.0):
    return [value for _ in range(n)]


UNIVERSE_CONFIG = {
    "japan_equity": {"min_avg_volume": 500_000, "stage1_shortlist_size": 2},
    "us_equity": {"min_avg_volume": 1_000_000, "stage1_shortlist_size": 2},
}


def test_average_recent_volume_uses_most_recent_window():
    series = _make_series("7203", _flat_closes(30), volume=1_000_000)
    assert stage1_screener.average_recent_volume(series, window=20) == 1_000_000


def test_average_recent_volume_returns_none_for_empty_series():
    meta = DataFetchMeta(source_used="test", fetched_at=datetime(2026, 7, 26))
    series = PriceSeries(ticker="EMPTY", currency="JPY", bars=(), meta=meta)
    assert stage1_screener.average_recent_volume(series) is None


def test_filter_by_liquidity_excludes_below_min_avg_volume():
    candidates = [
        {"ticker": "LIQUID", "asset_class": "japan_equity", "price_series": _make_series("LIQUID", _flat_closes(30), volume=1_000_000)},
        {"ticker": "THIN", "asset_class": "japan_equity", "price_series": _make_series("THIN", _flat_closes(30), volume=100_000)},
    ]
    passed, excluded = stage1_screener.filter_by_liquidity(candidates, UNIVERSE_CONFIG)

    assert [c["ticker"] for c in passed] == ["LIQUID"]
    assert excluded == {"THIN"}
    # avg_volumeが付加されていること
    assert passed[0]["avg_volume"] == 1_000_000


def test_filter_by_liquidity_no_threshold_configured_passes_all():
    candidates = [
        {"ticker": "A", "asset_class": "no_threshold_class", "price_series": _make_series("A", _flat_closes(30), volume=1)},
    ]
    passed, excluded = stage1_screener.filter_by_liquidity(candidates, {"no_threshold_class": {}})
    assert [c["ticker"] for c in passed] == ["A"]
    assert excluded == set()


def test_score_technical_attaches_axis_score_for_sufficient_history():
    candidates = [
        {"ticker": "UP", "asset_class": "japan_equity", "price_series": _make_series("UP", _uptrend_closes())},
    ]
    scored, excluded = stage1_screener.score_technical(candidates)

    assert len(scored) == 1
    assert excluded == {}
    assert 0 <= scored[0]["stage1_technical_score"] <= 100


def test_score_technical_excludes_ticker_with_insufficient_history():
    # RSI等の計算に必要な日数（14日程度）に満たない、新規上場直後を想定した短い系列
    candidates = [
        {"ticker": "NEWIPO", "asset_class": "us_equity", "price_series": _make_series("NEWIPO", [100.0, 101.0, 99.0])},
    ]
    scored, excluded = stage1_screener.score_technical(candidates)

    assert scored == []
    assert "NEWIPO" in excluded


def test_select_shortlist_picks_top_n_by_technical_score_per_asset_class():
    # 上昇トレンド（テクニカルスコア高）2銘柄、横ばい（スコア中庸）2銘柄、
    # 出来高不足で足切りされる1銘柄、を日本株・米国株それぞれ用意する
    candidates = []
    for asset_class, prefix, min_vol_ok_volume in (
        ("japan_equity", "JP", 1_000_000),
        ("us_equity", "US", 2_000_000),
    ):
        candidates.append({
            "ticker": f"{prefix}_UP1", "asset_class": asset_class,
            "price_series": _make_series(f"{prefix}_UP1", _uptrend_closes(step=2.0), volume=min_vol_ok_volume),
        })
        candidates.append({
            "ticker": f"{prefix}_UP2", "asset_class": asset_class,
            "price_series": _make_series(f"{prefix}_UP2", _uptrend_closes(step=1.5), volume=min_vol_ok_volume),
        })
        candidates.append({
            "ticker": f"{prefix}_FLAT", "asset_class": asset_class,
            "price_series": _make_series(f"{prefix}_FLAT", _flat_closes(), volume=min_vol_ok_volume),
        })
        candidates.append({
            "ticker": f"{prefix}_THIN", "asset_class": asset_class,
            "price_series": _make_series(f"{prefix}_THIN", _uptrend_closes(), volume=1),  # 出来高不足
        })

    result = stage1_screener.select_shortlist(candidates, UNIVERSE_CONFIG)

    # stage1_shortlist_size=2 なので各市場上位2件のみ、かつ出来高不足銘柄(_THIN)は必ず除外される
    assert len(result["shortlist"]["japan_equity"]) == 2
    assert "JP_THIN" not in result["shortlist"]["japan_equity"]
    assert len(result["shortlist"]["us_equity"]) == 2
    assert "US_THIN" not in result["shortlist"]["us_equity"]

    # 上昇トレンドの2銘柄が横ばい銘柄より優先的に選ばれること
    assert "JP_FLAT" not in result["shortlist"]["japan_equity"]
    assert "US_FLAT" not in result["shortlist"]["us_equity"]


def test_select_shortlist_uses_default_size_when_not_configured():
    candidates = [
        {"ticker": f"T{i}", "asset_class": "japan_equity", "price_series": _make_series(f"T{i}", _uptrend_closes(step=float(i)))}
        for i in range(1, 5)
    ]
    result = stage1_screener.select_shortlist(candidates, {"japan_equity": {}})
    # DEFAULT_SHORTLIST_SIZE=20 > 候補4件なので全件通過する
    assert len(result["shortlist"]["japan_equity"]) == 4


def test_select_shortlist_reports_excluded_counts_for_logging():
    candidates = [
        {"ticker": f"T{i}", "asset_class": "japan_equity", "price_series": _make_series(f"T{i}", _uptrend_closes(step=float(i)))}
        for i in range(1, 6)
    ]
    result = stage1_screener.select_shortlist(candidates, UNIVERSE_CONFIG)  # shortlist_size=2
    assert result["stage1_excluded_count"]["japan_equity"] == 3
