#!/usr/bin/env bash
# OpenReporting — tek komutla Docker kurulumu ve bakımı (Linux, root).
#
#   sudo ./kurulum.sh             Kur (veya yarım kalan kurulumu tamamla). Yalnız adres ve yönetici sorulur.
#   sudo ./kurulum.sh guncelle    Yedek al → yeni sürümü al → yeniden derle → kontrol et
#   sudo ./kurulum.sh durum       Servisler, worker, son yedek, çıkış kilidi
#   sudo ./kurulum.sh yedek       Hemen yedek al
#
# Soru sormadan kurmak için (otomasyon): OR_ADRES, OR_YONETICI, OR_PAROLA (en az 14 karakter),
# OR_IC_AGLAR ("10.20.0.0/16 192.168.5.10/32"; boş = çıkış kilidi yok), OR_HTTPS_PORT (443),
# OR_SERTIFIKA + OR_ANAHTAR (kurum sertifikası PEM dosyaları; boş = kendinden imzalı), OR_EVET=1.
# Betik tekrar çalıştırılabilir: var olan ayar, sertifika, kullanıcı ve veriye dokunmaz.
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
ENV_FILE=deploy/docker/openreporting.env
CERT=deploy/docker/certs/cert.pem
KEY=deploy/docker/certs/key.pem
KEY_VAULT=/root/openreporting-anahtar
CRON_FILE=/etc/cron.d/openreporting-yedek
UNIT=/etc/systemd/system/openreporting-cikis-kilidi.service
ROOT_DIR="$PWD"

adim() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
tamam() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
uyari() { printf '  \033[33m!\033[0m %s\n' "$*"; }
hata() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
evet() { [ "${OR_EVET:-}" = 1 ] && return 0; local c; read -r -p "  $1 [E/h] " c; [[ ! "$c" =~ ^[hHnN] ]]; }
sor() { # sor DEĞİŞKEN "soru" "varsayılan"
  local var=$1 cur="${!1:-}" answer
  if [ -n "$cur" ] || [ "${OR_EVET:-}" = 1 ]; then printf -v "$var" '%s' "${cur:-$3}"; return; fi
  read -r -p "  $2 [${3}]: " answer
  printf -v "$var" '%s' "${answer:-$3}"
}
compose() { docker compose "$@"; }
is_ip() { [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; }

on_kosullar() {
  [ "$(id -u)" = 0 ] || hata "Root yetkisi gerekir: sudo ./kurulum.sh"
  [ "$(uname -s)" = Linux ] || hata "Bu betik Linux sunucu içindir (Windows/macOS'ta Docker Desktop ile docs/DOCKER.md)."
  adim "Docker kontrol ediliyor"
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    command -v apt-get >/dev/null || hata "Docker Engine 24+ ve Docker Compose v2 kurun, sonra betiği tekrar çalıştırın."
    evet "Docker kurulu değil. Şimdi kurulsun mu (docker.io + docker-compose-v2)?" || hata "Docker olmadan devam edilemez."
    apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io docker-compose-v2 openssl
    systemctl enable --now docker
  fi
  command -v openssl >/dev/null || { command -v apt-get >/dev/null && apt-get install -y -q openssl; }
  local version
  version="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" || hata "Docker servisi çalışmıyor: systemctl start docker"
  [ "${version%%.*}" -ge 24 ] 2>/dev/null || hata "Docker $version eski; en az 24 gerekir."
  tamam "Docker $version, $(docker compose version --short)"
}

ayarlar() {
  adim "Ayarlar"
  local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -f "$ENV_FILE" ]; then
    tamam "Var olan ayar dosyası korunuyor ($ENV_FILE)"
    OR_ADRES="$(sed -n 's#^OPENREPORTING_PUBLIC_URL=https://\([^:/]*\).*#\1#p' "$ENV_FILE")"
    return
  fi
  sor OR_ADRES "Kullanıcıların tarayıcıya yazacağı adres (DNS adı veya IP)" "$(hostname -f 2>/dev/null || echo "$ip")"
  sor OR_HTTPS_PORT "HTTPS portu" 443
  [[ "$OR_ADRES" =~ ^[A-Za-z0-9.-]+$ ]] || hata "Geçersiz adres: $OR_ADRES"
  [[ "$OR_HTTPS_PORT" =~ ^[0-9]+$ ]] || hata "Geçersiz port: $OR_HTTPS_PORT"
  local url="https://$OR_ADRES" extra="" tz
  [ "$OR_HTTPS_PORT" = 443 ] || url="$url:$OR_HTTPS_PORT"
  [ -n "$ip" ] && [ "$ip" != "$OR_ADRES" ] && extra="$ip"
  tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  cp deploy/docker/openreporting.env.example "$ENV_FILE"
  sed -i -e "s#^OPENREPORTING_PUBLIC_URL=.*#OPENREPORTING_PUBLIC_URL=$url#" \
         -e "s#^OPENREPORTING_ALLOWED_HOSTS=.*#OPENREPORTING_ALLOWED_HOSTS=$extra#" \
         -e "s#^TZ=.*#TZ=${tz:-Europe/Istanbul}#" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  if [ "$OR_HTTPS_PORT" != 443 ] && ! grep -q '^OPENREPORTING_HTTPS_PORT=' .env 2>/dev/null; then
    echo "OPENREPORTING_HTTPS_PORT=$OR_HTTPS_PORT" >> .env
  fi
  tamam "Adres: $url${extra:+ (ayrıca $extra)}"
}

sertifika() {
  adim "TLS sertifikası"
  if [ -s "$CERT" ] && [ -s "$KEY" ]; then
    tamam "Var olan sertifika korunuyor"
  elif [ -n "${OR_SERTIFIKA:-}" ]; then
    [ -s "$OR_SERTIFIKA" ] && [ -s "${OR_ANAHTAR:-}" ] || hata "OR_SERTIFIKA ve OR_ANAHTAR okunabilir PEM dosyaları olmalı"
    install -m 0644 "$OR_SERTIFIKA" "$CERT" && install -m 0640 "$OR_ANAHTAR" "$KEY"
    tamam "Kurum sertifikası yerleştirildi"
  else
    local san="DNS:$OR_ADRES" ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    is_ip "$OR_ADRES" && san="IP:$OR_ADRES"
    [ -n "$ip" ] && [ "$ip" != "$OR_ADRES" ] && san="$san,IP:$ip"
    openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -subj "/CN=$OR_ADRES" \
      -addext "subjectAltName=$san" -keyout "$KEY" -out "$CERT" 2>/dev/null
    uyari "Kendinden imzalı sertifika üretildi; tarayıcı ilk girişte uyarı gösterir."
    uyari "Kurum sertifikasını sonra $CERT ve $KEY olarak koyup: sudo ./kurulum.sh"
  fi
  chown root:101 "$KEY" && chmod 0640 "$KEY" && chmod 0644 "$CERT"
  install -d -o 10001 -g 10001 -m 0700 backups
}

baslat() {
  adim "Servisler derleniyor ve başlatılıyor (ilk seferde birkaç dakika sürer)"
  compose up -d --build --wait
  tamam "proxy, web ve worker çalışıyor"
}

kullanici_sayisi() {
  compose exec -T web python -c 'from openreporting.config import Settings; from openreporting.db import connect
with connect(Settings.from_env()) as db: print(db.execute("SELECT count(*) FROM users").fetchone()[0])'
}

yonetici() {
  adim "İlk yönetici"
  if [ "$(kullanici_sayisi)" != 0 ]; then tamam "Kullanıcılar zaten var; atlandı"; return; fi
  sor OR_YONETICI "Yönetici kullanıcı adı" yonetici
  if [ -n "${OR_PAROLA:-}" ]; then
    [ "${#OR_PAROLA}" -ge 14 ] || hata "Parola en az 14 karakter olmalı"
    compose exec -T -e OR_PAROLA web python -c 'import os, sys
from openreporting.config import Settings; from openreporting.security import create_user
create_user(Settings.from_env(), sys.argv[1], os.environ["OR_PAROLA"], "admin")' "$OR_YONETICI"
  else
    echo "  Parolayı iki kez yazın (en az 14 karakter, ekranda görünmez):"
    compose exec web openreporting create-user "$OR_YONETICI" --role admin
  fi
  tamam "Yönetici '$OR_YONETICI' oluşturuldu (ilk girişte telefonla iki adımlı giriş kurulur)"
}

anahtar() {
  adim "Şifreleme anahtarının kopyası"
  install -d -m 0700 "$KEY_VAULT"
  if compgen -G "$KEY_VAULT/secret.key*" >/dev/null; then tamam "Kopya zaten var: $KEY_VAULT"; return; fi
  compose cp web:/run/openreporting-key/secret.key "$KEY_VAULT/secret.key"
  chmod 0600 "$KEY_VAULT/secret.key"
  tamam "Kopyalandı: $KEY_VAULT/secret.key"
  uyari "Bu dosyayı sunucu dışında güvenli bir yere (kasa/parola yöneticisi) taşıyın."
}

gece_yedegi() {
  adim "Gece yedeği"
  [ -d /etc/cron.d ] || { uyari "cron yok; yedek için: sudo ./kurulum.sh yedek"; return; }
  cat > "$CRON_FILE" <<CRON
# OpenReporting gece yedeği (kurulum.sh oluşturdu)
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root cd "$ROOT_DIR" && docker compose --profile backup run --rm -T backup >> /var/log/openreporting-yedek.log 2>&1
CRON
  chmod 0644 "$CRON_FILE"
  tamam "Her gece 02:30 → $ROOT_DIR/backups (14 gün saklanır)"
}

cikis_kilidi() {
  adim "İnternet çıkış kilidi (önerilir)"
  if [ -f "$UNIT" ]; then tamam "Zaten etkin ($UNIT)"; return; fi
  if [ -z "${OR_IC_AGLAR:-}" ] && [ "${OR_EVET:-}" != 1 ]; then
    echo "  Kurulumdan sonra uygulamanın internete ihtiyacı yoktur. Uygulamanın erişeceği iç ağları"
    echo "  yazarsanız (Zabbix, veritabanları, SMTP, LDAP, DNS) diğer her yere çıkış kapatılır."
    read -r -p "  İç ağlar (örn. 10.0.0.0/8 192.168.5.10/32; boş = şimdilik atla): " OR_IC_AGLAR
  fi
  if [ -z "${OR_IC_AGLAR:-}" ]; then uyari "Atlandı. Sonra: sudo OR_IC_AGLAR='…' ./kurulum.sh"; return; fi
  local nets; read -r -a nets <<< "$OR_IC_AGLAR"
  bash deploy/docker/egress-lock.sh apply "${nets[@]}" >/dev/null || hata "Geçersiz ağ listesi: $OR_IC_AGLAR"
  if command -v systemctl >/dev/null; then
    cat > "$UNIT" <<UNITFILE
[Unit]
Description=OpenReporting internet çıkış kilidi
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$ROOT_DIR
ExecStart=/usr/bin/env bash deploy/docker/egress-lock.sh apply $OR_IC_AGLAR
ExecStop=/usr/bin/env bash deploy/docker/egress-lock.sh remove
[Install]
WantedBy=multi-user.target
UNITFILE
    systemctl daemon-reload && systemctl enable --now openreporting-cikis-kilidi.service >/dev/null 2>&1
  fi
  tamam "Yalnız şu ağlara çıkış açık: $OR_IC_AGLAR (yeniden başlatmada korunur)"
}

saat() {
  if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ]; then return; fi
  uyari "Sunucu saati senkron görünmüyor. İki adımlı giriş doğru saat ister: iç NTP sunucusunu ayarlayın (timedatectl)."
}

kontrol() {
  adim "Son kontrol"
  if compose exec -T web openreporting doctor >/dev/null; then tamam "doctor: sorun yok"
  else uyari "doctor uyarı verdi: docker compose exec web openreporting doctor"; fi
}

kur() {
  on_kosullar; ayarlar; sertifika; baslat; yonetici; anahtar; gece_yedegi; cikis_kilidi; saat; kontrol
  local url; url="$(sed -n 's#^OPENREPORTING_PUBLIC_URL=##p' "$ENV_FILE")"
  printf '\n\033[1;32m══ Kurulum tamam ══\033[0m\n'
  echo "  Adres     : $url"
  echo "  Sonra     : Yönetim → Sistem ayarları (e-posta, LDAP) ve Yönetim → Veri kaynakları"
  echo "  Durum     : sudo ./kurulum.sh durum      Güncelleme: sudo ./kurulum.sh guncelle"
}

guncelle() {
  on_kosullar
  [ -f "$ENV_FILE" ] || hata "Önce kurulum yapın: sudo ./kurulum.sh"
  if [ -f "$UNIT" ]; then
    systemctl stop openreporting-cikis-kilidi.service   # derleme internete çıkmalı
    trap 'systemctl start openreporting-cikis-kilidi.service' EXIT
  fi
  adim "Önce yedek"; compose --profile backup run --rm -T backup
  if [ -d .git ]; then adim "Yeni sürüm alınıyor"; git pull --ff-only; fi
  baslat; kontrol
  tamam "Güncelleme tamam (geri dönüş: önceki sürüm + son yedek, bkz. docs/DOCKER.md)"
}

durum() {
  compose ps
  if compose exec -T web openreporting worker-health >/dev/null; then tamam "worker çalışıyor"; else uyari "worker sinyali yok"; fi
  local last; last="$(find backups -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)"
  if [ -n "$last" ]; then tamam "son yedek: ${last#backups/}"; else uyari "henüz yedek yok"; fi
  if [ -f "$UNIT" ]; then tamam "çıkış kilidi etkin"; else uyari "çıkış kilidi yok"; fi
}

case "${1:-kur}" in
  kur) kur ;;
  guncelle) guncelle ;;
  durum) [ "$(id -u)" = 0 ] || hata "sudo ./kurulum.sh durum"; durum ;;
  yedek) [ "$(id -u)" = 0 ] || hata "sudo ./kurulum.sh yedek"; compose --profile backup run --rm -T backup ;;
  *) echo "Kullanım: sudo ./kurulum.sh [kur|guncelle|durum|yedek]" >&2; exit 2 ;;
esac
