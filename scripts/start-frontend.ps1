$ErrorActionPreference = 'Stop'
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend')
try {
    npm run dev
    if ($LASTEXITCODE -ne 0) { throw 'Frontend exited with an error' }
} finally { Pop-Location }
