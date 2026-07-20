"""テクニカル軸（layer2_analysis_design.md §3-1、scoring_specification.md §3-1）。

入力：Layer1の`PriceSeries`（最低200日分の日次OHLCVが望ましい。200MA計算のため）。
出力：各指標の実測値（raw）＋バケットスコア（0-100）＋採点理由＋テクニカル軸スコア。

実装上の注記（設計書が数値的な閾値を明示していない箇所の扱い）：
  - MAの並び（perfect_order/mostly_up/converging/mostly_down/perfect_order_down）は、
    5/25/75/200の3つのペア比較（5>25、25>75、75>200）が何個成立するかで判定する
    ヒューリスティックを採用した（設計書は状態の意味のみ定義し、判定アルゴリズムの
    詳細は実装時に委ねられているため）。
  - VWAPの「expanding」判定・52週高値安値の計算窓は、標準的な定義（20日出来高加重、
    252営業日）を採用した。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..layer1_data_acquisition.models import PriceSeries
from .bucket import Bucket, score_from_buckets
from .reallocation import WeightedItem, weighted_axis_score

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


# --- バケット表（scoring_specification.md §3-1） -----------------------------------

RSI_BUCKETS = [
    Bucket(None, 20, 40, "TECH_RSI_DEEP_OVERSOLD", "深い売られすぎ"),
    Bucket(20, 30, 60, "TECH_RSI_OVERSOLD", "売られすぎ、反発期待"),
    Bucket(30, 45, 75, "TECH_RSI_PULLBACK", "調整局面、押し目買いゾーン"),
    Bucket(45, 60, 90, "TECH_RSI_HEALTHY", "健全な上昇トレンド"),
    Bucket(60, 70, 70, "TECH_RSI_WARM", "やや過熱"),
    Bucket(70, 80, 45, "TECH_RSI_OVERBOUGHT", "過熱、反落リスク"),
    Bucket(80, None, 25, "TECH_RSI_EXTREME_OVERBOUGHT", "極度の過熱"),
]

ADX_BUCKETS = [
    Bucket(None, 20, 40, "TECH_ADX_NO_TREND", "トレンドなし"),
    Bucket(20, 25, 55, "TECH_ADX_WEAK_TREND", "弱いトレンド"),
    Bucket(25, 40, 80, "TECH_ADX_STRONG_TREND", "強いトレンド"),
    Bucket(40, None, 65, "TECH_ADX_OVERHEATED_TREND", "過熱したトレンド"),
]

ATR_RATIO_BUCKETS = [
    Bucket(1.5, None, 40, "TECH_ATR_SPIKE", "ボラティリティ急拡大"),
    Bucket(1.0, 1.5, 65, "TECH_ATR_ELEVATED", "やや高いボラティリティ"),
    Bucket(0.7, 1.0, 85, "TECH_ATR_NORMAL", "通常のボラティリティ"),
    Bucket(None, 0.7, 60, "TECH_ATR_COMPRESSED", "ボラティリティ収縮"),
]

BB_BUCKETS = {
    "break_lower": Bucket(None, None, 35, "TECH_BB_BREAK_LOWER", "-2σ超え下抜け"),
    "lower_zone": Bucket(None, None, 75, "TECH_BB_LOWER_ZONE", "-2σ〜-1σ"),
    "mid_zone": Bucket(None, None, 65, "TECH_BB_MID_ZONE", "-1σ〜+1σ"),
    "upper_zone": Bucket(None, None, 80, "TECH_BB_UPPER_ZONE", "+1σ〜+2σ"),
    "walk_upper": Bucket(None, None, 55, "TECH_BB_WALK_UPPER", "+2σ超（バンドウォーク）"),
}

VWAP_BUCKETS = {
    "above_expanding": Bucket(None, None, 80, "TECH_VWAP_ABOVE_EXPANDING", "株価>VWAPで乖離拡大中"),
    "neutral": Bucket(None, None, 60, "TECH_VWAP_NEUTRAL", "株価≈VWAP"),
    "below": Bucket(None, None, 35, "TECH_VWAP_BELOW", "株価<VWAP"),
}

WEEK52_BUCKETS = {
    "new_high": Bucket(None, None, 85, "TECH_52W_NEW_HIGH", "52週高値更新中"),
    "near_high": Bucket(None, None, 75, "TECH_52W_NEAR_HIGH", "高値から-5%以内"),
    "mid_range": Bucket(None, None, 60, "TECH_52W_MID_RANGE_FROM_HIGH", "高値から-5〜-20%"),
    "near_low": Bucket(None, None, 50, "TECH_52W_NEAR_LOW", "安値から+20%以内"),
    "new_low": Bucket(None, None, 20, "TECH_52W_NEW_LOW", "52週安値更新中"),
}

MA_BUCKETS = {
    "perfect_up": Bucket(None, None, 95, "TECH_MA_PERFECT_ORDER_UP", "パーフェクトオーダー上昇"),
    "mostly_up": Bucket(None, None, 75, "TECH_MA_MOSTLY_UP", "概ね上昇配列"),
    "converging": Bucket(None, None, 50, "TECH_MA_CONVERGING", "もみ合い"),
    "mostly_down": Bucket(None, None, 30, "TECH_MA_MOSTLY_DOWN", "概ね下降配列"),
    "perfect_down": Bucket(None, None, 10, "TECH_MA_PERFECT_ORDER_DOWN", "パーフェクトオーダー下降"),
}

MACD_BUCKETS = {
    "golden_cross": Bucket(None, None, 90, "TECH_MACD_GOLDEN_CROSS", "ゴールデンクロス直後"),
    "bullish_expanding": Bucket(None, None, 85, "TECH_MACD_BULLISH_EXPANDING", "MACD>Signalかつヒストグラム拡大中"),
    "bullish_fading": Bucket(None, None, 60, "TECH_MACD_BULLISH_FADING", "MACD>Signalだがヒストグラム縮小中"),
    "bearish_fading": Bucket(None, None, 55, "TECH_MACD_BEARISH_FADING", "MACD<Signalだがヒストグラム縮小中"),
    "dead_cross": Bucket(None, None, 20, "TECH_MACD_DEAD_CROSS", "デッドクロス直後"),
    "bearish_expanding": Bucket(None, None, 15, "TECH_MACD_BEARISH_EXPANDING", "MACD<Signalかつヒストグラム拡大中"),
}


@dataclass(frozen=True)
class SubScore:
    indicator: str
    reason_code: str
    score: float
    weight_in_axis: float
    reason: str


def _price_frame(series: PriceSeries):
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas is required for technical_indicators")
    rows = [
        {
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in series.bars
    ]
    frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return frame


def _rsi(close, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)  # avg_loss=0（ずっと上昇）の場合はRSI=100扱い


def _macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram


def _adx(high, low, close, period: int = 14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    prev_close = close.shift()
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx, atr


def _classify_ma_alignment(ma5, ma25, ma75, ma200, close) -> str:
    pairs_up = [ma5 > ma25, ma25 > ma75, ma75 > ma200]
    up_count = sum(bool(p) for p in pairs_up)
    price_above_5 = close > ma5

    if up_count == 3 and price_above_5:
        return "perfect_up"
    if up_count == 0:
        return "perfect_down"
    # MAが近接（互いに1%以内）している場合はconvergingとみなす
    values = [ma5, ma25, ma75, ma200]
    spread = (max(values) - min(values)) / max(values) if max(values) else 0
    if spread < 0.01:
        return "converging"
    return "mostly_up" if up_count >= 2 else "mostly_down"


def _classify_macd_state(histogram) -> str:
    latest = histogram.iloc[-1]
    prev = histogram.iloc[-2] if len(histogram) > 1 else 0.0

    if prev <= 0 < latest:
        return "golden_cross"
    if prev >= 0 > latest:
        return "dead_cross"
    if latest > 0:
        return "bullish_expanding" if latest > prev else "bullish_fading"
    return "bearish_expanding" if latest < prev else "bearish_fading"


def _classify_bb_position(close_value: float, sma: float, std: float) -> str:
    if std == 0:
        return "mid_zone"
    z = (close_value - sma) / std
    if z < -2:
        return "break_lower"
    if z < -1:
        return "lower_zone"
    if z <= 1:
        return "mid_zone"
    if z <= 2:
        return "upper_zone"
    return "walk_upper"


def _classify_vwap(close_value: float, vwap_value: float, threshold_pct: float = 0.5) -> str:
    if vwap_value == 0:
        return "neutral"
    pct = (close_value - vwap_value) / vwap_value * 100
    if pct > threshold_pct:
        return "above_expanding"
    if pct < -threshold_pct:
        return "below"
    return "neutral"


def _classify_week52(close_value: float, high52: float, low52: float) -> str:
    if high52 == low52:
        return "mid_range"
    if close_value >= high52:
        return "new_high"
    if close_value <= low52:
        return "new_low"
    from_high_pct = (high52 - close_value) / high52 * 100
    from_low_pct = (close_value - low52) / low52 * 100 if low52 else 0
    if from_high_pct <= 5:
        return "near_high"
    if from_low_pct <= 20:
        return "near_low"
    return "mid_range"


def compute_raw_indicators(series: PriceSeries) -> dict:
    """PriceSeriesからテクニカル指標の実測値を計算する（§3-1）。"""
    frame = _price_frame(series)
    close, high, low, volume = frame["close"], frame["high"], frame["low"], frame["volume"]

    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()
    ma75 = close.rolling(75).mean()
    ma200 = close.rolling(200).mean()

    rsi = _rsi(close)
    macd, signal, histogram = _macd(close)
    adx, atr = _adx(high, low, close)

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()

    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).rolling(20).sum() / volume.rolling(20).sum()

    window = min(len(close), 252)
    week52_high = close.rolling(window, min_periods=1).max()
    week52_low = close.rolling(window, min_periods=1).min()

    atr20_avg = atr.rolling(20).mean()

    return {
        "close": close.iloc[-1],
        "rsi14": rsi.iloc[-1],
        "macd": macd.iloc[-1],
        "macd_signal": signal.iloc[-1],
        "macd_histogram": histogram.iloc[-1],
        "macd_histogram_series": histogram,
        "adx14": adx.iloc[-1],
        "atr14": atr.iloc[-1],
        "atr_ratio": (atr.iloc[-1] / atr20_avg.iloc[-1]) if atr20_avg.iloc[-1] else None,
        "ma5": ma5.iloc[-1],
        "ma25": ma25.iloc[-1],
        "ma75": ma75.iloc[-1],
        "ma200": ma200.iloc[-1],
        "ma200_available": bool(len(close) >= 200),
        "sma20": sma20.iloc[-1],
        "std20": std20.iloc[-1],
        "vwap": vwap.iloc[-1],
        "week52_high": week52_high.iloc[-1],
        "week52_low": week52_low.iloc[-1],
    }


def score_axis(series: PriceSeries) -> dict:
    """テクニカル軸のスコアを算出する（§3-1・§3-7）。

    戻り値はJSONスキーマ§5-1の`technical`フィールドと同じ形（raw／sub_scores／
    axis_score／axis_score_reason）。200MA欠損時は欠損マークを付け、他の指標のみで
    再配分する（§3-1「欠損時の扱い」）。
    """
    raw = compute_raw_indicators(series)
    sub_scores: list[SubScore] = []
    weighted_items: list[WeightedItem] = []

    weights = {"MA": 25, "MACD": 20, "RSI": 15, "ADX": 10, "ATR": 10, "BollingerBands": 10, "VWAP": 5, "Week52HighLow": 5}

    # RSI
    b = score_from_buckets(raw["rsi14"], RSI_BUCKETS)
    sub_scores.append(SubScore("RSI", b.reason_code, b.score, weights["RSI"], f"RSI={raw['rsi14']:.1f}、{b.label}"))
    weighted_items.append(WeightedItem("RSI", weights["RSI"], b.score, b.reason_code))

    # MACD
    macd_state = _classify_macd_state(raw["macd_histogram_series"])
    b = MACD_BUCKETS[macd_state]
    sub_scores.append(SubScore("MACD", b.reason_code, b.score, weights["MACD"], b.label))
    weighted_items.append(WeightedItem("MACD", weights["MACD"], b.score, b.reason_code))

    # MA（200MA欠損時は欠損扱い）
    if raw["ma200_available"]:
        alignment = _classify_ma_alignment(raw["ma5"], raw["ma25"], raw["ma75"], raw["ma200"], raw["close"])
        b = MA_BUCKETS[alignment]
        sub_scores.append(SubScore("MA", b.reason_code, b.score, weights["MA"], b.label))
        weighted_items.append(WeightedItem("MA", weights["MA"], b.score, b.reason_code))
    else:
        weighted_items.append(WeightedItem("MA", weights["MA"], None))

    # ADX
    b = score_from_buckets(raw["adx14"], ADX_BUCKETS)
    sub_scores.append(SubScore("ADX", b.reason_code, b.score, weights["ADX"], f"ADX(14)={raw['adx14']:.1f}、{b.label}"))
    weighted_items.append(WeightedItem("ADX", weights["ADX"], b.score, b.reason_code))

    # ATR
    if raw["atr_ratio"] is not None:
        b = score_from_buckets(raw["atr_ratio"], ATR_RATIO_BUCKETS)
        sub_scores.append(SubScore("ATR", b.reason_code, b.score, weights["ATR"], f"ATR比={raw['atr_ratio']:.2f}、{b.label}"))
        weighted_items.append(WeightedItem("ATR", weights["ATR"], b.score, b.reason_code))
    else:
        weighted_items.append(WeightedItem("ATR", weights["ATR"], None))

    # Bollinger Bands
    bb_state = _classify_bb_position(raw["close"], raw["sma20"], raw["std20"])
    b = BB_BUCKETS[bb_state]
    sub_scores.append(SubScore("BollingerBands", b.reason_code, b.score, weights["BollingerBands"], b.label))
    weighted_items.append(WeightedItem("BollingerBands", weights["BollingerBands"], b.score, b.reason_code))

    # VWAP
    vwap_state = _classify_vwap(raw["close"], raw["vwap"])
    b = VWAP_BUCKETS[vwap_state]
    sub_scores.append(SubScore("VWAP", b.reason_code, b.score, weights["VWAP"], b.label))
    weighted_items.append(WeightedItem("VWAP", weights["VWAP"], b.score, b.reason_code))

    # 52週高値・安値
    week_state = _classify_week52(raw["close"], raw["week52_high"], raw["week52_low"])
    b = WEEK52_BUCKETS[week_state]
    sub_scores.append(SubScore("Week52HighLow", b.reason_code, b.score, weights["Week52HighLow"], b.label))
    weighted_items.append(WeightedItem("Week52HighLow", weights["Week52HighLow"], b.score, b.reason_code))

    axis_score, realloc = weighted_axis_score(weighted_items)

    reason = "、".join(s.reason for s in sub_scores)
    if realloc.missing:
        reason += f"（欠損指標: {', '.join(realloc.missing)}、残り指標へ比例配分済み）"

    return {
        "raw": {k: v for k, v in raw.items() if k != "macd_histogram_series"},
        "sub_scores": [s.__dict__ for s in sub_scores],
        "axis_score": round(axis_score, 2),
        "axis_score_reason": reason,
        "missing_indicators": list(realloc.missing),
    }
