param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8810,
    [switch]$NoBrowser,
    [switch]$AllowEmail
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Install-OpenReporting.ps1 must be run first.'
}
. (Join-Path $PSScriptRoot 'Import-Settings.ps1')

if ($env:OPENREPORTING_MAIL_ENABLED -match '^(?i:true|yes|1)$' -and -not $AllowEmail) {
    throw 'SMTP is enabled. For a deliberate staging-mail test, rerun with -AllowEmail.'
}

$logDir = Join-Path $env:OPENREPORTING_DATA_DIR 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$outLog = Join-Path $logDir "worker-$stamp.stdout.log"
$errLog = Join-Path $logDir "worker-$stamp.stderr.log"
$worker = $null

Push-Location $projectRoot
try {
    & $python -m openreporting.cli init
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }

    # Start-Process inherits the launcher environment, exactly like the web.
    $worker = Start-Process -FilePath $python -ArgumentList @('-m','openreporting.cli','worker') `
        -WorkingDirectory $projectRoot -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog

    Start-Sleep -Milliseconds 900
    $worker.Refresh()
    if ($worker.HasExited) {
        throw "Worker exited immediately. Inspect: $errLog"
    }

    $url = "http://127.0.0.1:$Port"
    Write-Host "Local dashboard: $url" -ForegroundColor Green
    Write-Host 'Listening on loopback only. Press Ctrl+C to stop.'
    Write-Host "Worker errors: $errLog"
    if (-not $NoBrowser) { Start-Process $url }

    & $python -m openreporting.cli serve --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Local API server exited with an error.' }
} finally {
    if ($null -ne $worker) {
        try {
            $worker.Refresh()
            if (-not $worker.HasExited) {
                Stop-Process -Id $worker.Id -ErrorAction Stop
                $worker.WaitForExit(5000) | Out-Null
            }
        } catch {
            Write-Warning "Check if local worker PID $($worker.Id) is still active."
        }
    }
    Pop-Location
}

