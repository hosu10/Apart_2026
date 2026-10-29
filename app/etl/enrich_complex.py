"""
단지 마스터 Enrichment 파이프라인

1차 소스: 한국부동산원 공동주택 단지 식별정보 CSV
단지명 우선순위: 도로명주소 > 건축물대장 > 공시가격
세대수 50 미만 REB 후보는 매칭/반영에서 제외
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests
from sqlalchemy import select, text
from thefuzz import fuzz

from app.config import DATA_DIR, MOLIT_API_KEY, TARGET_LAWD_CDS
from app.db.schema import Complex, get_engine, get_session, init_db
from app.etl.matching import normalize_dong, normalize_name

ENRICH_DIR = DATA_DIR / "enrich"
REB_CSV = ENRICH_DIR / "reb_complex_master.csv"
MIN_HOUSEHOLDS = 50

APT_LIST_URL = "https://apis.data.go.kr/1613000/AptListService4/getSigunguAptList4"


def _parse_year(value) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().replace("-", "").replace(".", "")
    if len(s) >= 4 and s[:4].isdigit():
        y = int(s[:4])
        if 1960 <= y <= 2035:
            return y
    return None


def _clean_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def pick_reb_name(row: dict | pd.Series) -> str:
    """단지명 우선순위: 도로명주소 > 건축물대장 > 공시가격."""
    for key in ("name_road", "name_building", "name_reb"):
        s = _clean_str(row.get(key) if hasattr(row, "get") else row[key] if key in row else "")
        if s:
            return s
    return ""


def load_reb_master(
    path: Path = REB_CSV,
    apt_only: bool = True,
    min_households: int = MIN_HOUSEHOLDS,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"REB CSV 없음: {path}\n"
            "공공데이터포털에서 '한국부동산원_공동주택 단지 식별정보_기본정보' CSV를 "
            f"{path} 경로로 저장하세요."
        )
    df = pd.read_csv(path, encoding="cp949", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    rename = {
        "단지고유번호": "reb_id",
        "주소": "jibun_addr",
        "단지명_공시가격": "name_reb",
        "단지명_건축물대장": "name_building",
        "단지명_도로명주소": "name_road",
        "단지종류": "housing_type",
        "동수": "dong_count",
        "세대수": "households",
        "사용승인일": "use_date",
        "도로명주소": "road_addr",
    }
    df = df.rename(columns=rename)
    if apt_only and "housing_type" in df.columns:
        df = df[df["housing_type"].astype(str).str.strip() == "1"].copy()

    df["complex_name"] = df.apply(pick_reb_name, axis=1)
    df["households"] = pd.to_numeric(df["households"], errors="coerce")
    df["dong_count"] = pd.to_numeric(df["dong_count"], errors="coerce")
    df["completion_year"] = df["use_date"].map(_parse_year)
    df["name_normalized"] = df["complex_name"].map(normalize_name)
    df = df[df["complex_name"].astype(str).str.len() > 0].copy()
    # 세대수 50 미만 제외
    df = df[df["households"].fillna(0) >= min_households].copy()

    def parse_addr(addr: str) -> tuple[str, str, str]:
        if not isinstance(addr, str):
            return "", "", ""
        parts = addr.split()
        sido = parts[0] if parts else ""
        sigungu = ""
        dong = ""
        if len(parts) >= 2:
            if parts[1].endswith("시") and len(parts) >= 3 and parts[2].endswith("구"):
                sigungu = parts[1] + parts[2]
                rest = parts[3:]
            else:
                sigungu = parts[1]
                rest = parts[2:]
            for p in rest:
                if p.endswith("동") or p.endswith("읍") or p.endswith("면") or p.endswith("리"):
                    dong = re.sub(r"\d+$", "", p)
                    break
        return sido, sigungu, dong

    parsed = df["jibun_addr"].map(parse_addr)
    df["sido"] = parsed.map(lambda x: x[0])
    df["sigungu"] = parsed.map(lambda x: x[1])
    df["dong"] = parsed.map(lambda x: x[2])
    df["lawd_prefix"] = df["reb_id"].astype(str).str[:5]
    return df.reset_index(drop=True)


def filter_reb_to_targets(reb: pd.DataFrame, lawd_cds: list[str] | None = None) -> pd.DataFrame:
    codes = set(lawd_cds or TARGET_LAWD_CDS)
    return reb[reb["lawd_prefix"].isin(codes)].copy()


def load_db_complexes() -> pd.DataFrame:
    from app.db.migrate import migrate_complex_columns

    migrate_complex_columns()
    eng = get_engine()
    return pd.read_sql(
        text(
            """
            SELECT c.complex_id, c.complex_name, c.lawd_cd, c.dong,
                   c.total_households, c.completion_year, r.sigungu
            FROM dim_complex c
            JOIN dim_region r ON c.lawd_cd = r.lawd_cd
            """
        ),
        eng,
    )


def _score_name(query: str, candidate: str) -> tuple[int, str]:
    qn = normalize_name(query)
    cn = normalize_name(candidate)
    if not qn or not cn:
        return 0, "empty"
    if qn == cn:
        # 원문도 비슷하면 exact, 아니면 정규화 충돌 가능 → 점수 하향
        raw_ratio = fuzz.ratio(query.replace(" ", ""), candidate.replace(" ", ""))
        if raw_ratio >= 90:
            return 100, "exact"
        return max(88, raw_ratio), "norm_exact"
    if qn in cn or cn in qn:
        # 짧은 부분문자열(예: '태영')로 대단지 오매칭 방지
        if min(len(qn), len(cn)) >= 6 and max(len(qn), len(cn)) <= min(len(qn), len(cn)) * 2:
            return 94, "contains"
        return 0, "contains_rejected"
    score = fuzz.token_sort_ratio(qn, cn)
    return int(score), "fuzzy"


def match_complexes(
    db_df: pd.DataFrame,
    reb_df: pd.DataFrame,
    min_score: int = 85,
) -> pd.DataFrame:
    """DB 단지 ↔ REB 단지 매칭. 동 우선, 동점 시 세대수 큰 후보 선택."""
    rows = []
    reb_by_lawd: dict[str, pd.DataFrame] = {code: g for code, g in reb_df.groupby("lawd_prefix")}

    for _, c in db_df.iterrows():
        lawd = str(c["lawd_cd"])
        cand_df = reb_by_lawd.get(lawd)
        base = {
            **c.to_dict(),
            "match_status": "unmatched",
            "match_score": 0,
            "match_method": "",
        }
        if cand_df is None or cand_df.empty:
            base["match_status"] = "no_region"
            rows.append(base)
            continue

        dong = normalize_dong(str(c["dong"]))
        same_dong = cand_df[cand_df["dong"].map(normalize_dong) == dong]
        pools = []
        if not same_dong.empty:
            pools.append(("dong", same_dong, min_score))
        pools.append(("gu", cand_df, max(min_score, 92)))

        best = None
        for scope, pool, thr in pools:
            scored = []
            for idx, rr in pool.iterrows():
                score, method = _score_name(str(c["complex_name"]), str(rr["complex_name"]))
                if score < thr:
                    continue
                hh = float(rr["households"]) if pd.notna(rr["households"]) else 0
                scored.append((score, hh, method, scope, idx, rr))
            if not scored:
                continue
            # 점수 우선, 동점 시 세대수 큰 단지
            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best = scored[0]
            break

        if best is None:
            rows.append(base)
            continue

        score, hh, method, scope, idx, reb_row = best
        rows.append(
            {
                **c.to_dict(),
                "match_status": "matched",
                "match_score": int(score),
                "match_method": f"{method}:{scope}",
                "reb_id": reb_row.get("reb_id"),
                "reb_name": reb_row.get("complex_name"),
                "reb_households": reb_row.get("households"),
                "reb_dong_count": reb_row.get("dong_count"),
                "reb_completion_year": reb_row.get("completion_year"),
                "reb_use_date": reb_row.get("use_date"),
                "reb_jibun": reb_row.get("jibun_addr"),
                "reb_road": reb_row.get("road_addr"),
                "reb_dong": reb_row.get("dong"),
            }
        )
    return pd.DataFrame(rows)


def apply_matches_to_db(matched: pd.DataFrame, min_households: int = MIN_HOUSEHOLDS) -> dict:
    from app.db.migrate import migrate_complex_columns

    migrate_complex_columns()
    session = get_session()
    updated = 0
    skipped = 0
    skipped_small = 0
    renamed = 0
    # 배치 내 단지명 충돌 방지
    reserved_names: set[tuple[str, str, str]] = set()
    try:
        now = datetime.now()
        # 기존 유니크 키 선점
        for existing in session.execute(select(Complex)).scalars():
            reserved_names.add((existing.lawd_cd, existing.dong, existing.complex_name))

        for _, r in matched.iterrows():
            if r.get("match_status") != "matched":
                skipped += 1
                continue
            hh = r.get("reb_households")
            if pd.isna(hh) or int(hh) < min_households:
                skipped_small += 1
                continue
            c = session.get(Complex, int(r["complex_id"]))
            if c is None:
                skipped += 1
                continue

            # 세대수·사용승인일·도로명주소 반영 (+ 단지명은 유니크 가능할 때만)
            reb_name = _clean_str(r.get("reb_name"))
            if reb_name and reb_name != c.complex_name:
                key = (c.lawd_cd, c.dong, reb_name)
                if key not in reserved_names:
                    reserved_names.discard((c.lawd_cd, c.dong, c.complex_name))
                    c.complex_name = reb_name
                    reserved_names.add(key)
                    renamed += 1
            c.total_households = int(hh)
            cy = r.get("reb_completion_year")
            if pd.notna(cy) and cy:
                c.completion_year = int(cy)
            ud = r.get("reb_use_date")
            if pd.notna(ud) and _clean_str(ud):
                c.use_approval_date = str(ud).replace("-", "")[:8]
                if not cy:
                    y = _parse_year(ud)
                    if y:
                        c.completion_year = y
            road = _clean_str(r.get("reb_road"))
            if road:
                c.road_addr = road
            jibun = _clean_str(r.get("reb_jibun"))
            if jibun:
                c.jibun_addr = jibun
            dc = r.get("reb_dong_count")
            if pd.notna(dc):
                c.dong_count = int(dc)
            c.reb_complex_id = _clean_str(r.get("reb_id")) or None
            c.name_normalized = normalize_name(c.complex_name)
            c.enrich_source = "reb_csv"
            c.enrich_score = int(r.get("match_score") or 0)
            c.enriched_at = now
            updated += 1
        session.commit()
        return {
            "updated": updated,
            "renamed": renamed,
            "skipped_unmatched": skipped,
            "skipped_small_hh": skipped_small,
        }
    finally:
        session.close()


def clear_invalid_enrichment(min_households: int = MIN_HOUSEHOLDS) -> dict:
    """이전 오매칭(세대수 50 미만 enrichment) 표시 정리."""
    from app.db.migrate import migrate_complex_columns

    migrate_complex_columns()
    eng = get_engine()
    with eng.begin() as conn:
        # enrichment 되었지만 세대수 미달 → enrichment 플래그 제거 (분석에서 제외되도록)
        result = conn.execute(
            text(
                """
                UPDATE dim_complex
                SET enrich_source = NULL,
                    enrich_score = NULL,
                    reb_complex_id = NULL
                WHERE enrich_source IS NOT NULL
                  AND total_households < :min_hh
                """
            ),
            {"min_hh": min_households},
        )
        cleared = result.rowcount or 0
    return {"cleared_small_enriched": cleared}


def write_match_report(matched: pd.DataFrame) -> Path:
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)
    report = ENRICH_DIR / "match_report.csv"
    matched.to_csv(report, index=False, encoding="utf-8-sig")
    ok = matched[matched["match_status"] == "matched"] if not matched.empty else matched
    hh = pd.to_numeric(ok.get("reb_households"), errors="coerce") if not ok.empty else pd.Series(dtype=float)
    summary = {
        "total": int(len(matched)),
        "matched": int((matched["match_status"] == "matched").sum()) if not matched.empty else 0,
        "unmatched": int((matched["match_status"] == "unmatched").sum()) if not matched.empty else 0,
        "no_region": int((matched["match_status"] == "no_region").sum()) if not matched.empty else 0,
        "matched_hh_ge_50": int((hh >= MIN_HOUSEHOLDS).sum()) if len(hh) else 0,
        "matched_hh_mean": float(hh.mean()) if len(hh) else 0,
    }
    (ENRICH_DIR / "match_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def verify_enrichment(min_households: int = MIN_HOUSEHOLDS) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM dim_complex")).scalar()
        enriched = conn.execute(
            text("SELECT COUNT(*) FROM dim_complex WHERE enrich_source = 'reb_csv'")
        ).scalar()
        hh300 = conn.execute(
            text("SELECT COUNT(*) FROM dim_complex WHERE total_households = 300")
        ).scalar()
        hh_lt50 = conn.execute(
            text("SELECT COUNT(*) FROM dim_complex WHERE total_households < :m"),
            {"m": min_households},
        ).scalar()
        enriched_lt50 = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM dim_complex
                WHERE enrich_source = 'reb_csv' AND total_households < :m
                """
            ),
            {"m": min_households},
        ).scalar()
        stats = conn.execute(
            text(
                """
                SELECT ROUND(AVG(total_households),1), MIN(total_households), MAX(total_households)
                FROM dim_complex WHERE enrich_source = 'reb_csv'
                """
            )
        ).fetchone()
        samples = conn.execute(
            text(
                """
                SELECT complex_name, dong, total_households, use_approval_date, road_addr
                FROM dim_complex
                WHERE enrich_source = 'reb_csv' AND lawd_cd = '11440'
                ORDER BY total_households DESC
                LIMIT 8
                """
            )
        ).fetchall()
    return {
        "total_complexes": int(total or 0),
        "enriched": int(enriched or 0),
        "still_hh_300": int(hh300 or 0),
        "hh_lt_50": int(hh_lt50 or 0),
        "enriched_but_hh_lt_50": int(enriched_lt50 or 0),
        "enriched_hh_avg_min_max": [float(stats[0] or 0), int(stats[1] or 0), int(stats[2] or 0)]
        if stats
        else None,
        "mapo_top8": [list(r) for r in samples],
    }


def reset_stale_enrichment(matched_ids: set[int]) -> dict:
    """이번 매칭에 포함되지 않은 이전 enrichment 를 초기화."""
    from app.db.migrate import migrate_complex_columns

    migrate_complex_columns()
    eng = get_engine()
    with eng.begin() as conn:
        if matched_ids:
            # sqlite 파라미터 한계 대비 청크
            ids = list(matched_ids)
            stale = 0
            # 먼저 모든 enrichment 중 matched 제외분을 찾아 초기화
            rows = conn.execute(
                text("SELECT complex_id FROM dim_complex WHERE enrich_source IS NOT NULL")
            ).fetchall()
            stale_ids = [int(r[0]) for r in rows if int(r[0]) not in matched_ids]
            for i in range(0, len(stale_ids), 500):
                chunk = stale_ids[i : i + 500]
                placeholders = ",".join(str(x) for x in chunk)
                conn.execute(
                    text(
                        f"""
                        UPDATE dim_complex
                        SET enrich_source = NULL,
                            enrich_score = NULL,
                            reb_complex_id = NULL,
                            total_households = 300
                        WHERE complex_id IN ({placeholders})
                        """
                    )
                )
                stale += len(chunk)
        else:
            result = conn.execute(
                text(
                    """
                    UPDATE dim_complex
                    SET enrich_source = NULL,
                        enrich_score = NULL,
                        reb_complex_id = NULL,
                        total_households = 300
                    WHERE enrich_source IS NOT NULL
                    """
                )
            )
            stale = result.rowcount or 0
        # 세대수 50 미만은 분석 제외 대상 — enrichment 잔여 정리
        small = conn.execute(
            text(
                """
                UPDATE dim_complex
                SET enrich_source = NULL,
                    enrich_score = NULL
                WHERE total_households < :m
                """
            ),
            {"m": MIN_HOUSEHOLDS},
        )
    return {"stale_reset": stale, "small_flag_cleared": small.rowcount or 0}


def enrich_from_reb(min_score: int = 85, min_households: int = MIN_HOUSEHOLDS) -> dict:
    reb = load_reb_master(min_households=min_households)
    reb = filter_reb_to_targets(reb)
    db = load_db_complexes()
    matched = match_complexes(db, reb, min_score=min_score)
    report = write_match_report(matched)
    matched_ids = set(
        int(x)
        for x in matched.loc[matched["match_status"] == "matched", "complex_id"].tolist()
    )
    stale = reset_stale_enrichment(matched_ids)
    result = apply_matches_to_db(matched, min_households=min_households)
    result["report"] = str(report)
    result["reb_candidates_hh_ge_50"] = int(len(reb))
    result["db_complexes"] = int(len(db))
    result.update(stale)
    summary = json.loads((ENRICH_DIR / "match_summary.json").read_text(encoding="utf-8"))
    result.update(summary)
    result["verify"] = verify_enrichment(min_households=min_households)
    return result


def try_fetch_kapt_list(sigungu_code: str) -> list[dict]:
    if not MOLIT_API_KEY:
        return []
    url = (
        f"{APT_LIST_URL}?serviceKey={quote(MOLIT_API_KEY, safe='')}"
        f"&sigunguCode={sigungu_code}&pageNo=1&numOfRows=1000"
    )
    try:
        r = requests.get(url, timeout=30)
        data = r.json()
        if "OpenAPI_ServiceResponse" in data:
            return []
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]
        return items or []
    except Exception:  # noqa: BLE001
        return []


def geocode_nominatim(address: str) -> tuple[Optional[float], Optional[float]]:
    if not address:
        return None, None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "ApartTrendLab/0.1 (local research)"},
            timeout=20,
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:  # noqa: BLE001
        return None, None
    return None, None


def enrich_coordinates(limit: int = 50) -> dict:
    import time

    init_db()
    session = get_session()
    updated = 0
    try:
        q = (
            select(Complex)
            .where(Complex.jibun_addr.is_not(None))
            .where(Complex.latitude.is_(None))
            .limit(limit)
        )
        rows = session.execute(q).scalars().all()
        for c in rows:
            lat, lon = geocode_nominatim(c.road_addr or c.jibun_addr or "")
            if lat and lon:
                c.latitude = lat
                c.longitude = lon
                updated += 1
            time.sleep(1.1)
        session.commit()
        return {"geocoded": updated, "tried": len(rows)}
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="단지 마스터 enrichment")
    parser.add_argument("--min-score", type=int, default=85)
    parser.add_argument("--min-households", type=int, default=MIN_HOUSEHOLDS)
    parser.add_argument("--geocode", type=int, default=0)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify_enrichment(args.min_households), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(enrich_from_reb(args.min_score, args.min_households), ensure_ascii=False, indent=2, default=str))
        if args.geocode > 0:
            print(enrich_coordinates(limit=args.geocode))
