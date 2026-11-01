param(
  [string]$BackendPath = "$PSScriptRoot\..\backend"
)

$resolvedBackend = Resolve-Path -LiteralPath $BackendPath
Set-Location -LiteralPath $resolvedBackend
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
  throw "Backend virtual environment is missing. Create it with: py -3.12 -m venv .venv"
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " Starting FaceFinder Backend (API + Worker combined) " -ForegroundColor Green
Write-Host " API: http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host " Worker: Running in background" -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Cyan

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

