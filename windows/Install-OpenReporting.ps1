param(
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if ($PythonExe) {
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Python was not found at: $PythonExe"
    }
    $runner = $PythonExe
    $prefix = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $runner = 'py'
    $prefix = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $runner = 'python'
    $prefix = @()
} else {
    throw 'Python 3.11, 3.12 or 3.13 must be installed first (python.org).'
}

$check = 'import sys; print(sys.version.split()[0]); sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)'
Write-Host 'Checking installed Python...'
& $runner @prefix -c $check
if ($LASTEXITCODE -ne 0) {
    throw 'This Windows package requires Python 3.11, 3.12 or 3.13 (64-bit recommended).'
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host 'Creating an isolated Python environment...'
    & $runner @prefix -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}

Push-Location $projectRoot
try {
    Write-Host 'Verifying and installing pinned application dependencies...'
    & $venvPython -m pip install --require-hashes '--only-binary=:all:' -r requirements-runtime.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check pip/network access.' }
    & $venvPython -m pip install --no-deps .
    if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
    & $venvPython -m pip install 'httpx>=0.27,<1' 'pytest>=8,<10'
    if ($LASTEXITCODE -ne 0) { throw 'Test runner installation failed.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
    & $venvPython tools/check_runtime_lock.py
    if ($LASTEXITCODE -ne 0) { throw 'Installed runtime differs from the reviewed dependency lock.' }

    . (Join-Path $PSScriptRoot 'Import-Settings.ps1')
    New-Item -ItemType Directory -Path $env:OPENREPORTING_DATA_DIR -Force | Out-Null
    & $venvPython -m openreporting.cli init
    if ($LASTEXITCODE -ne 0) { throw 'Local application state initialization failed.' }

    $localSettings = Join-Path $PSScriptRoot 'Settings.local.ps1'
    if (-not (Test-Path -LiteralPath $localSettings -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Settings.example.ps1') -Destination $localSettings
    }

    Write-Host ''
    Write-Host 'Installation completed. No monitoring host was modified.' -ForegroundColor Green
    Write-Host '1) .\windows\New-Admin.ps1 -Username sergen'
    Write-Host '2) .\windows\Test-OpenReporting.ps1'
    Write-Host '3) .\windows\Start-OpenReporting.ps1'
    Write-Host 'Local dashboard: http://127.0.0.1:8810'
    Write-Host "Application data: $env:OPENREPORTING_DATA_DIR"
} finally {
    Pop-Location
}

