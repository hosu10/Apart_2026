"""주소 → 좌표 (Nominatim + 로컬 캐시)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests
from sqlalchemy import text

from app.config import DATA_DIR
from app.db.schema import get_engine, init_db

CACHE_PATH = DATA_DIR / "enrich" / "geocode_cache.json"
USER_AGENT = "ApartTrendLab/1.1 (local research; contact=local)"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def nominatim_geocode(query: str, sleep_s: float = 1.05) -> tuple[Optional[float], Optional[float], str]:
    """Returns lat, lon, source_label."""
    q = (query or "").strip()
    if not q:
        return None, None, "empty"
    cache = _load_cache()
    if q in cache and cache[q].get("lat") is not None:
        return float(cache[q]["lat"]), float(cache[q]["lon"]), "cache"
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "json",
                "limit": 1,
                "addressdetails": 0,
                "countrycodes": "kr",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        time.sleep(sleep_s)
        if r.status_code != 200:
            cache[q] = {"lat": None, "lon": None, "error": r.status_code}
            _save_cache(cache)
            return None, None, f"http_{r.status_code}"
        data = r.json()
        if not data:
            cache[q] = {"lat": None, "lon": None, "error": "no_result"}
            _save_cache(cache)
            return None, None, "no_result"
        lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
        cache[q] = {"lat": lat, "lon": lon, "display": data[0].get("display_name", "")}
        _save_cache(cache)
        return lat, lon, "nominatim"
    except Exception as exc:  # noqa: BLE001
        cache[q] = {"lat": None, "lon": None, "error": str(exc)}
        _save_cache(cache)
        return None, None, "error"


def build_address_queries(row: dict) -> list[str]:
    """우선순위: 시군구+도로명 → 지번 → 단지명+동."""
    sigungu = str(row.get("sigungu") or "").strip()
    dong = str(row.get("dong") or "").strip()
    road = str(row.get("road_addr") or "").strip()
    jibun = str(row.get("jibun_addr") or "").strip()
    name = str(row.get("complex_name") or "").strip()
    qs: list[str] = []
    if road:
        if road.startswith("서울") or road.startswith("경기"):
            qs.append(road)
        else:
            qs.append(f"서울특별시 {sigungu} {road}".strip())
            qs.append(f"{sigungu} {road}".strip())
    if jibun:
        qs.append(jibun)
    if name and sigungu and dong:
        qs.append(f"서울특별시 {sigungu} {dong} {name}")
        qs.append(f"{sigungu} {dong} {name}")
    # 중복 제거
    out: list[str] = []
    for q in qs:
        if q and q not in out:
            out.append(q)
    return out


def geocode_complex_row(row: dict) -> tuple[Optional[float], Optional[float], str]:
    for q in build_address_queries(row):
        lat, lon, src = nominatim_geocode(q)
        if lat is not None and lon is not None:
            return lat, lon, f"{src}:{q}"
    return None, None, "failed"


def geocode_missing_complexes(limit: int = 500, only_lawd: list[str] | None = None) -> dict:
    """road/jibun 있는 단지 중 좌표 품질이 낮은 항목을 실제 주소로 갱신."""
    init_db()
    eng = get_engine()
    sql = """
        SELECT c.complex_id, c.complex_name, c.dong, c.road_addr, c.jibun_addr,
               c.latitude, c.longitude, c.enrich_source, r.sigungu, c.lawd_cd
        FROM dim_complex c
        JOIN dim_region r ON c.lawd_cd = r.lawd_cd
        WHERE (c.road_addr IS NOT NULL AND c.road_addr != '')
           OR (c.jibun_addr IS NOT NULL AND c.jibun_addr != '')
        ORDER BY CASE WHEN c.enrich_source = 'reb_csv' THEN 0 ELSE 1 END, c.complex_id
    """
    with eng.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(sql)).mappings().all()]
    if only_lawd:
        rows = [r for r in rows if str(r["lawd_cd"]) in set(only_lawd)]

    # geocode_source 컬럼이 없으면 latitude만 보고, 전량 재geocode 대상 중 상위 limit
    updated = 0
    failed = 0
    tried = 0
    with eng.begin() as conn:
        # 품질 플래그 컬럼
        try:
            conn.execute(text("ALTER TABLE dim_complex ADD COLUMN geocode_source VARCHAR(80)"))
        except Exception:  # noqa: BLE001
            pass

        for r in rows:
            if tried >= limit:
                break
            # 이미 주소 geocode 된 것은 스킵
            src_existing = None
            try:
                src_existing = conn.execute(
                    text("SELECT geocode_source FROM dim_complex WHERE complex_id=:cid"),
                    {"cid": int(r["complex_id"])},
                ).scalar()
            except Exception:  # noqa: BLE001
                src_existing = None
            if src_existing and str(src_existing).startswith(("nominatim", "cache")):
                continue

            tried += 1
            lat, lon, src = geocode_complex_row(r)
            if lat is None:
                failed += 1
                continue
            conn.execute(
                text(
                    """
                    UPDATE dim_complex
                    SET latitude=:lat, longitude=:lon, geocode_source=:src
                    WHERE complex_id=:cid
                    """
                ),
                {"lat": lat, "lon": lon, "src": src[:80], "cid": int(r["complex_id"])},
            )
            updated += 1
    return {"tried": tried, "updated": updated, "failed": failed, "limit": limit}


def geocode_unique_dongs(limit: int = 400) -> dict:
    """동 단위 중심좌표 캐시(단지 주소 실패 시 폴백용)."""
    init_db()
    eng = get_engine()
    with eng.connect() as conn:
        dongs = conn.execute(
            text(
                """
                SELECT DISTINCT r.sigungu, c.dong
                FROM dim_complex c
                JOIN dim_region r ON c.lawd_cd = r.lawd_cd
                WHERE c.dong IS NOT NULL AND c.dong != ''
                """
            )
        ).mappings().all()
    updated = 0
    cache = _load_cache()
    for i, r in enumerate(dongs):
        if i >= limit:
            break
        q = f"서울특별시 {r['sigungu']} {r['dong']}"
        if "고양" in str(r["sigungu"]) or "김포" in str(r["sigungu"]):
            q = f"경기도 {r['sigungu']} {r['dong']}"
        if q in cache and cache[q].get("lat") is not None:
            continue
        lat, lon, _ = nominatim_geocode(q)
        if lat is not None:
            updated += 1
    return {"dong_pairs": len(dongs), "newly_geocoded": updated}


def apply_dong_fallback_coords() -> dict:
    """주소 geocode 실패/미실시 단지에 동 중심 좌표 폴백(추정 표시)."""
    init_db()
    eng = get_engine()
    cache = _load_cache()
    updated = 0
    with eng.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE dim_complex ADD COLUMN geocode_source VARCHAR(80)"))
        except Exception:  # noqa: BLE001
            pass
        rows = conn.execute(
            text(
                """
                SELECT c.complex_id, c.dong, r.sigungu, c.geocode_source
                FROM dim_complex c
                JOIN dim_region r ON c.lawd_cd = r.lawd_cd
                """
            )
        ).mappings().all()
        for r in rows:
            src = r.get("geocode_source") or ""
            if src.startswith(("nominatim", "cache")):
                continue
            sigungu, dong = str(r["sigungu"]), str(r["dong"] or "")
            q1 = f"서울특별시 {sigungu} {dong}"
            q2 = f"경기도 {sigungu} {dong}"
            hit = cache.get(q1) or cache.get(q2)
            if not hit or hit.get("lat") is None:
                continue
            conn.execute(
                text(
                    """
                    UPDATE dim_complex
                    SET latitude=:lat, longitude=:lon, geocode_source=:src
                    WHERE complex_id=:cid
                    """
                ),
                {
                    "lat": float(hit["lat"]),
                    "lon": float(hit["lon"]),
                    "src": "dong_fallback",
                    "cid": int(r["complex_id"]),
                },
            )
            updated += 1
    return {"dong_fallback_updated": updated}
