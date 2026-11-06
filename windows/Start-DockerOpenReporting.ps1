# OpenReporting'i Windows'ta Docker Desktop ile açar (yerel deneme).
# 1) Docker Desktop'ın kapanışta kilitli bıraktığı secrets-engine soketini kenara alır
#    (aksi halde Docker "rename engine.sock ... Sistem dosyaya erişemiyor" hatasıyla açılmaz),
# 2) Docker Desktop'ı başlatıp motorun hazır olmasını bekler,
# 3) docker compose ile proxy/web/worker'ı ayağa kaldırır, 4) tarayıcıda açar.
# Native tools (docker) write progress to stderr; failures are checked through exit codes below.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$secrets = Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'
$dockerExe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'

function Test-Engine { docker info 2>&1 | Out-Null; return $LASTEXITCODE -eq 0 }

Write-Host 'OpenReporting açılıyor...' -ForegroundColor Cyan
if (-not (Test-Engine)) {
    if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue) -and (Test-Path $secrets)) {
        $old = "$secrets.eski-$(Get-Date -Format yyyyMMddHHmmss)"
        Rename-Item $secrets $old -ErrorAction Stop
        Write-Host '  Docker Desktop kilitli dosyası kenara alındı.'
        # Keep only the three most recent set-aside folders.
        Get-ChildItem -Force $env:LOCALAPPDATA -Directory -Filter 'docker-secrets-engine.eski-*' |
            Sort-Object Name -Descending | Select-Object -Skip 3 |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
    }
    if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) { Start-Process $dockerExe }
    Write-Host '  Docker başlatılıyor (1-2 dakika)...'
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-Engine)) {
        if ((Get-Date) -gt $deadline) { throw 'Docker Desktop açılamadı. Docker Desktop penceresindeki hatayı kontrol edin (Reset to factory defaults KULLANMAYIN).' }
        Start-Sleep -Seconds 3
    }
}
Write-Host '  Docker hazır. Uygulama başlatılıyor...'
Push-Location $repo
try { cmd /c "docker compose up -d --wait 2>&1" | Out-Host; if ($LASTEXITCODE -ne 0) { throw 'docker compose up başarısız; docker compose logs web' } }
finally { Pop-Location }

$url = 'https://localhost'
$envFile = Join-Path $repo 'deploy\docker\openreporting.env'
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern '^OPENREPORTING_PUBLIC_URL=(.+)$' | Select-Object -First 1
    if ($line) { $url = $line.Matches[0].Groups[1].Value.Trim() }
}
Write-Host "  Hazır: $url" -ForegroundColor Green
Write-Host '  Tarayıcı sertifika uyarısı verirse: Gelişmiş → devam et (yerel, kendinden imzalı sertifika).'
Start-Process $url
Start-Sleep -Seconds 4
