#!/usr/bin/env bash
# Distribution boundaries only. Sourcing this file never changes the host.
# shellcheck disable=SC2034

detect_platform() {
  local id="$1" version="$2" major minor
  major="${version%%.*}"
  case "$id" in
    # Kali is Debian-based (same apt/systemd/nginx layout); supported for test labs.
    ubuntu|debian|kali)
      PLATFORM_FAMILY=debian
      PLATFORM_PYTHON=''
      NGINX_SITE=/etc/nginx/sites-available/openreporting.conf
      TLS_CERT_DEFAULT=/etc/ssl/certs/openreporting.crt
      TLS_KEY_DEFAULT=/etc/ssl/private/openreporting.key
      ;;
    ol)
      case "$version" in
        8.*) minor="${version#8.}"; if ! [[ "$minor" =~ ^[0-9]+$ ]] || [ "$minor" -lt 10 ]; then die 'Oracle Linux 8.10 veya sonrası gerekli'; fi ;;
        9.*) minor="${version#9.}"; if ! [[ "$minor" =~ ^[0-9]+$ ]] || [ "$minor" -lt 4 ]; then die 'Oracle Linux 9.4 veya sonrası gerekli'; fi ;;
        10.*|10) ;;
        *) die 'Oracle Linux hedefleri: 8.10, 9 ve 10; eski sürümler doğrulanmadı' ;;
      esac
      PLATFORM_FAMILY=oracle
      PLATFORM_PYTHON=python3.12
      [ "$major" != 10 ] || PLATFORM_PYTHON=python3
      NGINX_SITE=/etc/nginx/conf.d/openreporting.conf
      TLS_CERT_DEFAULT=/etc/pki/tls/certs/openreporting.crt
      TLS_KEY_DEFAULT=/etc/pki/tls/private/openreporting.key
      ;;
    *) die 'Desteklenen kurulum aileleri: Ubuntu/Debian/Kali ve Oracle Linux' ;;
  esac
  PLATFORM_ID="$id" PLATFORM_VERSION="$version" PLATFORM_MAJOR="$major"
}

load_platform() {
  [ -r /etc/os-release ] || die '/etc/os-release bulunamadı'
  # shellcheck disable=SC1091
  . /etc/os-release
  detect_platform "${ID:-}" "${VERSION_ID:-}"
}

# Full package-manager output goes to this log; the console shows stages, plan and the failure tail.
INSTALL_LOG="${OPENREPORTING_INSTALL_LOG:-/var/log/openreporting-install.log}"
APT_OPTS=(-o Acquire::Retries=3 -o Dpkg::Use-Pty=0)

run_logged() {
  local stage="$1" rc=0
  shift
  printf '\n### %s: %s\n' "$stage" "$*" >> "$INSTALL_LOG"
  "$@" >> "$INSTALL_LOG" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && return 0
  warn "Başarısız adım: $stage (çıkış kodu $rc)"
  warn "Komut: $*"
  tail -n 25 "$INSTALL_LOG" >&2
  return "$rc"
}

apt_mirror_help() {
  warn 'Paket deposuna ulaşılamadı veya paket indirilemedi. Kaynaklar otomatik DEĞİŞTİRİLMEDİ.'
  warn 'Kontrol edin: ağ/DNS/proxy, /etc/apt/sources.list ve /etc/apt/sources.list.d/*'
  warn 'HTTP aynası engelleniyorsa kaynaklarda https:// ayna kullanın, ardından: sudo apt-get update'
  die "Ayrıntılı çıktı: $INSTALL_LOG — sorun giderildikten sonra kurulumu aynı komutla tekrar çalıştırın"
}

# apt-get update can exit 0 while some indexes failed; treat that as a broken mirror.
apt_update_checked() {
  local before
  before="$(wc -l < "$INSTALL_LOG" 2>/dev/null || echo 0)"
  run_logged 'Paket listeleri güncelleniyor' apt-get "${APT_OPTS[@]}" update || apt_mirror_help
  if tail -n "+$((before + 1))" "$INSTALL_LOG" | grep -Eq '^(W|E): (Failed to fetch|Some index files failed)'; then
    tail -n "+$((before + 1))" "$INSTALL_LOG" | grep -E '^(W|E): ' >&2 || true
    apt_mirror_help
  fi
}

# Prints "new upgraded removed" from an apt-get -s plan on stdin.
apt_plan_counts() {
  awk '/^Inst /{ if ($3 ~ /^\[/) u++; else n++ } /^Remv /{ r++ } END { printf "%d %d %d\n", n, u, r }'
}

apt_preflight() {
  local allow_removal="$1" plan counts new upgraded removed
  shift
  plan="$(LC_ALL=C apt-get "${APT_OPTS[@]}" -s install -y "$@" 2>&1)" || {
    printf '%s\n' "$plan" >> "$INSTALL_LOG"; printf '%s\n' "$plan" | tail -n 15 >&2
    die "Paket planı çözülemedi (apt-get -s). Ayrıntı: $INSTALL_LOG"
  }
  printf '\n### Paket planı (simülasyon)\n%s\n' "$plan" >> "$INSTALL_LOG"
  counts="$(printf '%s\n' "$plan" | apt_plan_counts)"
  read -r new upgraded removed <<< "$counts"
  ok "Paket planı: $new yeni, $upgraded yükseltme, $removed kaldırma"
  [ "$upgraded" -le 50 ] || warn "Çok sayıda yükseltme planlandı ($upgraded); sistem güncel değil. Ayrıntı: $INSTALL_LOG"
  if [ "$removed" -gt 0 ]; then
    printf '%s\n' "$plan" | awk '/^Remv /{ print "    kaldırılacak: " $2 }' >&2
    [ "$allow_removal" -eq 1 ] || die 'Kurulum mevcut paketleri kaldırmayı gerektiriyor; hiçbir şey değiştirilmedi. İnceleyip onaylıyorsanız --allow-package-removal ile tekrar çalıştırın.'
    warn '--allow-package-removal verildi; yukarıdaki paketler kaldırılacak'
  fi
}

install_platform_packages() {
  local nginx="$1" deadsnakes="$2" allow_removal="${3:-0}"
  local pkgs
  if [ "$PLATFORM_FAMILY" = debian ]; then
    export DEBIAN_FRONTEND=noninteractive
    pkgs=(python3 python3-venv python3-pip fonts-dejavu-core sqlite3 ca-certificates rsync curl openssl tzdata)
    [ "$nginx" -eq 1 ] && pkgs+=(nginx)
    apt_update_checked
    apt_preflight "$allow_removal" "${pkgs[@]}"
    # Download first: a broken mirror fails here before anything is unpacked.
    run_logged 'Paketler indiriliyor' apt-get "${APT_OPTS[@]}" install -y --download-only "${pkgs[@]}" || apt_mirror_help
    run_logged 'Paketler kuruluyor' apt-get "${APT_OPTS[@]}" install -y "${pkgs[@]}" \
      || die "Paket kurulumu başarısız. Ayrıntı: $INSTALL_LOG (dpkg yarım kaldıysa: sudo dpkg --configure -a)"
  else
    [ "$deadsnakes" -eq 0 ] || die '--use-deadsnakes yalnız Ubuntu içindir'
    pkgs=(sqlite ca-certificates rsync curl openssl tzdata dejavu-sans-fonts policycoreutils-python-utils)
    if [ "$PLATFORM_MAJOR" = 10 ]; then
      pkgs+=(python3 python3-pip)
    else
      # Parallel interpreter: never replace Oracle's system Python or DNF runtime.
      pkgs+=(python3.12 python3.12-pip)
    fi
    if [ "$nginx" -eq 1 ]; then
      # OL8's default old stream is retired. Do not reset/switch an existing stream silently.
      [ "$PLATFORM_MAJOR" != 8 ] || run_logged 'nginx 1.24 modülü' dnf module enable -y nginx:1.24 || die "dnf modül etkinleştirme başarısız. Ayrıntı: $INSTALL_LOG"
      pkgs+=(nginx)
    fi
    run_logged 'Paketler kuruluyor' dnf install -y "${pkgs[@]}" \
      || die "Paket kurulumu başarısız (depo erişimi/abonelik?). Ayrıntı: $INSTALL_LOG"
  fi
  ok "Sistem paketleri hazır (tam çıktı: $INSTALL_LOG)"
}

http_backend_port_labeled() {
  LC_ALL=C semanage port -l | awk '
    $1=="http_port_t" && $2=="tcp" {
      for(i=3;i<=NF;i++) {
        gsub(/,/,"",$i)
        if($i=="8810") found=1
        if($i ~ /^[0-9]+-[0-9]+$/) {split($i,r,"-"); if(r[1]<=8810 && r[2]>=8810) found=1}
      }
    } END {exit !found}'
}

configure_selinux_proxy() {
  local apply="$1" mode
  [ "$PLATFORM_FAMILY" = oracle ] || return 0
  command -v getenforce >/dev/null || die 'SELinux araçları bulunamadı'
  mode="$(getenforce)"
  [ "$mode" = Enforcing ] || [ "$mode" = Permissive ] || { warn 'SELinux Disabled; enforcing kabulü ayrıca gerekli'; return 0; }
  if ! http_backend_port_labeled; then
    [ "$apply" -eq 1 ] || die 'SELinux 8810/http_port_t gerekli; --configure-selinux veya kurum politikasıyla hazırlayın'
    # Do not modify a port already explicitly owned by another service/type.
    semanage port -a -t http_port_t -p tcp 8810 || die '8810 etiketi değiştirilemedi; mevcut port politikasını işletmeci incelemeli'
  fi
  if ! getsebool httpd_can_network_relay | grep -q -- '--> on$'; then
    [ "$apply" -eq 1 ] || die 'SELinux nginx relay izni gerekli; --configure-selinux veya kurum politikasıyla hazırlayın'
    setsebool -P httpd_can_network_relay on
  fi
  ok "SELinux $mode korunuyor; yalnız HTTP relay ve 8810 port tipi hazır"
}

enable_site() {
  if [ "$PLATFORM_FAMILY" = debian ]; then
    install -d /etc/nginx/sites-available /etc/nginx/sites-enabled
    ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/openreporting.conf
    [ ! -e /etc/nginx/sites-enabled/default ] || warn "nginx default sitesi etkin; alan adı/port çakışmasını inceleyin"
  fi
}

open_platform_firewall() {
  local zone
  if [ "$PLATFORM_FAMILY" = oracle ]; then
    if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
      zone="$(firewall-cmd --get-default-zone)"
      firewall-cmd --zone="$zone" --add-service=http --add-service=https
      firewall-cmd --permanent --zone="$zone" --add-service=http --add-service=https
      ok "firewalld $zone: HTTP/HTTPS açıldı; ağ arayüzünün zone eşlemesini doğrulayın"
    else
      warn 'firewalld etkin değil; başlatılmadı veya güvenlik duvarı politikası değiştirilmedi'
    fi
  elif command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow 'Nginx Full' >/dev/null
  fi
}

render_unit() {
  local file="$1" version="$2"
  if ! [[ "$version" =~ ^[0-9]+$ ]] || [ "$version" -lt 239 ]; then die 'systemd >= 239 gerekli'; fi
  awk -F= -v v="$version" '
    $1=="ProtectHostname" && v<242 {next}
    $1=="ProtectKernelLogs" && v<244 {next}
    ($1=="ProtectProc" || $1=="ProcSubset") && v<247 {next}
    {print}' "$file"
}

install_service_units() {
  local file version
  version="$(systemctl --version | awk 'NR==1 {print $2}')"
  if ! [[ "$version" =~ ^[0-9]+$ ]] || [ "$version" -lt 239 ]; then die 'systemd >= 239 gerekli; servis dosyaları değiştirilmedi'; fi
  for file in "$OPENREPORTING_APP"/deploy/systemd/openreporting-*.service "$OPENREPORTING_APP"/deploy/systemd/openreporting-*.timer; do
    render_unit "$file" "$version" > "/etc/systemd/system/$(basename "$file")"
    chmod 0644 "/etc/systemd/system/$(basename "$file")"
  done
  [ "$version" -ge 247 ] || warn 'Eski systemd: ProtectProc/ProcSubset ve sürüme bağlı ek korumalar yok; çekirdek servis kısıtları korunur'
}
