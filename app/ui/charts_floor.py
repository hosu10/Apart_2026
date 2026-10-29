"""층별 가격 프리미엄 차트."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.analysis.floor_premium import FloorPremiumResult
from app.ui.chart_style import INTEREST, KR_FONT, PRICE, TEXT, axis_style, base_layout


def chart_floor_premium_bars(result: FloorPremiumResult) -> go.Figure:
    df = result.by_floor
    fig = go.Figure()
    if df.empty:
        fig.update_layout(**base_layout("층별 프리미엄 데이터 없음", height=420))
        return fig
    colors = [INTEREST if v < 0 else PRICE for v in df["평균프리미엄pct"]]
    fig.add_trace(
        go.Bar(
            x=df["floor"],
            y=df["평균프리미엄pct"],
            marker_color=colors,
            text=df["평균프리미엄pct"].map(lambda x: f"{x:+.1f}%"),
            textposition="outside",
            textfont=dict(family=KR_FONT, size=11, color=TEXT),
            customdata=df[["거래수"]],
            hovertemplate="층=%{x}<br>평균 프리미엄=%{y:.1f}%<br>거래=%{customdata[0]}건<extra></extra>",
            name="평균 프리미엄%",
        )
    )
    fig.add_hline(y=0, line_color="#666", line_width=1)
    fig.update_layout(
        **base_layout(
            "층별 추세가 대비 평균 프리미엄(%)",
            height=460,
            xaxis=axis_style("층"),
            yaxis=axis_style("프리미엄(%)"),
        )
    )
    return fig


def chart_height_premium_bars(result: FloorPremiumResult) -> go.Figure:
    df = result.by_height_pct
    fig = go.Figure()
    if df.empty:
        fig.update_layout(**base_layout("높이비율 프리미엄 데이터 없음", height=420))
        return fig
    best_i = int(df["평균프리미엄pct"].idxmax())
    colors = [INTEREST if i == best_i else PRICE for i in df.index]
    fig.add_trace(
        go.Bar(
            x=df["높이구간"],
            y=df["평균프리미엄pct"],
            marker_color=colors,
            text=df["평균프리미엄pct"].map(lambda x: f"{x:+.1f}%"),
            textposition="outside",
            textfont=dict(family=KR_FONT, size=12, color=TEXT),
            customdata=df[["거래수"]],
            hovertemplate="%{x}<br>평균 프리미엄=%{y:.1f}%<br>거래=%{customdata[0]}건<extra></extra>",
            name="높이구간 프리미엄%",
        )
    )
    fig.add_hline(y=0, line_color="#666", line_width=1)
    fig.update_layout(
        **base_layout(
            "최고층 대비 높이비율별 프리미엄(%) · 최고구간 강조",
            height=460,
            xaxis=axis_style("높이비율(최고층=100%)"),
            yaxis=axis_style("프리미엄(%)"),
        )
    )
    return fig
