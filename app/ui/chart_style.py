"""공통 차트 스타일 — 흰 배경에서도 검정 축/눈금이 보이도록."""

from __future__ import annotations

import math

KR_FONT = "Malgun Gothic, Apple SD Gothic Neo, NanumGothic, Noto Sans KR, sans-serif"
BG = "#ffffff"
PLOT_BG = "#fafafa"
TEXT = "#000000"
GRID = "#b0b0b0"
PRICE = "#1f4e79"
ACCENT = "#c45c26"
INTEREST = "#d62828"
TREND = "#1b7a6e"


def axis_style(title: str, **extra) -> dict:
    style = dict(
        title=dict(text=title, font=dict(family=KR_FONT, size=14, color=TEXT), standoff=10),
        tickfont=dict(family=KR_FONT, size=12, color=TEXT),
        color=TEXT,
        gridcolor=GRID,
        zeroline=True,
        zerolinecolor="#666666",
        linecolor=TEXT,
        showline=True,
        mirror=True,
        automargin=True,
        ticklabeloverflow="allow",
    )
    style.update(extra)
    return style


def _merge_dict(base: dict, override: dict | None) -> dict:
    out = dict(base)
    if not override:
        return out
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            nested = dict(out[k])
            nested.update(v)
            out[k] = nested
        else:
            out[k] = v
    return out


def base_layout(title: str, interest: bool = False, **kwargs) -> dict:
    """흰 배경 + 검정 글자. legend/font 부분 덮어써도 색이 날아가지 않도록 병합."""
    title_color = INTEREST if interest else TEXT
    prefix = "★ 관심단지 · " if interest else ""
    layout = dict(
        font=dict(family=KR_FONT, size=14, color=TEXT),
        title=dict(
            text=prefix + title,
            font=dict(family=KR_FONT, size=17, color=title_color),
            x=0.01,
            xanchor="left",
            y=0.98,
            yanchor="top",
        ),
        plot_bgcolor=PLOT_BG,
        paper_bgcolor=BG,
        margin=dict(l=80, r=40, t=90, b=110),
        hoverlabel=dict(font=dict(family=KR_FONT, size=13, color=TEXT), bgcolor="#ffffff"),
        legend=dict(
            font=dict(family=KR_FONT, size=12, color=TEXT),
            bgcolor="rgba(255,255,255,0.96)",
            bordercolor="#bbbbbb",
            borderwidth=1,
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="right",
            x=1.0,
            title=dict(text="", font=dict(color=TEXT)),
            itemsizing="constant",
            tracegroupgap=2,
        ),
        xaxis=dict(automargin=True),
        yaxis=dict(automargin=True, title=dict(text="")),
        colorway=[
            "#1f4e79",
            "#2a9d8f",
            "#c45c26",
            "#6d597a",
            "#227c9d",
            "#e9c46a",
            "#355070",
            "#d62828",
        ],
    )
    for key in ("legend", "font", "title", "hoverlabel", "xaxis", "yaxis"):
        if key in kwargs and isinstance(kwargs[key], dict):
            layout[key] = _merge_dict(layout.get(key, {}), kwargs.pop(key))
    layout.update(kwargs)
    return layout


def annotate_avg_growth(fig, avg_pct: float, interest: bool = False) -> None:
    fig.add_hline(
        y=avg_pct,
        line_dash="dot",
        line_color=INTEREST if interest else "#444444",
        line_width=1.5,
        annotation_text=f"평균 상승률 {avg_pct:.1f}%",
        annotation_position="top right",
        annotation_font=dict(family=KR_FONT, size=13, color=TEXT),
        annotation_bgcolor="rgba(255,255,255,0.85)",
    )


def _collect_y_values(fig) -> list[float]:
    vals: list[float] = []
    for tr in fig.data:
        ys = getattr(tr, "y", None)
        if ys is None:
            continue
        for y in ys:
            if y is None:
                continue
            try:
                vals.append(float(y))
            except (TypeError, ValueError):
                continue
    # annotation y (상승률 라벨 등)도 범위에 반영
    for ann in fig.layout.annotations or []:
        y = getattr(ann, "y", None) if not isinstance(ann, dict) else ann.get("y")
        yref = getattr(ann, "yref", "y") if not isinstance(ann, dict) else ann.get("yref", "y")
        if yref not in (None, "y", "y1"):
            continue
        if y is None:
            continue
        try:
            vals.append(float(y))
        except (TypeError, ValueError):
            continue
    return vals


def apply_price_yaxis(fig, title: str = "평균 거래가") -> None:
    """만원→억 스케일, 축 제목 제거, 데이터에 맞춘 Y범위(잘림·과다여백 방지)."""
    # 스케일 판별은 trace만 사용 (annotation 만원 좌표가 max를 왜곡하지 않게)
    trace_vals: list[float] = []
    for tr in fig.data:
        ys = getattr(tr, "y", None)
        if ys is None:
            continue
        for y in ys:
            if y is None:
                continue
            try:
                trace_vals.append(float(y))
            except (TypeError, ValueError):
                continue
    if not trace_vals:
        return
    scale = 10_000.0 if max(trace_vals) > 500 else 1.0

    for tr in fig.data:
        ys = getattr(tr, "y", None)
        if ys is None:
            continue
        new_y = []
        for y in ys:
            if y is None:
                new_y.append(None)
                continue
            try:
                new_y.append(float(y) / scale)
            except (TypeError, ValueError):
                new_y.append(y)
        tr.y = new_y

    scaled_vals = [v / scale for v in trace_vals]
    new_anns = []
    for ann in fig.layout.annotations or []:
        ad = ann.to_plotly_json() if hasattr(ann, "to_plotly_json") else dict(ann)
        if ad.get("name") == "price_unit_label":
            continue
        yref = ad.get("yref", "y")
        if yref in (None, "y", "y1") and ad.get("y") is not None:
            try:
                ad["y"] = float(ad["y"]) / scale
                scaled_vals.append(float(ad["y"]))
            except (TypeError, ValueError):
                pass
        new_anns.append(ad)

    for tr in fig.data:
        ht = getattr(tr, "hovertemplate", None)
        if isinstance(ht, str):
            tr.hovertemplate = (
                ht.replace("%{y:,.0f}만원", "%{y:.1f}억")
                .replace("평균가=%{y:,.0f}만원", "평균가=%{y:.1f}억")
                .replace("%{y:,.0f}만", "%{y:.1f}억")
            )

    ymin = min(scaled_vals)
    ymax = max(scaled_vals)
    span = max(ymax - ymin, 1.0)
    pad_bot = min(span * 0.05, 1.2)
    pad_top = max(span * 0.16, 1.2)
    lo = max(0.0, ymin - pad_bot)
    hi = ymax + pad_top

    for step in (1.0, 2.0, 2.5, 5.0, 10.0, 20.0):
        if (hi - lo) / step <= 7:
            break
    else:
        step = 25.0

    tick0 = math.ceil(lo / step) * step
    if tick0 > lo + step * 0.15:
        tick0 = max(0.0, tick0 - step)
    vals: list[float] = []
    texts: list[str] = []
    v = tick0
    while v <= hi + 1e-9:
        vals.append(round(v, 2))
        texts.append(f"{v:.0f}억" if abs(v - round(v)) < 1e-6 else f"{v:.1f}억")
        v += step
    if not vals:
        vals = [round(lo, 1), round(hi, 1)]
        texts = [f"{vals[0]}억", f"{vals[1]}억"]

    fig.update_yaxes(
        title=dict(text=""),
        tickmode="array",
        tickvals=vals,
        ticktext=texts,
        range=[lo, hi],
        automargin=True,
        tickfont=dict(family=KR_FONT, size=13, color=TEXT),
        ticklabelposition="outside",
        ticks="outside",
        showticklabels=True,
        side="left",
        separatethousands=False,
        fixedrange=False,
        zeroline=False,
    )

    new_anns.append(
        dict(
            name="price_unit_label",
            text=f"{title} · 단위: 억",
            xref="paper",
            yref="paper",
            x=1.0,
            y=1.14,
            xanchor="right",
            yanchor="bottom",
            showarrow=False,
            font=dict(family=KR_FONT, size=12, color="#444444"),
        )
    )
    # annotations는 merge가 아니라 통째 교체해야 스케일된 y가 유지됨
    fig.layout.annotations = tuple(new_anns)
    fig.update_layout(
        margin=dict(l=80, r=40, t=100, b=120),
        yaxis_title=None,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="right",
            x=1.0,
            bgcolor="rgba(255,255,255,0.96)",
            bordercolor="#bbbbbb",
            borderwidth=1,
            font=dict(family=KR_FONT, size=12, color=TEXT),
        ),
    )
    # 눈금은 표시 범위 안으로만
    vis_vals = [v for v in vals if lo - 1e-6 <= v <= hi + 1e-6]
    vis_texts = [t for v, t in zip(vals, texts) if lo - 1e-6 <= v <= hi + 1e-6]
    if vis_vals:
        fig.update_yaxes(tickvals=vis_vals, ticktext=vis_texts, range=[lo, hi])


def format_eok(manwon: float) -> str:
    """만원 → 'N.N억' 표시."""
    if manwon is None or (isinstance(manwon, float) and math.isnan(manwon)):
        return "-"
    eok = float(manwon) / 10_000.0
    if eok >= 10:
        return f"{eok:.1f}억"
    return f"{eok:.2f}억"
