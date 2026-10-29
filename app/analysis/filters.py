"""분석 대상 선정 + 제외 조건 파이프라인."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from app.config import (
    DEFAULT_AGE_MAX,
    DEFAULT_AGE_MIN,
    DEFAULT_HOUSEHOLDS_MAX,
    DEFAULT_HOUSEHOLDS_MIN,
    DEFAULT_LOOKBACK_YEARS,
    DEFAULT_MIN_AGE_YEARS,
    DEFAULT_MIN_TRANSACTIONS,
)
from app.etl.clean import remove_outliers_iqr


@dataclass
class SelectionCriteria:
    """분석 대상 선정 조건."""

    sigungu: Optional[str] = None  # None = 전체
    dong: Optional[str] = None
    area_min: float = 50.0
    area_max: float = 95.0
    age_min: int = DEFAULT_AGE_MIN  # 연식(년) 최소
    age_max: int = DEFAULT_AGE_MAX  # 연식(년) 최대
    # 면적대 세대수가 아니라 단지 전체 세대수(dim_complex.total_households)
    households_min: int = DEFAULT_HOUSEHOLDS_MIN
    households_max: int = DEFAULT_HOUSEHOLDS_MAX
    lookback_years: int = DEFAULT_LOOKBACK_YEARS
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@dataclass
class ExclusionCriteria:
    """선정된 데이터에서 제외할 조건."""

    min_age_years: int = DEFAULT_MIN_AGE_YEARS
    min_transactions: int = DEFAULT_MIN_TRANSACTIONS
    exclude_direct_deal: bool = True
    remove_outliers: bool = True


@dataclass
class FilterResult:
    selected: pd.DataFrame = field(default_factory=pd.DataFrame)
    filtered: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict = field(default_factory=dict)
    message: str = "ok"


def resolve_period(sel: SelectionCriteria) -> tuple[date, date]:
    end = sel.end_date or date.today()
    start = sel.start_date or date(end.year - sel.lookback_years, 1, 1)
    return start, end


def apply_selection(df: pd.DataFrame, sel: SelectionCriteria) -> tuple[pd.DataFrame, dict]:
    start, end = resolve_period(sel)
    summary = {
        "기간시작": start.isoformat(),
        "기간종료": end.isoformat(),
        "원본건수": int(len(df)),
        "선정후건수": 0,
        "선정단지수": 0,
    }
    if df.empty:
        return df.copy(), summary

    work = df.copy()
    work = work[(work["deal_date"] >= pd.Timestamp(start)) & (work["deal_date"] <= pd.Timestamp(end))]

    if sel.sigungu:
        work = work[work["sigungu"] == sel.sigungu]
    if sel.dong:
        work = work[work["dong"] == sel.dong]

    work = work[(work["exclusive_area"] >= sel.area_min) & (work["exclusive_area"] <= sel.area_max)]

    ref_year = end.year
    age = ref_year - work["completion_year"]
    work = work[(age >= sel.age_min) & (age <= sel.age_max)]

    # 단지 전체 세대수 기준 (전용면적 필터와 독립, 해당 면적 세대수 아님)
    work = work[
        (work["total_households"] >= sel.households_min)
        & (work["total_households"] <= sel.households_max)
    ]

    # 미보강 기본값(300) 단지는 세대수 신뢰 불가 → 분석 제외
    before_ph = len(work)
    if "enrich_source" in work.columns:
        placeholder = (work["total_households"] == 300) & (work["enrich_source"].isna())
        work = work[~placeholder]
    summary["미보강300제외"] = before_ph - len(work)

    summary["선정후건수"] = int(len(work))
    summary["선정단지수"] = int(work["complex_id"].nunique()) if not work.empty else 0
    summary["세대수최소적용"] = int(sel.households_min)
    return work, summary


def apply_exclusion(
    df: pd.DataFrame,
    exc: ExclusionCriteria,
    end_date: Optional[date] = None,
) -> tuple[pd.DataFrame, dict]:
    end = end_date or date.today()
    summary = {
        "직거래제외": 0,
        "이상치제외": 0,
        "최소연한제외": 0,
        "저거래제외": 0,
        "최종건수": 0,
        "최종단지수": 0,
    }
    if df.empty:
        return df.copy(), summary

    work = df.copy()

    if exc.exclude_direct_deal and "transaction_type" in work.columns:
        before = len(work)
        work = work[work["transaction_type"].fillna("중개거래") != "직거래"]
        summary["직거래제외"] = before - len(work)

    if exc.remove_outliers and not work.empty:
        before = len(work)
        group_cols = ["complex_id"]
        if "size_tier" in work.columns:
            group_cols.append("size_tier")
        work = remove_outliers_iqr(work, group_cols, "price")
        summary["이상치제외"] = before - len(work)

    before = len(work)
    age = end.year - work["completion_year"]
    work = work[age >= exc.min_age_years]
    summary["최소연한제외"] = before - len(work)

    before = len(work)
    counts = work.groupby("complex_id").size()
    keep_ids = counts[counts >= exc.min_transactions].index
    work = work[work["complex_id"].isin(keep_ids)]
    summary["저거래제외"] = before - len(work)

    summary["최종건수"] = int(len(work))
    summary["최종단지수"] = int(work["complex_id"].nunique()) if not work.empty else 0
    return work, summary


def apply_filters(
    df: pd.DataFrame,
    sel: SelectionCriteria,
    exc: ExclusionCriteria,
) -> FilterResult:
    if df.empty:
        return FilterResult(message="거래 데이터가 없습니다.")

    selected, sel_sum = apply_selection(df, sel)
    if selected.empty:
        return FilterResult(
            selected=selected,
            summary={**sel_sum, **asdict(exc)},
            message="선정 조건에 맞는 거래가 없습니다. 조건을 완화해 보세요.",
        )

    _, end = resolve_period(sel)
    filtered, exc_sum = apply_exclusion(selected, exc, end_date=end)
    summary = {**sel_sum, **exc_sum}
    if filtered.empty:
        return FilterResult(
            selected=selected,
            filtered=filtered,
            summary=summary,
            message="제외 조건 적용 후 남은 거래가 없습니다.",
        )
    return FilterResult(selected=selected, filtered=filtered, summary=summary, message="ok")


def complex_catalog(df: pd.DataFrame) -> pd.DataFrame:
    """단지 목록(선택 UI용)."""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "complex_id",
                "complex_name",
                "sigungu",
                "dong",
                "completion_year",
                "total_households",
            ]
        )
    return (
        df.groupby(
            ["complex_id", "complex_name", "sigungu", "dong", "completion_year", "total_households"],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "tx_count"})
        .sort_values(["sigungu", "dong", "complex_name"])
    )
