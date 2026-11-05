# OpenReporting — Docker ile kurulum ve işletim

Docker Compose yığını üç kalıcı servis ve bir yedek görevi içerir:

```
Kullanıcı ──HTTPS 443──▶ proxy (nginx, root olmayan) ──▶ web (OpenReporting API + arayüz, port 8810 dışarı kapalı)
                                                        worker (zamanlanmış raporlar, e-posta)
                                                        backup (isteğe bağlı görev: docker compose --profile backup run)
Kalıcı veri: openreporting-data (SQLite + rapor arşivi + logolar) · openreporting-key (şifreleme anahtarı, ayrı volume)
```

Bütün konteynerler salt okunur kök dosya sistemiyle, tüm Linux yetenekleri kaldırılmış ve
`no-new-privileges` ile çalışır. Uygulama yalnız sabit IP'li proxy konteynerinin `X-Forwarded-*`
başlıklarına güvenir; 8810 portu sunucu dışına açılmaz. CI her değişiklikte bu yığını kurar ve
HTTPS, güvenli çerez, HTTPS üzerinden MFA, worker, yeniden başlatma kalıcılığı ve yedek doğrulamasını test eder.

## 1. Gereksinimler

- Linux sunucu (Ubuntu 24.04 önerilir), **Docker Engine 24+** ve **Docker Compose v2** (`docker compose version`).
- 4 vCPU, 8 GB RAM, 50 GB SSD ile başlayın (ayrıntı: kılavuz Bölüm 11). Docker verisi yerel diskte olmalı.
- Sunucunun 80/443 portları ve bir DNS adı (örn. `openreporting.example.com`).
- Docker Desktop (Windows/macOS) yalnız deneme içindir.

```bash
# Ubuntu'da Docker (resmi depo); kurum standardınız varsa onu kullanın
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"   # oturumu kapatıp açın
```

### Platform desteği

| Ortam | Durum |
| --- | --- |
| Linux + Docker Engine 24+ / Compose v2, x86_64 (Ubuntu, Debian, Kali, Oracle Linux, RHEL, Rocky…) | Desteklenir; Ubuntu 24.04 ile CI'da her değişiklikte test edilir. SELinux açık sistemler için bağlanan dosyalar `:z` ile etiketlenir |
| Windows 10/11 + Docker Desktop (WSL 2) | Çalışır (Windows 11 + Docker Desktop 4.97 üzerinde denendi); deneme/geliştirme içindir |
| macOS + Docker Desktop | Çalışması beklenir; düzenli test edilmiyor |
| ARM64 (Apple Silicon, Graviton, Ampere) | İmaj çok mimarili tabanlar ve kilitteki ARM paketleriyle derlenebilir; CI'da test edilmiyor |
| Windows Server'ın yerel Windows konteynerleri | Desteklenmez; Linux konteyneri gerekir |
| Rootless Docker / Podman | 80/443 için ayrıcalıksız port ayarı gerekir (`OPENREPORTING_HTTPS_PORT=8443`); Podman Compose ayrıca doğrulanmalı |
| Kubernetes | [KUBERNETES.md](KUBERNETES.md) (PostgreSQL ile yatay ölçekleme) |

## 2. Kurulum (tek komut)

Sunucuda internet varken üç adım:

```bash
git clone https://github.com/sergenbasakcii/openreporting.git ~/openreporting
cd ~/openreporting
sudo ./kurulum.sh
```

Betik yalnızca şunları sorar: **sunucunun adresi** (DNS adı veya IP; varsayılanı önerir), **yönetici
kullanıcı adı ve parolası** ve isteğe bağlı olarak uygulamanın erişeceği **iç ağlar**. Kalan her şeyi
kendisi yapar:

| Betiğin yaptığı | Ayrıntı |
| --- | --- |
| Docker kontrolü | Yoksa (Ubuntu/Debian) kurmayı önerir; sürüm 24+ olmalı |
| Ayar dosyası | `deploy/docker/openreporting.env` adres, saat dilimi ve sunucu IP'siyle oluşturulur (root:10001, 0640) |
| Sertifika | Kurum sertifikası verilmediyse kendinden imzalı üretir, izinleri ayarlar |
| Başlatma | İmajı derler, proxy/web/worker sağlıklı olana kadar bekler |
| İlk yönetici | Hiç kullanıcı yoksa oluşturur; ilk girişte telefonla iki adımlı giriş kurulur |
| Anahtar kopyası | Şifreleme anahtarını `/root/openreporting-anahtar/` içine kopyalar — **sunucu dışına taşıyın** |
| Gece yedeği | `/etc/cron.d/openreporting-yedek` — her gece 02:30, 14 gün saklanır |
| Çıkış kilidi | İç ağlar yazıldıysa internete çıkışı kapatır, yeniden başlatmada korunur |
| Son kontrol | Saat senkronu ve `doctor` kontrolü |

Kurulum bitince tarayıcıda gösterilen adresi açın. E-posta (SMTP), LDAP ve veri kaynakları arayüzden
ayarlanır: **Yönetim → Sistem ayarları** ve **Yönetim → Veri kaynakları**.

Sonraki işler de aynı betikle yapılır:

```bash
sudo ./kurulum.sh durum       # servisler, worker, son yedek, çıkış kilidi
sudo ./kurulum.sh yedek       # hemen yedek al
sudo ./kurulum.sh guncelle    # yedek → yeni sürüm → yeniden derle → kontrol
```

Betik tekrar çalıştırılabilir; var olan ayar, sertifika, kullanıcı ve veriye dokunmaz. Kurum
sertifikası sonradan geldiğinde `deploy/docker/certs/cert.pem` ve `key.pem` olarak koyup
`sudo ./kurulum.sh` çalıştırmanız yeterlidir. Soru sormadan kurulum (otomasyon) için betiğin başındaki
`OR_*` değişkenlerine bakın.

### Elle kurulum (isteğe bağlı)

Betiğin yaptığı adımları kendiniz yapmak isterseniz:

```bash
git clone https://github.com/sergenbasakcii/openreporting.git ~/openreporting && cd ~/openreporting

# 1) Ayar dosyası
cp deploy/docker/openreporting.env.example deploy/docker/openreporting.env
sudo chown root:10001 deploy/docker/openreporting.env && sudo chmod 0640 deploy/docker/openreporting.env   # yedek konteyneri (uid 10001) okuyabilmeli
nano deploy/docker/openreporting.env      # OPENREPORTING_PUBLIC_URL=https://openreporting.example.com

# 2) TLS sertifikası: kurum sertifikasını koyun …
cp /yol/sertifika-zinciri.pem deploy/docker/certs/cert.pem
cp /yol/ozel-anahtar.pem      deploy/docker/certs/key.pem
#    … veya deneme için kendinden imzalı üretin
openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -subj "/CN=openreporting.example.com" \
  -addext "subjectAltName=DNS:openreporting.example.com" \
  -keyout deploy/docker/certs/key.pem -out deploy/docker/certs/cert.pem
#    Proxy uid/gid 101 ile çalışır; anahtarı yalnız o gruba okunur yapın
sudo chown root:101 deploy/docker/certs/key.pem && sudo chmod 0640 deploy/docker/certs/key.pem

# 3) Yedek klasörü (konteyner kullanıcısı uid/gid 10001)
sudo install -d -o 10001 -g 10001 -m 0700 backups

# 4) Başlat (ilk seferde imaj derlenir)
docker compose up -d --build --wait
docker compose ps

# 5) İlk yönetici (parola terminalde sorulur, en az 14 karakter)
docker compose exec web openreporting create-user yonetici --role admin
```

Tarayıcıda `https://openreporting.example.com` adresini açın. Yönetici ilk girişte doğrulayıcı
uygulamayla QR okutur (varsayılan `OPENREPORTING_MFA_REQUIRED_ROLES=admin`). SMTP, LDAP ve
sınırlar sonradan **Yönetim → Sistem ayarları** sayfasından yapılabilir; yeniden başlatma gerekmez.

### Portlar, adresler ve ağ (isteğe bağlı `.env`)

`docker-compose.yml` ile aynı klasörde bir `.env` dosyası Compose değişkenlerini değiştirir:

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `OPENREPORTING_HTTPS_PORT` | 443 | HTTPS portu. 443 değilse `PUBLIC_URL` içine portu yazın (`https://ad:8443`) |
| `OPENREPORTING_HTTP_PORT` | 80 | HTTP → HTTPS yönlendirmesi |
| `OPENREPORTING_BIND` | 0.0.0.0 | Yalnız tek arayüzden dinlemek için sunucu IP'si |
| `OPENREPORTING_SUBNET` | 172.30.88.0/24 | İç Docker ağı; kurum ağıyla çakışırsa değiştirin |
| `OPENREPORTING_PROXY_IP` | 172.30.88.10 | Proxy'nin sabit iç IP'si (alt ağ içinde olmalı) |
| `OPENREPORTING_TAG` | local | İmaj etiketi |

Kullanıcılar sunucuya birden fazla adla (örn. IP ile) giriyorsa bu adları
`OPENREPORTING_ALLOWED_HOSTS` içine yazın; bilinmeyen adlar güvenlik için reddedilir.

### İnternetsiz çalışma (kurulumdan sonra)

Kurulum sırasında internet gerekir (imaj tabanları ve kilitli Python paketleri indirilir). **Kurulumdan sonra
OpenReporting internete hiç bağlanmaz**; her şey sunucunun içinde çalışır:

| Konu | Durum |
| --- | --- |
| Arayüz | Tüm JavaScript, CSS, ikonlar ve grafik kütüphanesi (ECharts) imajın içindedir; tarayıcı yalnızca bu sunucuya bağlanır (CSP `'self'`). CDN, Google Fonts, harita döşemesi yoktur. |
| PDF / Excel | Yazı tipleri (DejaVu) ve şablonlar imajdadır; dışarıdan bir şey indirilmez. |
| Güncelleme kontrolü, telemetri, lisans | Yoktur. Metrikler (`/metrics`) ve loglar yalnız yereldir. |
| Yeniden başlatma | `restart: unless-stopped`; imajlar yerelde olduğu için çekme (pull) yapılmaz. |

Kurulumdan sonra sunucunun erişmesi gereken yerler yalnızca **kendi ağınızdadır**:

- Veri kaynakları (Zabbix API, veritabanları, Elasticsearch …): sunucudan bu adreslere erişim açık olmalı.
- SMTP (e-posta ile rapor teslimi) ve LDAP/AD (kullanıyorsanız).
- **Saat senkronizasyonu (iç NTP):** iki adımlı giriş (TOTP) ve rapor zamanlamaları doğru saate ihtiyaç duyar.
- İç DNS (veri kaynaklarının adlarını çözmek için).

**Önerilen sertleştirme — çıkış kilidi:** konteynerlerin internete çıkmasını sunucu güvenlik duvarında
tamamen kapatın, yalnız iç ağınızdaki gerekli adreslere izin verin (Docker'ın `DOCKER-USER` zinciri):

```bash
# Örnek: Zabbix ve veritabanlarının bulunduğu 10.20.0.0/16, SMTP/LDAP sunucusu 192.168.5.10
sudo deploy/docker/egress-lock.sh apply 10.20.0.0/16 192.168.5.10/32
sudo deploy/docker/egress-lock.sh status     # kuralları ve sayaçları gösterir
sudo deploy/docker/egress-lock.sh remove     # kilidi kaldırır (ör. sürüm yükseltmeden önce)
```

Kullanıcıların 80/443 üzerinden gelen bağlantıları ve konteynerlerin birbirleriyle konuşması etkilenmez.
Kurallar yeniden başlatmada kendiliğinden korunmaz: dağıtımınızın aracıyla kalıcı yapın veya `apply`
komutunu `docker.service` sonrasında çalışan bir systemd birimine koyun.

Bunun kanıtı her değişiklikte CI'da çalışır: kilit uygulanınca web konteynerinin internete bağlanamadığı
doğrulanır, ardından web ve worker yeniden başlatılır ve giriş, sorgu (önceki dönem karşılaştırmasıyla),
akıllı dashboard PDF'i, worker ve yedek çalıştırılır.

İnternet yalnız şu durumlarda tekrar gerekir: **sürüm yükseltme** (yeni imaj derlemek için; alternatif olarak
imaj başka bir makinede derlenip `docker save` / `docker load` ile taşınabilir), Python eklentisi kurmak ve
sertifika yenilemek (sertifikayı kurumunuz sağlıyorsa gerekmez; uygulama otomatik sertifika almaz).

## 3. Günlük işletim

```bash
docker compose ps                                   # durum ve sağlık
docker compose logs -f web worker                   # günlükler
docker compose exec web openreporting doctor        # kurulum kontrolü
docker compose exec web openreporting reset-password <kullanıcı>
docker compose exec web openreporting reset-mfa <kullanıcı> --reason lost-device
docker compose exec web openreporting verify-audit
docker compose restart web worker                   # yeniden başlatma
docker compose down                                 # durdur (veri volume'lerde kalır)
```

`deploy/docker/openreporting.env` değiştiyse `docker compose up -d` konteynerleri yeni ayarla
yeniden oluşturur. Arayüzden kaydedilen ayarlar için bu gerekmez.

## 4. Yedekleme ve geri yükleme

```bash
docker compose --profile backup run --rm backup     # backups/YYYYMMDD-HHMMSS/ oluşturur
```

Klasörde `state.sqlite3`, `archive.tar.gz`, `openreporting.env`, `SHA256SUMS` bulunur;
14 günden eski yedekler silinir (`OPENREPORTING_BACKUP_KEEP_DAYS`). Her gece çalıştırmak için
root cron'u (`sudo crontab -e`); `-T` cron altında terminal ayırmaz, günlük `backups/` dışında tutulur:

```cron
30 2 * * * cd /home/<kullanıcı>/openreporting && docker compose --profile backup run --rm -T backup >> /var/log/openreporting-backup.log 2>&1
```

**Şifreleme anahtarı** ayrı volume'dedir ve varsayılan olarak yedeğe girmez. Kurulumdan hemen sonra
bir kez güvenli yere alın:

```bash
# anahtar ilk parola kaydında üretilir; henüz yoksa şimdi üretin:
docker compose exec -T web python -c "from openreporting.config import Settings; from openreporting.secrets_store import ensure_key; ensure_key(Settings.from_env())"
docker compose cp web:/run/openreporting-key/secret.key ./secret.key.KASAYA-KOYUN && chmod 600 ./secret.key.KASAYA-KOYUN
```

Yedeği doğrulama (canlı veriye dokunmaz):

```bash
docker compose --profile backup run --rm --entrypoint openreporting backup \
  verify-backup /backups/YYYYMMDD-HHMMSS --key-file /run/openreporting-key/secret.key
```

Geri yükleme (bakım penceresinde):

```bash
docker compose stop web worker
docker run --rm -v openreporting_openreporting-data:/data -v "$PWD/backups/YYYYMMDD-HHMMSS:/b:ro" \
  --user 10001:10001 openreporting:local sh -c \
  'cp /b/state.sqlite3 /data/state.sqlite3 && rm -f /data/state.sqlite3-wal /data/state.sqlite3-shm && tar -C /data -xzf /b/archive.tar.gz'
docker compose up -d --wait
docker compose exec web openreporting verify-audit
```

Volume adı Compose proje adıyla başlar (klasör adı `openreporting` ise `openreporting_openreporting-data`);
`docker volume ls` ile kontrol edin. Anahtar kaybolduysa yedeklenen anahtarı
`openreporting_openreporting-key` volume'üne `secret.key` olarak geri koyun.

## 5. Yükseltme

```bash
sudo ./kurulum.sh guncelle      # çıkış kilidini geçici kaldırır, yedek alır, yeni sürümü derler, kilidi geri koyar
```

Elle yapmak isterseniz:

```bash
docker compose --profile backup run --rm backup     # önce yedek
git pull
docker compose up -d --build --wait                 # yeni imaj; şema açılışta otomatik yükseltilir
```

Geri dönüş: önceki git sürümüne dönüp imajı yeniden derleyin **ve** yükseltme öncesi yedeği geri
yükleyin. Eski kod yeni şemayı açmayı reddeder.

## 6. Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| Derlemede `CERTIFICATE_VERIFY_FAILED` (pypi.org) | Antivirüs (örn. Avast Web Shield) veya kurumsal proxy HTTPS'i kendi sertifikasıyla inceliyor. O kök sertifikanın açık kısmını PEM olarak `deploy/docker/build-ca/*.crt` içine koyun; yalnız derlemede güvenilir, paketler yine özetle doğrulanır, çalışan imaja girmez |
| Tarayıcı/araç localhost sertifikasını Avast adıyla görüyor | Antivirüsün HTTPS taraması yerel bağlantıyı yeniden imzalıyor; uygulamayla ilgisi yoktur. Sunucu kurulumunda görülmez |
| `env file … not found` | `deploy/docker/openreporting.env` oluşturulmamış (Bölüm 2, adım 1) |
| proxy başlamıyor, `cannot load certificate key` | `deploy/docker/certs/key.pem` yok veya uid 101 okuyamıyor: `chown root:101`, `chmod 0640` |
| `Pool overlaps with other one on this address space` | `OPENREPORTING_SUBNET` / `OPENREPORTING_PROXY_IP` değerlerini boş bir alt ağa çevirin |
| Tarayıcıda 400 “Invalid host header” | `PUBLIC_URL` adresi tarayıcıdakiyle aynı değil; ek adları `ALLOWED_HOSTS` içine yazın |
| MFA kurulumu “yalnız HTTPS” diyor | Uygulamaya proxy dışında erişiliyor veya `PROXY_IP` uyuşmuyor |
| Yedek: `not writable by uid 10001` | `sudo chown 10001:10001 backups && sudo chmod 0700 backups` |
| Yedek: `cp: cannot open '/run/openreporting.env'` | Ayar dosyası yalnız root'a açık: `sudo chown root:10001 deploy/docker/openreporting.env && sudo chmod 0640 deploy/docker/openreporting.env` (veya `sudo ./kurulum.sh`) |
| Raporlar kuyrukta | `docker compose logs worker`; Sunucu durumu sayfasındaki worker sinyali |
| Zabbix'e ulaşılamıyor | `docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('https://zabbix…', timeout=5).status)"`; DNS/güvenlik duvarı |
| Bellek | `docker stats`; kılavuz Bölüm 11. İsteğe bağlı sınır: servislere `mem_limit: 3g` |

## 7. systemd kurulumundan farklar

| Konu | systemd (`install-ubuntu.sh`) | Docker Compose |
| --- | --- | --- |
| Ayar dosyası | `/etc/openreporting/openreporting.env` | `deploy/docker/openreporting.env` |
| Yönetim komutu | `sudo …/openreporting-admin.sh <komut>` | `docker compose exec web openreporting <komut>` |
| Gece yedeği | systemd timer (otomatik) | host cron satırı (Bölüm 4) |
| TLS | host nginx | `proxy` konteyneri |
| Güncelleme | `upgrade.sh` (otomatik yedek + geri dönüş) | önce yedek, sonra `up -d --build` |
