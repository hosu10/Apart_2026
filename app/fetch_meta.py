"""MOLIT 실거래 갱신 메타(워터마크) 저장."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from app.config import FETCH_META_PATH


def load_fetch_meta(path: Path | None = None) -> dict[str, Any]:
    path = path or FETCH_META_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_fetch_meta(meta: dict[str, Any], path: Path | None = None) -> None:
    path = path or FETCH_META_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def update_after_refresh(result: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """refresh_recent_trades 결과로 워터마크 갱신."""
    now = datetime.now().isoformat(timespec="seconds")
    prev = load_fetch_meta(path)
    meta = {
        **prev,
        "last_checked_at": result.get("checked_at") or now,
        "last_refresh_at": now,
        "last_status": result.get("status"),
        "last_has_new": bool(result.get("has_new")),
        "last_period": result.get("period"),
        "last_message": result.get("message"),
        "watermark_deal_date": result.get("after_max_date")
        or result.get("api_max_date")
        or prev.get("watermark_deal_date"),
        "watermark_ym": None,
        "after_total": result.get("after_total"),
        "regions": result.get("regions"),
    }
    wd = meta.get("watermark_deal_date")
    if isinstance(wd, str) and len(wd) >= 7:
        meta["watermark_ym"] = wd[:4] + wd[5:7] if "-" in wd else wd[:6]
    save_fetch_meta(meta, path)
    return meta


def months_back_from_watermark(
    default: int = 2,
    *,
    today: Optional[date] = None,
    path: Path | None = None,
) -> int:
    """워터마크 이후만 조회하도록 months_back 축소 (API는 월 단위).

    - 워터마크 없으면 default
    - 같은 달이면 0(이번 달만), 이전이면 경과 개월(최대 default)
    """
    today = today or date.today()
    meta = load_fetch_meta(path)
    ym = meta.get("watermark_ym")
    wd = meta.get("watermark_deal_date")
    if not ym and isinstance(wd, str) and len(wd) >= 7:
        ym = wd[:4] + wd[5:7] if "-" in wd else wd[:6]
    if not ym or len(str(ym)) < 6:
        return default
    try:
        y, m = int(str(ym)[:4]), int(str(ym)[4:6])
    except ValueError:
        return default
    # 늦은 신고 대비 워터마크 월부터 다시 조회 → back = 오늘 기준 경과 개월
    cur_idx = today.year * 12 + (today.month - 1)
    wm_idx = y * 12 + (m - 1)
    back = max(0, cur_idx - wm_idx)
    # 최소 이번 달(+가능하면 직전 1개월)은 재확인 — 신고 지연
    if back == 0:
        return 0
    return min(default, max(1, back))
