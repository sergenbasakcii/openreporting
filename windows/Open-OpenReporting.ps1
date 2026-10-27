# Desktop launcher: opens OpenReporting in the default browser, starting it first if it is not running.
# The app runs in a minimized PowerShell window; closing that window stops it.
param([ValidateRange(1024, 65535)][int]$Port = 8810)

$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port"

function Test-Up {
    try { Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

if (-not (Test-Up)) {
    $start = Join-Path $PSScriptRoot 'Start-OpenReporting.ps1'
    Start-Process powershell.exe -WindowStyle Minimized -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$start`"", '-NoBrowser', '-Port', $Port)
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Test-Up)) {
        if ((Get-Date) -gt $deadline) {
            Add-Type -AssemblyName PresentationFramework
            [System.Windows.MessageBox]::Show(
                "OpenReporting başlatılamadı. Görev çubuğundaki küçültülmüş PowerShell penceresindeki hata mesajına bakın.",
                'OpenReporting') | Out-Null
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
}
Start-Process $url
