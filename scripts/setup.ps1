$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (!(Test-Path .venv\Scripts\python.exe)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
    }
    & .\.venv\Scripts\python.exe -m pip install --cache-dir .cache/pip -r backend/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' }
    Push-Location frontend
    try {
        npm ci --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    } finally { Pop-Location }
    & .\.venv\Scripts\python.exe -m backend.app.database
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed' }
} finally { Pop-Location }
