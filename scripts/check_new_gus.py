from sqlalchemy import text
from app.db.schema import get_engine

e = get_engine()
with e.connect() as c:
    rows = c.execute(
        text(
            """
            SELECT r.sigungu,
                   COUNT(*) AS complexes,
                   SUM(CASE WHEN c.enrich_source='reb_csv' THEN 1 ELSE 0 END) AS enriched,
                   SUM(CASE WHEN c.geocode_source LIKE 'nominatim%' OR c.geocode_source LIKE 'cache%' THEN 1 ELSE 0 END) AS addr_geo,
                   SUM(CASE WHEN c.geocode_source='dong_fallback' THEN 1 ELSE 0 END) AS dong_geo
            FROM dim_region r
            JOIN dim_complex c ON c.lawd_cd=r.lawd_cd
            WHERE r.sigungu IN ('성동구','서초구','강남구','송파구','강동구','마포구')
            GROUP BY r.sigungu
            ORDER BY r.sigungu
            """
        )
    ).fetchall()
    print("complexes / enriched / addr_geocode / dong_fallback")
    for r in rows:
        print(dict(r._mapping))

    txs = c.execute(
        text(
            """
            SELECT r.sigungu, COUNT(*) AS txs
            FROM fact_transaction t
            JOIN dim_complex c ON t.complex_id=c.complex_id
            JOIN dim_region r ON c.lawd_cd=r.lawd_cd
            WHERE r.sigungu IN ('성동구','서초구','강남구','송파구','강동구')
            GROUP BY r.sigungu
            ORDER BY r.sigungu
            """
        )
    ).fetchall()
    print("transactions:")
    for r in txs:
        print(dict(r._mapping))
