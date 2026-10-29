"""마포구 샘플 실거래 데이터 생성 (API 키 없이 데모용)."""

from __future__ import annotations

import random
from datetime import date

from app.db.schema import Complex, Region, Transaction, get_session, init_db

# 마포구 대표 단지 (준공연도, 세대수, 동, 기준가 만원/30평형대)
MAPO_COMPLEXES = [
    ("마포래미안푸르지오", 2014, 3885, "아현동", 145000),
    ("공덕자이", 2011, 1730, "공덕동", 138000),
    ("래미안공덕5차", 2015, 712, "공덕동", 142000),
    ("마포한강자이", 2010, 680, "합정동", 155000),
    ("메세나폴리스", 2012, 670, "합정동", 168000),
    ("마포자이2차", 2013, 548, "도화동", 125000),
    ("래미안마포리버웰", 2016, 956, "용강동", 148000),
    ("대흥동태영아파트", 1999, 498, "대흥동", 98000),
    ("신촌그랑자이", 2017, 1294, "노고산동", 152000),
    ("상암월드컵파크2단지", 2005, 1486, "상암동", 105000),
    ("상암월드컵파크7단지", 2006, 1628, "상암동", 108000),
    ("상암카카오그린", 2022, 420, "상암동", 135000),  # 신축 7년 미만 → 필터 제외 대상
    ("염리삼성래미안", 2003, 1204, "염리동", 112000),
    ("마포경남아너스빌", 2004, 356, "창전동", 95000),
    ("한화오벨리스크", 2004, 612, "서교동", 118000),
    ("성산시영아파트", 1986, 3600, "성산동", 78000),
    ("성산대림아파트", 1995, 892, "성산동", 88000),
    ("망원동두산위브", 2005, 310, "망원동", 92000),
    ("망원한강2차현대", 2001, 278, "망원동", 102000),
    ("신공덕경남아너스빌", 2004, 486, "신공덕동", 110000),
]

SIZE_SPECS = [
    ("20평형대", 59.9, 0.72),
    ("30평형대", 84.9, 1.00),
    ("40평형대", 114.5, 1.35),
]

# 단지별 연평균 성장률 시드 (7년 누적 차별화)
GROWTH_SEEDS = {
    "마포래미안푸르지오": 0.045,
    "공덕자이": 0.038,
    "래미안공덕5차": 0.042,
    "마포한강자이": 0.052,
    "메세나폴리스": 0.048,
    "마포자이2차": 0.033,
    "래미안마포리버웰": 0.050,
    "대흥동태영아파트": 0.028,
    "신촌그랑자이": 0.041,
    "상암월드컵파크2단지": 0.035,
    "상암월드컵파크7단지": 0.036,
    "상암카카오그린": 0.055,
    "염리삼성래미안": 0.031,
    "마포경남아너스빌": 0.025,
    "한화오벨리스크": 0.040,
    "성산시영아파트": 0.022,
    "성산대림아파트": 0.027,
    "망원동두산위브": 0.034,
    "망원한강2차현대": 0.039,
    "신공덕경남아너스빌": 0.032,
}


def _ensure_mapo_region(session) -> None:
    row = session.get(Region, "11440")
    if row is None:
        session.add(
            Region(lawd_cd="11440", sido="서울특별시", sigungu="마포구", dong="공덕동")
        )
        session.flush()


def seed_sample_data(years: int = 7, seed: int = 42, force: bool = False) -> dict:
    """샘플 거래 데이터를 DB에 적재."""
    random.seed(seed)
    init_db()
    session = get_session()
    try:
        existing = session.query(Transaction).count()
        if existing > 0 and not force:
            return {"status": "skipped", "transactions": existing}

        if force:
            session.query(Transaction).delete()
            session.query(Complex).delete()
            session.commit()

        _ensure_mapo_region(session)

        complex_ids: dict[str, int] = {}
        for name, year, hh, dong, _base in MAPO_COMPLEXES:
            c = Complex(
                complex_name=name,
                lawd_cd="11440",
                dong=dong,
                total_households=hh,
                completion_year=year,
            )
            session.add(c)
            session.flush()
            complex_ids[name] = c.complex_id

        today = date.today()
        start = date(today.year - years, 1, 1)
        rows: list[Transaction] = []

        for name, year, hh, dong, base_price in MAPO_COMPLEXES:
            annual = GROWTH_SEEDS.get(name, 0.03)
            cid = complex_ids[name]
            # 세대수에 비례해 거래 빈도 조정
            deals_per_year = max(4, min(28, hh // 80))

            for size_label, area, price_mult in SIZE_SPECS:
                # 상암카카오그린 20평형은 거래 적게 → 최소거래 필터 테스트
                local_deals = deals_per_year
                if name == "상암카카오그린" and size_label == "20평형대":
                    local_deals = 1
                if name == "마포경남아너스빌" and size_label == "40평형대":
                    local_deals = 1

                cursor = start
                while cursor < today:
                    year_idx = cursor.year - start.year
                    trend = (1 + annual) ** year_idx
                    # 연도 내 계절성·노이즈
                    for _ in range(local_deals):
                        month = random.randint(1, 12)
                        day = random.randint(1, 28)
                        deal_d = date(cursor.year, month, day)
                        if deal_d < start or deal_d > today:
                            continue
                        noise = random.uniform(0.92, 1.08)
                        floor = random.randint(1, 25)
                        floor_adj = 1.0 + (floor - 10) * 0.004
                        price = int(base_price * price_mult * trend * noise * floor_adj)
                        # 간헐적 직거래 저가 (이상치)
                        tx_type = "중개거래"
                        if random.random() < 0.03:
                            price = int(price * 0.7)
                            tx_type = "직거래"
                        rows.append(
                            Transaction(
                                complex_id=cid,
                                deal_date=deal_d,
                                exclusive_area=area + random.uniform(-0.5, 0.5),
                                price=price,
                                floor=floor,
                                transaction_type=tx_type,
                                is_cancelled=False,
                            )
                        )
                    cursor = date(cursor.year + 1, 1, 1)

        session.add_all(rows)
        session.commit()
        return {
            "status": "ok",
            "complexes": len(complex_ids),
            "transactions": len(rows),
        }
    finally:
        session.close()


if __name__ == "__main__":
    result = seed_sample_data(force=True)
    print(result)
