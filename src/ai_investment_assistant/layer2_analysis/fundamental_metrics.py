"""ファンダメンタル軸（layer2_analysis_design.md §3-2、scoring_specification.md §3-2）。

入力：Layer1の`FundamentalSnapshot`（生数値）＋（screener.pyが付加した）配当利回りの
母集団内パーセンタイル。比率（PER/PBR/ROE等）はここで算出する。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional

from ..layer1_data_acquisition.models import FundamentalSnapshot
from .bucket import Bucket, score_from_buckets
from .reallocation import WeightedItem, weighted_axis_score

PER_BUCKETS = [
    Bucket(None, 10, 85, "FUND_PER_CHEAP", "割安"),
    Bucket(10, 15, 80, "FUND_PER_LOW", "低め"),
    Bucket(15, 20, 70, "FUND_PER_MODERATE", "妥当な水準"),
    Bucket(20, 30, 55, "FUND_PER_ELEVATED", "やや高め"),
    Bucket(30, 50, 40, "FUND_PER_HIGH", "高め"),
    Bucket(50, None, 20, "FUND_PER_EXTREME_OR_NA", "極端に高い、または赤字で算出不能"),
]

PBR_BUCKETS = [
    Bucket(None, 1.0, 85, "FUND_PBR_BELOW_BOOK", "解散価値割れ"),
    Bucket(1.0, 1.5, 75, "FUND_PBR_LOW", "低め"),
    Bucket(1.5, 2.5, 60, "FUND_PBR_MODERATE", "妥当な水準"),
    Bucket(2.5, 4.0, 45, "FUND_PBR_HIGH", "高め"),
    Bucket(4.0, None, 30, "FUND_PBR_EXTREME", "極端に高い"),
]

ROE_BUCKETS = [
    Bucket(15, None, 90, "FUND_ROE_EXCELLENT", "優秀"),
    Bucket(10, 15, 75, "FUND_ROE_GOOD", "良好"),
    Bucket(5, 10, 55, "FUND_ROE_MODERATE", "平均的"),
    Bucket(0, 5, 35, "FUND_ROE_WEAK", "弱い"),
    Bucket(None, 0, 15, "FUND_ROE_NEGATIVE", "マイナス"),
]

ROA_BUCKETS = [
    Bucket(8, None, 85, "FUND_ROA_EXCELLENT", "優秀"),
    Bucket(5, 8, 70, "FUND_ROA_GOOD", "良好"),
    Bucket(2, 5, 50, "FUND_ROA_MODERATE", "平均的"),
    Bucket(0, 2, 35, "FUND_ROA_WEAK", "弱い"),
    Bucket(None, 0, 15, "FUND_ROA_NEGATIVE", "マイナス"),
]

EPS_GROWTH_BUCKETS = [
    Bucket(30, None, 95, "FUND_EPS_GROWTH_HIGH", "高成長"),
    Bucket(15, 30, 80, "FUND_EPS_GROWTH_GOOD", "良好な成長"),
    Bucket(5, 15, 65, "FUND_EPS_GROWTH_MODERATE", "平均的な成長"),
    Bucket(0, 5, 50, "FUND_EPS_GROWTH_FLAT", "横ばい"),
    Bucket(None, 0, 25, "FUND_EPS_GROWTH_NEGATIVE", "マイナス成長"),
]

SALES_GROWTH_BUCKETS = [
    Bucket(20, None, 90, "FUND_SALES_GROWTH_HIGH", "高成長"),
    Bucket(10, 20, 75, "FUND_SALES_GROWTH_GOOD", "良好な成長"),
    Bucket(3, 10, 60, "FUND_SALES_GROWTH_MODERATE", "平均的な成長"),
    Bucket(0, 3, 45, "FUND_SALES_GROWTH_FLAT", "横ばい"),
    Bucket(None, 0, 25, "FUND_SALES_GROWTH_NEGATIVE", "マイナス成長"),
]

OPERATING_MARGIN_BUCKETS = [
    Bucket(20, None, 90, "FUND_OPM_EXCELLENT", "優秀な収益性"),
    Bucket(10, 20, 75, "FUND_OPM_GOOD", "良好な収益性"),
    Bucket(5, 10, 55, "FUND_OPM_MODERATE", "平均的"),
    Bucket(0, 5, 35, "FUND_OPM_WEAK", "低収益"),
    Bucket(None, 0, 15, "FUND_OPM_NEGATIVE", "赤字"),
]

FCF_GROWTH_BUCKETS = [
    Bucket(20, None, 90, "FUND_FCF_GROWTH_HIGH", "高成長"),
    Bucket(10, 20, 75, "FUND_FCF_GROWTH_GOOD", "良好な成長"),
    Bucket(0, 10, 60, "FUND_FCF_GROWTH_MODERATE", "緩やかな成長"),
    Bucket(None, 0, 30, "FUND_FCF_GROWTH_NEGATIVE", "マイナス成長"),
]

EQUITY_RATIO_BUCKETS = [
    Bucket(60, None, 85, "FUND_EQUITY_RATIO_STRONG", "強固な財務基盤"),
    Bucket(40, 60, 70, "FUND_EQUITY_RATIO_GOOD", "健全"),
    Bucket(20, 40, 50, "FUND_EQUITY_RATIO_MODERATE", "平均的"),
    Bucket(None, 20, 30, "FUND_EQUITY_RATIO_WEAK", "財務レバレッジが高い"),
]

DIV_YIELD_RANK_BUCKETS = [
    Bucket(0.9, None, 90, "FUND_DIV_YIELD_TOP10", "上位10%以内"),
    Bucket(0.7, 0.9, 75, "FUND_DIV_YIELD_TOP30", "上位10〜30%"),
    Bucket(0.3, 0.7, 55, "FUND_DIV_YIELD_MID", "中位30〜70%"),
    Bucket(0.0, 0.3, 40, "FUND_DIV_YIELD_BOTTOM30", "下位30%"),
]
DIV_YIELD_NONE = Bucket(None, None, 30, "FUND_DIV_YIELD_NONE", "無配")


@dataclass(frozen=True)
class SubScore:
    indicator: str
    reason_code: str
    score: float
    weight_in_axis: float
    reason: str


class PERScorer(abc.ABC):
    """PERスコアリング方式の抽象インターフェース（§3-2、Strategyパターン）。"""

    @abc.abstractmethod
    def score(self, per: Optional[float], sector_code: Optional[str] = None) -> Bucket:
        ...


class AbsoluteRangePERScorer(PERScorer):
    """絶対レンジ方式（Ver1採用・デフォルト、§3-2のバケット表をそのまま適用）。"""

    def score(self, per: Optional[float], sector_code: Optional[str] = None) -> Bucket:
        if per is None or per <= 0:
            return PER_BUCKETS[-1]  # FUND_PER_EXTREME_OR_NA
        return score_from_buckets(per, PER_BUCKETS)


class SectorRelativePERScorer(PERScorer):
    """業種内偏差値化方式（将来拡張用、Ver1では未実装）。

    §3-2確定事項：入力（対象銘柄のPERと業種コード、母集団の業種別統計）／
    出力（0-100スコア）の型のみを定義し、実装はしない。
    """

    def score(self, per: Optional[float], sector_code: Optional[str] = None) -> Bucket:
        raise NotImplementedError(
            "SectorRelativePERScorerはVer1では未実装（layer2_analysis_design.md §3-2参照）"
        )


PER_SCORER_REGISTRY = {
    "absolute_range": AbsoluteRangePERScorer,
    "sector_relative": SectorRelativePERScorer,
}


def score_axis(
    snapshot: FundamentalSnapshot,
    per: Optional[float],
    pbr: Optional[float],
    dividend_yield_percentile: Optional[float],
    prior_year_eps: Optional[float] = None,
    prior_year_revenue: Optional[float] = None,
    prior_year_fcf: Optional[float] = None,
    per_scorer: Optional[PERScorer] = None,
    sector_code: Optional[str] = None,
) -> dict:
    """ファンダメンタル軸のスコアを算出する（§3-2・§3-7）。

    PER・PBRは時価総額を要するため、呼び出し側（screener.py／scorer.py）が計算して渡す。
    EPS成長率・売上成長率・FCF成長率は前年同期比が必要なため、前年値が渡された場合のみ計算し、
    渡されなければ欠損として再配分する。
    """
    per_scorer = per_scorer or AbsoluteRangePERScorer()
    weights = {
        "ROE": 15, "PER": 15, "EPSGrowth": 15, "SalesGrowth": 10, "OperatingMargin": 10,
        "PBR": 10, "FCFLevel": 5, "FCFGrowth": 5, "EquityRatio": 5, "DividendYieldRank": 5, "ROA": 5,
    }

    sub_scores: list[SubScore] = []
    items: list[WeightedItem] = []

    def _add(name: str, value: Optional[float], buckets, reason_prefix: str, fmt: str = "{:.1f}"):
        if value is None:
            items.append(WeightedItem(name, weights[name], None))
            return
        b = score_from_buckets(value, buckets)
        reason = f"{reason_prefix}={fmt.format(value)}、{b.label}"
        sub_scores.append(SubScore(name, b.reason_code, b.score, weights[name], reason))
        items.append(WeightedItem(name, weights[name], b.score, b.reason_code))

    # ROE, ROA
    roe = (snapshot.net_income / snapshot.net_assets * 100) if snapshot.net_income and snapshot.net_assets else None
    roa = (snapshot.net_income / snapshot.total_assets * 100) if snapshot.net_income and snapshot.total_assets else None
    _add("ROE", roe, ROE_BUCKETS, "ROE", "{:.1f}%")
    _add("ROA", roa, ROA_BUCKETS, "ROA", "{:.1f}%")

    # PER（Strategyパターン経由）
    if per is None:
        items.append(WeightedItem("PER", weights["PER"], None))
    else:
        b = per_scorer.score(per, sector_code)
        reason = f"PER={per:.1f}倍、{b.label}"
        sub_scores.append(SubScore("PER", b.reason_code, b.score, weights["PER"], reason))
        items.append(WeightedItem("PER", weights["PER"], b.score, b.reason_code))

    # PBR
    _add("PBR", pbr, PBR_BUCKETS, "PBR", "{:.2f}倍")

    # EPS成長率
    eps_growth = None
    if prior_year_eps and snapshot.eps is not None and prior_year_eps != 0:
        eps_growth = (snapshot.eps - prior_year_eps) / abs(prior_year_eps) * 100
    _add("EPSGrowth", eps_growth, EPS_GROWTH_BUCKETS, "EPS成長率", "{:.1f}%")

    # 売上成長率
    sales_growth = None
    if prior_year_revenue and snapshot.revenue is not None and prior_year_revenue != 0:
        sales_growth = (snapshot.revenue - prior_year_revenue) / abs(prior_year_revenue) * 100
    _add("SalesGrowth", sales_growth, SALES_GROWTH_BUCKETS, "売上成長率", "{:.1f}%")

    # 営業利益率
    opm = (snapshot.operating_income / snapshot.revenue * 100) if snapshot.operating_income is not None and snapshot.revenue else None
    _add("OperatingMargin", opm, OPERATING_MARGIN_BUCKETS, "営業利益率", "{:.1f}%")

    # FCF水準（営業CF・設備投資から算出）
    fcf = None
    if snapshot.operating_cash_flow is not None and snapshot.capital_expenditure is not None:
        fcf = snapshot.operating_cash_flow - snapshot.capital_expenditure
    if fcf is None:
        items.append(WeightedItem("FCFLevel", weights["FCFLevel"], None))
    else:
        prior_fcf = prior_year_fcf
        if fcf > 0:
            growing = prior_fcf is not None and fcf > prior_fcf
            if prior_fcf is None or growing:
                b = Bucket(None, None, 85, "FUND_FCF_POSITIVE_GROWING", "FCFプラスかつ前期比増加")
            else:
                b = Bucket(None, None, 65, "FUND_FCF_POSITIVE_SHRINKING", "FCFプラスだが前期比減少")
        elif snapshot.operating_cash_flow is not None and snapshot.operating_cash_flow > 0:
            b = Bucket(None, None, 50, "FUND_FCF_NEGATIVE_INVESTING", "FCFマイナスだが営業CFはプラス（投資先行）")
        else:
            b = Bucket(None, None, 20, "FUND_OCF_NEGATIVE", "営業CFもマイナス")
        sub_scores.append(SubScore("FCFLevel", b.reason_code, b.score, weights["FCFLevel"], b.label))
        items.append(WeightedItem("FCFLevel", weights["FCFLevel"], b.score, b.reason_code))

    # FCF成長率
    fcf_growth = None
    if fcf is not None and prior_year_fcf and prior_year_fcf != 0:
        fcf_growth = (fcf - prior_year_fcf) / abs(prior_year_fcf) * 100
    _add("FCFGrowth", fcf_growth, FCF_GROWTH_BUCKETS, "FCF成長率", "{:.1f}%")

    # 自己資本比率
    equity_ratio = None
    if snapshot.net_assets is not None and snapshot.total_assets:
        equity_ratio = snapshot.net_assets / snapshot.total_assets * 100
    _add("EquityRatio", equity_ratio, EQUITY_RATIO_BUCKETS, "自己資本比率", "{:.1f}%")

    # 配当利回り順位（screener.pyが付加したパーセンタイル、無配ならNoneではなく明示フラグが必要だが
    # ここではdividend=0を無配とみなす）
    if snapshot.dividend is not None and snapshot.dividend == 0:
        b = DIV_YIELD_NONE
        sub_scores.append(SubScore("DividendYieldRank", b.reason_code, b.score, weights["DividendYieldRank"], b.label))
        items.append(WeightedItem("DividendYieldRank", weights["DividendYieldRank"], b.score, b.reason_code))
    else:
        _add("DividendYieldRank", dividend_yield_percentile, DIV_YIELD_RANK_BUCKETS, "配当利回り順位パーセンタイル", "{:.2f}")

    axis_score, realloc = weighted_axis_score(items)

    reason = "、".join(s.reason for s in sub_scores)
    if realloc.missing:
        reason += f"（欠損指標: {', '.join(realloc.missing)}、残り指標へ比例配分済み）"

    return {
        "raw": {
            "per": per, "pbr": pbr, "roe": roe, "roa": roa,
            "eps_growth_yoy": eps_growth, "sales_growth_yoy": sales_growth,
            "operating_margin": opm, "fcf": fcf, "fcf_growth_rate": fcf_growth,
            "equity_ratio": equity_ratio, "dividend_yield_rank_pct": dividend_yield_percentile,
        },
        "sub_scores": [s.__dict__ for s in sub_scores],
        "axis_score": round(axis_score, 2),
        "axis_score_reason": reason,
        "missing_indicators": list(realloc.missing),
    }
