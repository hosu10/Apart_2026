from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.config import ENTITY_LABELS_KO

PRICE_COLOR = "#1f4e79"
ACCENT = "#c45c26"
BG = "#f7f4ef"
TEXT = "#1a1a1a"
GRID = "#d9d2c5"

# Windows/Mac 한글 폰트 폴백 (Plotly 캔버스)
KR_FONT = "Malgun Gothic, Apple SD Gothic Neo, NanumGothic, Noto Sans KR, sans-serif"


def _base_layout(**kwargs) -> dict:
    layout = dict(
        font=dict(family=KR_FONT, size=15, color=TEXT),
        title=dict(font=dict(family=KR_FONT, size=20, color=TEXT), x=0.01, xanchor="left"),
        legend=dict(
            font=dict(family=KR_FONT, size=12, color=TEXT),
            bgcolor="rgba(255,255,255,0.96)",
            bordercolor=GRID,
            borderwidth=1,
            orientation="v",
            yanchor="bottom",
            y=0.0,
            xanchor="left",
            x=1.02,
        ),
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        margin=dict(l=88, r=160, t=72, b=48),
        hoverlabel=dict(font=dict(family=KR_FONT, size=13)),
    )
    layout.update(kwargs)
    return layout


def format_manwon(v: float) -> str:
    if pd.isna(v):
        return "-"
    if abs(v) >= 10000:
        return f"{v/10000:.2f}억"
    return f"{v:,.0f}만"


def chart_complex_growth(rank_df: pd.DataFrame, top_n: int = 15) -> go.Figure:
    df = rank_df.head(top_n).copy()
    df = df.sort_values("price_change_pct", ascending=True)
    fig = px.bar(
        df,
        x="price_change_pct",
        y="complex_name",
        orientation="h",
        text=df["price_change_pct"].map(lambda x: f"{x:.1f}%"),
        labels={"price_change_pct": "기간 상승률(%)", "complex_name": "단지명"},
        title=f"단지별 가격 상승률 Top {min(top_n, len(df))}",
        color="price_change_pct",
        color_continuous_scale=["#8fb3c9", PRICE_COLOR, ACCENT],
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        textfont=dict(family=KR_FONT, size=13, color=TEXT),
        marker_line_width=0,
    )
    fig.update_layout(
        **_base_layout(
            height=max(460, 34 * len(df) + 140),
            coloraxis_showscale=False,
            margin=dict(l=20, r=80, t=80, b=40),
            xaxis=dict(
                title=dict(text="기간 상승률(%)", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=13, color=TEXT),
                gridcolor=GRID,
                zeroline=True,
                zerolinecolor="#999",
            ),
            yaxis=dict(
                title=dict(text="단지명", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=13, color=TEXT),
            ),
        )
    )
    return fig


def chart_dong_growth(rank_df: pd.DataFrame) -> go.Figure:
    df = rank_df.sort_values("price_change_pct", ascending=True).copy()
    fig = px.bar(
        df,
        x="price_change_pct",
        y="dong",
        orientation="h",
        text=df["price_change_pct"].map(lambda x: f"{x:.1f}%"),
        custom_data=["total_households", "complex_count", "cagr_pct"],
        labels={"price_change_pct": "세대수 가중 상승률(%)", "dong": "법정동"},
        title="동별 가격 상승률 (세대수 가중)",
        color="price_change_pct",
        color_continuous_scale=["#8fb3c9", PRICE_COLOR, ACCENT],
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        textfont=dict(family=KR_FONT, size=13, color=TEXT),
        hovertemplate=(
            "법정동=%{y}<br>상승률=%{x:.1f}%<br>세대수=%{customdata[0]}"
            "<br>단지수=%{customdata[1]}<br>연평균=%{customdata[2]:.2f}%<extra></extra>"
        ),
    )
    fig.update_layout(
        **_base_layout(
            height=max(440, 36 * len(df) + 140),
            coloraxis_showscale=False,
            margin=dict(l=20, r=80, t=80, b=40),
            xaxis=dict(
                title=dict(text="세대수 가중 상승률(%)", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=13, color=TEXT),
                gridcolor=GRID,
            ),
            yaxis=dict(
                title=dict(text="법정동", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=13, color=TEXT),
            ),
        )
    )
    return fig


def chart_time_series(ts: pd.DataFrame, entity_col: str, top_entities: list[str] | None = None) -> go.Figure:
    if ts.empty:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title="시계열 데이터 없음", height=360))
        return fig

    df = ts.copy()
    if top_entities:
        df = df[df[entity_col].isin(top_entities)]

    legend_name = ENTITY_LABELS_KO.get(entity_col, entity_col)
    fig = px.line(
        df,
        x="period",
        y="avg_price",
        color=entity_col,
        markers=True,
        labels={"period": "분기", "avg_price": "평균 거래가(만원)", entity_col: legend_name},
        title="분기별 평균 거래가 추이",
    )
    fig.update_traces(line=dict(width=2.5), marker=dict(size=7))
    fig.update_layout(
        **_base_layout(
            height=520,
            margin=dict(l=20, r=20, t=100, b=50),
            hovermode="x unified",
            xaxis=dict(
                title=dict(text="분기", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=12, color=TEXT),
                gridcolor=GRID,
            ),
            yaxis=dict(
                title=dict(text="평균 거래가(만원)", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=12, color=TEXT),
                tickformat=",",
                gridcolor=GRID,
            ),
        )
    )
    return fig


def chart_start_end_scatter(rank_df: pd.DataFrame) -> go.Figure:
    if rank_df.empty:
        return go.Figure()
    fig = px.scatter(
        rank_df,
        x="start_price",
        y="end_price",
        size="total_households",
        color="dong",
        hover_name="complex_name",
        custom_data=["price_change_pct", "tx_count", "dong"],
        labels={
            "start_price": "초반 평균가(만원)",
            "end_price": "최근 평균가(만원)",
            "dong": "법정동",
            "total_households": "세대수",
        },
        title="초반 vs 최근 평균가 (버블=세대수)",
    )
    fig.update_traces(
        hovertemplate=(
            "%{hovertext}<br>법정동=%{customdata[2]}<br>초반=%{x:,.0f}만"
            "<br>최근=%{y:,.0f}만<br>상승률=%{customdata[0]:.1f}%"
            "<br>거래건수=%{customdata[1]}<extra></extra>"
        ),
        marker=dict(line=dict(width=0.5, color="#fff"), opacity=0.85),
    )
    lo = min(rank_df["start_price"].min(), rank_df["end_price"].min())
    hi = max(rank_df["start_price"].max(), rank_df["end_price"].max())
    fig.add_trace(
        go.Scatter(
            x=[lo, hi],
            y=[lo, hi],
            mode="lines",
            name="변화없음",
            line=dict(dash="dash", color="#888", width=1.5),
        )
    )
    fig.update_layout(
        **_base_layout(
            height=520,
            xaxis=dict(
                title=dict(text="초반 평균가(만원)", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=12, color=TEXT),
                tickformat=",",
                gridcolor=GRID,
            ),
            yaxis=dict(
                title=dict(text="최근 평균가(만원)", font=dict(size=14, color=TEXT)),
                tickfont=dict(size=12, color=TEXT),
                tickformat=",",
                gridcolor=GRID,
            ),
        )
    )
    return fig


def chart_size_dong_heatmap(heat: pd.DataFrame) -> go.Figure:
    fig = px.density_heatmap(
        heat,
        x="평형대",
        y="동",
        z="상승률(%)",
        color_continuous_scale=["#8fb3c9", "#f7f4ef", "#c45c26"],
        title="동 × 평형대 상승률 히트맵",
        labels={"상승률(%)": "상승률(%)"},
    )
    fig.update_layout(
        **_base_layout(
            height=max(420, 28 * heat["동"].nunique() + 160),
            coloraxis_colorbar=dict(
                title=dict(text="상승률(%)", font=dict(family=KR_FONT, size=13, color=TEXT)),
                tickfont=dict(family=KR_FONT, size=12, color=TEXT),
            ),
            xaxis=dict(title=dict(text="평형대", font=dict(size=14, color=TEXT)), tickfont=dict(size=13, color=TEXT)),
            yaxis=dict(title=dict(text="법정동", font=dict(size=14, color=TEXT)), tickfont=dict(size=13, color=TEXT)),
        )
    )
    return fig
