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

## 2. İlk kurulum

```bash
git clone https://github.com/sergenbasakcii/openreporting.git ~/openreporting && cd ~/openreporting

# 1) Ayar dosyası
cp deploy/docker/openreporting.env.example deploy/docker/openreporting.env
chmod 600 deploy/docker/openreporting.env
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
sunucu cron'u (`crontab -e`):

```cron
30 2 * * * cd /home/<kullanıcı>/openreporting && docker compose --profile backup run --rm backup >> backups/backup.log 2>&1
```

**Şifreleme anahtarı** ayrı volume'dedir ve varsayılan olarak yedeğe girmez. Kurulumdan hemen sonra
bir kez güvenli yere alın:

```bash
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
docker compose --profile backup run --rm backup     # önce yedek
git pull
docker compose up -d --build --wait                 # yeni imaj; şema açılışta otomatik yükseltilir
```

Geri dönüş: önceki git sürümüne dönüp imajı yeniden derleyin **ve** yükseltme öncesi yedeği geri
yükleyin. Eski kod yeni şemayı açmayı reddeder.

## 6. Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| `env file … not found` | `deploy/docker/openreporting.env` oluşturulmamış (Bölüm 2, adım 1) |
| proxy başlamıyor, `cannot load certificate key` | `deploy/docker/certs/key.pem` yok veya uid 101 okuyamıyor: `chown root:101`, `chmod 0640` |
| `Pool overlaps with other one on this address space` | `OPENREPORTING_SUBNET` / `OPENREPORTING_PROXY_IP` değerlerini boş bir alt ağa çevirin |
| Tarayıcıda 400 “Invalid host header” | `PUBLIC_URL` adresi tarayıcıdakiyle aynı değil; ek adları `ALLOWED_HOSTS` içine yazın |
| MFA kurulumu “yalnız HTTPS” diyor | Uygulamaya proxy dışında erişiliyor veya `PROXY_IP` uyuşmuyor |
| Yedek: `not writable by uid 10001` | `sudo chown 10001:10001 backups && sudo chmod 0700 backups` |
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
