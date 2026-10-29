from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from app.config import DATA_DIR, DATABASE_URL


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "dim_region"

    lawd_cd = Column(String(5), primary_key=True)
    sido = Column(String(20), nullable=False, default="서울특별시")
    sigungu = Column(String(30), nullable=False)
    dong = Column(String(30), nullable=False)

    complexes = relationship("Complex", back_populates="region")


class Complex(Base):
    __tablename__ = "dim_complex"
    __table_args__ = (
        UniqueConstraint("complex_name", "lawd_cd", "dong", name="uq_complex_loc"),
    )

    complex_id = Column(Integer, primary_key=True, autoincrement=True)
    complex_name = Column(String(100), nullable=False)
    lawd_cd = Column(String(5), ForeignKey("dim_region.lawd_cd"), nullable=False)
    dong = Column(String(30), nullable=False)
    total_households = Column(Integer, nullable=False, default=0)
    completion_year = Column(Integer, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # enrichment
    kapt_code = Column(String(20), nullable=True)
    reb_complex_id = Column(String(30), nullable=True)
    jibun_addr = Column(String(200), nullable=True)
    road_addr = Column(String(200), nullable=True)
    dong_count = Column(Integer, nullable=True)
    parking_total = Column(Integer, nullable=True)
    heating_type = Column(String(50), nullable=True)
    corridor_type = Column(String(50), nullable=True)
    builder = Column(String(100), nullable=True)
    use_approval_date = Column(String(8), nullable=True)
    name_normalized = Column(String(100), nullable=True)
    enrich_source = Column(String(40), nullable=True)
    enrich_score = Column(Integer, nullable=True)
    enriched_at = Column(DateTime, nullable=True)

    region = relationship("Region", back_populates="complexes")
    transactions = relationship("Transaction", back_populates="complex")


class Transaction(Base):
    __tablename__ = "fact_transaction"

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    complex_id = Column(Integer, ForeignKey("dim_complex.complex_id"), nullable=False)
    deal_date = Column(Date, nullable=False)
    exclusive_area = Column(Float, nullable=False)
    price = Column(Integer, nullable=False)  # 만원
    floor = Column(Integer, nullable=True)
    transaction_type = Column(String(10), nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    complex = relationship("Complex", back_populates="transactions")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(DATABASE_URL, echo=False)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    # 기존 DB 호환: enrichment 컬럼 추가
    from app.db.migrate import migrate_complex_columns

    migrate_complex_columns()
