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

install_platform_packages() {
  local nginx="$1" deadsnakes="$2"
  local pkgs
  if [ "$PLATFORM_FAMILY" = debian ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    pkgs=(python3 python3-venv python3-pip fonts-dejavu-core sqlite3 ca-certificates rsync curl openssl tzdata)
    [ "$nginx" -eq 1 ] && pkgs+=(nginx)
    apt-get install -y -qq "${pkgs[@]}" >/dev/null
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
      [ "$PLATFORM_MAJOR" != 8 ] || dnf module enable -y nginx:1.24
      pkgs+=(nginx)
    fi
    dnf install -y "${pkgs[@]}"
  fi
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
