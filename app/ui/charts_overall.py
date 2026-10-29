"""전체 서열 분석 차트 (구별/동별 연도 추이 포함)."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.ui.chart_style import (
    INTEREST,
    KR_FONT,
    PRICE,
    TEXT,
    annotate_avg_growth,
    apply_price_yaxis,
    axis_style,
    base_layout,
)

# 구/동 다중 라인용 (관심단지 빨강은 별도)
_REGION_COLORS = [
    "#1f4e79",
    "#2a9d8f",
    "#e9c46a",
    "#f4a261",
    "#6d597a",
    "#355070",
    "#eaac8b",
    "#4a4e69",
    "#227c9d",
    "#17c3b2",
    "#fe6d73",
    "#264653",
]


def _mark_interest(df: pd.DataFrame, interest_id: int | None) -> pd.Series:
    if interest_id is None or "complex_id" not in df.columns:
        return pd.Series(["일반"] * len(df), index=df.index)
    return df["complex_id"].map(lambda x: "관심단지" if x == interest_id else "일반")


def _avg_growth(df: pd.DataFrame) -> float:
    if df.empty or "price_change_pct" not in df.columns:
        return 0.0
    return float(df["price_change_pct"].mean())


def chart_rank_page(
    rank_df: pd.DataFrame,
    page: int = 0,
    page_size: int = 10,
    interest_id: int | None = None,
) -> go.Figure:
    start = page * page_size
    chunk = rank_df.iloc[start : start + page_size].copy()
    avg_all = _avg_growth(rank_df)
    if chunk.empty:
        fig = go.Figure()
        fig.update_layout(**base_layout("표시할 단지가 없습니다", height=360))
        return fig

    chunk = chunk.sort_values("price_change_pct", ascending=True)
    chunk["구분"] = _mark_interest(chunk, interest_id)
    colors = chunk["구분"].map({"관심단지": INTEREST, "일반": PRICE})

    fig = go.Figure(
        go.Bar(
            x=chunk["price_change_pct"],
            y=chunk.apply(lambda r: f"{int(r['rank'])}. {r['complex_name']}", axis=1),
            orientation="h",
            text=chunk["price_change_pct"].map(lambda x: f"{x:.1f}%"),
            textposition="outside",
            textfont=dict(family=KR_FONT, size=13, color=TEXT),
            marker_color=colors,
            customdata=chunk[["dong", "sigungu", "total_households", "completion_year"]],
            hovertemplate=(
                "%{y}<br>상승률=%{x:.1f}%<br>%{customdata[1]} %{customdata[0]}"
                "<br>단지전체세대수=%{customdata[2]} · 준공=%{customdata[3]}<extra></extra>"
            ),
        )
    )
    total = len(rank_df)
    fig.add_vline(
        x=avg_all,
        line_dash="dot",
        line_color="#333333",
        line_width=1.5,
        annotation_text=f"전체 평균 {avg_all:.1f}%",
        annotation_position="top",
        annotation_font=dict(family=KR_FONT, size=13, color=TEXT),
        annotation_bgcolor="rgba(255,255,255,0.9)",
    )
    fig.update_layout(
        **base_layout(
            f"단지별 상승률 순위 ({start + 1}~{min(start + page_size, total)} / {total}) · 평균 {avg_all:.1f}%",
            height=max(420, 36 * len(chunk) + 140),
            margin=dict(l=140, r=90, t=80, b=48),
            xaxis=axis_style("상승률(%)"),
            yaxis=axis_style("", showgrid=False, automargin=True),
        )
    )
    return fig


def chart_households_vs_growth(rank_df: pd.DataFrame, interest_id: int | None = None) -> go.Figure:
    df = rank_df.copy()
    df["구분"] = _mark_interest(df, interest_id)
    avg = _avg_growth(df)
    fig = px.scatter(
        df,
        x="total_households",
        y="price_change_pct",
        size="tx_count",
        color="구분",
        color_discrete_map={"관심단지": INTEREST, "일반": PRICE},
        hover_name="complex_name",
        hover_data={"dong": True, "rank": True, "cagr_pct": ":.2f", "total_households": True},
        labels={
            "total_households": "단지 전체 세대수",
            "price_change_pct": "상승률(%)",
            "tx_count": "거래건수",
            "구분": "구분",
        },
        title=f"단지 전체 세대수 대비 상승률 · 평균 상승률 {avg:.1f}%",
    )
    fig.update_traces(marker=dict(opacity=0.88, line=dict(width=0.8, color="#333333")))
    annotate_avg_growth(fig, avg)
    fig.update_layout(
        **base_layout(
            f"단지 전체 세대수 대비 상승률 · 평균 상승률 {avg:.1f}%",
            height=540,
            xaxis=axis_style("단지 전체 세대수", tickformat=","),
            yaxis=axis_style("상승률(%)"),
        )
    )
    return fig


def chart_completion_vs_growth(rank_df: pd.DataFrame, interest_id: int | None = None) -> go.Figure:
    df = rank_df.copy()
    df["구분"] = _mark_interest(df, interest_id)
    avg = _avg_growth(df)
    fig = px.scatter(
        df,
        x="completion_year",
        y="price_change_pct",
        size="total_households",
        color="구분",
        color_discrete_map={"관심단지": INTEREST, "일반": PRICE},
        hover_name="complex_name",
        hover_data={"dong": True, "rank": True, "total_households": True},
        labels={
            "completion_year": "준공연도",
            "price_change_pct": "상승률(%)",
            "total_households": "단지 전체 세대수",
        },
        title=f"준공연도 대비 상승률 · 평균 상승률 {avg:.1f}%",
    )
    fig.update_traces(marker=dict(opacity=0.88, line=dict(width=0.8, color="#333333")))
    annotate_avg_growth(fig, avg)
    fig.update_layout(
        **base_layout(
            f"준공연도 대비 상승률 · 평균 상승률 {avg:.1f}%",
            height=540,
            xaxis=axis_style("준공연도", dtick=2),
            yaxis=axis_style("상승률(%)"),
        )
    )
    return fig


def chart_start_price_vs_growth(rank_df: pd.DataFrame, interest_id: int | None = None) -> go.Figure:
    df = rank_df.copy()
    df["구분"] = _mark_interest(df, interest_id)
    avg = _avg_growth(df)
    fig = px.scatter(
        df,
        x="start_price",
        y="price_change_pct",
        size="total_households",
        color="구분",
        color_discrete_map={"관심단지": INTEREST, "일반": PRICE},
        hover_name="complex_name",
        hover_data={"dong": True, "end_price": ":.0f", "rank": True, "total_households": True},
        labels={
            "start_price": "비교 시작가(만원)",
            "price_change_pct": "상승률(%)",
            "total_households": "단지 전체 세대수",
        },
        title=f"비교 시작가 대비 상승률 · 평균 상승률 {avg:.1f}%",
    )
    fig.update_traces(marker=dict(opacity=0.88, line=dict(width=0.8, color="#333333")))
    annotate_avg_growth(fig, avg)
    fig.update_layout(
        **base_layout(
            f"비교 시작가 대비 상승률 · 평균 상승률 {avg:.1f}%",
            height=540,
            xaxis=axis_style("비교 시작가(만원)", tickformat=","),
            yaxis=axis_style("상승률(%)"),
        )
    )
    return fig


def chart_group_price_growth_scatter(
    group_df: pd.DataFrame,
    group_col: str,
    *,
    highlight_name: str | None = None,
    title: str = "매매 평균가 vs 상승률",
) -> go.Figure:
    """구/동 산점도: X=매매 평균가, Y=상승률. 관심 구·동은 빨강 강조."""
    if group_df.empty or group_col not in group_df.columns:
        fig = go.Figure()
        fig.update_layout(**base_layout("표시할 데이터가 없습니다", height=480))
        return fig

    df = group_df.copy()
    df["avg_price_eok"] = df["avg_price"] / 10_000.0
    df["구분"] = df[group_col].map(
        lambda x: "관심" if highlight_name is not None and str(x) == str(highlight_name) else "일반"
    )
    avg = _avg_growth(df)
    label_ko = "법정동" if group_col == "dong" else "시군구"

    fig = px.scatter(
        df,
        x="avg_price_eok",
        y="price_change_pct",
        size="tx_count",
        color="구분",
        color_discrete_map={"관심": INTEREST, "일반": PRICE},
        text=group_col,
        hover_name=group_col,
        hover_data={
            "avg_price_eok": ":.2f",
            "price_change_pct": ":.1f",
            "tx_count": True,
            "complex_count": True,
            "cagr_pct": ":.2f",
            "구분": False,
        },
        labels={
            "avg_price_eok": "매매 평균가(억)",
            "price_change_pct": "상승률(%)",
            "tx_count": "거래건수",
            "complex_count": "단지수",
            "cagr_pct": "CAGR(%)",
            group_col: label_ko,
        },
        title=f"{title} · 평균 상승률 {avg:.1f}%",
    )
    fig.update_traces(
        marker=dict(opacity=0.88, line=dict(width=0.8, color="#333333")),
        textposition="top center",
        textfont=dict(family=KR_FONT, size=11, color=TEXT),
    )
    for tr in fig.data:
        if getattr(tr, "name", None) == "관심":
            tr.marker.symbol = "diamond"
            tr.textfont = dict(family=KR_FONT, size=12, color=INTEREST)
    annotate_avg_growth(fig, avg)
    fig.update_layout(
        **base_layout(
            f"{title} · 평균 상승률 {avg:.1f}%",
            height=560,
            xaxis=axis_style("매매 평균가(억)"),
            yaxis=axis_style("상승률(%)"),
            showlegend=bool(highlight_name and (df["구분"] == "관심").any()),
        )
    )
    return fig


def yearly_price_volume(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """연도 × 그룹별 평균 거래가·거래량."""
    if df.empty or group_col not in df.columns:
        return pd.DataFrame(columns=[group_col, "year", "avg_price", "tx_count"])
    work = df.copy()
    work["year"] = pd.to_datetime(work["deal_date"]).dt.year
    return (
        work.groupby([group_col, "year"], as_index=False)
        .agg(avg_price=("price", "mean"), tx_count=("price", "count"))
        .sort_values(["year", group_col])
    )


def chart_group_yearly_prices(
    region_df: pd.DataFrame,
    group_col: str,
    *,
    interest_df: Optional[pd.DataFrame] = None,
    interest_label: str = "★ 관심단지",
    title: str = "연도별 평균 거래가",
    max_groups: int = 12,
) -> go.Figure:
    """가로=연도, 세로=평균거래가, 점 크기=거래량. 관심단지 평형 시계열 오버레이."""
    fig = go.Figure()
    grouped = yearly_price_volume(region_df, group_col)
    note = ""
    if not grouped.empty:
        vol = grouped.groupby(group_col)["tx_count"].sum().sort_values(ascending=False)
        keep = vol.head(max_groups).index.tolist()
        if len(vol) > max_groups:
            note = f" · 거래량 상위 {max_groups}/{len(vol)}"
            grouped = grouped[grouped[group_col].isin(keep)]
        for i, name in enumerate(keep):
            sub = grouped[grouped[group_col] == name].sort_values("year")
            if sub.empty:
                continue
            sizes = 8 + 22 * (sub["tx_count"] / max(float(sub["tx_count"].max()), 1.0))
            color = _REGION_COLORS[i % len(_REGION_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=sub["year"],
                    y=sub["avg_price"],
                    mode="lines+markers",
                    name=str(name),
                    line=dict(color=color, width=2),
                    marker=dict(size=sizes, color=color, opacity=0.9, line=dict(width=0.6, color="#333")),
                    customdata=sub[["tx_count"]],
                    hovertemplate=(
                        f"{name}<br>%{{x}}년<br>평균가=%{{y:.1f}}억"
                        "<br>거래=%{customdata[0]}건<extra></extra>"
                    ),
                )
            )

    if interest_df is not None and not interest_df.empty:
        iwork = interest_df.copy()
        iwork["year"] = pd.to_datetime(iwork["deal_date"]).dt.year
        iser = (
            iwork.groupby("year", as_index=False)
            .agg(avg_price=("price", "mean"), tx_count=("price", "count"))
            .sort_values("year")
        )
        if not iser.empty:
            sizes = 10 + 24 * (iser["tx_count"] / max(float(iser["tx_count"].max()), 1.0))
            fig.add_trace(
                go.Scatter(
                    x=iser["year"],
                    y=iser["avg_price"],
                    mode="lines+markers",
                    name=interest_label,
                    line=dict(color=INTEREST, width=3),
                    marker=dict(
                        size=sizes,
                        color=INTEREST,
                        opacity=0.95,
                        symbol="diamond",
                        line=dict(width=1, color="#7a1010"),
                    ),
                    customdata=iser[["tx_count"]],
                    hovertemplate=(
                        f"{interest_label}<br>%{{x}}년<br>평균가=%{{y:.1f}}억"
                        "<br>거래=%{customdata[0]}건<extra></extra>"
                    ),
                )
            )

    if len(fig.data) == 0:
        fig.update_layout(**base_layout("표시할 데이터가 없습니다", height=480))
        return fig

    years = []
    for tr in fig.data:
        years.extend([int(x) for x in tr.x])
    fig.update_layout(
        **base_layout(
            title + note,
            height=580,
            xaxis=axis_style("연도", dtick=1, tickmode="linear"),
        )
    )
    apply_price_yaxis(fig, "평균 거래가")
    if years:
        fig.update_xaxes(range=[min(years) - 0.4, max(years) + 0.4])
    return fig


def merge_interest_rank(
    rank_df: pd.DataFrame,
    interest_rank: pd.DataFrame,
    interest_id: int | None,
) -> pd.DataFrame:
    """서열표에 관심단지(별도 평형) 행을 참고로 포함."""
    if interest_id is None or interest_rank.empty:
        return rank_df
    base = rank_df[rank_df["complex_id"] != interest_id].copy() if not rank_df.empty else rank_df
    row = interest_rank.iloc[[0]].copy()
    row["rank"] = 0
    if base.empty:
        out = row.reset_index(drop=True)
    else:
        out = pd.concat([base, row], ignore_index=True)
    return out
