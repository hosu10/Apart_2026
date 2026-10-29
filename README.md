# 아파트 실거래 비교 분석

서울·경기 아파트 실거래가를 조건별로 비교·분석하는 Streamlit 웹앱입니다.

**수집 지역**: 마포·종로·중구·용산·서대문·은평·동작·영등포·양천·강서·구로 / 고양(덕양·일산동·일산서) / 김포

## 주요 기능

- **대상 선정**: 지역(구/동), 전용면적, 연식, 세대수 범위
- **제외 조건**: 최소 연한, 최소 거래건수, 직거래, IQR 이상치
- **관심 단지 1개**: 전체/비교 화면에서 빨간색 강조, 비교 1번 창 고정
- **전체 서열 분석**: 상승률 순위(10개 단위), 세대수·준공연도·시작가 대비 상승률
- **비교 분석**: 최대 4창, 화면 유형 10종(매매/추정전세 추이, 단지정보, 지도 등)

## 빠른 시작

```powershell
cd D:\Pyhome\Apart
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.etl.seed_sample
streamlit run streamlit_app.py
```

브라우저에서 `http://localhost:8501` 로 접속합니다.

## 샘플 데이터

API 키 없이도 마포구 가상 실거래 샘플로 UI·분석을 바로 확인할 수 있습니다.
사이드바 **데이터 관리 → 샘플 데이터 재생성**으로 다시 만들 수 있습니다.

## 국토부 실거래 API 연동 (선택)

1. [공공데이터포털](https://www.data.go.kr)에서  
   `국토교통부_아파트 매매 실거래가 상세 자료` 활용신청 후 인증키 발급
2. `.env.example`을 복사해 `.env` 작성:

```env
MOLIT_API_KEY=발급받은_서비스키
```

3. 수집 실행 예:

```powershell
python -m app.etl.fetch_molit --gu 11440 --start 201901 --end 202512
```

## 단지 마스터 Enrichment (세대수·준공·주소)

실거래 API만으로는 세대수 등이 부정확하므로, **한국부동산원 공동주택 단지 식별정보 CSV**와 퍼지 매칭으로 `dim_complex`를 보강합니다.

1. [한국부동산원_공동주택 단지 식별정보_기본정보](https://www.data.go.kr/data/15106861/fileData.do) CSV 다운로드  
2. `data/enrich/reb_complex_master.csv` 로 저장  
3. 실행:

```powershell
python -m app.db.migrate
python -m app.etl.enrich_complex --min-score 85
```

- 매칭 리포트: `data/enrich/match_report.csv`
- 보강 필드: 세대수, 동수, 사용승인일/준공연도, 지번·도로명 주소, 매칭점수
- (선택) K-APT OpenAPI·브이월드 지오코딩은 별도 활용신청 키가 필요합니다.

## 프로젝트 구조

```
Apart/
  streamlit_app.py      # 웹 UI 진입점
  app/
    config.py
    db/schema.py        # 단지 마스터(+enrichment 컬럼)
    etl/                # 실거래 수집 / REB 매칭 enrichment
    analysis/           # 선정·제외·상승률
    ui/                 # 전체/비교 차트
  data/apart.db
  data/enrich/          # REB CSV, 매칭 리포트
  venv/
```

## 분석 로직 요약

1. 대상 선정(구·동·면적·연식·세대수) → 제외(연한·거래건수·직거래·이상치)
2. 단지별 초반/최근 평균가로 상승률·CAGR
3. 동·구 집계 시 `total_households`(enrichment 세대수) 가중평균
