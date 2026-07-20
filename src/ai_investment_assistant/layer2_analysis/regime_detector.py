"""市場レジーム判定（layer2_analysis_design.md §3-5、scoring_specification.md §3-6）。

入力：日経平均・TOPIX・S&P500等の指数レベルの`PriceSeries`。
レジーム自体（銘柄非依存）は当日1回のみ計算し、適合スコアの算出のみ銘柄ごとに行う（§3-5）。
"""

from __future__ import annotations

from ..layer1_data_acquisition.models import PriceSeries
from .technical_indicators import _adx, _price_frame  # noqa: F401 (再利用)

GROWTH_STYLE_TAGS = {"growth", "semiconductor", "ai"}
DEFENSIVE_STYLE_TAGS = {"defensive", "high_dividend", "bond"}


def detect_regime(index_series: PriceSeries, adx_threshold: float = 25.0) -> dict:
    """指数の200日線乖離とADX(14)から相場レジームを判定する（scoring_specification.md §3-6）。"""
    frame = _price_frame(index_series)
    close, high, low = frame["close"], frame["high"], frame["low"]
    ma200 = close.rolling(200, min_periods=1).mean()
    adx, _ = _adx(high, low, close)

    latest_close = close.iloc[-1]
    latest_ma200 = ma200.iloc[-1]
    latest_adx = adx.iloc[-1] if not adx.empty and adx.iloc[-1] == adx.iloc[-1] else 0.0  # NaN対策

    above_ma200 = latest_close > latest_ma200
    strong_trend = latest_adx >= adx_threshold

    if above_ma200 and strong_trend:
        regime = "uptrend"
        reason_code = "REGIME_UPTREND"
        reason = f"指数が200日線より上、ADX(14)={latest_adx:.1f}で上向きの強いトレンド"
    elif not above_ma200 and strong_trend:
        regime = "downtrend"
        reason_code = "REGIME_DOWNTREND"
        reason = f"指数が200日線より下、ADX(14)={latest_adx:.1f}で下向きの強いトレンド"
    else:
        regime = "range"
        reason_code = "REGIME_RANGE"
        reason = f"200日線±付近で推移、ADX(14)={latest_adx:.1f}と方向感が弱い"

    return {"regime": regime, "reason_code": reason_code, "reason": reason, "adx14": latest_adx}


def score_fit(regime: str, style_tags: list) -> dict:
    """個別銘柄のレジーム適合スコアを算出する（scoring_specification.md §3-6の表）。"""
    tags = set(style_tags or [])
    is_growth = bool(tags & GROWTH_STYLE_TAGS)
    is_defensive = bool(tags & DEFENSIVE_STYLE_TAGS)

    if regime == "uptrend":
        if is_growth:
            return {"score": 90, "reason_code": "REGIME_FIT_UPTREND_GROWTH", "reason": "上昇相場とグロース/半導体/AI関連タグが合致"}
        if is_defensive:
            return {"score": 40, "reason_code": "REGIME_FIT_UPTREND_DEFENSIVE_MISMATCH", "reason": "上昇相場だがディフェンシブ系銘柄でスタイル不一致"}
        return {"score": 60, "reason_code": "REGIME_FIT_RANGE_NEUTRAL", "reason": "上昇相場、スタイルタグは中立"}

    if regime == "downtrend":
        if is_defensive:
            return {"score": 90, "reason_code": "REGIME_FIT_DOWNTREND_DEFENSIVE", "reason": "下降相場とディフェンシブ/高配当/債券ETFタグが合致"}
        if is_growth:
            return {"score": 30, "reason_code": "REGIME_FIT_DOWNTREND_GROWTH_MISMATCH", "reason": "下降相場だがグロース/半導体銘柄でスタイル不一致"}
        return {"score": 60, "reason_code": "REGIME_FIT_RANGE_NEUTRAL", "reason": "下降相場、スタイルタグは中立"}

    return {"score": 60, "reason_code": "REGIME_FIT_RANGE_NEUTRAL", "reason": "レンジ相場のためスタイルタグを問わず中立スコア"}
