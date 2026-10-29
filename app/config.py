from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "apart.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# URL인코딩된 키가 들어와도 디코딩해서 사용 (requests가 재인코딩)
_raw_key = os.getenv("MOLIT_API_KEY", "")
MOLIT_API_KEY = unquote(_raw_key.strip()) if _raw_key else ""
MOLIT_TRADE_URL = (
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
)

# 서울 25개 구 법정동코드 (시군구 5자리)
SEOUL_GU = {
    "11110": "종로구",
    "11140": "중구",
    "11170": "용산구",
    "11200": "성동구",
    "11215": "광진구",
    "11230": "동대문구",
    "11260": "중랑구",
    "11290": "성북구",
    "11305": "강북구",
    "11320": "도봉구",
    "11350": "노원구",
    "11380": "은평구",
    "11410": "서대문구",
    "11440": "마포구",
    "11470": "양천구",
    "11500": "강서구",
    "11530": "구로구",
    "11545": "금천구",
    "11560": "영등포구",
    "11590": "동작구",
    "11620": "관악구",
    "11650": "서초구",
    "11680": "강남구",
    "11710": "송파구",
    "11740": "강동구",
}

# 경기도 (시·구 단위 LAWD_CD) — MOLIT 실거래 API 시군구 코드
GYEONGGI_GU = {
    "41111": "수원시 장안구",
    "41113": "수원시 권선구",
    "41115": "수원시 팔달구",
    "41117": "수원시 영통구",
    "41131": "성남시 수정구",
    "41133": "성남시 중원구",
    "41135": "성남시 분당구",
    "41150": "의정부시",
    "41171": "안양시 만안구",
    "41173": "안양시 동안구",
    # 부천: 2024 구 부활 이후 법정동코드 (구코드 41195/97/99 는 API 0건)
    "41192": "부천시 원미구",
    "41194": "부천시 소사구",
    "41196": "부천시 오정구",
    "41210": "광명시",
    "41220": "평택시",
    "41250": "동두천시",
    "41271": "안산시 상록구",
    "41273": "안산시 단원구",
    "41281": "고양시 덕양구",
    "41285": "고양시 일산동구",
    "41287": "고양시 일산서구",
    "41290": "과천시",
    "41310": "구리시",
    "41360": "남양주시",
    "41370": "오산시",
    "41390": "시흥시",
    "41410": "군포시",
    "41430": "의왕시",
    "41450": "하남시",
    "41461": "용인시 처인구",
    "41463": "용인시 기흥구",
    "41465": "용인시 수지구",
    "41480": "파주시",
    "41500": "이천시",
    "41550": "안성시",
    "41570": "김포시",
    "41590": "화성시",
    "41610": "광주시",
    "41630": "양주시",
    "41650": "포천시",
    "41670": "여주시",
    "41800": "연천군",
    "41820": "가평군",
    "41830": "양평군",
}

REGION_NAMES = {**SEOUL_GU, **GYEONGGI_GU}

REGION_SIDO = {
    **{code: "서울특별시" for code in SEOUL_GU},
    **{code: "경기도" for code in GYEONGGI_GU},
}

# 수집·분석 시도 라벨 (UI 선택값 → DB sido)
ANALYSIS_REGION_LABELS = ("서울", "경기도")
ANALYSIS_REGION_TO_SIDO = {
    "서울": "서울특별시",
    "경기도": "경기도",
}
DEFAULT_ANALYSIS_REGION = "서울"

# 시도별 법정동코드 = 전 지역 (서울 25구 · 경기 시군구 전체)
SEOUL_TARGET_LAWD_CDS = list(SEOUL_GU.keys())
GYEONGGI_TARGET_LAWD_CDS = list(GYEONGGI_GU.keys())

# 수집·갱신 대상 전체
TARGET_LAWD_CDS = [*SEOUL_TARGET_LAWD_CDS, *GYEONGGI_TARGET_LAWD_CDS]

REGION_LAWD_BY_LABEL = {
    "서울": SEOUL_TARGET_LAWD_CDS,
    "경기도": GYEONGGI_TARGET_LAWD_CDS,
}

# 전용면적(㎡) 기준 평형대
SIZE_TIERS = {
    "20평형대": (50.0, 70.0),
    "30평형대": (70.0, 95.0),
    "40평형대": (95.0, 125.0),
    "50평형대+": (125.0, 999.0),
}

# UI 테이블 컬럼 한글명
COLUMN_LABELS_KO = {
    "rank": "순위",
    "complex_name": "단지명",
    "dong": "법정동",
    "completion_year": "준공연도",
    "total_households": "단지전체세대수",
    "tx_count": "거래건수",
    "start_price": "초반평균가",
    "end_price": "최근평균가",
    "price_change_pct": "상승률(%)",
    "cagr_pct": "연평균상승률(%)",
    "growth_per_100hh": "세대100당상승률",
    "weighted_start_price": "가중초반평균가",
    "weighted_end_price": "가중최근평균가",
    "weighted_avg_ppp": "가중평균평당가",
    "complex_count": "단지수",
    "sigungu": "시군구",
    "deal_date": "계약일",
    "exclusive_area": "전용면적(㎡)",
    "size_tier": "평형대",
    "floor": "층",
    "price": "거래금액(만원)",
    "price_per_pyeong": "평당가(만원)",
    "transaction_type": "거래유형",
    "sido": "시도",
    "period": "분기",
    "avg_price": "평균거래가(만원)",
    "avg_ppp": "평균평당가(만원)",
    "avg_area": "평균전용면적",
}

ENTITY_LABELS_KO = {
    "complex_name": "단지",
    "dong": "법정동",
    "sigungu": "시군구",
    "size_tier": "평형대",
}

DEFAULT_MIN_AGE_YEARS = 5
DEFAULT_MIN_TRANSACTIONS = 5
DEFAULT_LOOKBACK_YEARS = 7

# 선정 조건 기본값 (사이드바)
DEFAULT_AGE_MIN = 5
DEFAULT_AGE_MAX = 25
DEFAULT_HOUSEHOLDS_MIN = 300
DEFAULT_HOUSEHOLDS_MAX = 5000
DEFAULT_SIZE_TIER = "30평형대"
DEFAULT_SIGUNGU = "마포구"

# 기본 관심단지: 마포구 아현동 마포센트럴 아이파크
DEFAULT_INTEREST_COMPLEX_ID = 2121
DEFAULT_INTEREST_LABEL = "마포구 아현동 마포센트럴 아이파크"

# UI·캐시 경로
USER_PREFS_PATH = DATA_DIR / "user_prefs.json"
FETCH_META_PATH = DATA_DIR / "fetch_meta.json"
TX_CACHE_DIR = DATA_DIR / "cache"
