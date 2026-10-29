"""국토교통부 아파트 매매 실거래 상세 API 수집."""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests
from sqlalchemy import delete, select

from app.config import (
    DATA_DIR,
    MOLIT_API_KEY,
    MOLIT_TRADE_URL,
    REGION_NAMES,
    REGION_SIDO,
    TARGET_LAWD_CDS,
)
from app.db.schema import Complex, Region, Transaction, get_engine, get_session, init_db
from app.etl.clean import normalize_complex_name


def _text(node: Optional[ET.Element], tag: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else default


def _region_label(lawd_cd: str) -> str:
    return REGION_NAMES.get(lawd_cd, lawd_cd)


def fetch_month(lawd_cd: str, deal_ymd: str, api_key: Optional[str] = None) -> list[dict]:
    """단일 구·월 실거래 조회. deal_ymd=YYYYMM"""
    key = api_key or MOLIT_API_KEY
    if not key or key.startswith("your_"):
        raise ValueError("MOLIT_API_KEY 가 .env 에 설정되어 있지 않습니다.")

    rows: list[dict] = []
    page = 1
    while True:
        # serviceKey는 이미 인코딩된 형태로 붙이고, 나머지는 requests가 인코딩
        query = (
            f"serviceKey={quote(key, safe='')}&LAWD_CD={lawd_cd}"
            f"&DEAL_YMD={deal_ymd}&numOfRows=1000&pageNo={page}"
        )
        url = f"{MOLIT_TRADE_URL}?{query}"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()

        # JSON 오류 응답 대비
        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type or resp.text.strip().startswith("{"):
            payload = resp.json()
            raise RuntimeError(f"API JSON 오류: {payload}")

        root = ET.fromstring(resp.content)
        result_code = _text(root.find(".//header"), "resultCode") or _text(root, "resultCode")
        result_msg = _text(root.find(".//header"), "resultMsg") or _text(root, "resultMsg")
        if result_code and result_code not in ("00", "000", "0"):
            # 데이터 없음
            if result_code in ("03", "INFO-3", "INFO-200"):
                break
            raise RuntimeError(f"API 오류 [{result_code}] {result_msg}")

        items = root.findall(".//item")
        if not items:
            break
        for item in items:
            cancel = _text(item, "cdealDay") or _text(item, "취소일")
            deal_year = _text(item, "dealYear")
            deal_month = _text(item, "dealMonth").zfill(2)
            deal_day = _text(item, "dealDay").zfill(2)
            amount = _text(item, "dealAmount").replace(",", "").replace(" ", "")
            area = _text(item, "excluUseAr") or _text(item, "전용면적")
            floor = _text(item, "floor")
            apt = _text(item, "aptNm") or _text(item, "아파트")
            dong = _text(item, "umdNm") or _text(item, "법정동")
            build_year = _text(item, "buildYear")
            dealing = _text(item, "dealingGbn") or _text(item, "거래유형")
            if not amount or not area or not deal_year:
                continue
            try:
                deal_d = date(int(deal_year), int(deal_month), int(deal_day))
            except ValueError:
                continue
            rows.append(
                {
                    "lawd_cd": lawd_cd,
                    "dong": dong.strip(),
                    "complex_name": apt.strip(),
                    "deal_date": deal_d,
                    "exclusive_area": float(area),
                    "price": int(amount),
                    "floor": int(floor) if floor.lstrip("-").isdigit() else None,
                    "completion_year": int(build_year) if build_year.isdigit() else None,
                    "transaction_type": dealing or "중개거래",
                    "is_cancelled": bool(cancel),
                }
            )
        total_el = root.find(".//totalCount")
        total_count = int(total_el.text) if total_el is not None and total_el.text else len(items)
        if page * 1000 >= total_count:
            break
        page += 1
        time.sleep(0.15)
    return rows


def fetch_range(
    lawd_cds: list[str],
    start_ym: str,
    end_ym: str,
    api_key: Optional[str] = None,
    progress_path: Optional[Path] = None,
    cache_path: Optional[Path] = None,
) -> pd.DataFrame:
    """여러 구·기간 수집. start_ym/end_ym = YYYYMM. 중단 시 이어받기 지원."""
    progress_path = progress_path or (DATA_DIR / "fetch_progress.json")
    cache_csv = cache_path or (DATA_DIR / "fetch_cache.csv")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    cached_rows: list[dict] = []

    if progress_path.exists():
        done = set(json.loads(progress_path.read_text(encoding="utf-8")).get("done", []))
    if cache_csv.exists():
        prev = pd.read_csv(cache_csv, parse_dates=["deal_date"])
        cached_rows = prev.to_dict(orient="records")
        for r in cached_rows:
            if hasattr(r["deal_date"], "date"):
                r["deal_date"] = r["deal_date"].date()
            elif isinstance(r["deal_date"], str):
                r["deal_date"] = date.fromisoformat(r["deal_date"][:10])

    y, m = int(start_ym[:4]), int(start_ym[4:6])
    ey, em = int(end_ym[:4]), int(end_ym[4:6])
    jobs: list[tuple[str, str]] = []
    while (y, m) <= (ey, em):
        ymd = f"{y}{m:02d}"
        for lawd in lawd_cds:
            jobs.append((lawd, ymd))
        m += 1
        if m > 12:
            m = 1
            y += 1

    all_rows = list(cached_rows)
    total = len(jobs)
    for idx, (lawd, ymd) in enumerate(jobs, start=1):
        key = f"{lawd}:{ymd}"
        if key in done:
            continue
        try:
            batch = fetch_month(lawd, ymd, api_key=api_key)
            all_rows.extend(batch)
            done.add(key)
            print(f"[{idx}/{total}] {_region_label(lawd)} {ymd}: {len(batch)}건")
            # 주기적 체크포인트
            if idx % 10 == 0:
                progress_path.write_text(
                    json.dumps({"done": sorted(done)}, ensure_ascii=False),
                    encoding="utf-8",
                )
                pd.DataFrame(all_rows).to_csv(cache_csv, index=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] {_region_label(lawd)} {ymd}: {exc}")
            time.sleep(1.0)
        time.sleep(0.2)

    progress_path.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False), encoding="utf-8")
    if all_rows:
        pd.DataFrame(all_rows).to_csv(cache_csv, index=False)
    out = pd.DataFrame(all_rows)
    # 요청한 법정동만 반환(공유 캐시에 다른 구가 있어도 적재 범위 제한)
    if not out.empty and "lawd_cd" in out.columns:
        want = {str(x) for x in lawd_cds}
        out = out[out["lawd_cd"].astype(str).isin(want)].copy()
    return out


def clear_db() -> None:
    init_db()
    session = get_session()
    try:
        session.execute(delete(Transaction))
        session.execute(delete(Complex))
        session.execute(delete(Region))
        session.commit()
    finally:
        session.close()


def load_dataframe_to_db(df: pd.DataFrame, default_households: int = 300, replace: bool = False) -> dict:
    """수집 DataFrame → DB 적재."""
    if df.empty:
        return {"status": "empty", "transactions": 0}

    if replace:
        clear_db()

    init_db()
    session = get_session()
    inserted = 0
    try:
        for lawd_cd in df["lawd_cd"].astype(str).unique():
            if session.get(Region, lawd_cd) is None:
                session.add(
                    Region(
                        lawd_cd=lawd_cd,
                        sido=REGION_SIDO.get(lawd_cd, "기타"),
                        sigungu=REGION_NAMES.get(lawd_cd, lawd_cd),
                        dong="",
                    )
                )
        session.flush()

        # 세대수: 단지별 거래 건수 기반 추정 (최소 default)
        household_est = (
            df.groupby(["complex_name", "lawd_cd", "dong"])
            .size()
            .mul(8)
            .clip(lower=default_households, upper=5000)
            .to_dict()
        )

        complex_cache: dict[tuple, int] = {}
        tx_bulk: list[Transaction] = []

        for _, r in df.iterrows():
            if r.get("is_cancelled"):
                continue
            dong = str(r["dong"]).strip()
            name = str(r["complex_name"]).strip()
            lawd = str(r["lawd_cd"])
            key = (normalize_complex_name(name), lawd, dong)
            if key not in complex_cache:
                existing = session.execute(
                    select(Complex).where(
                        Complex.complex_name == name,
                        Complex.lawd_cd == lawd,
                        Complex.dong == dong,
                    )
                ).scalar_one_or_none()
                if existing:
                    complex_cache[key] = existing.complex_id
                else:
                    cy = r.get("completion_year") or 2000
                    hh = int(household_est.get((name, lawd, dong), default_households))
                    c = Complex(
                        complex_name=name,
                        lawd_cd=lawd,
                        dong=dong,
                        total_households=hh,
                        completion_year=int(cy) if pd.notna(cy) else 2000,
                    )
                    session.add(c)
                    session.flush()
                    complex_cache[key] = c.complex_id

            deal_date = r["deal_date"]
            if isinstance(deal_date, str):
                deal_date = date.fromisoformat(deal_date[:10])
            elif hasattr(deal_date, "date"):
                deal_date = deal_date.date()

            tx_bulk.append(
                Transaction(
                    complex_id=complex_cache[key],
                    deal_date=deal_date,
                    exclusive_area=float(r["exclusive_area"]),
                    price=int(r["price"]),
                    floor=None if pd.isna(r.get("floor")) else int(r["floor"]),
                    transaction_type=r.get("transaction_type") or "중개거래",
                    is_cancelled=False,
                )
            )
            inserted += 1
            if len(tx_bulk) >= 2000:
                session.add_all(tx_bulk)
                session.commit()
                tx_bulk = []

        if tx_bulk:
            session.add_all(tx_bulk)
            session.commit()
        return {"status": "ok", "transactions": inserted, "complexes": len(complex_cache)}
    finally:
        session.close()


def _lawd_cds_in_db() -> set[str]:
    init_db()
    session = get_session()
    try:
        rows = session.execute(select(Region.lawd_cd)).scalars().all()
        return {str(x) for x in rows}
    finally:
        session.close()


def collect_targets(
    start_ym: str = "201901",
    end_ym: Optional[str] = None,
    replace: bool = False,
) -> dict:
    """요청 대상 지역 일괄 수집 후 DB 적재. 기본은 기존 데이터 유지(append)."""
    if end_ym is None:
        today = date.today()
        end_ym = f"{today.year}{today.month:02d}"
    print(f"수집 시작: {len(TARGET_LAWD_CDS)}개 지역, {start_ym}~{end_ym}")
    frame = fetch_range(TARGET_LAWD_CDS, start_ym, end_ym)
    # 취소 건 제외
    if not frame.empty and "is_cancelled" in frame.columns:
        frame = frame[~frame["is_cancelled"].fillna(False)].copy()
    result = load_dataframe_to_db(frame, replace=replace)
    print(result)
    return result


def collect_missing(
    start_ym: str = "201901",
    end_ym: Optional[str] = None,
    lawd_cds: Optional[list[str]] = None,
) -> dict:
    """TARGET 중 DB에 없는 시군구만 수집·적재 (기존 구는 유지)."""
    from app.analysis.trends import invalidate_tx_cache

    if end_ym is None:
        today = date.today()
        end_ym = f"{today.year}{today.month:02d}"
    want = [str(x) for x in (lawd_cds or TARGET_LAWD_CDS)]
    have = _lawd_cds_in_db()
    missing = [c for c in want if c not in have]
    if not missing:
        print("미수집 지역 없음 — 모두 DB에 있습니다.")
        return {"status": "ok", "missing": 0, "transactions": 0}

    labels = ", ".join(REGION_NAMES.get(c, c) for c in missing[:12])
    more = f" 외 {len(missing) - 12}곳" if len(missing) > 12 else ""
    print(f"미수집 {len(missing)}곳 수집: {labels}{more} · {start_ym}~{end_ym}")

    progress = DATA_DIR / "fetch_progress_missing.json"
    cache_csv = DATA_DIR / "fetch_cache_missing.csv"
    total_tx = 0
    loaded_regions = 0
    for i, lawd in enumerate(missing, start=1):
        label = REGION_NAMES.get(lawd, lawd)
        print(f"=== [{i}/{len(missing)}] {label} ({lawd}) ===")
        frame = fetch_range(
            [lawd],
            start_ym,
            end_ym,
            progress_path=progress,
            cache_path=cache_csv,
        )
        if frame.empty:
            print(f"{label}: 수집 0건")
            continue
        if "is_cancelled" in frame.columns:
            frame = frame[~frame["is_cancelled"].fillna(False)].copy()
        # 해당 구만 적재 (캐시에 이전 구가 남아 있어도 필터)
        frame = frame[frame["lawd_cd"].astype(str) == str(lawd)].copy()
        result = load_dataframe_to_db(frame, replace=False)
        n = int(result.get("transactions", 0))
        total_tx += n
        loaded_regions += 1
        print(f"{label} 적재: {result}")
        invalidate_tx_cache()

    out = {
        "status": "ok",
        "missing": len(missing),
        "loaded_regions": loaded_regions,
        "transactions": total_tx,
    }
    print(out)
    return out


def _shift_ym(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def fetch_recent_months(
    lawd_cds: list[str],
    months_back: int = 2,
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """최근 N+1개월(이번 달 포함)을 캐시 무시하고 새로 조회."""
    today = date.today()
    rows: list[dict] = []
    errors: list[str] = []
    for back in range(months_back, -1, -1):
        y, m = _shift_ym(today.year, today.month, -back)
        ymd = f"{y}{m:02d}"
        for lawd in lawd_cds:
            try:
                batch = fetch_month(lawd, ymd, api_key=api_key)
                rows.extend(batch)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{_region_label(lawd)} {ymd}: {exc}")
            time.sleep(0.12)
    out = pd.DataFrame(rows)
    out.attrs["fetch_errors"] = errors
    return out


def _tx_stats(since: Optional[date] = None) -> dict:
    """DB 거래 건수·최근 계약일. since가 있으면 해당일 이후만."""
    from sqlalchemy import func as sa_func

    init_db()
    session = get_session()
    try:
        filters = [Transaction.is_cancelled.is_(False)]
        if since is not None:
            filters.append(Transaction.deal_date >= since)
        cnt = session.execute(
            select(sa_func.count()).select_from(Transaction).where(*filters)
        ).scalar_one()
        max_d = session.execute(
            select(sa_func.max(Transaction.deal_date)).where(*filters)
        ).scalar_one()
        return {"count": int(cnt or 0), "max_date": max_d}
    finally:
        session.close()


def _delete_tx_since(since: date, lawd_cds: list[str]) -> int:
    """대상 지역의 since 이후 거래를 삭제(재적재 준비)."""
    init_db()
    session = get_session()
    try:
        cids = session.execute(
            select(Complex.complex_id).where(Complex.lawd_cd.in_([str(x) for x in lawd_cds]))
        ).scalars().all()
        if not cids:
            return 0
        doomed = session.execute(
            select(Transaction.transaction_id).where(
                Transaction.complex_id.in_(list(cids)),
                Transaction.deal_date >= since,
            )
        ).scalars().all()
        n = len(doomed)
        if n:
            session.execute(
                delete(Transaction).where(Transaction.transaction_id.in_(list(doomed)))
            )
            session.commit()
        return n
    finally:
        session.close()


def refresh_recent_trades(
    months_back: Optional[int] = None,
    lawd_cds: Optional[list[str]] = None,
) -> dict:
    """최근 실거래 신규 여부 확인 후 DB 반영.

    - 국토부 API에서 최근 months_back+1개월 재조회
    - 워터마크(data/fetch_meta.json)가 있으면 그 이후 월만 조회(최대 months_back 기본 2)
    - 동일 기간 DB 거래 삭제 후 재적재(중복 방지)
    - 신규/변동 요약 반환 + fetch_meta 워터마크 갱신
    """
    from app.analysis.trends import invalidate_tx_cache
    from app.fetch_meta import (
        load_fetch_meta,
        months_back_from_watermark,
        update_after_refresh,
    )

    today = date.today()
    if months_back is None:
        months_back = months_back_from_watermark(default=2)
    targets = list(lawd_cds) if lawd_cds else list(TARGET_LAWD_CDS)

    start_y, start_m = _shift_ym(today.year, today.month, -months_back)
    since = date(start_y, start_m, 1)
    start_ym = f"{start_y}{start_m:02d}"
    end_ym = f"{today.year}{today.month:02d}"
    prev_meta = load_fetch_meta()

    if not MOLIT_API_KEY or str(MOLIT_API_KEY).startswith("your_"):
        return {
            "status": "error",
            "message": "MOLIT_API_KEY 가 .env 에 없습니다. 공공데이터포털 인증키를 설정하세요.",
            "checked_at": today.isoformat(),
            "period": f"{start_ym}~{end_ym}",
            "watermark_ym": prev_meta.get("watermark_ym"),
            "last_refresh_at": prev_meta.get("last_refresh_at"),
        }

    before_win = _tx_stats(since)
    before_all = _tx_stats(None)

    try:
        frame = fetch_recent_months(targets, months_back=months_back)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"API 조회 실패: {exc}",
            "checked_at": today.isoformat(),
            "period": f"{start_ym}~{end_ym}",
            "watermark_ym": prev_meta.get("watermark_ym"),
        }

    fetch_errors = list(getattr(frame, "attrs", {}).get("fetch_errors", []) or [])
    if not frame.empty and "is_cancelled" in frame.columns:
        frame = frame[~frame["is_cancelled"].fillna(False)].copy()

    api_count = int(len(frame))
    api_max = None
    if not frame.empty and "deal_date" in frame.columns:
        api_max = pd.to_datetime(frame["deal_date"]).max()
        if pd.notna(api_max):
            api_max = api_max.date() if hasattr(api_max, "date") else api_max

    deleted = _delete_tx_since(since, targets)
    loaded = (
        load_dataframe_to_db(frame, replace=False)
        if not frame.empty
        else {"status": "empty", "transactions": 0}
    )

    after_win = _tx_stats(since)
    after_all = _tx_stats(None)

    delta_window = int(after_win["count"]) - int(before_win["count"])
    by_gu: dict[str, int] = {}
    if not frame.empty and "lawd_cd" in frame.columns:
        for lawd, n in frame.groupby("lawd_cd").size().items():
            by_gu[_region_label(str(lawd))] = int(n)

    before_global_max = before_all["max_date"]
    after_global_max = after_all["max_date"]
    has_new = (
        delta_window != 0
        or (
            api_max is not None
            and before_global_max is not None
            and api_max > before_global_max
        )
        or (before_global_max is None and api_count > 0)
    )

    result = {
        "status": "ok",
        "message": "신규·변동 실거래가 반영되었습니다." if has_new else "조회 구간에서 신규 실거래가 없거나 동일합니다.",
        "has_new": bool(has_new),
        "checked_at": today.isoformat(),
        "period": f"{start_ym}~{end_ym}",
        "months_back": months_back,
        "api_rows": api_count,
        "api_max_date": api_max.isoformat() if api_max else None,
        "before_window": int(before_win["count"]),
        "after_window": int(after_win["count"]),
        "delta_window": delta_window,
        "deleted": int(deleted),
        "loaded": int(loaded.get("transactions", 0)),
        "before_total": int(before_all["count"]),
        "after_total": int(after_all["count"]),
        "before_max_date": before_global_max.isoformat() if before_global_max else None,
        "after_max_date": after_global_max.isoformat() if after_global_max else None,
        "by_gu": by_gu,
        "fetch_errors": fetch_errors[:12],
        "regions": len(targets),
        "prev_watermark_ym": prev_meta.get("watermark_ym"),
    }
    meta = update_after_refresh(result)
    result["watermark_ym"] = meta.get("watermark_ym")
    result["last_refresh_at"] = meta.get("last_refresh_at")
    invalidate_tx_cache()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MOLIT 실거래 수집")
    parser.add_argument("--gu", default="", help="법정동코드(구), 쉼표구분. 비우면 TARGET 전체")
    parser.add_argument("--start", default="201901", help="시작 YYYYMM")
    parser.add_argument("--end", default="", help="종료 YYYYMM (기본: 이번 달)")
    parser.add_argument("--replace", action="store_true", help="기존 DB 비우고 재적재")
    parser.add_argument("--targets", action="store_true", help="요청 대상 지역 전체 수집")
    parser.add_argument("--missing", action="store_true", help="DB에 없는 TARGET 시군구만 수집")
    args = parser.parse_args()

    end = args.end or f"{date.today().year}{date.today().month:02d}"
    if args.missing:
        collect_missing(start_ym=args.start, end_ym=end)
    elif args.targets or not args.gu:
        collect_targets(start_ym=args.start, end_ym=end, replace=bool(args.replace))
    else:
        codes = [c.strip() for c in args.gu.split(",") if c.strip()]
        frame = fetch_range(codes, args.start, end)
        print(load_dataframe_to_db(frame, replace=bool(args.replace)))
