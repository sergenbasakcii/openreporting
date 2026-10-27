$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Install-OpenReporting.ps1 must be run first.'
}
. (Join-Path $PSScriptRoot 'Import-Settings.ps1')
Push-Location $projectRoot
try {
    Write-Host 'Running local tests (mocked; no external monitoring writes)...'
    & $python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed; do not enable mail.' }

    Write-Host 'Verifying local audit chain...'
    & $python -m openreporting.cli verify-audit
    if ($LASTEXITCODE -ne 0) { throw 'Local audit chain verification failed.' }

    Write-Host 'All local checks passed.' -ForegroundColor Green
} finally {
    Pop-Location
}

