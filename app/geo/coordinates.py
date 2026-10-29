"""단지 지도 좌표 유틸.

우선순위: DB 실측/주소 geocode → 동 폴백 → (최후) 구 중심 추정.
가짜 해시 좌표로 실측값을 덮어쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.config import DATA_DIR
from app.db.schema import get_engine, init_db

CACHE_PATH = DATA_DIR / "enrich" / "geocode_cache.json"

GU_CENTERS: dict[str, tuple[float, float]] = {
    "마포구": (37.5663, 126.9019),
    "종로구": (37.5735, 126.9790),
    "중구": (37.5641, 126.9979),
    "용산구": (37.5326, 126.9900),
    "서대문구": (37.5791, 126.9368),
    "은평구": (37.6027, 126.9291),
    "동작구": (37.5124, 126.9393),
    "영등포구": (37.5264, 126.8962),
    "양천구": (37.5170, 126.8664),
    "강서구": (37.5509, 126.8495),
    "구로구": (37.4954, 126.8874),
    "성동구": (37.5634, 127.0369),
    "강남구": (37.5172, 127.0473),
    "서초구": (37.4837, 127.0324),
    "송파구": (37.5145, 127.1059),
    "강동구": (37.5301, 127.1238),
    "고양덕양구": (37.6371, 126.8323),
    "고양일산동구": (37.6586, 126.7750),
    "고양일산서구": (37.6779, 126.7450),
    "김포시": (37.6153, 126.7155),
}


def _hash_unit(key: str, salt: str = "") -> float:
    h = hashlib.md5(f"{salt}:{key}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _dong_cache_lookup(sigungu: str, dong: str) -> tuple[float, float] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for q in (f"서울특별시 {sigungu} {dong}", f"경기도 {sigungu} {dong}", f"{sigungu} {dong}"):
        hit = cache.get(q)
        if hit and hit.get("lat") is not None:
            return float(hit["lat"]), float(hit["lon"])
    return None


def complex_coords(sigungu: str, dong: str, complex_id: int) -> tuple[float, float]:
    """최후 폴백 추정 좌표(지도에 점이라도 보이도록)."""
    cached = _dong_cache_lookup(sigungu, dong)
    if cached:
        lat0, lon0 = cached
    else:
        lat0, lon0 = GU_CENTERS.get(sigungu, (37.5665, 126.9780))
    u, v = _hash_unit(str(complex_id), "lat"), _hash_unit(str(complex_id), "lon")
    return lat0 + (u - 0.5) * 0.0025, lon0 + (v - 0.5) * 0.0030


def ensure_complex_coordinates(force: bool = False) -> dict:
    """실측 geocode가 없는 단지만 동 폴백/추정으로 채움. force여도 nominatim 결과는 보존.

    이미 lat/lon이 있으면 스킵(매 기동 수천 UPDATE 방지). force=True여도
    nominatim/cache 출처는 덮어쓰지 않는다.
    """
    init_db()
    eng = get_engine()
    updated = 0
    with eng.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE dim_complex ADD COLUMN geocode_source VARCHAR(80)"))
        except Exception:  # noqa: BLE001
            pass
        # 빠른 경로: 좌표가 모두 있으면 전체 루프 생략
        if not force:
            missing = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM dim_complex
                    WHERE latitude IS NULL OR longitude IS NULL
                    """
                )
            ).scalar_one()
            total = conn.execute(text("SELECT COUNT(*) FROM dim_complex")).scalar_one()
            if int(missing or 0) == 0:
                return {"updated": 0, "total": int(total or 0), "skipped": True}

        rows = conn.execute(
            text(
                """
                SELECT c.complex_id, c.dong, r.sigungu, c.latitude, c.longitude, c.geocode_source
                FROM dim_complex c
                JOIN dim_region r ON c.lawd_cd = r.lawd_cd
                """
            )
        ).mappings().all()
        for r in rows:
            src = (r.get("geocode_source") or "").strip()
            if src.startswith(("nominatim", "cache")):
                # force여도 주소 geocode는 유지
                continue
            # 이미 좌표가 있으면 재계산하지 않음 (approx/dong_fallback 유지)
            if (
                not force
                and r.get("latitude") is not None
                and r.get("longitude") is not None
            ):
                continue
            lat, lon = complex_coords(str(r["sigungu"]), str(r["dong"] or ""), int(r["complex_id"]))
            conn.execute(
                text(
                    """
                    UPDATE dim_complex
                    SET latitude=:lat, longitude=:lon,
                        geocode_source=COALESCE(NULLIF(geocode_source,''), 'approx')
                    WHERE complex_id=:cid
                      AND (geocode_source IS NULL OR geocode_source NOT LIKE 'nominatim%' AND geocode_source NOT LIKE 'cache%')
                    """
                ),
                {"lat": lat, "lon": lon, "cid": int(r["complex_id"])},
            )
            updated += 1
    return {"updated": updated, "total": len(rows)}


def attach_coords(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "latitude" not in out.columns:
        out["latitude"] = pd.NA
        out["longitude"] = pd.NA
    miss = out["latitude"].isna() | out["longitude"].isna()
    if miss.any():
        filled = out.loc[miss].apply(
            lambda r: complex_coords(str(r.get("sigungu", "")), str(r.get("dong", "")), int(r["complex_id"])),
            axis=1,
            result_type="expand",
        )
        out.loc[miss, "latitude"] = filled[0].to_numpy()
        out.loc[miss, "longitude"] = filled[1].to_numpy()
    return out


def complex_map_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "complex_id",
                "complex_name",
                "sigungu",
                "dong",
                "latitude",
                "longitude",
                "total_households",
                "geocode_source",
            ]
        )
    work = attach_coords(df)
    keep = ["complex_id", "complex_name", "sigungu", "dong", "latitude", "longitude"]
    for c in ("total_households", "geocode_source"):
        if c in work.columns:
            keep.append(c)
    return work[keep].drop_duplicates("complex_id").reset_index(drop=True)
