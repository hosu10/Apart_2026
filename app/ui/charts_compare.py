"""비교 분석 패널용 차트."""

from __future__ import annotations

import urllib.parse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

from app.analysis.metrics import (
    ESTIMATED_JEONSE_RATIO,
    complex_profile,
    dong_percentile,
    estimated_jeonse_series,
    floor_price_distribution,
    monthly_price_series,
    quarterly_price_series,
    volume_series,
)

from app.ui.chart_style import (  # noqa: E402
    ACCENT,
    INTEREST,
    KR_FONT,
    PRICE,
    TEXT,
    TREND,
    apply_price_yaxis,
    axis_style,
    base_layout,
)

COMPARE_VIEWS = [
    "최근 매매가 추이(추세선)",
    "최근 전세가 추이(추정·추세선)",
    "전세/매매 비율 추이(추정)",
    "단지 정보 비교",
    "단지 위치(지도 검색)",
    "평당가 추이",
    "거래량 추이",
    "층수별 가격 분포",
    "동일 동 내 상승률 위치",
    "요약 지표 카드",
]


def _layout(title: str, interest: bool = False, **kwargs) -> dict:
    return base_layout(title, interest=interest, height=380, margin=dict(l=88, r=140, t=64, b=48), **kwargs)


def _series_color(interest: bool, fallback: str = PRICE) -> str:
    return INTEREST if interest else fallback


def _add_trendline(fig: go.Figure, x_idx: np.ndarray, y: np.ndarray, name: str = "추세선") -> None:
    if len(y) < 2 or np.all(np.isnan(y)):
        return
    mask = ~np.isnan(y)
    if mask.sum() < 2:
        return
    coef = np.polyfit(x_idx[mask], y[mask], 1)
    trend = coef[0] * x_idx + coef[1]
    fig.add_trace(
        go.Scatter(
            x=list(range(len(x_idx))),
            y=trend,
            mode="lines",
            name=name,
            line=dict(color=TREND, width=2, dash="dash"),
        )
    )


def chart_sale_trend(
    df: pd.DataFrame,
    complex_id: int,
    interest: bool = False,
    growth_pct: float | None = None,
) -> go.Figure:
    ts = quarterly_price_series(df, complex_id)
    fig = go.Figure()
    if ts.empty:
        fig.update_layout(**_layout("매매가 데이터 없음", interest))
        return fig
    x = np.arange(len(ts))
    color = _series_color(interest)
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=ts["avg_price"],
            mode="lines+markers",
            name="평균매매가",
            line=dict(color=color, width=2.5),
            marker=dict(size=7, color=color),
        )
    )
    y = ts["avg_price"].to_numpy(dtype=float)
    coef = np.polyfit(x, y, 1)
    trend_y = coef[0] * x + coef[1]
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=trend_y,
            mode="lines",
            name="추세선",
            line=dict(color=color if interest else TREND, width=2, dash="dot"),
        )
    )
    if growth_pct is None and len(y) >= 2 and y[0] > 0:
        growth_pct = float((y[-1] / y[0] - 1.0) * 100)
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    title = f"{name} · 분기 매매가"
    if growth_pct is not None:
        title = f"{title} · 상승률 {growth_pct:+.1f}%"
        fig.add_annotation(
            x=ts["period"].iloc[-1],
            y=float(trend_y[-1]),
            text=f"<b>{growth_pct:+.1f}%</b>",
            showarrow=True,
            arrowhead=0,
            ax=28,
            ay=-20,
            font=dict(family=KR_FONT, size=14, color=color),
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor=color,
            borderwidth=1,
        )
    fig.update_layout(
        **_layout(
            title,
            interest,
            xaxis=axis_style("분기"),
            legend=dict(
                orientation="v",
                yanchor="bottom",
                y=0.0,
                xanchor="left",
                x=1.02,
                font=dict(family=KR_FONT, size=12, color=TEXT),
            ),
        )
    )
    apply_price_yaxis(fig, "매매가")
    return fig


def chart_jeonse_trend(df: pd.DataFrame, complex_id: int, interest: bool = False) -> go.Figure:
    ts = estimated_jeonse_series(quarterly_price_series(df, complex_id))
    fig = go.Figure()
    if ts.empty:
        fig.update_layout(**_layout("전세 추정 데이터 없음", interest))
        return fig
    x = np.arange(len(ts))
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=ts["avg_jeonse"],
            mode="lines+markers",
            name=f"추정전세(매매×{ESTIMATED_JEONSE_RATIO:.0%})",
            line=dict(color=_series_color(interest, ACCENT), width=2.5),
            marker=dict(color=_series_color(interest, ACCENT)),
        )
    )
    y = ts["avg_jeonse"].to_numpy(dtype=float)
    coef = np.polyfit(x, y, 1)
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=coef[0] * x + coef[1],
            mode="lines",
            name="추세선",
            line=dict(color=TREND, width=2, dash="dash"),
        )
    )
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    fig.update_layout(
        **_layout(
            f"{name} · 추정 전세가 (실전세 미수집)",
            interest,
            xaxis=axis_style("분기"),
            legend=dict(
                orientation="v",
                yanchor="bottom",
                y=0.0,
                xanchor="left",
                x=1.02,
                font=dict(family=KR_FONT, size=12, color=TEXT),
            ),
        )
    )
    apply_price_yaxis(fig, "추정전세")
    return fig


def chart_jeonse_sale_ratio(df: pd.DataFrame, complex_id: int, interest: bool = False) -> go.Figure:
    ts = estimated_jeonse_series(quarterly_price_series(df, complex_id))
    fig = go.Figure()
    if ts.empty:
        fig.update_layout(**_layout("비율 데이터 없음", interest))
        return fig
    # 고정 추정 비율이므로 참고선 + 변동 없음 안내. 향후 실전세 연동 시 변동.
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=ts["jeonse_ratio"],
            mode="lines+markers",
            name="추정 전세가율(%)",
            line=dict(color=_series_color(interest, ACCENT), width=2.5),
            marker=dict(color=_series_color(interest, ACCENT)),
        )
    )
    fig.add_hline(y=70, line_dash="dot", line_color="#888", annotation_text="참고 70%")
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    fig.update_layout(
        **_layout(
            f"{name} · 전세/매매 비율(추정 {ESTIMATED_JEONSE_RATIO:.0%})",
            interest,
            yaxis=axis_style("전세가율(%)", range=[50, 90]),
            xaxis=axis_style("분기"),
        )
    )
    return fig


def chart_ppp_trend(df: pd.DataFrame, complex_id: int, interest: bool = False) -> go.Figure:
    ts = quarterly_price_series(df, complex_id)
    fig = go.Figure()
    if ts.empty:
        fig.update_layout(**_layout("평당가 데이터 없음", interest))
        return fig
    x = np.arange(len(ts))
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=ts["avg_ppp"],
            mode="lines+markers",
            name="평당가",
            line=dict(color=_series_color(interest), width=2.5),
            marker=dict(color=_series_color(interest)),
        )
    )
    y = ts["avg_ppp"].to_numpy(dtype=float)
    coef = np.polyfit(x, y, 1)
    fig.add_trace(
        go.Scatter(
            x=ts["period"],
            y=coef[0] * x + coef[1],
            mode="lines",
            name="추세선",
            line=dict(color=TREND, width=2, dash="dash"),
        )
    )
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    fig.update_layout(
        **_layout(
            f"{name} · 평당가 추이",
            interest,
            yaxis=axis_style("만원/평", tickformat=","),
            xaxis=axis_style("분기"),
            legend=dict(
                orientation="v",
                yanchor="bottom",
                y=0.0,
                xanchor="left",
                x=1.02,
                font=dict(family=KR_FONT, size=12, color=TEXT),
            ),
        )
    )
    return fig


def chart_volume(df: pd.DataFrame, complex_id: int, interest: bool = False) -> go.Figure:
    ts = volume_series(df, complex_id)
    fig = go.Figure()
    if ts.empty:
        fig.update_layout(**_layout("거래량 데이터 없음", interest))
        return fig
    fig.add_trace(go.Bar(x=ts["period"], y=ts["거래건수"], name="거래건수", marker_color=_series_color(interest)))
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    fig.update_layout(
        **_layout(
            f"{name} · 분기 거래량",
            interest,
            yaxis=axis_style("건수"),
            xaxis=axis_style("분기"),
        )
    )
    return fig


def chart_floor_dist(df: pd.DataFrame, complex_id: int, interest: bool = False) -> go.Figure:
    dist = floor_price_distribution(df, complex_id)
    fig = go.Figure()
    if dist.empty:
        fig.update_layout(**_layout("층수 데이터 없음", interest))
        return fig
    order = ["저층(1~5)", "중층(6~15)", "고층(16+)"]
    dist["층구분"] = pd.Categorical(dist["층구분"], categories=order, ordered=True)
    dist = dist.sort_values("층구분")
    fig.add_trace(
        go.Bar(
            x=dist["층구분"],
            y=dist["평균가"],
            text=dist["건수"].map(lambda n: f"{n}건"),
            textposition="outside",
            textfont=dict(family=KR_FONT, size=12, color=TEXT),
            marker_color=_series_color(interest),
        )
    )
    name = df.loc[df["complex_id"] == complex_id, "complex_name"].iloc[0]
    fig.update_layout(
        **_layout(
            f"{name} · 층수별 평균가",
            interest,
            xaxis=axis_style("층구분"),
        )
    )
    apply_price_yaxis(fig, "평균가")
    return fig


def render_profile_dict(df: pd.DataFrame, complex_id: int) -> dict:
    return complex_profile(df, complex_id)


def render_dong_position(rank_df: pd.DataFrame, complex_id: int) -> dict | None:
    return dong_percentile(rank_df, complex_id)


def kakao_map_url(sigungu: str, dong: str, complex_name: str) -> str:
    q = urllib.parse.quote(f"{sigungu} {dong} {complex_name}")
    return f"https://map.kakao.com/?q={q}"


def naver_map_url(
    *,
    address: str = "",
    sigungu: str = "",
    dong: str = "",
    complex_name: str = "",
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    """네이버 지도 검색/좌표 URL (새 탭 링크용)."""
    q = (address or "").strip() or f"{sigungu} {dong} {complex_name}".strip()
    if lat is not None and lon is not None and not address:
        # 좌표 중심 보기 + 단지명 검색 보조
        return (
            f"https://map.naver.com/v5/search/{urllib.parse.quote(q)}"
            f"?c={lon},{lat},16,0,0,0,dh"
        )
    return f"https://map.naver.com/v5/search/{urllib.parse.quote(q)}"


def monthly_spark(df: pd.DataFrame, complex_id: int) -> pd.DataFrame:
    return monthly_price_series(df, complex_id)
