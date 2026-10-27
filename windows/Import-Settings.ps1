# Shared environment for local Windows launch scripts. No service or registry edits.
$ErrorActionPreference = 'Stop'
$env:OPENREPORTING_DATA_DIR = Join-Path $env:LOCALAPPDATA 'OpenReporting'
$env:OPENREPORTING_COOKIE_SECURE = 'false'  # HTTP allowed on 127.0.0.1 only.
$env:OPENREPORTING_MAIL_ENABLED = 'false'

$settingsPath = Join-Path $PSScriptRoot 'Settings.local.ps1'
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    . $settingsPath
}

if (-not $env:OPENREPORTING_DATA_DIR) {
    throw 'OPENREPORTING_DATA_DIR cannot be empty.'
}
$script:OpenReportingDataDir = [System.IO.Path]::GetFullPath($env:OPENREPORTING_DATA_DIR)
if ($script:OpenReportingDataDir.StartsWith('\\')) {
    throw 'Do not put SQLite state on a UNC/network share.'
}
$env:OPENREPORTING_DATA_DIR = $script:OpenReportingDataDir

