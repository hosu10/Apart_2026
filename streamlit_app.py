"""아파트 실거래 비교 분석 — 선정/제외/관심단지 · 서열·비교·상대비교·층별분석."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from app.analysis.filters import (
    ExclusionCriteria,
    SelectionCriteria,
    apply_filters,
    complex_catalog,
)
from app.analysis.floor_premium import compute_floor_premiums
from app.analysis.metrics import complex_ranking, group_price_growth
from app.analysis.trends import invalidate_tx_cache, load_transactions
from app.config import (
    ANALYSIS_REGION_LABELS,
    ANALYSIS_REGION_TO_SIDO,
    DEFAULT_AGE_MAX,
    DEFAULT_AGE_MIN,
    DEFAULT_ANALYSIS_REGION,
    DEFAULT_HOUSEHOLDS_MAX,
    DEFAULT_HOUSEHOLDS_MIN,
    DEFAULT_INTEREST_COMPLEX_ID,
    DEFAULT_INTEREST_LABEL,
    DEFAULT_LOOKBACK_YEARS,
    DEFAULT_MIN_AGE_YEARS,
    DEFAULT_MIN_TRANSACTIONS,
    DEFAULT_SIGUNGU,
    DEFAULT_SIZE_TIER,
    REGION_LAWD_BY_LABEL,
    REGION_NAMES,
    SIZE_TIERS,
)
from app.db.schema import init_db
from app.etl.fetch_molit import refresh_recent_trades
from app.etl.seed_sample import seed_sample_data
from app.fetch_meta import load_fetch_meta
from app.geo.coordinates import ensure_complex_coordinates
from app.prefs import load_prefs, prefs_from_session, save_prefs
from app.ui.charts_compare import (
    COMPARE_VIEWS,
    chart_floor_dist,
    chart_jeonse_sale_ratio,
    chart_jeonse_trend,
    chart_ppp_trend,
    chart_sale_trend,
    chart_volume,
    kakao_map_url,
    naver_map_url,
    render_dong_position,
    render_profile_dict,
)
from app.ui.charts_floor import chart_floor_premium_bars, chart_height_premium_bars
from app.ui.chart_style import format_eok
from app.ui.charts_overall import (
    chart_completion_vs_growth,
    chart_group_price_growth_scatter,
    chart_group_yearly_prices,
    chart_households_vs_growth,
    chart_rank_page,
    chart_start_price_vs_growth,
    merge_interest_rank,
)
from app.ui.charts_relative import (
    chart_complex_transactions,
    chart_multi_complex_prices,
    transactions_table,
)
from app.ui.labels import rename_columns_ko

st.set_page_config(
    page_title="아파트 실거래 비교 분석",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 외부 폰트 CDN 제거 — 기동 시 네트워크 대기 방지 (시스템 한글 폰트 사용)
CUSTOM_CSS = """
<style>
html, body, [class*="css"] { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; color: #111; }
.block-container { padding-top: 1rem; max-width: 1400px; }
.hero {
  background: linear-gradient(135deg, #1f4e79 0%, #2f6f9f 55%, #c45c26 140%);
  color: #f7f4ef; border-radius: 16px; padding: 1.0rem 1.2rem; margin-bottom: 0.6rem;
}
.hero h1 { margin: 0; font-size: 1.45rem; font-weight: 700; }
.hero p { margin: 0.25rem 0 0; opacity: 0.92; font-size: 0.92rem; }
.interest-badge {
  display: inline-block; background: #d62828; color: #fff; padding: 0.2rem 0.6rem;
  border-radius: 999px; font-size: 0.85rem; font-weight: 600;
}
.panel-box {
  border: 1px solid #e4ddd2; border-radius: 12px; padding: 0.6rem 0.8rem; background: #ffffff;
}
.panel-interest { border: 2px solid #d62828; background: #fff6f6; }
.name-chip {
  display:inline-block; background:#eef3f8; border:1px solid #c5d4e4; border-radius:8px;
  padding:0.15rem 0.55rem; margin:0.1rem 0.25rem 0.1rem 0; font-weight:600; color:#1f4e79;
}
/* 분석 대상 요약 — 다크테마에서도 보이도록 밝은 글자 */
.sum-stat { margin: 0 0 0.2rem 0; }
.sum-lab { display:block; font-size: 0.85rem; color: rgba(250,250,250,0.72); margin-bottom: 0.15rem; }
.sum-val { display:block; font-size: 1.15rem; font-weight: 600; color: #f5f5f5; line-height: 1.3; }
/* 선정 조건: 검정 배경 + 흰 글씨 (카드형 흰 박스 아님) */
.sel-cond {
  font-size: 1.05rem; line-height: 1.45; color: #ffffff; background: #111111;
  padding: 0.55rem 0.75rem; margin: 0.35rem 0 0.55rem 0; border: none; border-radius: 0;
}
.sel-cond code {
  background: transparent; color: #ffffff; padding: 0; font-size: inherit;
}
/* Plotly Y축 눈금이 컨테이너에 잘리지 않도록 */
div[data-testid="stPlotlyChart"],
div[data-testid="stPlotlyChart"] > div,
.js-plotly-plot,
.js-plotly-plot .plotly,
.js-plotly-plot .svg-container {
  overflow: visible !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

PLOTLY_CFG = {
    "displayModeBar": True,
    "displaylogo": False,
    "scrollZoom": True,
    # 범례를 마우스로 드래그해 위치 이동
    "edits": {"legendPosition": True, "legendText": False},
}


def show_plotly(fig, **kwargs):
    """Streamlit dark theme이 Plotly 범례/축 글자를 흰색으로 덮어쓰지 않도록 theme=None."""
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("config", PLOTLY_CFG)
    kwargs.setdefault("theme", None)
    return st.plotly_chart(fig, **kwargs)


ANALYSIS_MODES = ["전체 서열 분석", "비교분석", "층별 가격 분석"]
# 이전 모드명 → 현재
_MODE_ALIASES = {
    "상대비교분석": "비교분석",
    "비교 분석": "비교분석",
}

OVERALL_MENUS = [
    "상승률 순위 (10개 단위)",
    "단지 전체 세대수 대비 상승률",
    "준공연도 대비 상승률",
    "비교 시작가 대비 상승률",
    "구별 분석",
    "동별 분석",
    "동별비교",
    "구별비교",
]


def _init_state() -> None:
    """prefs → session_state (위젯 생성 전에 키 주입)."""
    if not st.session_state.get("_prefs_loaded"):
        prefs = load_prefs()
        for k, v in prefs.items():
            if k not in st.session_state:
                st.session_state[k] = v
        st.session_state._prefs_loaded = True

    defaults = {
        "interest_complex_id": DEFAULT_INTEREST_COMPLEX_ID,
        "interest_label": DEFAULT_INTEREST_LABEL,
        "interest_size_tier": DEFAULT_SIZE_TIER,
        "compare_n": 2,
        "compare_ids": [DEFAULT_INTEREST_COMPLEX_ID, None, None, None],
        "relative_ids": [DEFAULT_INTEREST_COMPLEX_ID, None, None, None],
        "rank_page": 0,
        "mode": "전체 서열 분석",
        "interest_initialized": True,
        "coords_ready": False,
        "analysis_region": DEFAULT_ANALYSIS_REGION,
        "filter_sigungu": DEFAULT_SIGUNGU,
        "filter_dong": "전체",
        "filter_size_tier": DEFAULT_SIZE_TIER,
        "filter_age_min": DEFAULT_AGE_MIN,
        "filter_age_max": DEFAULT_AGE_MAX,
        "filter_hh_min": DEFAULT_HOUSEHOLDS_MIN,
        "filter_hh_max": DEFAULT_HOUSEHOLDS_MAX,
        "filter_lookback": DEFAULT_LOOKBACK_YEARS,
        "filter_min_age": DEFAULT_MIN_AGE_YEARS,
        "filter_min_tx": DEFAULT_MIN_TRANSACTIONS,
        "filter_exclude_direct": True,
        "filter_remove_outliers": True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # mode_seg 위젯용 — prefs mode 반영
    if "mode_seg" not in st.session_state and st.session_state.get("mode") in ANALYSIS_MODES:
        st.session_state.mode_seg = st.session_state.mode


def _persist_prefs() -> None:
    try:
        save_prefs(prefs_from_session(st.session_state))
    except Exception:  # noqa: BLE001
        pass


def interest_area_bounds() -> tuple[float, float, str]:
    """관심단지 전용 평형대 → (area_min, area_max, tier_label)."""
    tier = st.session_state.get("interest_size_tier") or DEFAULT_SIZE_TIER
    if tier in SIZE_TIERS:
        lo, hi = SIZE_TIERS[tier]
        return float(lo), float(hi) - 1e-6, tier
    return 70.0, 94.999999, tier


def interest_label_with_tier() -> str:
    base = st.session_state.get("interest_label") or ""
    if not base:
        return ""
    _, _, tier = interest_area_bounds()
    if f"· {tier}" in base or tier in base:
        return base
    return f"{base} · {tier}"


@st.cache_data(show_spinner=False)
def cached_load(region: str = DEFAULT_ANALYSIS_REGION, _cache_ver: str = "enrich_v6_region") -> pd.DataFrame:
    return load_transactions(region=region)


def ensure_data() -> pd.DataFrame:
    region = st.session_state.get("analysis_region") or DEFAULT_ANALYSIS_REGION
    if region not in ANALYSIS_REGION_LABELS:
        region = DEFAULT_ANALYSIS_REGION
        st.session_state.analysis_region = region

    progress = st.sidebar.progress(0, text="데이터 준비…")
    try:
        progress.progress(10, text="DB 초기화…")
        init_db()
        if not st.session_state.coords_ready:
            progress.progress(25, text="좌표 확인…")
            ensure_complex_coordinates()
            st.session_state.coords_ready = True
        progress.progress(55, text=f"{region} 거래 적재…")
        df = cached_load(region)
        if df.empty:
            progress.progress(70, text="샘플 데이터 생성…")
            with st.spinner("샘플 데이터 생성 중..."):
                seed_sample_data(force=True)
                ensure_complex_coordinates(force=True)
                invalidate_tx_cache()
                cached_load.clear()
                df = cached_load(region)
        progress.progress(100, text="준비 완료")
    finally:
        progress.empty()

    # None(해제)일 때는 기본 관심단지를 다시 넣지 않음
    cid = st.session_state.interest_complex_id
    if cid is not None and not df.empty and cid not in set(df["complex_id"].unique()):
        # 서울 기본 관심단지만 서울 데이터에서 복구 시도
        hit = df[
            (df["sigungu"] == "마포구")
            & (df["dong"] == "아현동")
            & (df["complex_name"].astype(str).str.replace(" ", "") == "마포센트럴아이파크")
        ]
        if not hit.empty:
            new_id = int(hit.iloc[0]["complex_id"])
            st.session_state.interest_complex_id = new_id
            st.session_state.interest_label = f"마포구 아현동 {hit.iloc[0]['complex_name']}"
            for key in ("compare_ids", "relative_ids"):
                ids = list(st.session_state[key])
                ids[0] = new_id
                st.session_state[key] = ids
        else:
            _clear_interest(rerun=False)
    return df


def _clear_interest(*, rerun: bool = True) -> None:
    """관심단지 완전 해제 — 분석 화면 오버레이/고정창도 함께 제거."""
    st.session_state.interest_complex_id = None
    st.session_state.interest_label = ""
    st.session_state.interest_cleared = True
    for key in ("compare_ids", "relative_ids"):
        ids = list(st.session_state.get(key, [None, None, None, None]))
        while len(ids) < 4:
            ids.append(None)
        ids[0] = None
        st.session_state[key] = ids
    if rerun:
        st.rerun()


def _complex_name(df: pd.DataFrame, cid: int) -> str:
    sub = df.loc[df["complex_id"] == cid, "complex_name"]
    return str(sub.iloc[0]) if not sub.empty else str(cid)


def _name_chips(df: pd.DataFrame, cids: list[int], interest_id: Optional[int]) -> None:
    parts = []
    for cid in cids:
        if cid is None:
            continue
        name = _complex_name(df, cid)
        star = "★ " if interest_id is not None and cid == interest_id else ""
        parts.append(f"<span class='name-chip'>{star}{name}</span>")
    if parts:
        st.markdown(" ".join(parts), unsafe_allow_html=True)


def load_interest_df(raw_df: pd.DataFrame, sel: SelectionCriteria) -> pd.DataFrame:
    """관심단지 거래 — 분석 대상과 다른 평형대여도 관심단지 지정 평형으로 추출."""
    interest_id = st.session_state.get("interest_complex_id")
    if interest_id is None or raw_df.empty:
        return pd.DataFrame(columns=raw_df.columns)
    ref = raw_df[raw_df["complex_id"] == interest_id].copy()
    if ref.empty:
        return ref
    if sel.start_date is not None:
        ref = ref[ref["deal_date"] >= pd.Timestamp(sel.start_date)]
    if sel.end_date is not None:
        ref = ref[ref["deal_date"] <= pd.Timestamp(sel.end_date)]
    lo, hi, _ = interest_area_bounds()
    ref = ref[(ref["exclusive_area"] >= lo) & (ref["exclusive_area"] <= hi)]
    return ref.reset_index(drop=True)


def with_interest_reference(
    filtered: pd.DataFrame,
    interest_df: pd.DataFrame,
) -> pd.DataFrame:
    """분석 대상 + 관심단지(지정 평형). 필터에 섞인 관심단지 행은 제거하고 관심 평형으로 대체."""
    interest_id = st.session_state.get("interest_complex_id")
    if interest_id is None:
        return filtered
    base = (
        filtered[filtered["complex_id"] != interest_id].copy()
        if not filtered.empty
        else filtered.copy()
    )
    if interest_df.empty:
        return base
    if base.empty:
        return interest_df.copy()
    return pd.concat([base, interest_df], ignore_index=True)


def _interest_sidebar(df: pd.DataFrame) -> None:
    """반드시 st.sidebar.* 만 사용 — st.selectbox 쓰면 우측 메인에 그려짐."""
    sb = st.sidebar
    sb.caption("구·동·단지·평형으로 지정. 분석 대상과 구·평형이 달라도 참고치(빨강)로 비교합니다.")
    if st.session_state.interest_complex_id and st.session_state.interest_label:
        sb.markdown(
            f"<span class='interest-badge'>★ {interest_label_with_tier()}</span>",
            unsafe_allow_html=True,
        )

    gu_opts = sorted(df["sigungu"].dropna().unique().tolist())
    default_gu = "마포구" if "마포구" in gu_opts else (gu_opts[0] if gu_opts else "")
    ig = sb.selectbox(
        "관심단지 구/시",
        ["(미설정)"] + gu_opts,
        index=(["(미설정)"] + gu_opts).index(default_gu)
        if st.session_state.interest_complex_id and default_gu in gu_opts
        else 0,
        key="interest_gu",
    )
    if ig == "(미설정)":
        if sb.button("관심단지 해제", use_container_width=True, key="interest_clear_unset"):
            _clear_interest()
        return

    dongs = sorted(df.loc[df["sigungu"] == ig, "dong"].dropna().unique().tolist())
    default_dong = "아현동" if "아현동" in dongs else (dongs[0] if dongs else "")
    idong = sb.selectbox(
        "관심단지 동",
        dongs,
        index=dongs.index(default_dong) if default_dong in dongs else 0,
        key="interest_dong",
    )
    cats = complex_catalog(df[(df["sigungu"] == ig) & (df["dong"] == idong)])
    names = cats["complex_name"].tolist() if not cats.empty else []
    default_name = "마포센트럴 아이파크"
    if default_name not in names:
        for n in names:
            if str(n).replace(" ", "") == "마포센트럴아이파크":
                default_name = n
                break
        else:
            default_name = names[0] if names else ""
    pick = sb.selectbox(
        "관심 단지",
        ["(선택)"] + names,
        index=(["(선택)"] + names).index(default_name) if default_name in names else 0,
        key="interest_pick",
    )

    tier_opts = list(SIZE_TIERS.keys())
    if st.session_state.get("interest_size_tier") not in tier_opts:
        st.session_state.interest_size_tier = "30평형대"
    interest_tier = sb.selectbox(
        "관심단지 평형대",
        tier_opts,
        key="interest_size_tier",
        help="분석 대상 평형과 달라도 됩니다. 관심단지 비교는 이 평형 거래만 사용합니다.",
    )
    lo, hi = SIZE_TIERS[interest_tier]
    sb.caption(f"관심 전용면적 {lo:g} ≤ ㎡ < {hi:g}")

    # 이미 설정된 관심단지에서 평형만 바꾼 경우 라벨 동기화
    if st.session_state.interest_complex_id and st.session_state.interest_label:
        base_lab = st.session_state.interest_label.split(" · ")[0]
        st.session_state.interest_label = base_lab

    c1, c2 = sb.columns(2)
    if pick != "(선택)" and c1.button(
        "관심단지로 설정", type="primary", use_container_width=True, key="interest_set_btn"
    ):
        cid = int(cats.loc[cats["complex_name"] == pick, "complex_id"].iloc[0])
        st.session_state.interest_complex_id = cid
        st.session_state.interest_label = f"{ig} {idong} {pick}"
        st.session_state.interest_cleared = False
        for key in ("compare_ids", "relative_ids"):
            ids = list(st.session_state[key])
            ids[0] = cid
            st.session_state[key] = ids
        st.rerun()
    if c2.button("관심단지 해제", use_container_width=True, key="interest_clear_btn"):
        _clear_interest()



def sidebar_filters(df: pd.DataFrame) -> tuple[SelectionCriteria, ExclusionCriteria]:
    st.sidebar.markdown("### 1. 분석 대상 선정")

    region = st.sidebar.radio(
        "분석 권역",
        list(ANALYSIS_REGION_LABELS),
        horizontal=True,
        key="analysis_region",
        help="서울(25구)·경기도(시·군·구)를 각각 지연 적재합니다. 기본은 서울.",
    )
    # 위젯 값이 스크립트 시작 전에 반영되므로, 직전 적재 권역과 비교
    if st.session_state.get("_data_region") != region:
        if st.session_state.get("_data_region") is not None:
            st.session_state.filter_sigungu = "전체"
            st.session_state.filter_dong = "전체"
        st.session_state._data_region = region

    sido = ANALYSIS_REGION_TO_SIDO.get(region, "서울특별시")
    expected_n = len(REGION_LAWD_BY_LABEL.get(region, []))
    loaded_n = int(df["sigungu"].nunique()) if not df.empty and "sigungu" in df.columns else 0
    st.sidebar.caption(f"적재 범위: {sido} · 구/시 {loaded_n}/{expected_n}")

    gu_opts = ["전체"] + sorted(df["sigungu"].dropna().unique().tolist())
    cur_gu = st.session_state.get("filter_sigungu", DEFAULT_SIGUNGU)
    if cur_gu not in gu_opts:
        cur_gu = DEFAULT_SIGUNGU if DEFAULT_SIGUNGU in gu_opts else gu_opts[0]
        st.session_state.filter_sigungu = cur_gu
    gu = st.sidebar.selectbox("지역(구/시)", gu_opts, key="filter_sigungu")
    sigungu = None if gu == "전체" else gu

    if sigungu:
        dong_opts = ["전체"] + sorted(df.loc[df["sigungu"] == sigungu, "dong"].dropna().unique().tolist())
    else:
        dong_opts = ["전체"]
    cur_dong = st.session_state.get("filter_dong", "전체")
    if cur_dong not in dong_opts:
        st.session_state.filter_dong = "전체"
    dong_sel = st.sidebar.selectbox("지역(동)", dong_opts, key="filter_dong")
    dong = None if dong_sel == "전체" else dong_sel

    tier_opts = ["직접 입력"] + list(SIZE_TIERS.keys())
    cur_tier = st.session_state.get("filter_size_tier", DEFAULT_SIZE_TIER)
    if cur_tier not in tier_opts:
        st.session_state.filter_size_tier = DEFAULT_SIZE_TIER
    size_tier = st.sidebar.selectbox(
        "평형대",
        tier_opts,
        key="filter_size_tier",
        help="전용면적 기준 프리셋. 우측 분석은 이 범위만 사용합니다.",
    )
    if size_tier != "직접 입력":
        lo, hi = SIZE_TIERS[size_tier]
        area_min, area_max = float(lo), float(hi) - 1e-6
        st.sidebar.caption(f"전용면적 {lo:g} ≤ ㎡ < {hi:g}")
    else:
        c1, c2 = st.sidebar.columns(2)
        area_min = c1.number_input("전용면적 최소(㎡)", 20.0, 250.0, 70.0, 1.0, key="filter_area_min")
        area_max = c2.number_input("전용면적 최대(㎡)", 20.0, 250.0, 95.0, 1.0, key="filter_area_max")

    c3, c4 = st.sidebar.columns(2)
    age_min = c3.number_input("연식 최소(년)", 0, 60, key="filter_age_min")
    age_max = c4.number_input("연식 최대(년)", 0, 60, key="filter_age_max")

    c5, c6 = st.sidebar.columns(2)
    hh_min = c5.number_input("단지 전체 세대수 최소", 50, 10000, step=50, key="filter_hh_min")
    hh_max = c6.number_input("단지 전체 세대수 최대", 50, 20000, step=100, key="filter_hh_max")

    lookback = st.sidebar.slider("분석 기간(년)", 3, 10, key="filter_lookback")
    today = date.today()
    sel = SelectionCriteria(
        sigungu=sigungu,
        dong=dong,
        area_min=float(min(area_min, area_max)),
        area_max=float(max(area_min, area_max)),
        age_min=int(min(age_min, age_max)),
        age_max=int(max(age_min, age_max)),
        households_min=int(min(hh_min, hh_max)),
        households_max=int(max(hh_min, hh_max)),
        lookback_years=int(lookback),
        start_date=date(today.year - int(lookback), 1, 1),
        end_date=today,
    )

    st.sidebar.markdown("### 2. 제외 조건")
    min_age = st.sidebar.number_input("최소 연한(년)", 0, 30, key="filter_min_age")
    min_tx = st.sidebar.number_input("최소 거래 건수", 1, 100, key="filter_min_tx")
    exclude_direct = st.sidebar.checkbox("직거래 제외", key="filter_exclude_direct")
    remove_outliers = st.sidebar.checkbox("IQR 이상치 제거", key="filter_remove_outliers")
    exc = ExclusionCriteria(
        min_age_years=int(min_age),
        min_transactions=int(min_tx),
        exclude_direct_deal=bool(exclude_direct),
        remove_outliers=bool(remove_outliers),
    )

    st.sidebar.markdown("### 3. 관심 단지 (구/동/단지)")
    _interest_sidebar(df)

    with st.sidebar.expander("데이터", expanded=True):
        st.caption(f"권역 {region} · 적재 거래 {len(df):,}건")
        max_d = pd.to_datetime(df["deal_date"]).max() if not df.empty else None
        if max_d is not None and pd.notna(max_d):
            st.caption(f"DB 최근 계약일 {pd.Timestamp(max_d).date()}")
        meta = load_fetch_meta()
        if meta.get("last_refresh_at"):
            st.caption(f"실거래 갱신 {meta['last_refresh_at']}")
        if meta.get("watermark_deal_date") or meta.get("watermark_ym"):
            st.caption(
                f"워터마크 {meta.get('watermark_deal_date') or meta.get('watermark_ym')}"
            )
        want = set(REGION_LAWD_BY_LABEL.get(region, []))
        have_codes = set()
        if not df.empty and "lawd_cd" in df.columns:
            have_codes = set(df["lawd_cd"].astype(str).unique())
        elif not df.empty and "sigungu" in df.columns:
            name_to_cd = {v: k for k, v in REGION_NAMES.items() if k in want}
            have_codes = {name_to_cd[n] for n in df["sigungu"].dropna().unique() if n in name_to_cd}
        missing_cds = sorted(want - have_codes)
        if missing_cds:
            names = ", ".join(REGION_NAMES.get(c, c) for c in missing_cds[:8])
            more = f" 외 {len(missing_cds) - 8}곳" if len(missing_cds) > 8 else ""
            st.caption(f"⚠ 미수집 {len(missing_cds)}곳: {names}{more}")
        if st.button("실거래 신규 확인·반영", type="primary", use_container_width=True, key="btn_molit_refresh"):
            lawds = REGION_LAWD_BY_LABEL.get(region) or None
            with st.spinner("국토부 API에서 워터마크 이후 실거래를 확인·반영하는 중…"):
                st.session_state.molit_refresh_result = refresh_recent_trades(lawd_cds=lawds)
            invalidate_tx_cache()
            cached_load.clear()
            st.session_state.coords_ready = False
            st.session_state.open_refresh_dialog = True
            _persist_prefs()
            st.rerun()
        if st.button("캐시 새로고침", use_container_width=True, key="btn_cache_refresh"):
            st.session_state.coords_ready = False
            invalidate_tx_cache()
            cached_load.clear()
            st.rerun()

    return sel, exc


@st.dialog("실거래 신규 확인 결과", width="large")
def _molit_refresh_dialog() -> None:
    r = st.session_state.get("molit_refresh_result") or {}
    if not r:
        st.info("결과가 없습니다.")
        return
    if r.get("status") != "ok":
        st.error(r.get("message") or "갱신 실패")
        if st.button("닫기", key="molit_dlg_close_err"):
            st.session_state.open_refresh_dialog = False
            st.rerun()
        return

    if r.get("has_new"):
        st.success(r.get("message", "반영 완료"))
    else:
        st.info(r.get("message", "변동 없음"))

    c1, c2, c3 = st.columns(3)
    c1.metric("조회 구간", r.get("period", "-"))
    c2.metric("구간 건수 변화", f"{r.get('delta_window', 0):+d}", help="최근 조회 월 구간 DB 건수 증감")
    c3.metric("전체 거래", f"{r.get('after_total', 0):,}")

    st.write(
        f"- 확인 시각: **{r.get('checked_at')}** · 대상 지역 **{r.get('regions')}**곳\n"
        f"- API 수집: **{r.get('api_rows', 0):,}**건 (최근 계약일 {r.get('api_max_date') or '-'})\n"
        f"- DB 구간: {r.get('before_window', 0):,} → **{r.get('after_window', 0):,}** "
        f"(삭제 {r.get('deleted', 0):,} / 재적재 {r.get('loaded', 0):,})\n"
        f"- DB 최근 계약일: {r.get('before_max_date') or '-'} → **{r.get('after_max_date') or '-'}**"
    )
    by_gu = r.get("by_gu") or {}
    if by_gu:
        top = sorted(by_gu.items(), key=lambda x: -x[1])[:10]
        st.caption("구별 API 건수(상위 10)")
        st.dataframe(
            pd.DataFrame(top, columns=["구/시", "건수"]),
            use_container_width=True,
            hide_index=True,
        )
    errs = r.get("fetch_errors") or []
    if errs:
        with st.expander(f"일부 조회 경고 {len(errs)}건"):
            for e in errs:
                st.write(f"- {e}")
    st.caption("분석 화면 데이터는 이미 갱신된 DB를 다시 불러온 상태입니다.")
    if st.button("닫기", type="primary", key="molit_dlg_close_ok"):
        st.session_state.open_refresh_dialog = False
        st.rerun()


def _rank_page_nav(total: int, page_size: int = 10) -> int:
    max_page = max(0, (total - 1) // page_size)
    labels = [f"{i * page_size + 1}~{min((i + 1) * page_size, total)}위" for i in range(max_page + 1)]
    if "rank_page_num" not in st.session_state:
        st.session_state.rank_page_num = min(st.session_state.get("rank_page", 0), max_page) + 1
    if int(st.session_state.rank_page_num) > max_page + 1:
        st.session_state.rank_page_num = max_page + 1

    c1, c2, c3 = st.columns([1, 1.6, 1])
    cur = int(st.session_state.rank_page_num) - 1
    with c1:
        if st.button("◀ 이전", use_container_width=True, disabled=cur <= 0, key="rank_prev"):
            st.session_state.rank_page_num = max(1, cur)
            st.rerun()
    with c2:
        st.number_input(
            f"페이지 (1~{max_page + 1})",
            min_value=1,
            max_value=max_page + 1,
            step=1,
            key="rank_page_num",
        )
    with c3:
        if st.button("다음 ▶", use_container_width=True, disabled=cur >= max_page, key="rank_next"):
            st.session_state.rank_page_num = min(max_page + 1, cur + 2)
            st.rerun()
    page = int(st.session_state.rank_page_num) - 1
    st.session_state.rank_page = page
    st.caption(f"현재 {labels[page]} · 전체 {total}개 단지")
    return page


def _show_complex_deal_detail(
    filtered: pd.DataFrame,
    raw_df: pd.DataFrame,
    complex_id: int,
    interest_id: Optional[int],
) -> None:
    use = filtered if complex_id in set(filtered["complex_id"]) else raw_df
    interest = complex_id == interest_id
    st.markdown(f"**{_complex_name(use, complex_id)}**")
    show_plotly(
        chart_complex_transactions(use, complex_id, interest=interest),
        use_container_width=True,
        config=PLOTLY_CFG,
    )
    tbl = transactions_table(use, complex_id)
    st.caption(f"실거래 {len(tbl):,}건 (최신순)")
    st.dataframe(tbl, use_container_width=True, hide_index=True, height=360)


def render_overall(
    filtered: pd.DataFrame,
    raw_df: pd.DataFrame,
    interest_df: pd.DataFrame,
    interest_id: Optional[int],
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    sel: Optional[SelectionCriteria] = None,
    exc: Optional[ExclusionCriteria] = None,
    menu: Optional[str] = None,
) -> None:
    base = (
        filtered[filtered["complex_id"] != interest_id]
        if interest_id is not None and not filtered.empty
        else filtered
    )
    rank = complex_ranking(base, period_start=period_start, period_end=period_end)
    interest_rank = (
        complex_ranking(interest_df, period_start=period_start, period_end=period_end)
        if not interest_df.empty
        else pd.DataFrame()
    )
    display_rank = merge_interest_rank(rank, interest_rank, interest_id)

    menu = menu or st.session_state.get("overall_menu") or OVERALL_MENUS[0]
    if menu not in OVERALL_MENUS:
        menu = OVERALL_MENUS[0]
    i_lab = interest_label_with_tier() or "관심단지"
    _, _, i_tier = interest_area_bounds()

    if menu in ("구별 분석", "동별 분석"):
        show_selection_condition(sel)
        # 구별: 적재 구 전체를 동일 연식·평형·세대수·기간으로 비교
        # 동별: 좌측에서 고른 구 범위의 동별 추이
        if menu == "구별 분석" and sel is not None and exc is not None:
            sel_all_gu = replace(sel, sigungu=None, dong=None)
            gu_result = apply_filters(raw_df, sel_all_gu, exc)
            region_df = gu_result.filtered if gu_result.message == "ok" else pd.DataFrame()
            scope_note = "적재 구 전체 · "
            max_groups = 30
        else:
            region_df = base if not base.empty else filtered
            scope_note = "좌측 선정 구·동 · "
            max_groups = 12
        if interest_id is not None and not region_df.empty:
            region_df = region_df[region_df["complex_id"] != interest_id]

        st.caption(
            f"{scope_note}연식·평형·세대수·기간 반영 · 가로=연도 · 세로=평균거래가 · 점 크기=거래량"
            + (f" · ★ {i_lab} 오버레이" if interest_id else "")
        )
        group_col = "sigungu" if menu == "구별 분석" else "dong"
        title = (
            f"{'구별' if group_col == 'sigungu' else '동별'} 연도별 평균 거래가"
            + (f" vs ★ {i_lab}" if interest_id else "")
        )
        show_plotly(
            chart_group_yearly_prices(
                region_df,
                group_col,
                interest_df=interest_df,
                interest_label=f"★ {i_lab}",
                title=title,
                max_groups=max_groups,
            )
        )
        if interest_df.empty and interest_id is not None:
            st.info(f"관심단지({i_lab})의 {i_tier} 거래가 분석 기간에 없습니다.")
        return

    if menu in ("동별비교", "구별비교"):
        show_selection_condition(sel)
        # 동별비교: 좌측 시군구 내 법정동 산점도 (동 필터는 풀어 구 전체 동 비교)
        # 구별비교: 적재 구 전체 · 동일 평형·연식·세대수·기간
        group_col = "dong" if menu == "동별비교" else "sigungu"
        highlight_name: Optional[str] = None
        if not interest_df.empty and group_col in interest_df.columns:
            highlight_name = str(interest_df.iloc[0][group_col])
        elif interest_id is not None and not raw_df.empty:
            meta = raw_df.loc[raw_df["complex_id"] == interest_id]
            if not meta.empty and group_col in meta.columns:
                highlight_name = str(meta.iloc[0][group_col])

        if menu == "구별비교" and sel is not None and exc is not None:
            sel_all_gu = replace(sel, sigungu=None, dong=None)
            gu_result = apply_filters(raw_df, sel_all_gu, exc)
            region_df = gu_result.filtered if gu_result.message == "ok" else pd.DataFrame()
            scope_note = "적재 구 전체 · "
        elif menu == "동별비교" and sel is not None and exc is not None:
            sel_gu = replace(sel, dong=None)
            dong_result = apply_filters(raw_df, sel_gu, exc)
            region_df = dong_result.filtered if dong_result.message == "ok" else pd.DataFrame()
            scope_label = sel.sigungu or "선정 지역"
            scope_note = f"{scope_label} 내 법정동 · "
        else:
            region_df = base if not base.empty else filtered
            scope_note = "좌측 선정 범위 · "

        if interest_id is not None and not region_df.empty:
            region_df = region_df[region_df["complex_id"] != interest_id]

        group_rank = group_price_growth(
            region_df, group_col, period_start=period_start, period_end=period_end
        )
        st.caption(
            f"{scope_note}연식·평형·세대수·기간 반영 · X=매매 평균가 · Y=상승률(초반·후반 기간 평균) · 점 크기=거래량"
            + (f" · ★ 관심 {group_col} 강조" if highlight_name else "")
        )
        if group_rank.empty:
            st.warning(
                "비교할 구/동 상승률을 계산할 수 없습니다. "
                "(초반·후반 기간 거래가 있는 그룹이 필요합니다)"
            )
            return
        title = (
            f"{'법정동별' if group_col == 'dong' else '구별'} 매매 평균가 vs 상승률"
            + (f" · ★ {highlight_name}" if highlight_name else "")
        )
        show_plotly(
            chart_group_price_growth_scatter(
                group_rank,
                group_col,
                highlight_name=highlight_name,
                title=title,
            )
        )
        show_cols = [
            group_col,
            "rank",
            "complex_count",
            "tx_count",
            "avg_price",
            "start_price",
            "end_price",
            "price_change_pct",
            "cagr_pct",
        ]
        show_cols = [c for c in show_cols if c in group_rank.columns]
        tbl = rename_columns_ko(group_rank[show_cols].copy())
        for col in ("평균거래가(만원)", "초반평균가", "최근평균가"):
            if col in tbl.columns:
                tbl[col] = tbl[col].map(lambda x: f"{float(x) / 10_000:.2f}억")
        st.dataframe(
            tbl,
            use_container_width=True,
            hide_index=True,
            height=min(420, 40 + 28 * len(tbl)),
        )
        return

    if rank.empty and interest_rank.empty:
        st.warning("상승률을 계산할 단지가 없습니다. (좌측 선정 범위 내, 초반·후반 거래 필요)")
        return

    st.caption(
        f"좌측 선정 범위 · 분석 단지 {len(rank):,}개 · "
        + (
            f"평균상승률 {rank['price_change_pct'].mean():.1f}% · "
            if not rank.empty
            else ""
        )
        + (f"★ {i_lab} 참고 표시" if interest_id else "관심단지 미설정")
    )

    if menu == "상승률 순위 (10개 단위)":
        if not interest_rank.empty:
            ir = interest_rank.iloc[0]
            st.markdown(
                f"<span class='interest-badge'>★ {i_lab}</span> "
                f"상승률 **{ir['price_change_pct']:+.1f}%** · CAGR {ir['cagr_pct']:.2f}% · "
                f"거래 {int(ir['tx_count']):,}건 · 초반 {ir['start_price']:,.0f} → 최근 {ir['end_price']:,.0f}만",
                unsafe_allow_html=True,
            )
        if rank.empty:
            st.info("선정 범위 내 서열 단지가 없습니다. 관심단지 참고치만 표시합니다.")
            return
        page = _rank_page_nav(len(rank), page_size=10)
        show_selection_condition(sel)
        show_plotly(
            chart_rank_page(rank, page=page, page_size=10, interest_id=interest_id),
            use_container_width=True,
            config=PLOTLY_CFG,
        )
        start = page * 10
        page_df = rank.iloc[start : start + 10]
        show = page_df[
            [
                "rank",
                "complex_name",
                "sigungu",
                "dong",
                "completion_year",
                "total_households",
                "tx_count",
                "start_price",
                "end_price",
                "price_change_pct",
                "cagr_pct",
            ]
        ].copy()
        show["price_change_pct"] = show["price_change_pct"].map(lambda x: f"{x:.1f}%")
        show["cagr_pct"] = show["cagr_pct"].map(lambda x: f"{x:.2f}%")
        show["start_price"] = show["start_price"].map(lambda x: f"{x:,.0f}")
        show["end_price"] = show["end_price"].map(lambda x: f"{x:,.0f}")
        st.dataframe(rename_columns_ko(show), use_container_width=True, hide_index=True)

        labels = [f"{int(r.rank)}. {r.complex_name} ({r.dong})" for r in page_df.itertuples(index=False)]
        id_map = {lab: int(cid) for lab, cid in zip(labels, page_df["complex_id"])}
        pick = st.selectbox("단지 선택 → 실거래 내역", ["(선택)"] + labels, key="rank_detail_pick")
        if pick != "(선택)":
            cid = id_map[pick]
            st.subheader(f"실거래 상세 · {pick}")
            _show_complex_deal_detail(filtered, raw_df, cid, interest_id)

    elif menu == "단지 전체 세대수 대비 상승률":
        show_selection_condition(sel)
        show_plotly(
            chart_households_vs_growth(display_rank, interest_id),
            use_container_width=True,
            config=PLOTLY_CFG,
        )
    elif menu == "준공연도 대비 상승률":
        show_selection_condition(sel)
        show_plotly(
            chart_completion_vs_growth(display_rank, interest_id),
            use_container_width=True,
            config=PLOTLY_CFG,
        )
    else:
        show_selection_condition(sel)
        show_plotly(
            chart_start_price_vs_growth(display_rank, interest_id),
            use_container_width=True,
            config=PLOTLY_CFG,
        )


def _inject_complex_arrow_keys() -> None:
    """ArrowUp/Down → 활성 픽의 ↑/↓ 버튼 클릭. st.html 1회 주입(iframe 없음)."""
    if st.session_state.get("_apart_arrow_nav_injected"):
        return
    st.session_state._apart_arrow_nav_injected = True
    st.html(
        """
<script>
(function () {
  const doc = window.document;
  if (doc.documentElement.dataset.apartArrowNav === "1") return;
  doc.documentElement.dataset.apartArrowNav = "1";
  doc.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    const t = e.target;
    const tag = (t && t.tagName) ? t.tagName.toLowerCase() : "";
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (t && t.isContentEditable) return;
    if (t && t.closest && t.closest('[data-baseweb="select"]')) return;
    e.preventDefault();
    const want = e.key === "ArrowUp" ? "↑" : "↓";
    const buttons = Array.from(doc.querySelectorAll("button"));
    const btn = buttons.find(function (b) {
      return (b.textContent || "").replace(/\\s+/g, "").trim() === want;
    });
    if (btn) btn.click();
  }, true);
})();
</script>
        """,
        unsafe_allow_javascript=True,
    )


def _pick_complex_menu(
    scope_df: pd.DataFrame,
    panel_idx: int,
    locked: bool,
    id_key: str,
    interest_id: Optional[int],
    default_gu: Optional[str],
) -> Optional[int]:
    """구/동/단지 셀렉트 + ↑↓(버튼·키보드)로 비교 대상 선택."""
    key = f"{id_key}_p{panel_idx}"
    css = "panel-box panel-interest" if locked else "panel-box"
    st.markdown(f"<div class='{css}'>", unsafe_allow_html=True)
    st.markdown(f"**창 {panel_idx + 1}{' · ★ 관심단지(고정)' if locked else ''}**")

    if locked and interest_id is not None:
        st.write(interest_label_with_tier() or str(interest_id))
        st.caption("좌측 관심단지·지정 평형 (분석 범위·평형과 달라도 참고)")
        st.markdown("</div>", unsafe_allow_html=True)
        return interest_id

    if scope_df.empty:
        st.warning("좌측 선정 범위에 단지가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return None

    gu_opts = sorted(scope_df["sigungu"].dropna().unique().tolist())
    if not gu_opts:
        st.markdown("</div>", unsafe_allow_html=True)
        return None
    gu_default = default_gu if default_gu in gu_opts else gu_opts[0]
    gu = st.selectbox("구/시", gu_opts, index=gu_opts.index(gu_default), key=f"{key}_gu")

    area = scope_df[scope_df["sigungu"] == gu]
    dong_opts = ["(동 전체)"] + sorted(area["dong"].dropna().unique().tolist())
    dong = st.selectbox("동", dong_opts, key=f"{key}_dong")
    if dong != "(동 전체)":
        area = area[area["dong"] == dong]

    cats = complex_catalog(area)
    if cats.empty:
        st.info("해당 범위에 단지가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return None

    labels = (cats["complex_name"] + " (" + cats["dong"] + ")").tolist()
    id_by_label = dict(zip(labels, cats["complex_id"].astype(int)))
    idx_key = f"{key}_idx"
    labels_key = f"{key}_labels"
    scope_fp = f"{gu}|{dong}"
    fp_key = f"{key}_scope_fp"
    st.session_state[labels_key] = labels

    ids = list(st.session_state.get(id_key, []))
    prev = ids[panel_idx] if panel_idx < len(ids) else None

    if st.session_state.get(fp_key) != scope_fp:
        st.session_state[fp_key] = scope_fp
        new_idx = 0
        if prev is not None:
            for i, lab in enumerate(labels):
                if int(id_by_label[lab]) == int(prev):
                    new_idx = i
                    break
        st.session_state[idx_key] = new_idx
        st.session_state[f"{key}_complex"] = labels[new_idx]

    if not st.session_state.get("kbd_nav_key"):
        st.session_state.kbd_nav_key = key
    kbd_active = st.session_state.get("kbd_nav_key") == key
    up_lbl = "↑" if kbd_active else "▲"
    down_lbl = "↓" if kbd_active else "▼"

    n1, n2, n3 = st.columns([1, 1, 4])
    with n1:
        if st.button(up_lbl, key=f"{key}_up", use_container_width=True, help="이전 단지 (↑)"):
            st.session_state.kbd_nav_key = key
            i = max(0, int(st.session_state.get(idx_key, 0)) - 1)
            st.session_state[idx_key] = i
            st.session_state[f"{key}_complex"] = labels[i]
            st.rerun()
    with n2:
        if st.button(down_lbl, key=f"{key}_down", use_container_width=True, help="다음 단지 (↓)"):
            st.session_state.kbd_nav_key = key
            i = min(len(labels) - 1, int(st.session_state.get(idx_key, 0)) + 1)
            st.session_state[idx_key] = i
            st.session_state[f"{key}_complex"] = labels[i]
            st.rerun()
    with n3:
        if kbd_active:
            st.caption(f"키보드 ↑↓ · {int(st.session_state.get(idx_key, 0)) + 1}/{len(labels)}")
        elif st.button("이 창에 ↑↓ 키", key=f"{key}_kbd", use_container_width=True):
            st.session_state.kbd_nav_key = key
            st.rerun()

    cur = st.session_state.get(f"{key}_complex")
    if cur not in labels:
        i = max(0, min(int(st.session_state.get(idx_key, 0)), len(labels) - 1))
        st.session_state[idx_key] = i
        st.session_state[f"{key}_complex"] = labels[i]

    def _on_complex_change(widget_key: str = key) -> None:
        lab_now = st.session_state.get(f"{widget_key}_complex")
        labs_now = st.session_state.get(f"{widget_key}_labels", [])
        if lab_now in labs_now:
            st.session_state[f"{widget_key}_idx"] = labs_now.index(lab_now)
        st.session_state.kbd_nav_key = widget_key

    lab = st.selectbox("단지", labels, key=f"{key}_complex", on_change=_on_complex_change)
    st.session_state[idx_key] = labels.index(lab) if lab in labels else 0

    cid = int(id_by_label[lab])
    while len(ids) <= panel_idx:
        ids.append(None)
    ids[panel_idx] = cid
    st.session_state[id_key] = ids
    st.markdown(f"<span class='name-chip'>{_complex_name(scope_df, cid)}</span>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    return cid


def _growth_for(rank: pd.DataFrame, cid: int) -> Optional[float]:
    row = rank[rank["complex_id"] == cid]
    if row.empty:
        return None
    return float(row.iloc[0]["price_change_pct"])


def _render_compare_view(view: str, filtered: pd.DataFrame, rank: pd.DataFrame, cid: int, interest: bool) -> None:
    st.markdown(f"<span class='name-chip'>{'★ ' if interest else ''}{_complex_name(filtered, cid)}</span>", unsafe_allow_html=True)
    growth = _growth_for(rank, cid)
    if view == "최근 매매가 추이(추세선)":
        show_plotly(
            chart_sale_trend(filtered, cid, interest, growth_pct=growth),
            use_container_width=True,
            config=PLOTLY_CFG,
        )
        if growth is not None:
            st.metric("분석기간 상승률", f"{growth:+.1f}%")
    elif view == "최근 전세가 추이(추정·추세선)":
        st.info("전세 실거래는 아직 미수집입니다. 매매가×65%로 추정 표시합니다.")
        show_plotly(chart_jeonse_trend(filtered, cid, interest), use_container_width=True, config=PLOTLY_CFG)
    elif view == "전세/매매 비율 추이(추정)":
        show_plotly(chart_jeonse_sale_ratio(filtered, cid, interest), use_container_width=True, config=PLOTLY_CFG)
    elif view == "단지 정보 비교":
        profile = render_profile_dict(filtered, cid)
        if profile:
            st.dataframe(pd.DataFrame(profile.items(), columns=["항목", "값"]), use_container_width=True, hide_index=True)
    elif view == "단지 위치(지도 검색)":
        profile = render_profile_dict(filtered, cid)
        if profile:
            st.write(f"**{profile['단지명']}** · {profile['시군구']} {profile['법정동']}")
            addr = profile.get("도로명주소") or profile.get("지번주소") or ""
            if addr:
                st.caption(addr)
            url = kakao_map_url(profile["시군구"], profile["법정동"], profile["단지명"])
            st.link_button("카카오맵에서 위치 보기", url)
    elif view == "평당가 추이":
        show_plotly(chart_ppp_trend(filtered, cid, interest), use_container_width=True, config=PLOTLY_CFG)
        if growth is not None:
            st.metric("분석기간 상승률", f"{growth:+.1f}%")
    elif view == "거래량 추이":
        show_plotly(chart_volume(filtered, cid, interest), use_container_width=True, config=PLOTLY_CFG)
    elif view == "층수별 가격 분포":
        show_plotly(chart_floor_dist(filtered, cid, interest), use_container_width=True, config=PLOTLY_CFG)
    elif view == "동일 동 내 상승률 위치":
        pos = render_dong_position(rank, cid)
        if not pos:
            st.warning("동 내 비교 정보가 없습니다.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("동 내 순위", f"{pos['동내순위']} / {pos['동내단지수']}")
            m2.metric("상승률", f"{pos['상승률']:.1f}%")
            m3.metric("동 내 백분위", f"{pos['동내백분위']:.0f}%")
    else:
        profile = render_profile_dict(filtered, cid)
        row = rank[rank["complex_id"] == cid]
        c1, c2, c3 = st.columns(3)
        c1.metric("평균매매가", f"{profile.get('평균매매가', 0):,.0f}만")
        c2.metric("거래건수", f"{profile.get('거래건수', 0):,}")
        if not row.empty:
            c3.metric("상승률", f"{row.iloc[0]['price_change_pct']:.1f}%", f"CAGR {row.iloc[0]['cagr_pct']:.2f}%")
        else:
            c3.metric("상승률", "-")


def render_compare(
    filtered: pd.DataFrame,
    analysis_df: pd.DataFrame,
    sel: SelectionCriteria,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> None:
    """비교 분석 — 창 2개 고정. 단지 선택은 구/동/단지 메뉴."""
    rank = complex_ranking(filtered, period_start=period_start, period_end=period_end)
    st.caption(
        "비교 창 2개 고정 · 구/동/단지 메뉴 선택 · **↑↓ 키**(또는 ▲▼ 버튼)로 단지 이동. 관심단지는 1번 창 참고치."
    )
    _inject_complex_arrow_keys()
    st.session_state.compare_n = 2
    n = 2
    view = st.selectbox("화면 유형", COMPARE_VIEWS, index=0)

    pick_cols = st.columns(n)
    selected_ids: list[Optional[int]] = []
    interest_id = st.session_state.interest_complex_id
    for i in range(n):
        locked = i == 0 and interest_id is not None
        with pick_cols[i]:
            selected_ids.append(
                _pick_complex_menu(
                    filtered if not locked else analysis_df,
                    i,
                    locked=locked,
                    id_key="compare_ids",
                    interest_id=interest_id,
                    default_gu=sel.sigungu,
                )
            )

    chart_cols = st.columns(n)
    for i, cid in enumerate(selected_ids):
        with chart_cols[i]:
            if cid is None:
                st.info("구/동/단지 메뉴에서 단지를 선택하세요.")
                continue
            interest = cid == interest_id
            use_df = analysis_df if cid in set(analysis_df["complex_id"]) else filtered
            use_rank = rank if not rank.empty else complex_ranking(use_df, period_start=period_start, period_end=period_end)
            _render_compare_view(view, use_df, use_rank, cid, interest)


def _pick_complex_in_scope(
    cats: pd.DataFrame,
    panel_idx: int,
    locked: bool,
    id_key: str,
    interest_id: Optional[int],
) -> Optional[int]:
    """좌측 선정 범위 단지 목록에서만 선택 (구/동 재선택 없음). ▲▼·↑↓키로 이동."""
    key = f"{id_key}_scope_p{panel_idx}"

    if locked and interest_id is not None:
        st.caption("★ 관심단지(고정)")
        st.write(interest_label_with_tier() or str(interest_id))
        ids = list(st.session_state.get(id_key, []))
        while len(ids) <= panel_idx:
            ids.append(None)
        if ids[panel_idx] != int(interest_id):
            ids[panel_idx] = int(interest_id)
            st.session_state[id_key] = ids
        return int(interest_id)

    if cats is None or cats.empty:
        st.warning("좌측 선정 범위에 단지가 없습니다.")
        return None

    options = [int(x) for x in cats["complex_id"].tolist()]
    label_of = {
        int(r.complex_id): f"{r.complex_name} ({r.dong})"
        for r in cats.itertuples(index=False)
    }
    ids = list(st.session_state.get(id_key, []))
    prev = ids[panel_idx] if panel_idx < len(ids) else None

    # 위젯 값은 complex_id(int)만 사용 — 문자열 라벨 세션 충돌/렉 방지
    widget_key = f"{key}_cid"
    default_cid = options[0]
    if prev is not None:
        try:
            prev_i = int(prev)
            if prev_i in label_of:
                default_cid = prev_i
        except (TypeError, ValueError):
            pass
    cur = st.session_state.get(widget_key)
    if cur not in label_of:
        st.session_state[widget_key] = default_cid

    if not st.session_state.get("kbd_nav_key"):
        st.session_state.kbd_nav_key = key
    kbd_active = st.session_state.get("kbd_nav_key") == key
    up_lbl = "↑" if kbd_active else "▲"
    down_lbl = "↓" if kbd_active else "▼"

    n1, n2, n3 = st.columns([1, 1, 5])
    with n1:
        if st.button(up_lbl, key=f"{key}_up", width="stretch", help="이전 단지 (↑)"):
            st.session_state.kbd_nav_key = key
            i = options.index(int(st.session_state[widget_key]))
            st.session_state[widget_key] = options[max(0, i - 1)]
            st.rerun()
    with n2:
        if st.button(down_lbl, key=f"{key}_down", width="stretch", help="다음 단지 (↓)"):
            st.session_state.kbd_nav_key = key
            i = options.index(int(st.session_state[widget_key]))
            st.session_state[widget_key] = options[min(len(options) - 1, i + 1)]
            st.rerun()
    with n3:
        cur_i = options.index(int(st.session_state[widget_key])) if st.session_state[widget_key] in label_of else 0
        if kbd_active:
            st.caption(f"키보드 ↑↓ · {cur_i + 1}/{len(options)}")
        elif st.button("이 칸에 ↑↓ 키", key=f"{key}_kbd", width="stretch"):
            st.session_state.kbd_nav_key = key
            st.rerun()

    def _on_cid_change(wk: str = widget_key, nav: str = key) -> None:
        st.session_state.kbd_nav_key = nav

    cid = int(
        st.selectbox(
            "단지 (좌측 선정 범위)",
            options,
            format_func=lambda x: label_of.get(int(x), str(x)),
            key=widget_key,
            on_change=_on_cid_change,
        )
    )
    while len(ids) <= panel_idx:
        ids.append(None)
    if ids[panel_idx] != cid:
        ids[panel_idx] = cid
        st.session_state[id_key] = ids
    return cid


def render_relative(
    filtered: pd.DataFrame,
    analysis_df: pd.DataFrame,
    sel: SelectionCriteria,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> None:
    region = sel.sigungu or "전체"
    if sel.dong:
        region = f"{region} {sel.dong}"
    st.caption(
        f"좌측 선정 범위(**{region}**, 전용 {sel.area_min:.0f}~{sel.area_max:.0f}㎡)에서 "
        "단지 2개를 비교합니다. **↑↓ 키**(또는 ▲▼)로 이동 · ★관심단지는 지정 평형으로 참고 표시됩니다."
    )

    n = 2
    st.session_state.compare_n = n
    # 선정 조건은 차트 직전에 표시
    # 이전 비교 수 위젯·문자열 라벨 키 잔존 시 정리
    st.session_state.pop("relative_n_seg", None)
    for stale in list(st.session_state.keys()):
        if isinstance(stale, str) and stale.startswith("relative_ids_scope_") and stale.endswith("_complex"):
            del st.session_state[stale]

    _inject_complex_arrow_keys()

    cats = complex_catalog(filtered)
    interest_id = st.session_state.interest_complex_id
    # 관심단지 고정 시 키보드 기본 대상을 2번 픽으로
    if interest_id is not None and not st.session_state.get("kbd_nav_key"):
        st.session_state.kbd_nav_key = "relative_ids_scope_p1"

    pick_cols = st.columns(n)
    selected: list[int] = []
    for i in range(n):
        locked = i == 0 and interest_id is not None
        with pick_cols[i]:
            try:
                cid = _pick_complex_in_scope(
                    cats,
                    i,
                    locked=locked,
                    id_key="relative_ids",
                    interest_id=interest_id,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"단지 선택 UI 오류: {exc}")
                cid = None
            if cid is not None:
                selected.append(int(cid))

    uniq: list[int] = []
    for c in selected:
        if c not in uniq:
            uniq.append(c)
    if not uniq:
        st.info("단지를 선택하세요.")
        return

    plot_src = analysis_df if not analysis_df.empty else filtered
    plot_df = plot_src[plot_src["complex_id"].isin(uniq)]
    _name_chips(plot_df, uniq, interest_id)
    light_cfg = {
        "displayModeBar": True,
        "displaylogo": False,
        "scrollZoom": False,
    }
    try:
        show_selection_condition(sel)
        with st.spinner("비교분석 차트 그리는 중…"):
            fig = chart_multi_complex_prices(
                plot_df,
                uniq,
                interest_id=interest_id,
                period_start=period_start,
                period_end=period_end,
                title="비교분석 · 실거래 / 월평균 / 추세(상승률%)",
                height=760,
            )
            show_plotly(fig, config=light_cfg)
    except Exception as exc:  # noqa: BLE001
        st.error("비교분석 차트 생성 중 오류가 발생했습니다.")
        st.exception(exc)

    _render_relative_compare_table(
        plot_df,
        uniq,
        interest_id=interest_id,
        period_start=period_start,
        period_end=period_end,
    )


def _render_relative_compare_table(
    df: pd.DataFrame,
    complex_ids: list[int],
    interest_id: Optional[int] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> None:
    """차트 아래 단지 정보 나란히 비교 + 선택 단지 실거래 내역."""
    if len(complex_ids) < 1:
        return
    st.markdown("#### 단지 정보 비교")
    rank = complex_ranking(df, period_start=period_start, period_end=period_end)
    cols = st.columns(len(complex_ids))
    compare_keys = [
        "단지명",
        "도로명주소",
        "지번주소",
        "시군구",
        "법정동",
        "준공연도",
        "단지전체세대수",
        "거래건수",
        "평균매매가",
        "평균평당가",
        "상승률(%)",
        "연평균상승률(%)",
        "최근거래일",
    ]
    label_by_cid: dict[int, str] = {}
    for i, cid in enumerate(complex_ids):
        with cols[i]:
            star = "★ " if interest_id is not None and cid == interest_id else ""
            profile = render_profile_dict(df, cid)
            if not profile:
                st.warning(f"단지 {cid}")
                label_by_cid[cid] = str(cid)
                continue
            row_rank = rank[rank["complex_id"] == cid] if not rank.empty else pd.DataFrame()
            if not row_rank.empty:
                r0 = row_rank.iloc[0]
                profile["상승률(%)"] = round(float(r0["price_change_pct"]), 2)
                if "cagr_pct" in r0.index and pd.notna(r0["cagr_pct"]):
                    profile["연평균상승률(%)"] = round(float(r0["cagr_pct"]), 2)
            show = {}
            for k in compare_keys:
                if k not in profile:
                    continue
                v = profile[k]
                if k in ("평균매매가", "평균평당가") and isinstance(v, (int, float)):
                    show[k] = f"{v:,.0f}"
                elif isinstance(v, float):
                    show[k] = f"{v:.2f}" if abs(v) < 1000 else f"{v:,.0f}"
                else:
                    show[k] = str(v)
            name = str(profile.get("단지명", cid))
            label_by_cid[cid] = f"{star}{name}"
            st.markdown(f"**{star}{name}**")

            road = str(profile.get("도로명주소") or "").strip()
            jibun = str(profile.get("지번주소") or "").strip()
            addr = road or jibun
            lat = profile.get("위도")
            lon = profile.get("경도")
            if addr or (lat is not None and lon is not None):
                url = naver_map_url(
                    address=addr,
                    sigungu=str(profile.get("시군구") or ""),
                    dong=str(profile.get("법정동") or ""),
                    complex_name=name,
                    lat=float(lat) if lat is not None else None,
                    lon=float(lon) if lon is not None else None,
                )
                if road:
                    st.markdown(f"주소 [{road}]({url})")
                elif jibun:
                    st.markdown(f"주소 [{jibun}]({url})")
                else:
                    st.markdown(f"[네이버 지도에서 위치 보기]({url})")
            else:
                st.caption("주소 정보 없음")

            st.dataframe(
                pd.DataFrame({"항목": list(show.keys()), "값": list(show.values())}),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("#### 실거래 내역")
    opts = list(complex_ids)
    default_cid = interest_id if interest_id in opts else opts[0]
    if "relative_tx_cid" not in st.session_state or st.session_state.relative_tx_cid not in opts:
        st.session_state.relative_tx_cid = default_cid
    pick = st.radio(
        "실거래 볼 단지",
        options=opts,
        format_func=lambda c: label_by_cid.get(int(c), str(c)),
        horizontal=True,
        key="relative_tx_cid",
    )
    tbl = transactions_table(df, int(pick))
    if tbl.empty:
        st.info("선택한 단지의 실거래가 없습니다.")
    else:
        st.caption(f"실거래 {len(tbl):,}건 (최근순)")
        st.dataframe(tbl, use_container_width=True, hide_index=True, height=420)


def render_floor_analysis(filtered: pd.DataFrame, sel: Optional[SelectionCriteria] = None) -> None:
    st.subheader("층별 가격 분석")
    st.caption(
        "좌측 선정·제외 범위(해당 지역·평형) 거래만 사용합니다. "
        "각 단지 월평균 추세가 대비 개별 거래가의 편차(%)를 층·높이비율로 집계합니다."
    )
    if filtered.empty:
        st.warning("좌측 조건에 맞는 거래가 없습니다.")
        return

    result = compute_floor_premiums(filtered)
    s = result.summary
    if s.get("거래수", 0) == 0:
        st.warning(s.get("메시지", "분석 가능한 표본이 없습니다."))
        return

    def _fmt(v):
        return "-" if v is None else f"{v:+.1f}%"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("분석 단지", f"{s['단지수']:,}")
    c2.metric("분석 거래", f"{s['거래수']:,}")
    c3.metric("1층 vs 추세가", _fmt(s.get("1층_평균프리미엄pct")))
    c4.metric("2층 vs 추세가", _fmt(s.get("2층_평균프리미엄pct")))
    c5.metric("꼭대기층 vs 추세가", _fmt(s.get("꼭대기층_평균프리미엄pct")))
    if s.get("최고프리미엄_높이구간"):
        st.success(
            f"최고 높이 구간 **{s['최고프리미엄_높이구간']}** "
            f"({s['최고프리미엄_높이구간_pct']:+.1f}%)"
        )
    show_selection_condition(sel)
    show_plotly(chart_floor_premium_bars(result), key="floor_fl")
    show_plotly(chart_height_premium_bars(result), key="floor_ht")
    with st.expander("층별 집계"):
        show = result.by_floor.copy()
        show["평균프리미엄pct"] = show["평균프리미엄pct"].map(lambda x: f"{x:+.2f}%")
        show["중앙프리미엄pct"] = show["중앙프리미엄pct"].map(lambda x: f"{x:+.2f}%")
        show["평균가"] = show["평균가"].map(lambda x: f"{x:,.0f}")
        st.dataframe(show.rename(columns={"floor": "층"}), use_container_width=True, hide_index=True)


def show_selection_condition(sel: Optional[SelectionCriteria]) -> None:
    """분석 그래프 바로 위 — 검정 배경·흰 글씨 (카드 박스 없음)."""
    if sel is None:
        return
    region = sel.sigungu or "전체 지역"
    if sel.dong:
        region = f"{region} {sel.dong}"
    period = f"{sel.start_date} ~ {sel.end_date}" if sel.start_date and sel.end_date else "-"
    area = f"{sel.area_min:.0f}~{sel.area_max:.0f}㎡"
    age = f"{sel.age_min}~{sel.age_max}년"
    hh = f"{sel.households_min:,}~{sel.households_max:,}세대"
    interest = (
        f" · ★관심 {interest_label_with_tier()}"
        if st.session_state.interest_complex_id
        else " · 관심단지 미설정"
    )
    st.markdown(
        f"<div class='sel-cond'><b>선정 조건</b> · 지역 {region} · 기간 {period} · "
        f"전용면적 {area} · 연식 {age} · 단지세대수 {hh}{interest}</div>",
        unsafe_allow_html=True,
    )


def render_baseline_summary(
    filtered: pd.DataFrame,
    sel: SelectionCriteria,
    result,
) -> None:
    """분석 항목 아래: 좌측 선정 범위 기초 통계 (한 줄). 선정 조건은 그래프 위에 표시."""
    st.markdown("#### 분석 대상 요약")

    if filtered.empty:
        st.info("현재 선정·제외 조건에 해당하는 거래가 없습니다. 좌측 조건을 완화해 보세요.")
        return

    n_tx = int(len(filtered))
    n_cx = int(filtered["complex_id"].nunique())
    n_dong = int(filtered["dong"].nunique()) if "dong" in filtered.columns else 0
    avg_p = float(filtered["price"].mean())
    min_p = float(filtered["price"].min())
    max_p = float(filtered["price"].max())
    avg_area = float(filtered["exclusive_area"].mean()) if "exclusive_area" in filtered.columns else 0.0
    avg_ppp = float(filtered["price_per_pyeong"].mean()) if "price_per_pyeong" in filtered.columns else 0.0
    remain = result.summary.get("최종건수", n_tx)

    stats = [
        ("대상 단지", f"{n_cx:,}"),
        ("거래 건수", f"{n_tx:,}"),
        ("법정동 수", f"{n_dong:,}"),
        ("평균 거래가", format_eok(avg_p)),
        ("최저 / 최고", f"{format_eok(min_p)} / {format_eok(max_p)}"),
        ("평균 전용면적", f"{avg_area:.1f}㎡"),
        ("평균 평당가", f"{avg_ppp:,.0f}만/평" if avg_ppp else "-"),
        ("필터 후 잔여", f"{remain:,}건"),
    ]
    # 한 줄 HTML로 묶어 Streamlit이 span을 숨기지 않게 함
    cells = "".join(
        f"<div style='flex:1;min-width:0;padding:0 0.35rem'>"
        f"<div class='sum-lab'>{lab}</div><div class='sum-val'>{val}</div></div>"
        for lab, val in stats
    )
    st.markdown(
        f"<div style='display:flex;flex-wrap:wrap;gap:0.35rem 0.2rem;width:100%'>{cells}</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    _init_state()

    df = ensure_data()
    if st.session_state.get("open_refresh_dialog"):
        _molit_refresh_dialog()
    sel, exc = sidebar_filters(df)
    result = apply_filters(df, sel, exc)

    top_l, top_r = st.columns([3, 2])
    with top_l:
        st.markdown(
            """
            <div class="hero">
              <h1>아파트 실거래 비교 분석</h1>
              <p>좌측에서 대상·제외·관심단지를 설정하고, 우측 상단에서 분석 유형을 고르세요.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_r:
        st.markdown("##### 분석 유형")
        for key in ("mode", "mode_seg"):
            cur = st.session_state.get(key)
            if cur in _MODE_ALIASES:
                st.session_state[key] = _MODE_ALIASES[cur]
        if st.session_state.mode not in ANALYSIS_MODES:
            st.session_state.mode = ANALYSIS_MODES[0]
        if "mode_seg" not in st.session_state:
            st.session_state.mode_seg = st.session_state.mode
        if st.session_state.mode_seg not in ANALYSIS_MODES:
            st.session_state.mode_seg = ANALYSIS_MODES[0]
        mode = st.segmented_control(
            "분석 유형",
            options=ANALYSIS_MODES,
            required=True,
            key="mode_seg",
            label_visibility="collapsed",
        )
        st.session_state.mode = mode or st.session_state.mode

    filtered = result.filtered if result.message == "ok" else pd.DataFrame(columns=df.columns)
    mode = st.session_state.mode

    # 분석 유형 바로 아래: 전체 서열의 분석 항목
    overall_menu: Optional[str] = None
    if mode == "전체 서열 분석":
        if "overall_menu" in st.session_state and st.session_state.overall_menu not in OVERALL_MENUS:
            st.session_state.overall_menu = OVERALL_MENUS[0]
        overall_menu = st.radio(
            "분석 항목",
            OVERALL_MENUS,
            horizontal=True,
            key="overall_menu",
        )

    render_baseline_summary(filtered, sel, result)

    if result.message != "ok":
        st.warning(result.message)

    interest_id = st.session_state.interest_complex_id
    period_start, period_end = sel.start_date, sel.end_date
    interest_df = load_interest_df(df, sel)
    analysis_df = with_interest_reference(filtered, interest_df)

    st.divider()
    if mode == "전체 서열 분석":
        if result.message != "ok" and interest_df.empty:
            _persist_prefs()
            return
        render_overall(
            filtered,
            df,
            interest_df,
            interest_id,
            period_start,
            period_end,
            sel=sel,
            exc=exc,
            menu=overall_menu,
        )
    elif mode == "비교분석":
        render_relative(filtered, analysis_df, sel, period_start, period_end)
    else:
        render_floor_analysis(filtered, sel=sel)

    _persist_prefs()


if __name__ == "__main__":
    main()
