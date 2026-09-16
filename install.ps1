$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.11+ is required.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 20+ is required.' }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'npm is required.' }

python -m venv backend/.venv
& backend/.venv/Scripts/python.exe -m pip install --upgrade pip
& backend/.venv/Scripts/pip.exe install -r backend/requirements.txt -r backend/requirements-dev.txt
npm --prefix frontend install --no-audit --no-fund

if (-not (Test-Path backend/.env)) {
  Copy-Item backend/.env.example backend/.env
  Write-Host 'Created backend/.env — add DEFAULT_LLM_API_KEY before starting.'
}

Write-Host 'Dependencies installed. Start backend with: make backend (or backend/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000)'
Write-Host 'Start frontend in another terminal with: npm --prefix frontend run dev'
Write-Host 'Web UI: http://localhost:5173 | API docs: http://localhost:8000/api/docs'
