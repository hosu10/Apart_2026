"""지도에서 단지 선택 (줌/팬 유지)."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.geo.coordinates import complex_map_frame
from app.ui.chart_style import INTEREST, KR_FONT, TEXT, base_layout


def _selection_complex_id(event, frame: pd.DataFrame) -> Optional[int]:
    if event is None:
        return None
    sel = getattr(event, "selection", None)
    if sel is None:
        return None
    points = getattr(sel, "points", None) or []
    if not points:
        return None
    p0 = points[0]
    if isinstance(p0, dict):
        cd = p0.get("customdata")
        idx = p0.get("point_index", p0.get("pointNumber"))
    else:
        cd = getattr(p0, "customdata", None)
        idx = getattr(p0, "point_index", getattr(p0, "point_number", None))
    if cd is not None:
        try:
            if isinstance(cd, (list, tuple)):
                return int(cd[0])
            return int(cd)
        except Exception:  # noqa: BLE001
            pass
    if idx is not None and 0 <= int(idx) < len(frame):
        return int(frame.iloc[int(idx)]["complex_id"])
    return None


def chart_complex_map(
    catalog: pd.DataFrame,
    selected_id: Optional[int] = None,
    interest_id: Optional[int] = None,
    title: str = "단지 지도",
    uirevision: str = "complex-map",
) -> go.Figure:
    frame = complex_map_frame(catalog)
    fig = go.Figure()
    if frame.empty:
        fig.update_layout(**base_layout("지도에 표시할 단지가 없습니다", height=480))
        return fig

    # 일반 / 관심 / 선택 분리 → 줌 시 마커가 좌표에 고정되도록 scattermap 사용
    def _subset(mask):
        return frame.loc[mask].copy()

    interest_mask = frame["complex_id"] == interest_id if interest_id is not None else pd.Series(False, index=frame.index)
    selected_mask = frame["complex_id"] == selected_id if selected_id is not None else pd.Series(False, index=frame.index)
    normal = ~(interest_mask | selected_mask)

    def _add(sub: pd.DataFrame, color: str, size: int, name: str, with_text: bool) -> None:
        if sub.empty:
            return
        fig.add_trace(
            go.Scattermap(
                lat=sub["latitude"],
                lon=sub["longitude"],
                mode="markers+text" if with_text else "markers",
                text=sub["complex_name"] if with_text else None,
                textposition="top center",
                textfont=dict(size=11, color=TEXT, family=KR_FONT),
                marker=dict(size=size, color=color, opacity=0.92),
                customdata=sub[["complex_id", "dong", "sigungu", "complex_name"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>%{customdata[2]} %{customdata[1]}"
                    "<br>단지ID=%{customdata[0]}<extra></extra>"
                ),
                name=name,
            )
        )

    _add(_subset(normal), "#1f4e79", 10, "단지", with_text=False)
    _add(_subset(interest_mask & ~selected_mask), INTEREST, 14, "관심단지", with_text=True)
    _add(_subset(selected_mask), "#c45c26", 16, "선택단지", with_text=True)

    # 선택/관심 없으면 줌 기준은 전체, 있으면 그 주변
    focus = frame
    if selected_id is not None and selected_mask.any():
        focus = _subset(selected_mask)
        zoom = 14
    elif interest_id is not None and interest_mask.any():
        focus = _subset(interest_mask)
        zoom = 13
    else:
        zoom = 12

    layout = base_layout(title, height=500, margin=dict(l=0, r=0, t=48, b=0))
    layout.update(
        {
            "legend": dict(
                orientation="v",
                yanchor="bottom",
                y=0.0,
                xanchor="left",
                x=1.02,
                font=dict(family=KR_FONT, size=12, color=TEXT),
                bgcolor="rgba(255,255,255,0.96)",
            ),
            "map": dict(
                style="open-street-map",
                center=dict(lat=float(focus["latitude"].mean()), lon=float(focus["longitude"].mean())),
                zoom=zoom,
            ),
            "clickmode": "event+select",
            "uirevision": uirevision,
        }
    )
    fig.update_layout(layout)
    return fig


def pick_complex_on_map(
    source_df: pd.DataFrame,
    *,
    key: str,
    interest_id: Optional[int] = None,
    default_gu: Optional[str] = None,
    allow_all_gu: bool = True,
    title: str = "지도에서 단지 선택",
) -> Optional[int]:
    if source_df.empty:
        st.info("표시할 단지가 없습니다. 좌측 선정 범위를 확인하세요.")
        return None

    gu_opts = sorted(source_df["sigungu"].dropna().unique().tolist())
    if not gu_opts:
        return None
    if default_gu not in gu_opts:
        default_gu = gu_opts[0]
    gu = st.selectbox("지도 표시 구/시", gu_opts, index=gu_opts.index(default_gu), key=f"{key}_map_gu")
    area = source_df[source_df["sigungu"] == gu]
    dong_opts = ["(동 전체)"] + sorted(area["dong"].dropna().unique().tolist())
    dong = st.selectbox("동 필터", dong_opts, key=f"{key}_map_dong")
    if dong != "(동 전체)":
        area = area[area["dong"] == dong]

    state_key = f"{key}_selected_id"
    prev = st.session_state.get(state_key)
    frame = complex_map_frame(area)

    accurate = 0
    if "geocode_source" in frame.columns:
        accurate = int(frame["geocode_source"].astype(str).str.startswith(("nominatim", "cache")).sum())
    st.caption(
        f"마커 클릭으로 선택 · 확대/이동 유지 · 주소 geocode {accurate}/{len(frame)}곳 "
        "(나머지는 동 중심 추정)"
    )

    event = st.plotly_chart(
        chart_complex_map(
            frame,
            selected_id=prev,
            interest_id=interest_id,
            title=f"{title} · {gu}",
            uirevision=f"{key}-{gu}-{dong}",
        ),
        use_container_width=True,
        config={"displayModeBar": True, "scrollZoom": True},
        on_select="rerun",
        selection_mode="points",
        key=f"{key}_map_chart",
    )
    picked = _selection_complex_id(event, frame)
    if picked is not None:
        st.session_state[state_key] = picked
        prev = picked

    names = frame.sort_values("complex_name")[["complex_id", "complex_name", "dong"]].assign(
        label=lambda d: d["complex_name"] + " (" + d["dong"] + ")"
    )
    label_map = dict(zip(names["label"], names["complex_id"]))
    labels = names["label"].tolist()
    default_lab = None
    if prev is not None and prev in set(names["complex_id"]):
        default_lab = names.loc[names["complex_id"] == prev, "label"].iloc[0]
    lab = st.selectbox(
        "또는 목록에서 선택",
        ["(미선택)"] + labels,
        index=(["(미선택)"] + labels).index(default_lab) if default_lab in labels else 0,
        key=f"{key}_list_pick",
    )
    if lab != "(미선택)":
        st.session_state[state_key] = int(label_map[lab])
        prev = st.session_state[state_key]

    if prev is not None and prev in set(frame["complex_id"]):
        row = frame.loc[frame["complex_id"] == prev].iloc[0]
        st.success(f"선택: **{row['complex_name']}** ({row['sigungu']} {row['dong']})")
        return int(prev)
    return None
