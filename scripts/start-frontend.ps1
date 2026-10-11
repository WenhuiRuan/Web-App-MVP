param([ValidateRange(1024, 65535)][int]$Port = 5173)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend')
try {
    npm run dev -- --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Frontend exited with an error' }
} finally { Pop-Location }
