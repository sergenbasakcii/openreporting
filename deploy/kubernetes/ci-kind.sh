#!/usr/bin/env bash
# CI acceptance on a disposable kind cluster: ingress-nginx TLS, 2 web + 2 worker replicas on
# PostgreSQL, shared archive volume, proxy trust, sessions across pods, worker failover, reports.
set -euo pipefail
[ "${OPENREPORTING_K8S_CI:-}" = 1 ] || { echo 'Disposable CI runner required' >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
EVIDENCE="${EVIDENCE:-build/k8s}"
INGRESS_VERSION=controller-v1.12.1
HOST=openreporting.localtest
mkdir -p "$EVIDENCE"
dump() {
  kubectl get all,pvc,ingress -n openreporting -o wide > "$EVIDENCE/resources.txt" 2>&1 || true
  kubectl describe pods -n openreporting > "$EVIDENCE/pods.txt" 2>&1 || true
  kubectl get events -A --sort-by=.lastTimestamp > "$EVIDENCE/events.txt" 2>&1 || true
  kubectl describe nodes > "$EVIDENCE/nodes.txt" 2>&1 || true
  kubectl describe pvc -n openreporting > "$EVIDENCE/pvc.txt" 2>&1 || true
  for pod in $(kubectl get pods -n openreporting -o name 2>/dev/null); do
    kubectl logs -n openreporting "$pod" --all-containers > "$EVIDENCE/$(basename "$pod").log" 2>&1 || true
  done
}
trap dump EXIT

kind version && kubectl version --client
kind create cluster --name openreporting --config deploy/kubernetes/overlays/kind-ci/kind.yaml --wait 120s
kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/$INGRESS_VERSION/deploy/static/provider/kind/deploy.yaml"
kubectl wait -n ingress-nginx --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=180s

docker build -t openreporting:ci .
kind load docker-image openreporting:ci --name openreporting
# Pre-load the probe image so a NetworkPolicy "blocked" result can never be an image-pull timeout.
docker pull curlimages/curl:8.11.1
kind load docker-image curlimages/curl:8.11.1 --name openreporting

kubectl create namespace openreporting
DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
kubectl -n openreporting create secret generic postgres-ci --from-literal=password="$DB_PASSWORD"
kubectl -n openreporting create secret generic openreporting-secrets \
  --from-literal=OPENREPORTING_DATABASE_URL="postgresql://openreporting:$DB_PASSWORD@postgres:5432/openreporting"
# The key never touches the uploaded evidence directory.
KEY_FILE="$(mktemp)"
docker run --rm openreporting:ci python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end="")' > "$KEY_FILE"
kubectl -n openreporting create secret generic openreporting-key --from-file=secret.key="$KEY_FILE"
rm -f "$KEY_FILE"
openssl req -x509 -newkey rsa:3072 -sha256 -days 1 -nodes -subj "/CN=$HOST" -addext "subjectAltName=DNS:$HOST" \
  -keyout "$EVIDENCE/tls.key" -out "$EVIDENCE/tls.crt" 2>/dev/null
kubectl -n openreporting create secret tls openreporting-tls --cert="$EVIDENCE/tls.crt" --key="$EVIDENCE/tls.key"
rm -f "$EVIDENCE/tls.key"
echo "127.0.0.1 $HOST" | sudo tee -a /etc/hosts >/dev/null

kubectl apply -k deploy/kubernetes/overlays/kind-ci
kubectl -n openreporting rollout status deploy/postgres --timeout=180s
kubectl -n openreporting rollout status deploy/openreporting-web --timeout=300s
kubectl -n openreporting rollout status deploy/openreporting-worker --timeout=300s
[ "$(kubectl -n openreporting get deploy openreporting-web -o jsonpath='{.status.readyReplicas}')" = 2 ]

PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
kubectl -n openreporting exec deploy/openreporting-web -- env FIXTURE_PASSWORD="$PASSWORD" python -c \
  'import os; from openreporting.config import Settings; from openreporting.security import create_user; create_user(Settings.from_env(), "k8sadmin", os.environ["FIXTURE_PASSWORD"], "admin")'

# Pods can be Ready a moment before the ingress controller routes to them.
for _ in $(seq 1 60); do
  curl -fsS --cacert "$EVIDENCE/tls.crt" "https://$HOST/api/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS --cacert "$EVIDENCE/tls.crt" "https://$HOST/api/health"
export OPENREPORTING_K8S_URL="https://$HOST" OPENREPORTING_K8S_CA="$EVIDENCE/tls.crt" OPENREPORTING_K8S_PASSWORD="$PASSWORD"
python3 deploy/kubernetes/acceptance.py phase1 | tee "$EVIDENCE/phase1.json"

# NetworkPolicy: pods other than the ingress controller must not reach the app (they could forge
# X-Forwarded-Proto). Probe from another namespace and from the app's own namespace.
for ns in default openreporting; do
  if kubectl -n "$ns" run "np-probe-$RANDOM" --image=curlimages/curl:8.11.1 --restart=Never --image-pull-policy=Never --rm -i --quiet --command --        curl -fsS -m 5 -H 'X-Forwarded-Proto: https' -H 'Host: 127.0.0.1' http://openreporting-web.openreporting.svc:8810/healthz; then
    echo "NetworkPolicy did not block a pod in namespace $ns" >&2
    exit 1
  fi
  echo "NetworkPolicy blocked a pod in namespace $ns" | tee -a "$EVIDENCE/networkpolicy.txt"
done

# Worker failover: delete the active worker; the standby must take over the advisory lock.
ACTIVE="$(python3 deploy/kubernetes/acceptance.py active-worker)"
STANDBY=0
for pod in $(kubectl -n openreporting get pods -l app.kubernetes.io/component=worker -o name); do
  if kubectl -n openreporting logs "$pod" | grep -q 'waiting as standby'; then
    STANDBY=$((STANDBY + 1))
  else
    VICTIM="$pod"
  fi
done
if [ "$STANDBY" != 1 ] || [ -z "${VICTIM:-}" ]; then
  echo "Expected exactly one active and one standby worker" >&2
  exit 1
fi
echo "Deleting active worker $VICTIM (heartbeat worker id $ACTIVE)"
kubectl -n openreporting delete "$VICTIM" --wait=true
python3 deploy/kubernetes/acceptance.py failover "$ACTIVE" | tee "$EVIDENCE/failover.json"

# Rolling restart of web keeps sessions (stored in PostgreSQL) and stays available.
kubectl -n openreporting rollout restart deploy/openreporting-web
kubectl -n openreporting rollout status deploy/openreporting-web --timeout=300s
python3 deploy/kubernetes/acceptance.py phase2 | tee "$EVIDENCE/phase2.json"
echo 'Kubernetes acceptance passed'
