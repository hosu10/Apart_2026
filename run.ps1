# Seoul Apt Trend Lab 실행
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
    Write-Host "venv 생성 중..."
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
} else {
    .\venv\Scripts\Activate.ps1
}

$env:PYTHONPATH = $PSScriptRoot

# DB가 비어 있으면 샘플 적재
python -c "from app.etl.seed_sample import seed_sample_data; print(seed_sample_data())"

Write-Host "브라우저에서 http://localhost:8501 을 여세요."
streamlit run streamlit_app.py
