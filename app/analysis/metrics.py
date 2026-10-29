"""단지 상승률·시계열 등 분석 지표."""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from app.analysis.trends import _period_avg


def complex_ranking(
    df: pd.DataFrame,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
    window_years: int = 2,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    meta = (
        df.groupby(
            ["complex_id", "complex_name", "sigungu", "dong", "total_households", "completion_year"]
        )
        .agg(
            tx_count=("price", "count"),
            avg_price=("price", "mean"),
            avg_ppp=("price_per_pyeong", "mean"),
            avg_area=("exclusive_area", "mean"),
        )
        .reset_index()
    )
    growth = _period_avg(
        df,
        ["complex_id"],
        years=window_years,
        period_start=period_start,
        period_end=period_end,
    )
    if growth.empty:
        return pd.DataFrame()
    merged = meta.merge(growth, on="complex_id", how="inner")
    merged["growth_per_100hh"] = merged["price_change_pct"] / (merged["total_households"] / 100).replace(0, np.nan)
    merged = merged.sort_values("price_change_pct", ascending=False).reset_index(drop=True)
    merged["rank"] = merged.index + 1
    return merged


def group_price_growth(
    df: pd.DataFrame,
    group_col: str,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
    window_years: int = 2,
) -> pd.DataFrame:
    """구/동 단위 매매 평균가 + 초반·후반 기간 상승률 (단지 서열과 동일 _period_avg)."""
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()
    meta = (
        df.groupby(group_col, as_index=False)
        .agg(
            tx_count=("price", "count"),
            avg_price=("price", "mean"),
            avg_ppp=("price_per_pyeong", "mean"),
            complex_count=("complex_id", "nunique"),
        )
    )
    growth = _period_avg(
        df,
        [group_col],
        years=window_years,
        period_start=period_start,
        period_end=period_end,
    )
    if growth.empty:
        return pd.DataFrame()
    merged = meta.merge(growth, on=group_col, how="inner")
    merged = merged.sort_values("price_change_pct", ascending=False).reset_index(drop=True)
    merged["rank"] = merged.index + 1
    return merged


def quarterly_price_series(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["period"] = pd.to_datetime(sub["deal_date"]).dt.to_period("Q").astype(str)
    out = (
        sub.groupby("period", as_index=False)
        .agg(avg_price=("price", "mean"), avg_ppp=("price_per_pyeong", "mean"), tx_count=("price", "count"))
        .sort_values("period")
    )
    return out


def monthly_price_series(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["period"] = pd.to_datetime(sub["deal_date"]).dt.to_period("M").astype(str)
    return (
        sub.groupby("period", as_index=False)
        .agg(avg_price=("price", "mean"), avg_ppp=("price_per_pyeong", "mean"), tx_count=("price", "count"))
        .sort_values("period")
    )


def floor_price_distribution(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty or "floor" not in sub.columns:
        return pd.DataFrame()
    sub = sub.dropna(subset=["floor"])
    if sub.empty:
        return pd.DataFrame()

    def _band(f: float) -> str:
        if f <= 5:
            return "저층(1~5)"
        if f <= 15:
            return "중층(6~15)"
        return "고층(16+)"

    sub["층구분"] = sub["floor"].map(_band)
    return (
        sub.groupby("층구분", as_index=False)
        .agg(평균가=("price", "mean"), 건수=("price", "count"), 평당가=("price_per_pyeong", "mean"))
    )


def volume_series(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["period"] = pd.to_datetime(sub["deal_date"]).dt.to_period("Q").astype(str)
    return sub.groupby("period", as_index=False).agg(거래건수=("price", "count")).sort_values("period")


def dong_percentile(rank_df: pd.DataFrame, complex_id: int) -> Optional[dict]:
    if rank_df.empty or complex_id not in set(rank_df["complex_id"]):
        return None
    row = rank_df.loc[rank_df["complex_id"] == complex_id].iloc[0]
    peers = rank_df[rank_df["dong"] == row["dong"]]
    if peers.empty:
        return None
    pct = float((peers["price_change_pct"] < row["price_change_pct"]).mean() * 100)
    return {
        "단지명": row["complex_name"],
        "법정동": row["dong"],
        "상승률": float(row["price_change_pct"]),
        "동내백분위": pct,
        "동내순위": int((peers["price_change_pct"] > row["price_change_pct"]).sum() + 1),
        "동내단지수": int(len(peers)),
    }


def complex_profile(df: pd.DataFrame, complex_id: int) -> dict:
    sub = df[df["complex_id"] == complex_id]
    if sub.empty:
        return {}
    row = sub.iloc[0]
    profile = {
        "단지ID": int(complex_id),
        "단지명": row["complex_name"],
        "시군구": row["sigungu"],
        "법정동": row["dong"],
        "준공연도": int(row["completion_year"]),
        "단지전체세대수": int(row["total_households"]),
        "평균전용면적": round(float(sub["exclusive_area"].mean()), 1),
        "거래건수": int(len(sub)),
        "평균매매가": round(float(sub["price"].mean()), 0),
        "평균평당가": round(float(sub["price_per_pyeong"].mean()), 0),
        "최저가": int(sub["price"].min()),
        "최고가": int(sub["price"].max()),
        "최근거래일": str(pd.to_datetime(sub["deal_date"]).max().date()),
    }
    # DB enrichment 컬럼이 거래 조인에 없으면 마스터에서 보강
    try:
        from sqlalchemy import text
        from app.db.schema import get_engine

        eng = get_engine()
        meta = pd.read_sql(
            text(
                """
                SELECT dong_count, jibun_addr, road_addr, use_approval_date,
                       enrich_source, enrich_score, latitude, longitude
                FROM dim_complex WHERE complex_id = :cid
                """
            ),
            eng,
            params={"cid": int(complex_id)},
        )
        if not meta.empty:
            m = meta.iloc[0]
            if pd.notna(m.get("dong_count")):
                profile["동수"] = int(m["dong_count"])
            if isinstance(m.get("jibun_addr"), str) and m["jibun_addr"]:
                profile["지번주소"] = m["jibun_addr"]
            if isinstance(m.get("road_addr"), str) and m["road_addr"]:
                profile["도로명주소"] = m["road_addr"]
            if isinstance(m.get("use_approval_date"), str) and m["use_approval_date"]:
                profile["사용승인일"] = m["use_approval_date"]
            if isinstance(m.get("enrich_source"), str) and m["enrich_source"]:
                profile["정보출처"] = f"{m['enrich_source']} (점수 {m.get('enrich_score', '-')})"
            if pd.notna(m.get("latitude")) and pd.notna(m.get("longitude")):
                profile["위도"] = float(m["latitude"])
                profile["경도"] = float(m["longitude"])
    except Exception:  # noqa: BLE001
        pass
    return profile


# 전세 미수집 시 참고용 추정 비율 (UI에서 명시)
ESTIMATED_JEONSE_RATIO = 0.65


def estimated_jeonse_series(sale_series: pd.DataFrame, ratio: float = ESTIMATED_JEONSE_RATIO) -> pd.DataFrame:
    if sale_series.empty:
        return sale_series
    out = sale_series.copy()
    out["avg_jeonse"] = out["avg_price"] * ratio
    out["jeonse_ratio"] = ratio * 100
    return out
