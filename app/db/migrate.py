"""SQLite 스키마 확장 (단지 마스터 enrichment 컬럼)."""

from __future__ import annotations

from sqlalchemy import text

from app.db.schema import get_engine

COMPLEX_COLUMNS = {
    "kapt_code": "VARCHAR(20)",
    "reb_complex_id": "VARCHAR(30)",
    "jibun_addr": "VARCHAR(200)",
    "road_addr": "VARCHAR(200)",
    "dong_count": "INTEGER",
    "parking_total": "INTEGER",
    "heating_type": "VARCHAR(50)",
    "corridor_type": "VARCHAR(50)",
    "builder": "VARCHAR(100)",
    "use_approval_date": "VARCHAR(8)",
    "name_normalized": "VARCHAR(100)",
    "enrich_source": "VARCHAR(40)",
    "enrich_score": "INTEGER",
    "enriched_at": "DATETIME",
}


def migrate_complex_columns() -> list[str]:
    engine = get_engine()
    # create_all만 수행 (init_db는 migrate를 다시 호출하므로 순환 방지)
    from app.db.schema import Base

    Base.metadata.create_all(engine)
    added: list[str] = []
    with engine.begin() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('dim_complex')")).fetchall()
        }
        for col, typedef in COMPLEX_COLUMNS.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE dim_complex ADD COLUMN {col} {typedef}"))
                added.append(col)
    return added


if __name__ == "__main__":
    print({"added": migrate_complex_columns()})
