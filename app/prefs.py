"""UI 설정 로컬 저장/복원 (data/user_prefs.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import (
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
    USER_PREFS_PATH,
)

# session_state / 위젯 key 와 동기화되는 항목
PREF_KEYS = (
    "analysis_region",
    "filter_sigungu",
    "filter_dong",
    "filter_size_tier",
    "filter_age_min",
    "filter_age_max",
    "filter_hh_min",
    "filter_hh_max",
    "filter_lookback",
    "filter_min_age",
    "filter_min_tx",
    "filter_exclude_direct",
    "filter_remove_outliers",
    "interest_complex_id",
    "interest_label",
    "interest_size_tier",
    "mode",
    "compare_n",
    "compare_ids",
    "relative_ids",
)


def default_prefs() -> dict[str, Any]:
    return {
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
        "interest_complex_id": DEFAULT_INTEREST_COMPLEX_ID,
        "interest_label": DEFAULT_INTEREST_LABEL,
        "interest_size_tier": DEFAULT_SIZE_TIER,
        "mode": "전체 서열 분석",
        "compare_n": 2,
        "compare_ids": [DEFAULT_INTEREST_COMPLEX_ID, None, None, None],
        "relative_ids": [DEFAULT_INTEREST_COMPLEX_ID, None, None, None],
    }


def load_prefs(path: Path | None = None) -> dict[str, Any]:
    path = path or USER_PREFS_PATH
    base = default_prefs()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return base
    except Exception:  # noqa: BLE001
        return base
    mode_aliases = {"상대비교분석": "비교분석", "비교 분석": "비교분석"}
    for k in PREF_KEYS:
        if k not in raw:
            continue
        val = raw[k]
        if k == "mode" and isinstance(val, str) and val in mode_aliases:
            val = mode_aliases[val]
        if k in ("compare_ids", "relative_ids") and isinstance(val, list):
            ids: list[Any] = []
            for x in val[:4]:
                if x is None:
                    ids.append(None)
                else:
                    try:
                        ids.append(int(x))
                    except (TypeError, ValueError):
                        ids.append(None)
            while len(ids) < 4:
                ids.append(None)
            base[k] = ids
        else:
            base[k] = val
    return base


def save_prefs(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or USER_PREFS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    out = default_prefs()
    for k in PREF_KEYS:
        if k in data:
            out[k] = data[k]
    # JSON 직렬화: None 유지
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def prefs_from_session(session_state: Any) -> dict[str, Any]:
    """st.session_state 에서 저장용 dict 추출."""
    out: dict[str, Any] = {}
    for k in PREF_KEYS:
        if k in session_state:
            out[k] = session_state[k]
    # mode_seg 위젯이 있으면 동기화
    if "mode_seg" in session_state and session_state["mode_seg"]:
        out["mode"] = session_state["mode_seg"]
    return out
