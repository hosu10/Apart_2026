from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.config import (
    ANALYSIS_REGION_TO_SIDO,
    DB_PATH,
    DEFAULT_ANALYSIS_REGION,
    DEFAULT_LOOKBACK_YEARS,
    DEFAULT_MIN_AGE_YEARS,
    DEFAULT_MIN_TRANSACTIONS,
    SIZE_TIERS,
    TX_CACHE_DIR,
)
from app.db.schema import get_engine, init_db
from app.etl.clean import prepare_analysis_frame, remove_outliers_iqr

StatUnit = Literal["단지", "동", "구", "평형"]

_TX_SQL = """
    SELECT
        t.transaction_id,
        t.deal_date,
        t.exclusive_area,
        t.price,
        t.floor,
        t.transaction_type,
        t.is_cancelled,
        c.complex_id,
        c.complex_name,
        c.dong,
        c.total_households,
        c.completion_year,
        c.lawd_cd,
        c.enrich_source,
        c.latitude,
        c.longitude,
        c.geocode_source,
        r.sigungu,
        r.sido
    FROM fact_transaction t
    JOIN dim_complex c ON t.complex_id = c.complex_id
    JOIN dim_region r ON c.lawd_cd = r.lawd_cd
    WHERE t.is_cancelled = 0
"""


def _resolve_sido(region_or_sido: Optional[str]) -> Optional[str]:
    if not region_or_sido:
        return None
    if region_or_sido in ANALYSIS_REGION_TO_SIDO:
        return ANALYSIS_REGION_TO_SIDO[region_or_sido]
    return region_or_sido


def _cache_path(sido: Optional[str]) -> Path:
    TX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = (sido or "all").replace(" ", "")
    return TX_CACHE_DIR / f"tx_{key}.feather"


def _db_mtime() -> float:
    try:
        return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0
    except OSError:
        return 0.0


def invalidate_tx_cache() -> None:
    """DB 갱신 후 feather 캐시 삭제."""
    if not TX_CACHE_DIR.exists():
        return
    for p in TX_CACHE_DIR.glob("tx_*.feather"):
        try:
            p.unlink()
        except OSError:
            pass
    meta = TX_CACHE_DIR / "cache_meta.json"
    if meta.exists():
        try:
            meta.unlink()
        except OSError:
            pass


def _try_read_cache(sido: Optional[str]) -> Optional[pd.DataFrame]:
    path = _cache_path(sido)
    meta_path = TX_CACHE_DIR / "cache_meta.json"
    if not path.exists() or not meta_path.exists():
        return None
    try:
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stamp = float(meta.get(sido or "all", 0))
        if abs(stamp - _db_mtime()) > 0.5:
            return None
        return pd.read_feather(path)
    except Exception:  # noqa: BLE001
        return None


def _write_cache(df: pd.DataFrame, sido: Optional[str]) -> None:
    if df.empty:
        return
    import json

    TX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(sido)
    meta_path = TX_CACHE_DIR / "cache_meta.json"
    try:
        df.reset_index(drop=True).to_feather(path)
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
        meta[sido or "all"] = _db_mtime()
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


@dataclass
class AnalysisParams:
    sigungu: str = "마포구"
    dong: Optional[str] = None  # None = 구 전체
    size_tier: str = "30평형대"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    lookback_years: int = DEFAULT_LOOKBACK_YEARS
    min_age_years: int = DEFAULT_MIN_AGE_YEARS
    min_transactions: int = DEFAULT_MIN_TRANSACTIONS
    stat_unit: StatUnit = "단지"
    exclude_direct_deal: bool = True
    remove_outliers: bool = True


@dataclass
class AnalysisResult:
    params: AnalysisParams
    filtered: pd.DataFrame = field(default_factory=pd.DataFrame)
    complex_rank: pd.DataFrame = field(default_factory=pd.DataFrame)
    dong_rank: pd.DataFrame = field(default_factory=pd.DataFrame)
    gu_rank: pd.DataFrame = field(default_factory=pd.DataFrame)
    time_series: pd.DataFrame = field(default_factory=pd.DataFrame)
    excluded_summary: dict = field(default_factory=dict)
    message: str = ""


def load_transactions(region: Optional[str] = None) -> pd.DataFrame:
    """거래 로드. region='서울'|'경기도'|sido명 — 기본은 호출측에서 서울.

    Feather 캐시(DB mtime 연동)로 재기동을 빠르게 한다.
    좌표는 DB에 이미 있으면 attach_coords 비용이 거의 없다.
    """
    init_db()
    sido = _resolve_sido(region)
    cached = _try_read_cache(sido)
    if cached is not None:
        return cached

    engine = get_engine()
    sql = _TX_SQL
    params: dict = {}
    if sido:
        sql = _TX_SQL + " AND r.sido = :sido"
        params["sido"] = sido
    try:
        df = pd.read_sql(text(sql), engine, params=params or None, parse_dates=["deal_date"])
    except Exception:
        # geocode_source 컬럼 없을 수 있음
        sql2 = sql.replace("c.geocode_source,", "")
        df = pd.read_sql(text(sql2), engine, params=params or None, parse_dates=["deal_date"])
    if df.empty:
        return df
    from app.geo.coordinates import attach_coords

    out = prepare_analysis_frame(attach_coords(df))
    _write_cache(out, sido)
    return out


def default_load_region() -> str:
    return DEFAULT_ANALYSIS_REGION


def _resolve_period(params: AnalysisParams) -> tuple[date, date]:
    end = params.end_date or date.today()
    start = params.start_date or date(end.year - params.lookback_years, end.month, 1)
    return start, end


def _apply_base_filters(df: pd.DataFrame, params: AnalysisParams) -> tuple[pd.DataFrame, dict]:
    start, end = _resolve_period(params)
    excluded = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "cancelled_or_empty": 0,
        "region": 0,
        "size_tier": 0,
        "direct_deal": 0,
        "outlier": 0,
        "new_build": 0,
        "low_volume": 0,
    }
    if df.empty:
        return df, excluded

    work = df.copy()
    before = len(work)

    work = work[(work["deal_date"] >= pd.Timestamp(start)) & (work["deal_date"] <= pd.Timestamp(end))]
    if params.sigungu:
        work = work[work["sigungu"] == params.sigungu]
    if params.dong:
        work = work[work["dong"] == params.dong]
    excluded["region"] = before - len(work)

    before = len(work)
    if params.size_tier in SIZE_TIERS:
        lo, hi = SIZE_TIERS[params.size_tier]
        work = work[(work["exclusive_area"] >= lo) & (work["exclusive_area"] < hi)]
    excluded["size_tier"] = before - len(work)

    if params.exclude_direct_deal and "transaction_type" in work.columns:
        before = len(work)
        work = work[work["transaction_type"].fillna("중개거래") != "직거래"]
        excluded["direct_deal"] = before - len(work)

    if params.remove_outliers and not work.empty:
        before = len(work)
        work = remove_outliers_iqr(work, ["complex_id", "size_tier"], "price")
        excluded["outlier"] = before - len(work)

    # 신축 제외: 분석 종료일 기준 연한 < min_age_years
    before = len(work)
    age = end.year - work["completion_year"]
    work = work[age >= params.min_age_years]
    excluded["new_build"] = before - len(work)

    # 동일 단지·평형 최소 거래 건수
    before = len(work)
    counts = work.groupby("complex_id").size()
    keep_ids = counts[counts >= params.min_transactions].index
    work = work[work["complex_id"].isin(keep_ids)]
    excluded["low_volume"] = before - len(work)
    excluded["kept"] = len(work)
    excluded["complexes_kept"] = work["complex_id"].nunique() if not work.empty else 0

    return work, excluded


def _period_avg(
    df: pd.DataFrame,
    group_cols: list[str],
    years: int = 2,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """분석기간 초반/후반 N년 평균 가격.

    창은 가능하면 선정 기간(period_start~end) 기준으로 잡는다.
    (필터된 거래의 min/max를 쓰면 다른 단지의 최근 거래 때문에
     최근 거래가 적은 단지가 서열에서 탈락할 수 있음)
    """
    if df.empty:
        return pd.DataFrame()
    dmin = pd.Timestamp(period_start) if period_start is not None else df["deal_date"].min()
    dmax = pd.Timestamp(period_end) if period_end is not None else df["deal_date"].max()
    if pd.isna(dmin) or pd.isna(dmax) or dmax <= dmin:
        return pd.DataFrame()

    span_years = max((dmax - dmin).days / 365.25, 0.5)
    use_years = min(float(years), max(span_years / 2.0, 0.5))
    early_end = dmin + pd.DateOffset(months=int(round(use_years * 12)))
    late_start = dmax - pd.DateOffset(months=int(round(use_years * 12)))
    if early_end > late_start:
        mid = dmin + (dmax - dmin) / 2
        early_end = mid
        late_start = mid

    early = (
        df[(df["deal_date"] >= dmin) & (df["deal_date"] < early_end)]
        .groupby(group_cols)
        .agg(
            start_price=("price", "mean"),
            start_ppp=("price_per_pyeong", "mean"),
            start_count=("price", "count"),
        )
    )
    late = (
        df[(df["deal_date"] > late_start) & (df["deal_date"] <= dmax)]
        .groupby(group_cols)
        .agg(
            end_price=("price", "mean"),
            end_ppp=("price_per_pyeong", "mean"),
            end_count=("price", "count"),
        )
    )
    out = early.join(late, how="inner").reset_index()
    if out.empty:
        return out
    out["price_change_pct"] = (out["end_price"] / out["start_price"] - 1.0) * 100
    out["cagr_pct"] = ((out["end_price"] / out["start_price"]) ** (1 / span_years) - 1.0) * 100
    out["ppp_change_pct"] = (out["end_ppp"] / out["start_ppp"] - 1.0) * 100
    return out


def _complex_ranking(
    df: pd.DataFrame,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    meta = (
        df.groupby(["complex_id", "complex_name", "dong", "total_households", "completion_year"])
        .agg(tx_count=("price", "count"), avg_price=("price", "mean"), avg_ppp=("price_per_pyeong", "mean"))
        .reset_index()
    )
    growth = _period_avg(df, ["complex_id"], period_start=period_start, period_end=period_end)
    if growth.empty:
        return pd.DataFrame()
    merged = meta.merge(growth, on="complex_id", how="inner")
    merged = merged.sort_values("price_change_pct", ascending=False).reset_index(drop=True)
    merged["rank"] = merged.index + 1
    return merged


def _dong_weighted_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """동별 세대수 가중 평균 가격 상승률."""
    complex_rank = _complex_ranking(df)
    if complex_rank.empty:
        return pd.DataFrame()

    def _wavg(g: pd.DataFrame, col: str) -> float:
        w = g["total_households"].astype(float)
        if w.sum() == 0:
            return float(g[col].mean())
        return float(np.average(g[col], weights=w))

    rows = []
    for dong, g in complex_rank.groupby("dong"):
        rows.append(
            {
                "dong": dong,
                "complex_count": len(g),
                "total_households": int(g["total_households"].sum()),
                "tx_count": int(g["tx_count"].sum()),
                "weighted_start_price": _wavg(g, "start_price"),
                "weighted_end_price": _wavg(g, "end_price"),
                "price_change_pct": _wavg(g, "price_change_pct"),
                "cagr_pct": _wavg(g, "cagr_pct"),
                "weighted_avg_ppp": _wavg(g, "avg_ppp"),
            }
        )
    out = pd.DataFrame(rows).sort_values("price_change_pct", ascending=False).reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def _gu_ranking(df: pd.DataFrame) -> pd.DataFrame:
    complex_rank = _complex_ranking(df)
    if complex_rank.empty:
        return pd.DataFrame()
    gu_map = df.drop_duplicates("complex_id")[["complex_id", "sigungu"]]
    tmp = complex_rank.merge(gu_map, on="complex_id", how="left")

    def _wavg(g: pd.DataFrame, col: str) -> float:
        w = g["total_households"].astype(float)
        return float(np.average(g[col], weights=w)) if w.sum() else float(g[col].mean())

    rows = []
    for gu, g in tmp.groupby("sigungu"):
        rows.append(
            {
                "sigungu": gu,
                "complex_count": len(g),
                "total_households": int(g["total_households"].sum()),
                "price_change_pct": _wavg(g, "price_change_pct"),
                "cagr_pct": _wavg(g, "cagr_pct"),
            }
        )
    out = pd.DataFrame(rows).sort_values("price_change_pct", ascending=False).reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def _time_series(df: pd.DataFrame, unit: StatUnit) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["period"] = pd.to_datetime(df["deal_date"]).dt.to_period("Q").astype(str)

    if unit == "단지":
        gcols = ["period", "complex_name"]
    elif unit == "동":
        gcols = ["period", "dong"]
    elif unit == "구":
        gcols = ["period", "sigungu"]
    else:  # 평형
        gcols = ["period", "size_tier"]

    if unit == "동":
        # 분기별: 단지 평균 → 세대수 가중 동 평균
        base = (
            df.groupby(["period", "dong", "complex_id", "total_households"], as_index=False)
            .agg(avg_price=("price", "mean"), avg_ppp=("price_per_pyeong", "mean"), tx_count=("price", "count"))
        )
        rows = []
        for (period, dong), g in base.groupby(["period", "dong"]):
            w = g["total_households"].astype(float)
            rows.append(
                {
                    "period": period,
                    "dong": dong,
                    "avg_price": float(np.average(g["avg_price"], weights=w)) if w.sum() else float(g["avg_price"].mean()),
                    "avg_ppp": float(np.average(g["avg_ppp"], weights=w)) if w.sum() else float(g["avg_ppp"].mean()),
                    "tx_count": int(g["tx_count"].sum()),
                }
            )
        return pd.DataFrame(rows).sort_values("period")

    return (
        df.groupby(gcols, as_index=False)
        .agg(avg_price=("price", "mean"), avg_ppp=("price_per_pyeong", "mean"), tx_count=("price", "count"))
        .sort_values("period")
    )


def analyze(params: AnalysisParams, df: Optional[pd.DataFrame] = None) -> AnalysisResult:
    raw = df if df is not None else load_transactions()
    if raw.empty:
        return AnalysisResult(params=params, message="거래 데이터가 없습니다. 샘플 데이터를 먼저 적재하세요.")

    filtered, excluded = _apply_base_filters(raw, params)
    if filtered.empty:
        return AnalysisResult(
            params=params,
            excluded_summary=excluded,
            message="조건에 맞는 거래가 없습니다. 필터를 완화해 보세요.",
        )

    complex_rank = _complex_ranking(filtered)
    dong_rank = _dong_weighted_ranking(filtered)
    gu_rank = _gu_ranking(filtered)
    ts = _time_series(filtered, params.stat_unit)

    return AnalysisResult(
        params=params,
        filtered=filtered,
        complex_rank=complex_rank,
        dong_rank=dong_rank,
        gu_rank=gu_rank,
        time_series=ts,
        excluded_summary=excluded,
        message="ok",
    )


def list_dong_options(sigungu: str = "마포구") -> list[str]:
    df = load_transactions()
    if df.empty:
        return []
    return sorted(df.loc[df["sigungu"] == sigungu, "dong"].dropna().unique().tolist())


def list_sigungu_options() -> list[str]:
    df = load_transactions()
    if df.empty:
        return ["마포구"]
    return sorted(df["sigungu"].dropna().unique().tolist())
