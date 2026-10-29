"""층별 가격 프리미엄 분석.

단지별 시점 추세가(월평균·선형보간) 대비 개별 거래의 편차(%)를 구하고,
층·층높이비율별로 집계한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FloorPremiumResult:
    deals: pd.DataFrame
    by_floor: pd.DataFrame
    by_height_pct: pd.DataFrame
    summary: dict


def _trend_price_series(sub: pd.DataFrame) -> pd.Series:
    """거래일별 추세가: 월평균을 일자에 보간."""
    s = sub.copy()
    s["deal_date"] = pd.to_datetime(s["deal_date"])
    monthly = (
        s.groupby(s["deal_date"].dt.to_period("M"))["price"]
        .mean()
        .rename("trend")
        .to_frame()
    )
    monthly.index = monthly.index.to_timestamp()
    if monthly.empty:
        return pd.Series(np.nan, index=s.index)
    if len(monthly) == 1:
        return pd.Series(float(monthly["trend"].iloc[0]), index=s.index)

    # 일자 선형 보간 (월 중심 기준)
    x = monthly.index.asi8.astype(float)
    y = monthly["trend"].to_numpy(dtype=float)
    xd = s["deal_date"].astype("int64").astype(float).to_numpy()
    trend = np.interp(xd, x, y)
    return pd.Series(trend, index=s.index)


def compute_floor_premiums(df: pd.DataFrame, min_complex_tx: int = 8) -> FloorPremiumResult:
    if df.empty or "floor" not in df.columns:
        return FloorPremiumResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"거래수": 0, "단지수": 0})

    work = df.dropna(subset=["floor", "price", "deal_date"]).copy()
    work = work[work["floor"] >= 1]  # 지하 제외
    if work.empty:
        return FloorPremiumResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"거래수": 0, "단지수": 0})

    parts: list[pd.DataFrame] = []
    for cid, g in work.groupby("complex_id"):
        if len(g) < min_complex_tx:
            continue
        g = g.copy()
        max_fl = int(g["floor"].max())
        if max_fl <= 1:
            continue
        g["trend_price"] = _trend_price_series(g)
        g = g[g["trend_price"] > 0]
        if g.empty:
            continue
        g["max_floor"] = max_fl
        g["height_pct"] = (g["floor"] / max_fl) * 100.0
        g["premium"] = g["price"] - g["trend_price"]
        g["premium_pct"] = (g["premium"] / g["trend_price"]) * 100.0
        g["is_1f"] = g["floor"] == 1
        g["is_2f"] = g["floor"] == 2
        g["is_top"] = g["floor"] == max_fl
        parts.append(g)

    if not parts:
        return FloorPremiumResult(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            {"거래수": 0, "단지수": 0, "메시지": "표본이 부족합니다. 조건을 완화해 보세요."},
        )

    deals = pd.concat(parts, ignore_index=True)

    by_floor = (
        deals.groupby("floor", as_index=False)
        .agg(
            거래수=("premium_pct", "count"),
            평균프리미엄pct=("premium_pct", "mean"),
            중앙프리미엄pct=("premium_pct", "median"),
            평균가=("price", "mean"),
        )
        .sort_values("floor")
    )

    # 최고층 대비 높이 % 구간 (10%p)
    deals["height_bin"] = (deals["height_pct"] // 10 * 10).clip(0, 90).astype(int)
    by_height = (
        deals.groupby("height_bin", as_index=False)
        .agg(
            거래수=("premium_pct", "count"),
            평균프리미엄pct=("premium_pct", "mean"),
            중앙프리미엄pct=("premium_pct", "median"),
        )
        .sort_values("height_bin")
    )
    by_height["높이구간"] = by_height["height_bin"].map(lambda x: f"{int(x)}~{int(x)+10}%")

    best = by_height.loc[by_height["평균프리미엄pct"].idxmax()] if not by_height.empty else None
    summary = {
        "거래수": int(len(deals)),
        "단지수": int(deals["complex_id"].nunique()),
        "1층_평균프리미엄pct": float(deals.loc[deals["is_1f"], "premium_pct"].mean())
        if deals["is_1f"].any()
        else None,
        "2층_평균프리미엄pct": float(deals.loc[deals["is_2f"], "premium_pct"].mean())
        if deals["is_2f"].any()
        else None,
        "꼭대기층_평균프리미엄pct": float(deals.loc[deals["is_top"], "premium_pct"].mean())
        if deals["is_top"].any()
        else None,
        "최고프리미엄_높이구간": str(best["높이구간"]) if best is not None else None,
        "최고프리미엄_높이구간_pct": float(best["평균프리미엄pct"]) if best is not None else None,
        "전체_평균프리미엄pct": float(deals["premium_pct"].mean()),
    }
    return FloorPremiumResult(deals=deals, by_floor=by_floor, by_height_pct=by_height, summary=summary)
