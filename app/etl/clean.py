from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from app.config import SIZE_TIERS


def normalize_complex_name(name: str) -> str:
    """단지명 공백·특수문자 정규화."""
    if not isinstance(name, str):
        return ""
    name = name.strip()
    name = re.sub(r"\s+", "", name)
    name = name.replace("아파트", "")
    return name


def area_to_size_tier(exclusive_area: float) -> Optional[str]:
    for label, (lo, hi) in SIZE_TIERS.items():
        if lo <= exclusive_area < hi:
            return label
    return None


def exclusive_to_pyeong(exclusive_area: float) -> float:
    """전용면적(㎡) → 평 (관용 환산)."""
    return round(exclusive_area / 3.3058, 1)


def remove_outliers_iqr(
    df: pd.DataFrame,
    group_cols: list[str],
    value_col: str = "price",
    k: float = 1.5,
    min_group_size: int = 20,
) -> pd.DataFrame:
    """동일 단지·평형대 내 IQR 이상치 제거.

    표본이 적은 단지·평형(기본 20건 미만)은 IQR이 최근 정상 상승가를
    이상치로 오인하기 쉬워 제거하지 않는다.
    """
    if df.empty:
        return df

    out = df.copy()
    keep_idx: list[int] = []
    for _, g in out.groupby(group_cols):
        if len(g) < min_group_size:
            keep_idx.extend(g.index.tolist())
            continue
        q1 = g[value_col].quantile(0.25)
        q3 = g[value_col].quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - k * iqr, q3 + k * iqr
        keep_idx.extend(g.index[(g[value_col] >= lo) & (g[value_col] <= hi)].tolist())
    return out.loc[sorted(keep_idx)].copy()


def prepare_analysis_frame(df: pd.DataFrame) -> pd.DataFrame:
    """분석용 공통 파생 컬럼 추가."""
    out = df.copy()
    out["size_tier"] = out["exclusive_area"].map(area_to_size_tier)
    out["pyeong"] = out["exclusive_area"].map(exclusive_to_pyeong)
    out["price_per_pyeong"] = out["price"] / out["pyeong"].replace(0, pd.NA)
    out["deal_year"] = pd.to_datetime(out["deal_date"]).dt.year
    out["deal_month"] = pd.to_datetime(out["deal_date"]).dt.to_period("M").astype(str)
    out["deal_quarter"] = pd.to_datetime(out["deal_date"]).dt.to_period("Q").astype(str)
    return out
