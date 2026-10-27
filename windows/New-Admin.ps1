param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]{3,80}$')]
    [string]$Username
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Install-OpenReporting.ps1 must be run first.'
}
. (Join-Path $PSScriptRoot 'Import-Settings.ps1')
& $python -m openreporting.cli create-user $Username --role admin
if ($LASTEXITCODE -ne 0) { throw 'Admin account creation failed.' }

