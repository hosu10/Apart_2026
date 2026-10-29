"""상대비교·단지분석·실거래 상세 차트."""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.analysis.trends import _period_avg
from app.ui.chart_style import INTEREST, KR_FONT, TEXT, apply_price_yaxis, axis_style, base_layout

# 관심단지=빨강, 나머지=파랑·주황·녹색
PEER_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"]


def _color_for(idx: int, complex_id: int, interest_id: Optional[int]) -> str:
    if interest_id is not None and complex_id == interest_id:
        return INTEREST
    # interest를 제외한 순번으로 색 배정
    return PEER_COLORS[idx % len(PEER_COLORS)]


def _complex_label(df: pd.DataFrame, complex_id: int) -> str:
    sub = df.loc[df["complex_id"] == complex_id, "complex_name"]
    return str(sub.iloc[0]) if not sub.empty else str(complex_id)


def _growth_pct(
    df: pd.DataFrame,
    complex_id: int,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
) -> Optional[float]:
    sub = df[df["complex_id"] == complex_id]
    if sub.empty:
        return None
    g = _period_avg(sub, ["complex_id"], years=2, period_start=period_start, period_end=period_end)
    if g.empty:
        # 폴백: 월평균 첫·끝
        m = (
            sub.assign(ym=pd.to_datetime(sub["deal_date"]).dt.to_period("M"))
            .groupby("ym", as_index=False)["price"]
            .mean()
            .sort_values("ym")
        )
        if len(m) < 2 or m.iloc[0]["price"] <= 0:
            return None
        return float((m.iloc[-1]["price"] / m.iloc[0]["price"] - 1.0) * 100)
    return float(g.iloc[0]["price_change_pct"])


def chart_multi_complex_prices(
    df: pd.DataFrame,
    complex_ids: Sequence[int],
    interest_id: Optional[int] = None,
    period_start: date | pd.Timestamp | None = None,
    period_end: date | pd.Timestamp | None = None,
    title: str = "상대 비교 · 실거래가",
    height: int = 580,
) -> go.Figure:
    """여러 단지를 한 그래프에: 실거래 점 + 월평균 꺾은선 + 색별 점선 추세(끝에 상승률)."""
    fig = go.Figure()
    ids = [int(c) for c in complex_ids if c is not None]
    if not ids:
        fig.update_layout(**base_layout("비교할 단지가 없습니다", height=min(480, height)))
        return fig

    # 관심단지를 앞에 두고 색 인덱스 안정화
    ordered: list[int] = []
    if interest_id is not None and interest_id in ids:
        ordered.append(int(interest_id))
    for c in ids:
        if c not in ordered:
            ordered.append(c)

    peer_i = 0
    for cid in ordered:
        sub = df[df["complex_id"] == cid].copy()
        if sub.empty:
            continue
        is_interest = interest_id is not None and cid == interest_id
        color = INTEREST if is_interest else PEER_COLORS[peer_i % len(PEER_COLORS)]
        if not is_interest:
            peer_i += 1

        name = _complex_label(df, cid)
        prefix = "★ " if is_interest else ""
        sub["deal_date"] = pd.to_datetime(sub["deal_date"])
        sub = sub.sort_values("deal_date")

        # 실거래 점
        fig.add_trace(
            go.Scatter(
                x=sub["deal_date"],
                y=sub["price"],
                mode="markers",
                name=f"{prefix}{name} 실거래",
                marker=dict(size=8, color=color, opacity=0.55, line=dict(width=0.5, color="#333")),
                hovertemplate=(
                    f"{name}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.0f}}만원"
                    "<br>면적=%{customdata[0]:.1f}㎡ · %{customdata[1]}층<extra></extra>"
                ),
                customdata=np.column_stack(
                    [
                        sub["exclusive_area"].to_numpy(),
                        sub["floor"].fillna(0).to_numpy() if "floor" in sub.columns else np.zeros(len(sub)),
                    ]
                ),
                legendgroup=str(cid),
            )
        )

        # 월평균 꺾은선
        monthly = (
            sub.groupby(sub["deal_date"].dt.to_period("M"))
            .agg(avg_price=("price", "mean"), n=("price", "count"))
            .reset_index()
        )
        monthly["deal_date"] = monthly["deal_date"].dt.to_timestamp()
        monthly = monthly.sort_values("deal_date")
        if not monthly.empty:
            fig.add_trace(
                go.Scatter(
                    x=monthly["deal_date"],
                    y=monthly["avg_price"],
                    mode="lines+markers",
                    name=f"{prefix}{name} 월평균",
                    line=dict(color=color, width=2.4),
                    marker=dict(size=6, color=color),
                    hovertemplate=f"{name} 월평균<br>%{{x|%Y-%m}}<br>%{{y:,.0f}}만원<extra></extra>",
                    legendgroup=str(cid),
                )
            )

        # 점선 추세선 + 끝 상승률
        if len(monthly) >= 2:
            x_ord = np.arange(len(monthly), dtype=float)
            y = monthly["avg_price"].to_numpy(dtype=float)
            coef = np.polyfit(x_ord, y, 1)
            trend_y = coef[0] * x_ord + coef[1]
            growth = _growth_pct(df, cid, period_start, period_end)
            growth_txt = f"{growth:+.1f}%" if growth is not None else ""
            fig.add_trace(
                go.Scatter(
                    x=monthly["deal_date"],
                    y=trend_y,
                    mode="lines",
                    name=f"{prefix}{name} 추세",
                    line=dict(color=color, width=2, dash="dot"),
                    hovertemplate=f"{name} 추세<br>%{{y:,.0f}}만원<extra></extra>",
                    legendgroup=str(cid),
                    showlegend=True,
                )
            )
            # 끝점 상승률 라벨
            fig.add_annotation(
                x=monthly["deal_date"].iloc[-1],
                y=float(trend_y[-1]),
                text=f"<b>{growth_txt}</b>" if growth_txt else "",
                showarrow=True,
                arrowhead=0,
                ax=36,
                ay=-18,
                font=dict(family=KR_FONT, size=13, color=color),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor=color,
                borderwidth=1,
            )

    fig.update_layout(
        **base_layout(
            title,
            height=height,
            xaxis=axis_style("계약일"),
        )
    )
    apply_price_yaxis(fig, "거래가")
    return fig


def chart_complex_transactions(
    df: pd.DataFrame,
    complex_id: int,
    interest: bool = False,
) -> go.Figure:
    """단일 단지 실거래 시계열(점 + 월평균 꺾은선)."""
    fig = go.Figure()
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty:
        fig.update_layout(**base_layout("실거래 없음", interest=interest, height=420))
        return fig
    color = INTEREST if interest else "#1f77b4"
    name = _complex_label(df, complex_id)
    sub["deal_date"] = pd.to_datetime(sub["deal_date"])
    sub = sub.sort_values("deal_date")

    fig.add_trace(
        go.Scatter(
            x=sub["deal_date"],
            y=sub["price"],
            mode="markers",
            name="실거래",
            marker=dict(size=9, color=color, opacity=0.65),
            customdata=np.column_stack(
                [
                    sub["exclusive_area"].to_numpy(),
                    sub["floor"].fillna(0).to_numpy() if "floor" in sub.columns else np.zeros(len(sub)),
                ]
            ),
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>%{y:,.0f}만원<br>면적=%{customdata[0]:.1f}㎡ · %{customdata[1]}층"
                "<extra></extra>"
            ),
        )
    )
    monthly = (
        sub.groupby(sub["deal_date"].dt.to_period("M"))
        .agg(avg_price=("price", "mean"))
        .reset_index()
    )
    monthly["deal_date"] = monthly["deal_date"].dt.to_timestamp()
    fig.add_trace(
        go.Scatter(
            x=monthly["deal_date"],
            y=monthly["avg_price"],
            mode="lines+markers",
            name="월평균",
            line=dict(color=color, width=2.5),
            marker=dict(size=6, color=color),
        )
    )
    fig.update_layout(
        **base_layout(
            f"{name} · 실거래 추이",
            interest=interest,
            height=420,
            xaxis=axis_style("계약일"),
        )
    )
    apply_price_yaxis(fig, "거래가")
    return fig


def transactions_table(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    sub = df[df["complex_id"] == complex_id].copy()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.sort_values("deal_date", ascending=False)
    out = pd.DataFrame(
        {
            "계약일": pd.to_datetime(sub["deal_date"]).dt.strftime("%Y-%m-%d"),
            "거래가(만원)": sub["price"].map(lambda x: f"{x:,.0f}"),
            "전용면적(㎡)": sub["exclusive_area"].map(lambda x: f"{x:.1f}"),
            "층": sub["floor"] if "floor" in sub.columns else "",
            "거래유형": sub["transaction_type"] if "transaction_type" in sub.columns else "",
            "평당가(만원)": sub["price_per_pyeong"].map(lambda x: f"{x:,.0f}")
            if "price_per_pyeong" in sub.columns
            else "",
        }
    )
    return out
