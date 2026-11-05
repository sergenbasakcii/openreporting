#!/usr/bin/env bash
# Host firewall egress lock for the OpenReporting containers (Linux Docker Engine, run as root).
#
#   sudo deploy/docker/egress-lock.sh apply  [ALLOWED_CIDR ...]   # e.g. 10.20.0.0/16 192.168.5.10/32
#   sudo deploy/docker/egress-lock.sh remove
#   sudo deploy/docker/egress-lock.sh status
#
# Containers on the OpenReporting subnet may answer users (replies to inbound connections), talk to each
# other and open new connections ONLY to the allowed networks (Zabbix, databases, SMTP, LDAP, NTP …).
# Everything else — the internet in particular — is rejected. Rules live in Docker's DOCKER-USER chain,
# which Docker evaluates before its own rules and never rewrites. They do not survive a reboot on their
# own: persist them with your distribution's tool (iptables-persistent, firewalld direct rules, …) or
# run "apply" from a systemd unit after docker.service.
set -euo pipefail

SUBNET="${OPENREPORTING_SUBNET:-172.30.88.0/24}"
CHAIN=OPENREPORTING-EGRESS

need_root() { [ "$(id -u)" = 0 ] || { echo "Run as root (sudo)" >&2; exit 2; }; }
valid_cidr() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/([0-9]|[12][0-9]|3[0-2]))?$ ]]; }

remove() {
  while iptables -C DOCKER-USER -s "$SUBNET" -j "$CHAIN" 2>/dev/null; do iptables -D DOCKER-USER -s "$SUBNET" -j "$CHAIN"; done
  if iptables -nL "$CHAIN" >/dev/null 2>&1; then iptables -F "$CHAIN" && iptables -X "$CHAIN"; fi
}

apply() {
  for cidr in "$@"; do valid_cidr "$cidr" || { echo "Not an IPv4 network: $cidr" >&2; exit 2; }; done
  iptables -nL DOCKER-USER >/dev/null 2>&1 || { echo "DOCKER-USER chain missing: is Docker running with iptables enabled?" >&2; exit 2; }
  remove
  iptables -N "$CHAIN"
  # Replies to users who reached the published 80/443 ports, and traffic between the containers.
  iptables -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  iptables -A "$CHAIN" -d "$SUBNET" -j RETURN
  for cidr in "$@"; do iptables -A "$CHAIN" -d "$cidr" -j RETURN; done
  iptables -A "$CHAIN" -j REJECT --reject-with icmp-admin-prohibited
  iptables -I DOCKER-USER 1 -s "$SUBNET" -j "$CHAIN"
  echo "Egress locked for $SUBNET; allowed: ${*:-only the OpenReporting subnet}"
}

need_root
case "${1:-}" in
  apply) shift; apply "$@" ;;
  remove) remove; echo "Egress lock removed for $SUBNET" ;;
  status) iptables -nvL "$CHAIN" 2>/dev/null || echo "Egress lock is not applied" ;;
  *) echo "Usage: $0 apply [ALLOWED_CIDR ...] | remove | status" >&2; exit 2 ;;
esac
