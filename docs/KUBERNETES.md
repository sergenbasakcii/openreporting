# OpenReporting — Kubernetes ve yatay ölçekleme

```
Ingress (TLS) ──▶ Service ──▶ openreporting-web  × N   (HPA: 2–10, CPU %70)   ─┐
                              openreporting-worker × 2 (1 aktif + 1 sıcak yedek) ─┼─▶ PostgreSQL (uygulama verisi)
                                                                                  └─▶ RWX volume (rapor arşivi, logolar)
Secret: openreporting-secrets (veritabanı adresi) · openreporting-key (şifreleme anahtarı, tüm pod'larda aynı)
```

## Neden ölçeklenebilir

| Bileşen | Çok kopyada davranış |
| --- | --- |
| Oturumlar, ayarlar, MFA, kullanıcılar, dashboard'lar | PostgreSQL'de; her istek herhangi bir web pod'una gidebilir |
| Sistem ayarları sayfası | Değişiklik 2–3 sn içinde bütün pod'lara yansır (revizyon kontrolü) |
| Şema geçişleri | Açılışta kilitli tek işlemde; aynı anda açılan pod'lar sırayla bekler |
| Rapor worker'ı | PostgreSQL danışma kilidi: yalnız biri çalışır, diğeri bekler; aktif pod ölünce saniyeler içinde devralır |
| Rapor arşivi / logolar | Paylaşımlı ReadWriteMany volume; worker yazar, her web pod'u indirir |
| Şifreleme anahtarı | Tek Secret; `OPENREPORTING_REQUIRE_KEY_FILE=true` pod'un kendi anahtarını üretmesini engeller |
| HTTPS tespiti | Yalnız Ingress controller'ın pod ağından gelen `X-Forwarded-*` güvenilir; NetworkPolicy başka pod'ları engeller |

CI her değişiklikte geçici bir **kind** kümesinde bu yapıyı kurar: Ingress TLS, 2 web + 2 worker +
PostgreSQL, güvenli çerez, HTTPS üzerinden MFA, oturum ve ayarların pod'lar arası tutarlılığı,
worker'da üretilen raporun her pod'dan aynı indirilmesi, aktif worker silinince yedeğin devralması,
web pod'larının hepsi yenilendikten sonra oturum ve arşivin korunması.

Bilinen sınırlar: yazma işlemleri veritabanında tek kilitle sıralanır (okuma ölçeklenir; yoğun eşzamanlı
yazmada sınır PostgreSQL'dir). Rapor üretimi tek aktif worker'dadır; çok sayıda ağır zamanlanmış rapor
için saatleri dağıtın. Her istek yeni veritabanı bağlantısı açar; çok pod'da **PgBouncer** önerilir.

## 1. Gereksinimler

- Kubernetes 1.27+, bir Ingress controller (örnekler ingress-nginx için), metrics-server (HPA için).
- **PostgreSQL 14+** (yönetilen servis veya operatör: CloudNativePG, Crunchy vb.) ve yalnız bu uygulamaya ait bir rol.
- **ReadWriteMany** destekleyen bir StorageClass (NFS, CephFS, EFS, Azure Files…). Tek düğümde RWO yeterlidir.
- Kurumun imaj deposu (registry).

## 2. İmaj

```bash
docker build -t registry.example.com/openreporting/openreporting:1.2.0 .
docker push registry.example.com/openreporting/openreporting:1.2.0
```

`deploy/kubernetes/base/kustomization.yaml` içindeki `images` bölümünü kendi deponuza göre düzenleyin
(veya bir overlay'de değiştirin).

## 3. Kurulum

```bash
kubectl create namespace openreporting

# Veritabanı adresi (TLS doğrulamalı önerilir: sslmode=verify-full&sslrootcert=...)
kubectl -n openreporting create secret generic openreporting-secrets \
  --from-literal=OPENREPORTING_DATABASE_URL='postgresql://openreporting:PAROLA@pg.example.com:5432/openreporting?sslmode=verify-full'

# Şifreleme anahtarı: bir kez üretin, kasada saklayın, bütün pod'lar aynısını kullanır
docker run --rm registry.example.com/openreporting/openreporting:1.2.0 \
  python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end="")' > secret.key
kubectl -n openreporting create secret generic openreporting-key --from-file=secret.key=secret.key
# secret.key dosyasını kurum kasasına taşıyın ve sunucudan silin

# TLS sertifikası
kubectl -n openreporting create secret tls openreporting-tls --cert=cert.pem --key=key.pem
```

Kendi overlay'inizi oluşturun (örnek `deploy/kubernetes/overlays/kind-ci`):

```yaml
# overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: openreporting
resources: [../../base]
images:
  - {name: registry.example.com/openreporting/openreporting, newName: registry.sirket.local/openreporting, newTag: "1.2.0"}
patches:
  - target: {kind: ConfigMap, name: openreporting-config}
    patch: |
      - {op: replace, path: /data/OPENREPORTING_PUBLIC_URL, value: "https://openreporting.sirket.local"}
      - {op: replace, path: /data/OPENREPORTING_FORWARDED_ALLOW_IPS, value: "10.42.0.0/16"}   # kümenin pod CIDR'ı
  - target: {kind: Ingress, name: openreporting}
    patch: |
      - {op: replace, path: /spec/rules/0/host, value: openreporting.sirket.local}
      - {op: replace, path: /spec/tls/0/hosts/0, value: openreporting.sirket.local}
  - target: {kind: PersistentVolumeClaim, name: openreporting-archive}
    patch: |
      - {op: add, path: /spec/storageClassName, value: nfs-client}
```

```bash
kubectl apply -k deploy/kubernetes/overlays/prod
kubectl -n openreporting rollout status deploy/openreporting-web
kubectl -n openreporting exec -it deploy/openreporting-web -- openreporting create-user yonetici --role admin
```

Ingress controller farklı bir namespace'teyse `networkpolicy.yaml` içindeki `ingress-nginx` adını değiştirin.
Kümenin pod CIDR'ını `kubectl cluster-info dump | grep -m1 cluster-cidr` veya CNI ayarlarından öğrenin.

## 4. İşletim

```bash
kubectl -n openreporting get pods
kubectl -n openreporting logs -f deploy/openreporting-web
kubectl -n openreporting logs -l app.kubernetes.io/component=worker      # biri "waiting as standby" yazar
kubectl -n openreporting exec deploy/openreporting-web -- openreporting doctor
kubectl -n openreporting exec -it deploy/openreporting-web -- openreporting reset-password <kullanıcı>
kubectl -n openreporting exec deploy/openreporting-web -- openreporting reset-mfa <kullanıcı> --reason lost-device
kubectl -n openreporting scale deploy/openreporting-web --replicas=4      # HPA yoksa elle
```

Ayarlar: ConfigMap değişince `kubectl rollout restart deploy/openreporting-web deploy/openreporting-worker`.
SMTP, LDAP, MFA rolleri ve sınırlar için **Yönetim → Sistem ayarları** yeniden başlatma gerektirmez.

## 5. Yedekleme

| Ne | Nasıl |
| --- | --- |
| PostgreSQL | Kullandığınız servisin/operatörün yedeği (PITR önerilir) veya `pg_dump` CronJob'u |
| Rapor arşivi + logolar | RWX volume snapshot'ı veya depolama sisteminin yedeği |
| Şifreleme anahtarı | `openreporting-key` Secret'ının kasadaki kopyası. Anahtar olmadan veri kaynağı, MFA ve SMTP/LDAP parolaları açılamaz |

Geri yüklemede üçü aynı ana ait olmalıdır.

## 6. Güncelleme

```bash
docker build -t registry.example.com/openreporting/openreporting:1.2.1 . && docker push …
kubectl -n openreporting set image deploy/openreporting-web web=registry.example.com/openreporting/openreporting:1.2.1
kubectl -n openreporting set image deploy/openreporting-worker worker=registry.example.com/openreporting/openreporting:1.2.1
```

Web pod'ları kesintisiz sırayla yenilenir (`maxUnavailable: 0`). Şema değişen sürümlerde önce
veritabanı yedeği alın; şema geçişleri geriye doğru uyumludur (yeni tablo/kolon eklenir), eski kod yeni
şemayı yeni açılışta reddeder; geri dönüş için yedekten dönün.

## 7. SQLite kurulumundan geçiş

Mevcut tek sunuculu (SQLite) kurulumdan PostgreSQL'e otomatik veri taşıma aracı henüz yoktur.
Dashboard'lar `export-dashboards` / `import-dashboards` ile taşınabilir; kullanıcılar, veri kaynakları ve
rapor tanımları yeni kurulumda yeniden oluşturulur.

## 8. Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| Pod `Şifreleme anahtarı bulunamadı … önceden sağlanmalı` | `openreporting-key` Secret'ı yok veya `secret.key` anahtarı eksik |
| Readiness başarısız, `/api/health` 503 | Veritabanı erişimi: `OPENREPORTING_DATABASE_URL`, ağ, TLS |
| Tarayıcıda 400 “Invalid host header” | `OPENREPORTING_PUBLIC_URL` / Ingress host aynı olmalı; ek adlar `OPENREPORTING_ALLOWED_HOSTS` |
| MFA kurulumu “yalnız HTTPS” | `OPENREPORTING_FORWARDED_ALLOW_IPS` Ingress pod'larının ağını kapsamıyor |
| Rapor indirilemiyor (dosya yok) | Arşiv volume'ü RWX değil ve pod'lar farklı düğümlerde |
| İki worker da çalışmıyor | `kubectl logs`; veritabanı bağlantısı; `openreporting worker-health` |
