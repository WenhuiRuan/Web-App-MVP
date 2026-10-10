param([ValidateSet('configured', 'mock', 'deepseek')][string]$ModelMode = 'configured')
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    # Explicit process override; configured preserves environment/.env precedence.
    if ($ModelMode -ne 'configured') { $env:MODEL_PROVIDER = $ModelMode }
    & .\.venv\Scripts\python.exe -m backend.app.server
    if ($LASTEXITCODE -ne 0) { throw 'Backend exited with an error' }
} finally { Pop-Location }
