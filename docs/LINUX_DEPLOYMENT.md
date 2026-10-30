# OpenReporting 1.0 — Ubuntu Sunucu Kurulumu ve İşletimi

CI ile doğrulanan üretim tabanı: **Ubuntu 24.04 LTS**, systemd, Python 3.11–3.13 ve yerel SQLite.
Ubuntu 22.04/Debian 12 bu kabul matrisinde doğrulanmadı; ayrı ortam kabulü gerekir.

## 1. Kapasite

Ölçüm öncesi donanım planı (kullanıcı/host veya günlük rapor kapasitesi garantisi değildir):

| Plan | CPU | RAM | Disk |
| --- | --- | --- | --- |
| İlk kabul ortamı | 4 vCPU | 8 GB | 50 GB SSD (arşiv saklama süresine göre büyütün) |
| Daha yoğun iş yükü için aday bütçe | 8 vCPU | 16 GB | arşiv × saklama gün sayısı |

Veritabanı SQLite (WAL) ve yerel diskte olmalıdır; NFS/SMB üzerinde çalıştırmayın.
Ölçülmüş sentetik HTTP sonuçları ve sınırları [performans kabul kaydındadır](PERFORMANCE_ACCEPTANCE.md).
Gerçek kaynak/rapor/TLS/LDAP/SMTP yüküyle kurum kabulü yapılmadan bu tablo üretim kapasitesi sayılmaz.

## 2. Kurulum

```bash
# 1a) GitHub’dan (özel depo: salt-okunur bir deploy key veya “Contents: read” yetkili ince taneli token gerekir)
sudo apt-get install -y git
git clone --branch v1.0.0 https://github.com/sergenbasakcii/openreporting.git /tmp/openreporting && cd /tmp/openreporting

# 1b) veya internetsiz sunucuya paket olarak taşıyın
scp openreporting-1.0.0.zip admin@sunucu:/tmp/ && ssh admin@sunucu
cd /tmp && unzip openreporting-1.0.0.zip -d openreporting && cd openreporting

# 2a) Kurum sertifikası ile
sudo ./deploy/install-ubuntu.sh --domain openreporting.sirket.local \
     --cert /etc/ssl/certs/openreporting.pem --key /etc/ssl/private/openreporting.key --admin sergen

# 2b) Hızlı deneme: kendinden imzalı sertifika
sudo ./deploy/install-ubuntu.sh --domain openreporting.sirket.local --self-signed --admin sergen
```

Ubuntu 22.04 sistem Python’u 3.10 olduğundan `--use-deadsnakes` ekleyin (Python 3.12 kurulur) veya `--python /yol/python3.12` verin.
İnternetsiz ortamda önce internet erişimi olan, aynı Ubuntu ve Python sürümündeki bir makinede depo klasöründe
önce build araçlarını `requirements-build.lock` ile hash doğrulayarak kurun;
`python3 -m pip download --require-hashes --only-binary=:all: -r requirements-build.lock -d wheels` ve
aynı komutla `requirements-runtime.lock` paketlerini indirin.
`python3 -m pip wheel --no-deps --no-build-isolation -w wheels .`
ile runtime, uygulama ve kurulum aracı wheel’lerini hazırlayıp kaynak ağacıyla sunucuya taşıyın ve
`--wheelhouse /yol/wheels` kullanın.
Kapsam ve güncelleme kabulü [paket kilidi yönergesindedir](DEPENDENCY_LOCK.md).

Betik **idempotent**tir; tekrar çalıştırmak mevcut `/etc/openreporting/openreporting.env` ve anahtarı korur.

### Oluşturulan yapı

| Yol | Sahip / izin | İçerik |
| --- | --- | --- |
| `/opt/openreporting/app` | root, 0755 | Uygulama kaynak kodu (`app.prev` = önceki sürüm) |
| `/opt/openreporting/venv` | root | Python sanal ortamı |
| `/var/lib/openreporting` | openreporting, 0750 | `state.sqlite3`, `archive/` (raporlar), `worker.lock` |
| `/etc/openreporting/openreporting.env` | root:openreporting 0640 | Ayarlar (SMTP parolası dahil) |
| `/etc/openreporting/secret.key` | root:openreporting 0640 | Veri kaynağı kimlik bilgilerini şifreleyen Fernet anahtarı |
| `/var/backups/openreporting` | root, 0700 | Günlük yedekler (14 gün) |
| `openreporting-web.service` | openreporting | API + arayüz, `127.0.0.1:8810`, 2 uvicorn işçisi |
| `openreporting-worker.service` | openreporting | Tek rapor zamanlayıcı/üretici (dosya kilidiyle tekil) |
| `openreporting-backup.timer` | root | Her gece 02:30 tutarlı yedek |
| nginx `openreporting.conf` | — | HTTP→HTTPS yönlendirme, TLS 1.2/1.3, gzip, `/metrics` dışarıya kapalı |

## 3. Yapılandırma (`/etc/openreporting/openreporting.env`)

Değişiklikten sonra: `sudo systemctl restart openreporting-web openreporting-worker`.

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `OPENREPORTING_PUBLIC_URL` | https://alan-adi | E-postalardaki bağlantılar |
| `OPENREPORTING_WEB_WORKERS` | 2 | uvicorn işçi sayısı (CPU sayısı kadar artırılabilir) |
| `OPENREPORTING_SESSION_HOURS` | 12 | Oturum süresi |
| `OPENREPORTING_QUERY_TIMEOUT_MS` | 30000 | SQL sorgu zaman aşımı |
| `OPENREPORTING_QUERY_CONCURRENCY` | 6 | Panel başına paralel sorgu |
| `OPENREPORTING_MAX_SERIES_POINTS` | 2000000 | Tek yanıt nokta bütçesi (aşılırsa sorgu reddedilir, sessiz kırpma yok) |
| `OPENREPORTING_REPORT_RETENTION_DAYS` | 365 | Rapor arşivi saklama süresi (0 = sınırsız) |
| `OPENREPORTING_PROVISION_TESTDATA` | true | Sentetik TestData veri kaynağı (katı üretimde false) |
| `OPENREPORTING_MAIL_ENABLED` | false | E-posta gönderimi (aşağıya bakın) |

### E-posta (SMTP)

```dotenv
OPENREPORTING_MAIL_ENABLED=true
OPENREPORTING_SMTP_HOST=smtp.sirket.local
OPENREPORTING_SMTP_PORT=587
OPENREPORTING_SMTP_STARTTLS=true
OPENREPORTING_SMTP_USER=openreporting-raporlar
OPENREPORTING_SMTP_PASSWORD=********
OPENREPORTING_SMTP_FROM=openreporting@sirket.local
OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS=sirket.local,example.com
```

STARTTLS zorunludur; alıcılar yalnızca izinli alan adlarından olabilir; zamanlamayı yalnızca **yönetici** etkinleştirebilir.

## 4. Zabbix bağlantısı

1. Zabbix’te yalnızca okuma yetkili bir kullanıcı/rol oluşturun (API erişimi açık, yalnız gereken host gruplarına *Read*).
2. *Kullanıcılar → API tokenları* altında token üretin (süreli olması önerilir).
3. OpenReporting → **Yönetim → Veri kaynakları → Ekle → Zabbix**: URL `https://zabbix.sirket.local/api_jsonrpc.php`, token,
   iç CA kullanıyorsanız PEM sertifikası. **Kaydet ve test et** “Zabbix API x.y bağlantısı başarılı” göstermelidir.
4. Zabbix < 6.4 için *Kimlik doğrulama yöntemi*ni “auth alanı” seçin.
5. Büyük gruplar (binlerce host) için TimescaleDB/PostgreSQL’deki Zabbix history tablolarını ayrı bir **PostgreSQL**
   veri kaynağı olarak ekleyip Zabbix veri kaynağında *History kaynağı = SQL* seçin. Grup/host/item keşfi yine API’den yapılır.

PostgreSQL rolü yalnız `SELECT` yetkili olmalı; OpenReporting tüm sorguları `READ ONLY` işlemde çalıştırır.

## 5. İşletim

```bash
systemctl status openreporting-web openreporting-worker
journalctl -u openreporting-web -u openreporting-worker -f
sudo /opt/openreporting/app/deploy/openreporting-admin.sh doctor            # kurulum sağlık kontrolü
sudo /opt/openreporting/app/deploy/openreporting-admin.sh create-user ayse --role editor
sudo /opt/openreporting/app/deploy/openreporting-admin.sh reset-password sergen
curl -s http://127.0.0.1:8810/metrics                          # Prometheus (yalnız yerel)
```

Prometheus metrikleri: `openreporting_up`, `openreporting_report_runs_total{status}`, `openreporting_worker_heartbeat_age_seconds`,
`openreporting_active_schedules`, `openreporting_data_disk_free_bytes`. Öneri: heartbeat > 120 sn ve disk < %10 için uyarı.

### Dashboard’ları kod olarak saklama

```bash
sudo /opt/openreporting/app/deploy/openreporting-admin.sh export-dashboards /var/lib/openreporting/export
# git deposuna alın; başka bir sunucuya aktarmak için:
sudo /opt/openreporting/app/deploy/openreporting-admin.sh import-dashboards /var/lib/openreporting/import
```

## 6. Yedekleme ve geri yükleme

Gece yedeği `/var/backups/openreporting/YYYYMMDD-HHMMSS/` içine `state.sqlite3`, `archive.tar.gz`, `openreporting.env`
ve `SHA256SUMS` yazar. Elle: `sudo systemctl start openreporting-backup`. Yedekleri sunucu dışına kopyalayın.
`archive.tar.gz` rapor arşiviyle birlikte varsa `logos/` dizinini de içerir. LDAP/SMTP parola
dosyalarını ve kurum CA dosyalarını ayrıca kontrollü kurtarma planına dahil edin.

Sağlık izleme: `/healthz` süreç canlılığını, `/api/health` yerel DB/şema erişimini gösterir
(arıza: HTTP 503). Yönetici oturumu gerektiren `/readyz` ayrıca audit zincirini doğrular; bozuk zincir
veya erişilemeyen DB başarılı readiness sayılmaz. Bu kontroller harici veri kaynağına sorgu veya e-posta göndermez.

> **Şifreleme anahtarı (`/etc/openreporting/secret.key`) varsayılan olarak yedeğe konmaz** — veritabanı yedeği çalınsa bile
> veri kaynağı parolaları çözülemesin diye. Kurulumdan hemen sonra anahtarı ayrı ve güvenli bir yerde (parola kasası,
> çevrimdışı ortam) saklayın; anahtar olmadan veri kaynağı kimlik bilgileri yeniden girilmelidir.
> Anahtarı yedeğe katmak için `/etc/openreporting/openreporting.env` içine `OPENREPORTING_BACKUP_INCLUDE_KEY=true` ekleyin.
> Yedekleri bir GPG açık anahtarıyla şifrelemek için: `OPENREPORTING_BACKUP_GPG_RECIPIENT=yedek@sirket.local` (`apt install gnupg`).

Geri yükleme:

Önce yedeği canlı verinin üzerine yazmadan doğrulayın. Bu komut yalnız yeni geçici dizinde çalışır;
SHA256SUMS, DB bütünlüğü/şeması, audit zinciri, rapor manifesti/dosyaları, logolar ve şifreli
kaynakların ayrı anahtarla açılmasını kontrol eder. Canlı ayarları yüklemez, migrasyon/worker/SMTP çalıştırmaz.
Çıkış kodu 0 ve `ok:true` başarılı doğrulamadır. GPG yedeğini önce güvenli ayrı bir dizine çözün.
Varsayılan açılmış boyut bütçesi 2048 MB; büyük arşivlerde `--max-unpacked-mb` ile bilinçli artırın.

```bash
sudo /opt/openreporting/venv/bin/openreporting verify-backup /var/backups/openreporting/YYYYMMDD-HHMMSS \
  --key-file /etc/openreporting/secret.key
```

SHA256SUMS ve audit zinciri tutarlılık kanıtıdır; tam yetkili bir saldırganın yedeği yeniden
üretmesine karşı bağımsız dijital imza yerine geçmez. Yedeğin kaynağını ve ayrı anahtarın emanetini doğrulayın.
Canlıya geri yükleme işlemi bakım penceresinde, eşleşen uygulama sürümü ve doğrulanmış yedekle yapılmalıdır.

```bash
sudo systemctl stop openreporting-worker openreporting-web
cd /var/backups/openreporting/20261024-023000 && sha256sum -c SHA256SUMS
sudo install -o openreporting -g openreporting -m 0640 state.sqlite3 /var/lib/openreporting/state.sqlite3
sudo rm -f /var/lib/openreporting/state.sqlite3-wal /var/lib/openreporting/state.sqlite3-shm
sudo tar -C /var/lib/openreporting -xzf archive.tar.gz
sudo chown -R openreporting:openreporting /var/lib/openreporting/archive
if [ -d /var/lib/openreporting/logos ]; then sudo chown -R openreporting:openreporting /var/lib/openreporting/logos; fi
# Anahtar ayrı saklandıysa oradan, yedeğe dahil edildiyse buradan geri koyun:
sudo install -o root -g openreporting -m 0640 secret.key /etc/openreporting/secret.key
sudo systemctl start openreporting-web openreporting-worker
sudo /opt/openreporting/app/deploy/openreporting-admin.sh verify-audit
```

Uygulama, anahtar dosyası kayıpken şifreli kimlik bilgisi bulursa sessizce yeni anahtar üretmez; açık bir hata verir.

## 7. Yükseltme

```bash
# git ile kurulduysa
cd /tmp/openreporting && git fetch --tags && git checkout v1.x.y && sudo ./deploy/upgrade.sh
# paketle kurulduysa
cd /tmp && unzip openreporting-1.x.y.zip -d openreporting-new && cd openreporting-new
sudo ./deploy/upgrade.sh
```

Betik önce yedek alır, servisleri durdurur, kodu `/opt/openreporting/app` içine kopyalar (öncekini `app.prev` olarak tutar),
bağımlılıkları kurar, şemayı yükseltir ve sağlık kontrolü yapar. Hata olursa önceki kodu otomatik geri yükler; şema
yükseltilmişse veritabanını son yedekten geri yükleyin.

## 8. Kaldırma

`sudo /opt/openreporting/app/deploy/uninstall.sh` (veriyi korur) · `--purge` (veri ve ayarları da siler; yedekler kalır).

## 9. Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| 502 Bad Gateway | `systemctl status openreporting-web`, `journalctl -u openreporting-web -n 100` |
| Raporlar “Kuyrukta” kalıyor | `systemctl status openreporting-worker`; Sunucu durumu sayfasındaki worker sinyali |
| “Zabbix API’ye ulaşılamadı” | Sunucudan `curl -I https://zabbix.../api_jsonrpc.php`, DNS, firewall, CA sertifikası |
| “Sorgu N item ile eşleşti; güvenlik sınırı …” | Filtreyi daraltın, `aggregateBy` kullanın veya veri kaynağında *Sorgu başına en fazla item* artırın |
| PDF’de Türkçe karakter sorunu | `apt install fonts-dejavu-core`, `openreporting doctor` |
| Oturum hemen düşüyor | HTTPS dışında erişiliyorsa `OPENREPORTING_COOKIE_SECURE=true` çerezi göndermez; nginx üzerinden https ile girin |
| E-posta gitmiyor | Çalıştırma geçmişinde “E-posta” sütunu: *kısmi veri nedeniyle gönderilmedi* / *E-posta kapalı* / *belirsiz* |

## 10. Docker (alternatif)

```bash
docker compose up -d --build
docker compose exec web openreporting create-user sergen --role admin
```

Konteyner `127.0.0.1:8810` üzerinden yayınlanır; önüne TLS sonlandıran bir ters vekil koyun. Veri `openreporting-data`,
şifreleme anahtarı ayrı `openreporting-key` volume’ündedir — ikisini ayrı yerlerde yedekleyin. Konteynerler salt okunur kök
dosya sistemi, tüm yetenekler kaldırılmış ve `no-new-privileges` ile çalışır.
