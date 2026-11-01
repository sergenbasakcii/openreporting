#!/usr/bin/env bash
# OpenReporting native Linux installer (Ubuntu/Debian + Oracle Linux).
#
#   sudo ./deploy/install-ubuntu.sh --domain openreporting.example.com --self-signed --admin sergen
#   sudo ./deploy/install-ubuntu.sh --domain openreporting.example.com --cert /etc/ssl/certs/openreporting.pem --key /etc/ssl/private/openreporting.key
#   sudo ./deploy/install-ubuntu.sh --no-nginx            # API on 127.0.0.1:8810 only
#
# Options:
#   --domain NAME        nginx server_name and OPENREPORTING_PUBLIC_URL (default: hostname -f)
#   --cert PATH --key PATH  existing TLS certificate + key for nginx
#   --self-signed        generate a self-signed certificate (replace with a corporate cert later)
#   --no-nginx           do not install/configure nginx
#   --admin USER         create this admin account (password prompted on the terminal)
#   --python PATH        Python >= 3.11 interpreter to use
#   --use-deadsnakes     on Ubuntu 22.04 without Python >= 3.11, install python3.12 from ppa:deadsnakes
#   --wheelhouse DIR     offline install: pip wheels directory (no internet needed)
#   --open-firewall      if firewall is active, allow HTTP/HTTPS
#   --configure-selinux  opt in to Oracle nginx relay + 8810 HTTP port labeling
#   --allow-package-removal  accept an apt plan that removes installed packages (reviewed first)
#   -y                   non-interactive (skip optional prompts)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=deploy/lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck source=deploy/platform.sh
. "$SCRIPT_DIR/platform.sh"

DOMAIN="$(hostname -f 2>/dev/null || hostname)"
CERT="" KEY="" SELF_SIGNED=0 NGINX=1 ADMIN="" DEADSNAKES=0 WHEELHOUSE="" OPEN_FW=0 YES=0 SELINUX=0 EXPECT_OS="" ALLOW_REMOVAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --cert) CERT="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --self-signed) SELF_SIGNED=1; shift ;;
    --no-nginx) NGINX=0; shift ;;
    --admin) ADMIN="$2"; shift 2 ;;
    --python) OPENREPORTING_PYTHON="$2"; shift 2 ;;
    --use-deadsnakes) DEADSNAKES=1; shift ;;
    --wheelhouse) WHEELHOUSE="$(cd "$2" && pwd)"; shift 2 ;;
    --open-firewall) OPEN_FW=1; shift ;;
    --configure-selinux) SELINUX=1; shift ;;
    --expect-os) EXPECT_OS="$2"; shift 2 ;;
    --allow-package-removal) ALLOW_REMOVAL=1; shift ;;
    -y|--yes) YES=1; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) die "Bilinmeyen seçenek: $1 (--help)" ;;
  esac
done

require_root
install -m 0600 /dev/null "$INSTALL_LOG.new" && mv -f "$INSTALL_LOG.new" "$INSTALL_LOG"
printf '# OpenReporting kurulumu %s
' "$(date -Is)" >> "$INSTALL_LOG"
trap 'rc=$?; [ "$rc" -eq 0 ] || warn "Kurulum yarıda kaldı (çıkış $rc). Günlük: $INSTALL_LOG — sorunu giderip aynı komutla tekrar çalıştırabilirsiniz; mevcut ayar, anahtar ve veriler korunur."' EXIT
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Geçersiz alan adı: $DOMAIN"
load_platform
[ -z "$EXPECT_OS" ] || [ "$EXPECT_OS" = "$PLATFORM_FAMILY" ] || die 'Kurulum betiği bu işletim sistemi ailesi için değil'
[ "$DEADSNAKES" -eq 0 ] || [ "$PLATFORM_ID" = ubuntu ] || die '--use-deadsnakes yalnız Ubuntu içindir'
ok "İşletim sistemi: $PLATFORM_ID $PLATFORM_VERSION"
command -v systemctl >/dev/null || die 'systemd gerekli'
if [ -r /proc/sys/crypto/fips_enabled ] && [ "$(cat /proc/sys/crypto/fips_enabled)" = 1 ]; then
  die 'FIPS etkin ortam bu kripto paketiyle doğrulanmadı; FIPS/kripto politikası değiştirilmedi'
fi

log 'Sistem paketleri kuruluyor'
install_platform_packages "$NGINX" "$DEADSNAKES" "$ALLOW_REMOVAL"
[ "$NGINX" -eq 0 ] || configure_selinux_proxy "$SELINUX"

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  if [ "$DEADSNAKES" -eq 1 ]; then
    log "Python 3.12 deadsnakes PPA üzerinden kuruluyor"
    run_logged 'software-properties-common' apt-get "${APT_OPTS[@]}" install -y software-properties-common || apt_mirror_help
    run_logged 'deadsnakes PPA' add-apt-repository -y ppa:deadsnakes/ppa || apt_mirror_help
    apt_update_checked
    run_logged 'python3.12' apt-get "${APT_OPTS[@]}" install -y python3.12 python3.12-venv || apt_mirror_help
    PY="$(command -v python3.12)"
  else
    die "Python >= 3.11 bulunamadı; dağıtım paketlerini veya --python yolunu doğrulayın."
  fi
fi
ok "Python: $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"
"$PY" -c 'import venv' 2>/dev/null || die "Seçilen Python venv modülü içermiyor"

log "Servis kullanıcısı ve dizinler"
if ! id "$OPENREPORTING_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$OPENREPORTING_DATA" --no-create-home --shell /usr/sbin/nologin "$OPENREPORTING_USER"
fi
install -d -o "$OPENREPORTING_USER" -g "$OPENREPORTING_USER" -m 0750 "$OPENREPORTING_DATA"
install -d -o root -g "$OPENREPORTING_USER" -m 0750 "$OPENREPORTING_ETC"
install -d -o root -g root -m 0700 "$OPENREPORTING_BACKUPS"
ok "kullanıcı=$OPENREPORTING_USER veri=$OPENREPORTING_DATA yapılandırma=$OPENREPORTING_ETC"

log "Uygulama kodu $OPENREPORTING_APP içine kopyalanıyor"
sync_code "$SRC"

log "Python sanal ortamı ve bağımlılıklar"
if [ ! -x "$OPENREPORTING_VENV/bin/python" ] || ! python_ok "$OPENREPORTING_VENV/bin/python"; then
  rm -rf "$OPENREPORTING_VENV"
  "$PY" -m venv "$OPENREPORTING_VENV"
fi
install_package "$WHEELHOUSE"
ok "$("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print("openreporting", openreporting.__version__)')"

log "Yapılandırma ve şifreleme anahtarı"
if [ ! -f "$OPENREPORTING_ENV" ]; then
  sed -e "s#^OPENREPORTING_PUBLIC_URL=.*#OPENREPORTING_PUBLIC_URL=https://$DOMAIN#" \
      -e "s#^OPENREPORTING_COOKIE_SECURE=.*#OPENREPORTING_COOKIE_SECURE=$([ "$NGINX" -eq 1 ] && echo true || echo false)#" \
      "$OPENREPORTING_APP/deploy/openreporting.env.example" > "$OPENREPORTING_ENV"
  ok "$OPENREPORTING_ENV oluşturuldu"
else
  ok "$OPENREPORTING_ENV korunuyor (üzerine yazılmadı)"
fi
chown root:"$OPENREPORTING_USER" "$OPENREPORTING_ENV"; chmod 0640 "$OPENREPORTING_ENV"
ACTIVE_KEY="$(as_openreporting "$OPENREPORTING_VENV/bin/python" -c 'from openreporting.config import Settings; from openreporting.secrets_store import installation_key_path; print(installation_key_path(Settings.from_env()))')"
if [ "$ACTIVE_KEY" = "$OPENREPORTING_ETC/secret.key" ] && [ ! -f "$ACTIVE_KEY" ]; then
  umask 077
  "$OPENREPORTING_VENV/bin/python" -c 'from cryptography.fernet import Fernet; import sys; sys.stdout.write(Fernet.generate_key().decode())' > "$OPENREPORTING_ETC/secret.key"
  ok "Şifreleme anahtarı üretildi: $OPENREPORTING_ETC/secret.key (yedeklerin parçasıdır!)"
fi
if [ "$ACTIVE_KEY" = "$OPENREPORTING_ETC/secret.key" ]; then
  chown root:"$OPENREPORTING_USER" "$ACTIVE_KEY"; chmod 0640 "$ACTIVE_KEY"
fi
# Custom existing keyrings retain their ownership/path; missing custom keys are never generated.
as_openreporting "$OPENREPORTING_VENV/bin/python" -c 'from openreporting.config import Settings; from openreporting.secrets_store import key_path, read_keys; read_keys(key_path(Settings.from_env()))'

log "Veritabanı hazırlanıyor (şema geçişleri)"
as_openreporting "$OPENREPORTING_VENV/bin/openreporting" init

log "systemd servisleri"
install_service_units
systemctl daemon-reload
systemctl enable --quiet openreporting-web.service openreporting-worker.service openreporting-backup.timer
systemctl restart openreporting-web.service
systemctl restart openreporting-worker.service
systemctl start openreporting-backup.timer
if health_check; then ok "API yanıt veriyor (127.0.0.1:8810)"; else
  journalctl -u openreporting-web -n 40 --no-pager >&2 || true
  die "openreporting-web başlamadı; yukarıdaki günlüklere bakın"
fi

if [ "$NGINX" -eq 1 ]; then
  log "nginx (HTTPS ters vekil)"
  if [ -z "$CERT" ] || [ -z "$KEY" ]; then
    CERT="$TLS_CERT_DEFAULT"
    KEY="$TLS_KEY_DEFAULT"
    [ -d "$(dirname "$CERT")" ] || install -d -m 0755 "$(dirname "$CERT")"
    [ -d "$(dirname "$KEY")" ] || install -d -m 0700 "$(dirname "$KEY")"
    if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
      [ "$SELF_SIGNED" -eq 1 ] || die "TLS sertifikası gerekli: --cert/--key verin veya geçici olarak --self-signed kullanın"
      openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -subj "/CN=$DOMAIN" \
        -addext "subjectAltName=DNS:$DOMAIN" -keyout "$KEY" -out "$CERT" >/dev/null 2>&1
      chmod 0600 "$KEY"
      warn "Kendinden imzalı sertifika üretildi; kurum sertifikasıyla değiştirin: $CERT"
    fi
  fi
  if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then die "Sertifika/anahtar bulunamadı: $CERT / $KEY"; fi
  if [ -L "$NGINX_SITE" ] || { [ -e "$NGINX_SITE" ] && ! grep -q '^# OpenReporting — nginx' "$NGINX_SITE"; }; then
    die "Uygulamaya ait olmayan nginx dosyasının üzerine yazılmadı: $NGINX_SITE"
  fi
  sed -e "s#__DOMAIN__#$DOMAIN#g" -e "s#__CERT__#$CERT#g" -e "s#__KEY__#$KEY#g" \
    "$OPENREPORTING_APP/deploy/nginx/openreporting.conf" > "$NGINX_SITE"
  enable_site
  if [ "$PLATFORM_FAMILY" = oracle ] && command -v restorecon >/dev/null; then
    restorecon "$NGINX_SITE"
    # Standard PKI paths inherit the distribution policy. Never relabel arbitrary custom paths.
    if [ "$CERT" = "$TLS_CERT_DEFAULT" ] && [ "$KEY" = "$TLS_KEY_DEFAULT" ]; then restorecon "$CERT" "$KEY"; fi
  fi
  nginx -t >/dev/null 2>&1 || { nginx -t; die "nginx yapılandırma testi başarısız"; }
  systemctl enable --quiet nginx
  systemctl reload nginx || systemctl restart nginx
  ok "https://$DOMAIN"
  [ "$OPEN_FW" -eq 0 ] || open_platform_firewall
fi

HAS_ADMIN="$(as_openreporting "$OPENREPORTING_VENV/bin/python" -c '
import sqlite3, os
db = sqlite3.connect(os.path.join(os.environ.get("OPENREPORTING_DATA_DIR", "/var/lib/openreporting"), "state.sqlite3"))
print(db.execute("SELECT COUNT(*) FROM users WHERE role=? AND active=1", ("admin",)).fetchone()[0])' 2>/dev/null || echo 0)"
if [ -n "$ADMIN" ]; then
  log "Yönetici hesabı: $ADMIN (parola en az 14 karakter)"
  as_openreporting_tty "$OPENREPORTING_VENV/bin/openreporting" create-user "$ADMIN" --role admin
elif [ "${HAS_ADMIN:-0}" = "0" ] && [ "$YES" -eq 0 ] && [ -t 0 ]; then
  read -r -p "Henüz yönetici yok. Şimdi oluşturulacak kullanıcı adı (boş = atla): " ADMIN_NAME
  if [ -n "$ADMIN_NAME" ]; then
    as_openreporting_tty "$OPENREPORTING_VENV/bin/openreporting" create-user "$ADMIN_NAME" --role admin
  fi
elif [ "${HAS_ADMIN:-0}" = "0" ]; then
  warn "Henüz yönetici yok. Oluşturmak için:"
  echo "    sudo $OPENREPORTING_APP/deploy/openreporting-admin.sh create-user <kullanıcı> --role admin"
fi

log "Kurulum kontrolü"
DOCTOR=tamam
as_openreporting "$OPENREPORTING_VENV/bin/openreporting" doctor || { DOCTOR='uyarı var (yukarıda)'; warn "doctor bazı uyarılar verdi (yukarıda)"; }
ADMINS="$(as_openreporting "$OPENREPORTING_VENV/bin/python" -c '
import sqlite3, os
db = sqlite3.connect(os.path.join(os.environ.get("OPENREPORTING_DATA_DIR", "/var/lib/openreporting"), "state.sqlite3"))
print(", ".join(r[0] for r in db.execute("SELECT username FROM users WHERE role=? AND active=1 ORDER BY username", ("admin",))))' 2>/dev/null || true)"
MFA_ROLES="$(sed -n 's/^OPENREPORTING_MFA_REQUIRED_ROLES=//p' "$OPENREPORTING_ENV" | tail -n 1)"
service_state() { systemctl is-active "$1" 2>/dev/null || true; }
trap - EXIT
echo
ok "OpenReporting $("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print(openreporting.__version__)') kuruldu."
echo "   Adres     : $([ "$NGINX" -eq 1 ] && echo "https://$DOMAIN" || echo "http://127.0.0.1:8810 (yerel)")"
if [ "$NGINX" -eq 1 ]; then
  echo "   TLS       : $CERT$([ "$CERT" = "$TLS_CERT_DEFAULT" ] && [ "$SELF_SIGNED" -eq 1 ] && echo ' (kendinden imzalı; tarayıcı uyarısı normaldir)')"
fi
echo "   Servisler : web=$(service_state openreporting-web) worker=$(service_state openreporting-worker) yedek-zamanlayıcı=$(service_state openreporting-backup.timer)"
echo "   Kontrol   : doctor $DOCTOR"
echo "   Yönetici  : ${ADMINS:-yok — oluşturun: sudo $OPENREPORTING_APP/deploy/openreporting-admin.sh create-user <kullanıcı> --role admin}"
echo "   Günlükler : journalctl -u openreporting-web -u openreporting-worker -f · kurulum: $INSTALL_LOG"
echo "   Ayarlar   : $OPENREPORTING_ENV  (değişiklikten sonra: systemctl restart openreporting-web openreporting-worker)"
echo "   Yedek     : $OPENREPORTING_BACKUPS (her gece 02:30) · elle: systemctl start openreporting-backup"
echo
echo "   Sonraki adımlar:"
echo "    1. Adresi tarayıcıda açın; yönetici kullanıcı adı ve parolasıyla giriş yapın."
if [ -n "$MFA_ROLES" ]; then
  echo "    2. İlk girişte iki adımlı giriş istenir ($MFA_ROLES): telefondaki doğrulayıcıyla QR kodu okutun, 6 haneli kodu girin, kurtarma kodlarını saklayın."
else
  echo "    2. Profil sayfasından iki adımlı girişi açmanız önerilir."
fi
echo "    3. Erişim sorunu: sudo $OPENREPORTING_APP/deploy/openreporting-admin.sh reset-password <kullanıcı>"
echo "       Telefon kaybı/MFA sıfırlama: sudo $OPENREPORTING_APP/deploy/openreporting-admin.sh reset-mfa <kullanıcı> --reason lost-device"
