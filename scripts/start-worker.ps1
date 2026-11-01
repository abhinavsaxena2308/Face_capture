param(
  [string]$BackendPath = "$PSScriptRoot\..\backend"
)

$resolvedBackend = Resolve-Path -LiteralPath $BackendPath
Set-Location -LiteralPath $resolvedBackend
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
  throw "Backend virtual environment is missing. Create it with: py -3.12 -m venv .venv"
}
& .\.venv\Scripts\python.exe -m app.worker
