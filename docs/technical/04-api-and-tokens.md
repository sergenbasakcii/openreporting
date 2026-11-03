# 04 · REST API ve servis hesabı API anahtarları

| | |
| --- | --- |
| Durum | Uygulandı (şema 8) |
| Modüller | `openreporting/api_tokens.py`, `openreporting/api/tokens.py`, `openreporting/security.py` (`authenticate`, `require_csrf`), `openreporting/web.py` (`/api/openapi.json`) |
| Arayüz | Yönetim → API anahtarları (`/admin/api-keys`), API başvurusu (`/admin/api`) |
| Testler | `tests/test_api_tokens.py` |

## Amaç

Uygulamanın tüm işlevleri (dashboard, rapor, arşiv, veri kaynağı sorgusu, değişkenler…) zaten bir REST API
üzerinden çalışır; arayüz de bu API'nin istemcisidir. Otomasyon — CI/CD ile dashboard-as-code, değişiklik
penceresinde rapor tetikleme, arşivlenmiş PDF/XLSX'i ticket sistemine çekme — tarayıcı oturumu olmadan
yapılabilmelidir. Bu geliştirme API'yi kimliği doğrulanmış biçimde belgeleyip makineler için süreli,
iptal edilebilir anahtarlar ekler.

## Kimlik doğrulama modelleri

| Model | Nasıl | CSRF | Kullanım |
| --- | --- | --- | --- |
| Tarayıcı oturumu | HttpOnly, Secure, SameSite=Strict çerez + `X-CSRF-Token` | Zorunlu | Arayüz |
| API anahtarı | `Authorization: Bearer ortk_<önek>_<gizli>` | Gerekmez | Otomasyon |

Çerez varsa her zaman oturum modeli kullanılır; anahtar yalnız çerez yokken değerlendirilir. Bearer başlığını
tarayıcı kendiliğinden göndermediği için siteler arası istek sahteciliği (CSRF) mümkün değildir; bu yüzden
anahtarlı isteklerde CSRF kontrolü atlanır.

## Veri modeli (şema 8)

```sql
CREATE TABLE api_tokens(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL,
 prefix TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT);
```

**Servis hesabı**, `users` tablosunda parola özeti `!service` olan kayıttır. Bu değer geçerli bir scrypt
özeti olmadığından etkileşimli giriş hiçbir parolayla başarılı olamaz. Ayrı bir hesap türü tablosu yerine bu
yaklaşım seçildi; klasör izinleri (`folder_user_grants`), denetim kaydı (`audit.actor`) ve rol kontrolleri
insan kullanıcılarla aynı kod yolunu kullanır.

## Güvenlik kuralları

- Anahtar biçimi `ortk_` + 8 karakter hex önek + 32 bayt rastgele (URL-güvenli). Yalnız SHA-256 özeti
  saklanır (yüksek entropi nedeniyle yavaş özet gerekmez); anahtar yalnız üretim yanıtında **bir kez** döner.
- Her anahtarın son kullanma tarihi zorunludur (1–365 gün). İptal anında etkilidir (`revoked_at`).
- Servis hesabı rolü yalnız **İzleyici** veya **Editör** olabilir; yönetici yapılamaz, parolası sıfırlanamaz
  (API ve CLI ikisi de reddeder).
- Anahtarlar şu uçlarda reddedilir (403): `/api/user*`, `/api/session*`, `/api/login`, `/api/logout`,
  `/api/admin*`, `/api/users*`, `/api/audit`. Böylece bir anahtar hesap, MFA, oturum veya yönetim işlemi yapamaz.
- Anahtar üretmek yöneticinin **mevcut parolasını** ister (step-up); üretme, iptal, hesap oluşturma/değiştirme
  denetim kaydına yazılır.
- `last_used_at` en fazla 5 dakikada bir güncellenir (her istekte yazma yükü oluşmaz).
- Devre dışı bırakılan servis hesabının tüm anahtarları anında çalışmaz.

## API uçları

| Yöntem | Uç | Yetki | Açıklama |
| --- | --- | --- | --- |
| GET | `/api/openapi.json` | Oturum veya anahtar | OpenAPI 3 belgesi |
| GET | `/api/admin/service-accounts` | Yönetici | Hesaplar ve anahtar özetleri (gizli değer yok) |
| POST | `/api/admin/service-accounts` | Yönetici + CSRF | `{username, role, display_name}` |
| PATCH | `/api/admin/service-accounts/{id}` | Yönetici + CSRF | `{role?, active?}` |
| POST | `/api/admin/service-accounts/{id}/tokens` | Yönetici + CSRF + parola | `{name, days, password}` → `{token, …}` |
| DELETE | `/api/admin/tokens/{id}` | Yönetici + CSRF | Anahtarı iptal eder |

## Örnek kullanım

```bash
TOKEN='ortk_...'   # Yönetim → API anahtarları sayfasından, bir kez gösterilir
# Dashboard ara
curl -fsS -H "Authorization: Bearer $TOKEN" https://openreporting.example.com/api/search
# Dashboard'u koddan kaydet (editör anahtarı)
curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d @dashboard.json https://openreporting.example.com/api/dashboards/db
# Raporu çalıştır ve arşivden indir
curl -fsS -H "Authorization: Bearer $TOKEN" -X POST -H 'Content-Type: application/json' -d '{}' \
  https://openreporting.example.com/api/dash-reports/<rapor-id>/runs
curl -fsS -H "Authorization: Bearer $TOKEN" -o rapor.pdf \
  https://openreporting.example.com/api/report-runs/<çalışma-id>/files/pdf
```

## API kararlılığı

`/api` altındaki uçlar arayüzle aynı sözleşmeyi kullanır. Geriye uyumsuz değişiklikler CHANGELOG'da
"API" başlığıyla duyurulur; alan eklemek uyumlu kabul edilir. OpenAPI belgesi her sürümde koddan üretilir,
elle tutulan bir kopya yoktur.

## Testler

`tests/test_api_tokens.py`: tek gösterim ve özet saklama, CSRF'siz editör yazması, izleyici yazma reddi,
yasaklı uçlar, iptal / süre dolumu / hesap devre dışı, bozuk ve bilinmeyen anahtar, servis hesabının giriş /
yönetici / parola kısıtları, parolasız anahtar üretiminin reddi, klasör izinlerinin anahtara uygulanması.
