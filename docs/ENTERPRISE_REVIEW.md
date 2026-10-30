# Kurumsal değerlendirme — 120 somut kontrol

Gece çalışma hedefi: 30 Ekim 2026 sabahı (Europe/Istanbul). Bu kayıt ürünün kod/test kanıtı ve açık risklerini izler.
Google kabulü, bağımsız denetim veya standart sertifikasyonu iddiası içermez. Tam ASVS uyumluluğu da iddia edilmez.

Referans çerçeveler: [OWASP ASVS 5.0](https://asvs.owasp.org/),
[NIST SSDF 1.1](https://csrc.nist.gov/pubs/sp/800/218/final) ve
[Google SRE üretime hazırlık incelemesi](https://sre.google/sre-book/evolving-sre-engagement-model/).
Maddeler bu ürünün kapsamına göre somutlaştırıldı; resmi standart maddeleriyle birebir eşdeğer değildir.

Durumlar: **V** = mevcut test kanıtı var; **R** = kaynak/doküman incelendi, bağımsız test kanıtı yeterli değil;
**P** = kısmi; **O** = açık; **E** = gerçek kurum/işletmeci kabulü veya dış karar gerekli.
V, tüm saldırı/yük/dağıtım koşullarının doğrulandığı anlamına gelmez. P1 önce ele alınacak risktir; P2 sonraki iyileştirmedir.
Önizleme hesabı yalnız kullanıcının yerel deneme istisnasıdır; üretim parola politikası korunur.

MFA temel değişikliği `f7ba845` için [CI tümü başarılı](https://github.com/sergenbasakcii/openreporting/actions/runs/41036010496).
Hashli build/runtime QA ortamında yerelde **269 Python testi başarılı, 14 ortam/Windows yetkisi bağımlı test atlandı**; gerçek LDAP/SMTP/PostgreSQL ve Ubuntu kontrolleri başarılı.
Yeni Ubuntu kurulumu zorunlu admin MFA kurulumundan rapor üretimine, MFA seed anahtar
değişimine ve yedek doğrulamaya kadar geçti; yerel/CI sonucu gerçek kurum kabulü değildir.
Arayüzde 10 Node testi, ES modülü sözdizimi ve gerçek Chromium tema/klavye kontrolleri başarılı.
Axe-core 4.14 ile giriş + sekiz yönetici rotasında koyu/açık toplam 17 taramada otomatik bulgu kalmadı;
bu sonuç tam WCAG veya gerçek ekran okuyucu kabulü değildir. Son commitlerin CI sonucu PROGRESS.md'de izlenir.
Yeni MFA akışlarında geçici Chromium uygulamasında iki temada ek 20 tarama temizdir;
[yerel kanıt](evidence/mfa-browser-2026-10-30.json) sır veya şirket verisi içermez.
Oracle Linux 8.10/9.8/10.2 kullanıcı alanında kurulum paketleri, servis dosyası ayrıştırma,
gerçek nginx HTTPS/MFA ve PDF/XLSX/CSV worker kabulü başarılıdır;
[ortam kanıtı](evidence/oracle-linux-userspace-2026-10-31.json) PID1/SELinux Enforcing
ve tam VM/kurum kabulünün açık kaldığını kaydeder. Ubuntu dışındaki bu kapsam tam host kabulü değildir.
Test dosyası referansları o başlığın kanıt alanını gösterir; her satır için ayrı bir yeni test yazıldığı iddia edilmez.

Gövde sınırı, Host/Origin izolasyonu, logo yedeği, izole kurtarma doğrulayıcı ve bağımlılık taraması eklendi.
16 sentetik viewer ile 120 saniyede 7.404 HTTP isteği, sıfır hata; sorgu p95 445,654 ms ölçüldü.
Bu kısa ve tek süreçli test gerçek kaynak/worker kapasitesini veya uzun soak kabulünü kanıtlamaz.
TOTP kurulum/giriş/kurtarma ve şifreli seed yaşam döngüsü eklendi; B10 kısmi.
Öncelikli kalanlar: gerçek kaynaklı yük/uzun çalışma ve kurum kabulü. SSO/WebAuthn, tenant ACL,
deneysel PostgreSQL işletimi ve gerçek kurum anahtar bakım/emanet kabulü ayrıca değerlendirilmelidir.
Kullanıcı adına lisans/üretim kabul kararı verilmez.

Makine okunur kaynak: [enterprise-controls.json](enterprise-controls.json).

Durum dağılımı: V: 86, R: 16, P: 9, O: 3, E: 6.

## A — Mimari ve kapsam

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| A01 | Tek web ve tek worker sorumluluğu | R | P2 | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) — Dağıtım topolojisi gözden geçirildi |
| A02 | Ekran ve rapor için ortak sorgu hattı | V | P2 | [tests/test_datasources_engine.py](../tests/test_datasources_engine.py) — Aynı motor sözleşmesi testli |
| A03 | Tek host SQLite ve yerel disk sınırı | R | P1 | [docs/LINUX_DEPLOYMENT.md](../docs/LINUX_DEPLOYMENT.md) — NFS/SMB desteklenmiyor |
| A04 | Uygulama DB seçimi ve sessiz fallback reddi | V | P1 | [tests/test_database_settings.py](../tests/test_database_settings.py) — Bozuk PostgreSQL URL reddediliyor |
| A05 | PostgreSQL üretim işletim paketi | O | P1 | [docs/adr/0001-application-database-migration.md](../docs/adr/0001-application-database-migration.md) — pg_dump/restore ve taşıma eksik |
| A06 | Yapılandırma tür ve sınır doğrulaması | V | P1 | [tests/test_enterprise_settings.py](../tests/test_enterprise_settings.py) — Güvensiz entegrasyon ayarları reddediliyor |
| A07 | API/driver/rapor modül sınırları | R | P2 | [openreporting/api/deps.py](../openreporting/api/deps.py) — Kaynak sorguları uygulama DB adapterine yönlendirilmiyor |
| A08 | Resmi veri akışı ve tehdit modeli | R | P1 | [docs/THREAT_MODEL.md](../docs/THREAT_MODEL.md) — Varlıklar, aktörler, güven sınırları ve kötüye kullanım senaryoları kaydedildi; bağımsız denetim değil |
| A09 | Kapasite ve kullanıcı yükü ölçümü | P | P1 | [docs/PERFORMANCE_ACCEPTANCE.md](../docs/PERFORMANCE_ACCEPTANCE.md) — Gerçek loopback HTTP, geçici SQLite ve kayıtlı panel tanımıyla sentetik viewer ölçümü; gerçek kaynak/kurum kapasitesi açık |
| A10 | Eksik veri ve bağımlılık hatasında kapalı davranış | V | P1 | [tests/test_reporting.py](../tests/test_reporting.py) — Kısmi raporda e-posta engeli testli |

## B — Yerel kimlik ve hesaplar

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| B01 | scrypt parola türetme | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Gerçek scrypt roundtrip, ayrı salt, yanlış parola ve maliyet parametresi reddi testli; bağımsız KDF/maliyet sertifikasyonu değil |
| B02 | Üretimde en az 14 karakter parola | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — 13/14 karakter sınırı ve zayıf API resetinin oturumlara dokunmaması testli; önizleme istisnası üretim politikasını değiştirmez |
| B03 | Parola karşılaştırmasında sabit süreli karşılaştırma | R | P1 | [openreporting/security.py](../openreporting/security.py) — hmac.compare_digest kullanılıyor |
| B04 | Bilinmeyen yerel hesap için dummy hash | R | P2 | [openreporting/security.py](../openreporting/security.py) — Hesap keşfi yan kanalını azaltır; dizin gecikmesi eşitlenmez |
| B05 | Başarısız giriş sayacının kalıcılığı | V | P1 | [tests/test_platform_core.py](../tests/test_platform_core.py) — DB kaydı regresyonu var |
| B06 | Beş denemede 15 dakika kilit | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — 429 davranışı doğrulandı |
| B07 | Son yerel kurtarma yöneticisi korunması | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — LDAP yöneticisi varken de yerel yönetici korunuyor |
| B08 | Pasif kullanıcının erişiminin reddi | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — Dizin girişi yerel pasifliği geri alamaz |
| B09 | Parola sıfırlamada oturum iptali | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — API ve CLI resetinde iki eski oturumun iptali, eski/yeni parola ve sır içermeyen CLI çıktı kabulü testli |
| B10 | Çok faktörlü kimlik doğrulama | P | P1 | [tests/test_mfa.py](../tests/test_mfa.py) — Yerel/LDAP TOTP, rol-zorunlu kurulum izolasyonu, tek kullanımlık kurtarma, replay/race/oturum iptali ve key/backup roundtrip testli; SSO/WebAuthn/kimlik avına dayanıklı kurum politikası açık. docs/MFA.md sınırları açıklar. |

## C — LDAP ve dizin güveni

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| C01 | LDAPS zincir ve DNS adı doğrulaması | V | P1 | [tests/test_ldap_server.py](../tests/test_ldap_server.py) — Gerçek OpenLDAP TLS ve yanlış hostname reddi |
| C02 | LDAP portunda kimlik bilgisi öncesi StartTLS | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — TLS başarısızsa bind yapılmıyor |
| C03 | Servis hesabı salt okunur istemci ve sunucu ACL | V | P1 | [tests/test_ldap_server.py](../tests/test_ldap_server.py) — Client guard ve yetersiz yetki 50 ayrı doğrulandı |
| C04 | LDAP filtre enjeksiyonunun kaçırılması | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — Yıldız/parantez girdisi literal oluyor |
| C05 | Boş parolayla anonim bind reddi | V | P1 | [tests/test_ldap_server.py](../tests/test_ldap_server.py) — Boş kullanıcı parolası ağ bindine gitmiyor |
| C06 | Tekil arama ve kalıcı dizin kimliği | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — Çoklu eşleşme ve kimlik/username devralma reddediliyor |
| C07 | Doğrudan grup üyeliğinden rol eşleme | V | P1 | [tests/test_ldap_server.py](../tests/test_ldap_server.py) — Viewer/editor geçişi gerçek memberOf ile testli |
| C08 | Rol düşürmede eski oturumların iptali | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — Eski oturum kaydı kalmıyor |
| C09 | Dizin kesintisinde yerel parolaya fallback reddi | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — 503 ve yeni profil oluşturmama doğrulandı |
| C10 | Kurum AD ve iç içe grup kabulü | E | P1 | [docs/ENTERPRISE_DEPLOYMENT.md](../docs/ENTERPRISE_DEPLOYMENT.md) — Gerçek kurum kabulü yapılmadı; nested group/primary group çözümü yok |

## D — Oturum ve yetkilendirme

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| D01 | Rastgele yüksek entropili oturum belirteci | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Gerçek API oturumları, token uzunluğu ve DBde yalnız digest saklama kabulü; CSPRNG secrets modülü |
| D02 | CSRF tokeninin hashli saklanması | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Gerçek CSRF digest saklama ve rotasyon sonrası eski token reddi testli |
| D03 | Mutasyonlarda CSRF zorunluluğu | V | P1 | [tests/test_platform_core.py](../tests/test_platform_core.py) — Başlıksız mutasyon 403 |
| D04 | Yönetici/editör/izleyici rol sınırları | V | P1 | [tests/test_report_authorization.py](../tests/test_report_authorization.py) — API hesap iptali ve güncel rolün kuyruk/zamanlama/render/SMTP devrinde yeniden kontrolü testli; test_reporting.py API rol sınırlarını korur. Tenant/klasör ACL D10 açık. İzleyicide zamanlama alıcılarının redaksiyonu iki APIde testli. |
| D05 | İzleyici serbest sorgu ve metric-find reddi | V | P1 | [tests/test_review_fixes.py](../tests/test_review_fixes.py) — Ad hoc sorgu ve değişken tanımı enjeksiyonu reddediliyor |
| D06 | İzleyicinin kayıtlı paneli çalıştırması | V | P1 | [tests/test_review_fixes.py](../tests/test_review_fixes.py) — Gönderilen target ve dönüşümler güven kaynağı değil |
| D07 | HttpOnly Secure SameSite çerez | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — HTTPS cookie HttpOnly/Secure/SameSite=Strict/Path ve HTTPde gönderilmeme kabulü; browser SameSite matrisi değil |
| D08 | Oturum süresi ve LDAP üst sınırı | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — LDAP varsayılan en çok 60 dakika |
| D09 | Çıkış ve CSRF yenileme akışı | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Same-origin CSRF refresh ve eski token reddi, logout sonrası session401 kabulü |
| D10 | Çok kiracılı ve klasör bazlı ayrıntılı ACL | O | P1 | [openreporting/dashboards.py](../openreporting/dashboards.py) — Ürün şu anda tek kurum ve genel roller; tenant/klasör ACL yok |

## E — HTTP ve API savunmaları

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| E01 | Liveness ve readiness ayrımı | V | P1 | [tests/test_healthchecks.py](../tests/test_healthchecks.py) — Liveness DB arızasında da 200; readiness kimlik ister |
| E02 | DB arızasında sağlık HTTP 503 | V | P1 | [tests/test_healthchecks.py](../tests/test_healthchecks.py) — SELECT 1 ve şema kontrolü; yerel yeni test |
| E03 | Bozuk audit zincirinde readiness 503 | V | P1 | [tests/test_healthchecks.py](../tests/test_healthchecks.py) — Yeni regresyon testi; CI sonucu son kayıtta |
| E04 | Kimlik deposu arızasında redakte 503 | V | P1 | [tests/test_healthchecks.py](../tests/test_healthchecks.py) — SQLite/PostgreSQL/OSError detayları gösterilmiyor |
| E05 | Gövde sınırının akış üzerinde uygulanması | V | P1 | [tests/test_request_limits.py](../tests/test_request_limits.py) — 11 test: eksik/yanlış Content-Length, chunked, gerçek boyut, framing, endpoint mutasyon izolasyonu |
| E06 | CSP ve frame/object kısıtları | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Gerçek HTTP yanıtlarında CSP/frame/object/no-sniff/referrer/HSTS kabulü; inline style istisnası korunuyor |
| E07 | Giriş/API/ağır işlem rate limit | R | P1 | [deploy/nginx/openreporting.conf](../deploy/nginx/openreporting.conf) — nginx IP limitleri + dört pahalı login işi/süreç admission sınırı ve Retry-After; dağıtık/global rate limit kabulü değil |
| E08 | Proxy başlıklarına sınırlı güven | R | P1 | [openreporting/cli.py](../openreporting/cli.py) — Yalnız loopback forwarded_allow_ips |
| E09 | Bilinmeyen API yollarında SPA fallback reddi | V | P2 | [tests/test_platform_core.py](../tests/test_platform_core.py) — 404 davranışı testli |
| E10 | URL/Host ve origin sınırları | V | P1 | [tests/test_http_security.py](../tests/test_http_security.py) — 24 Host/Origin yapılandırma ve HTTP senaryosu; rebinding/alias/IPv6/CSRF destekleyen same-origin sınırı, yeni CI bekliyor |

## F — Veri kaynakları ve sorgular

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| F01 | Zabbix yazma metodu reddi | V | P1 | [tests/test_datasources_engine.py](../tests/test_datasources_engine.py) — Yalnız get metotları |
| F02 | SQL tek ifade ve yazma koruması | V | P1 | [tests/test_review_fixes.py](../tests/test_review_fixes.py) — Tırnak ve çoklu ifade hileleri reddediliyor |
| F03 | SQL sunucusunda READ ONLY ve timeout | R | P1 | [openreporting/datasources/postgres.py](../openreporting/datasources/postgres.py) — transaction/connection güvenlik seçenekleri mevcut |
| F04 | SQL TLS verify-full varsayılanı | R | P1 | [openreporting/datasources/postgres.py](../openreporting/datasources/postgres.py) — Kurum CA ve gerçek DB kabulü ayrıca gerekli |
| F05 | HTTP kaynaklarında sabit origin GET | V | P1 | [tests/test_http_sources.py](../tests/test_http_sources.py) — Kayıtlı admin adresi; kullanıcı target URL seçmiyor |
| F06 | Redirect ve metadata peer reddi | V | P1 | [tests/test_http_sources.py](../tests/test_http_sources.py) — Link-local/metadata ve 8 MB sınırı testli |
| F07 | PromQL/LogQL değişken bağlamı | V | P1 | [tests/test_http_sources.py](../tests/test_http_sources.py) — Yalnız tırnaklı bağlamda güvenli kaçış |
| F08 | Eşzamanlılık ve nokta/satır bütçesi | R | P1 | [openreporting/query_engine.py](../openreporting/query_engine.py) — Süreç bazında semaphore ve genel bütçeler; yükle ölçülecek |
| F09 | Regex süre ve uzunluk sınırları | V | P1 | [tests/test_review_fixes.py](../tests/test_review_fixes.py) — Kullanıcı regex doğrulaması ve timeout |
| F10 | Eksik sayıların sıfıra çevrilmemesi | V | P1 | [tests/test_engine_core.py](../tests/test_engine_core.py) — Reducer ve sayaç reset davranışı testli |

## G — Depolama kripto ve geçişler

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| G01 | Şifreli kaynak sırları ve ayrı Fernet anahtarı | V | P1 | [tests/test_security_acceptance.py](../tests/test_security_acceptance.py) — Gerçek kaynak API kaydı/okuma/listede sır redaksiyonu, SQLite ciphertext ve ayrı anahtarla decrypt kabulü |
| G02 | Eksik anahtarda yeni anahtar üretmeme | V | P1 | [tests/test_secret_key_recovery.py](../tests/test_secret_key_recovery.py) — Şifreli veri varken anahtar kaybı kapalı hata |
| G03 | Bilinmeyen/okunamayan DBde anahtar koruması | V | P1 | [tests/test_secret_key_recovery.py](../tests/test_secret_key_recovery.py) — İnceleme hatası yeni anahtar yetkisi sayılmıyor |
| G04 | Atomik numaralı schema geçişleri | V | P1 | [tests/test_db_migrations.py](../tests/test_db_migrations.py) — Başarısız adım veriyi ve sürümü koruyor |
| G05 | Aynı anda web worker başlangıcı | V | P1 | [tests/test_db_migrations.py](../tests/test_db_migrations.py) — Tek sürüm kaydı ve tutarlılık |
| G06 | Daha yeni schema ile eski kodu reddetme | V | P1 | [tests/test_platform_core.py](../tests/test_platform_core.py) — Sessiz downgrade yok |
| G07 | v3te yerel kullanıcı ve kimlik koruması | V | P1 | [tests/test_directory_auth.py](../tests/test_directory_auth.py) — v2den geçiş ve tekrar init testli |
| G08 | PostgreSQL audit append-only ve kilit | V | P1 | [tests/test_postgres_store.py](../tests/test_postgres_store.py) — Gerçek PGde FK ve audit tetikleyicileri |
| G09 | Anahtar rotasyonu ve anahtar versiyonlama | V | P1 | [tests/test_key_rotation.py](../tests/test_key_rotation.py) — Raw uyumlu bounded ring, ayrı hazırlık, SQLite offline atomik rekey/audit/rollback ve doğrulanan retirement; yedek eski/yeni anahtar kabulü testli; kurum bakım/emanet kabulü ayrıca gerekli |
| G10 | Disk/DB/yedek şifreleme kurum politikası | E | P1 | [docs/ENTERPRISE_DEPLOYMENT.md](../docs/ENTERPRISE_DEPLOYMENT.md) — Fernet kaynak sırları ve TOTP seedlerini kapsar; tam disk/DB/yedek politikası kuruma bağlı |

## H — Rapor ve teslimat doğruluğu

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| H01 | PDF/Excel/CSV gerçek grup bölümleri | V | P1 | [tests/test_reporting.py](../tests/test_reporting.py) — Gerçek oluşturulan dosyalar ve arşiv testli |
| H02 | CSV/Excel formül enjeksiyonu | V | P1 | [tests/test_review_fixes.py](../tests/test_review_fixes.py) — Tehlikeli metin hücreleri nötrleniyor |
| H03 | Logo boyut/piksel/tür doğrulaması | V | P1 | [tests/test_reporting.py](../tests/test_reporting.py) — Logo normalize ve PDF gömme testli |
| H04 | Rapor arşiv SHA ve audit çapası | V | P1 | [tests/test_reporting.py](../tests/test_reporting.py) — Bozulmuş dosya indirmesi reddediliyor |
| H05 | Takvim ve DST güvenli zamanlama | V | P1 | [tests/test_platform_core.py](../tests/test_platform_core.py) — Önceki tam dönem ve gelecek çalışma hesabı |
| H06 | Kısmi veri e-posta engeli | V | P1 | [tests/test_reporting.py](../tests/test_reporting.py) — Varsayılan gönderim kapalı |
| H07 | SMTP TLS AUTH ve relay | V | P1 | [tests/test_smtp_transport.py](../tests/test_smtp_transport.py) — Gerçek TLS socket; Linux CI implicit TLS dahil |
| H08 | Alıcı alan adı ve gönderim boyut sınırı | R | P1 | [openreporting/reporting/service.py](../openreporting/reporting/service.py) — Tam domain izin listesi ve ham 20 MB ek bütçesi |
| H09 | Kısmi/belirsiz teslimatı otomatik oynamama | V | P1 | [tests/test_smtp_transport.py](../tests/test_smtp_transport.py) — DATA kabul yanıtı kaybı ve alıcı retleri testli |
| H10 | Yeni tüm grafiklerin vektör PDF eşliği | P | P2 | [docs/EXTRA_SOURCES_AND_PANELS.md](../docs/EXTRA_SOURCES_AND_PANELS.md) — 20 yeni türün 14ü vektör; 6 tür etiketli veri tablosu |

## I — Arayüz erişilebilirlik ve kullanım

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| I01 | Mevcut sade tasarımın korunması | V | P2 | [tests/browser/theme-surfaces.cjs](../tests/browser/theme-surfaces.cjs) — Genel izleme hero kaldırıldı; yeni hero yok |
| I02 | Koyu/açık native seçim yüzeyleri | V | P2 | [tests/browser/theme-surfaces.cjs](../tests/browser/theme-surfaces.cjs) — Gerçek Chromium kabul kontrolü |
| I03 | Yirmi yeni grafik ve veri doğruluğu | V | P1 | [tests/test_extended_panels.mjs](../tests/test_extended_panels.mjs) — Veri uydurmama ve gerekli sütunlar testli |
| I04 | Tema değişiminde sorgusuz yeniden çizim | V | P2 | [tests/browser/theme-surfaces.cjs](../tests/browser/theme-surfaces.cjs) — Canvas disposal ve cached redraw |
| I05 | Panel inceleme ve PDF bekleme yüzeyi | V | P2 | [tests/browser/theme-surfaces.cjs](../tests/browser/theme-surfaces.cjs) — Beyaz ekran regresyonu giderildi |
| I06 | DOM/Markdown güvenli metin oluşturma | R | P1 | [openreporting/static/app/markdown.js](../openreporting/static/app/markdown.js) — innerHTML yok; link scheme kontrolü |
| I07 | Modal odak tuzağı ve klavye menüsü | V | P2 | [tests/browser/accessibility-surfaces.cjs](../tests/browser/accessibility-surfaces.cjs) — Gerçek Chromium: modal Tab/Shift+Tab, Escape/odak dönüşü, menü okları ve bölüm Space/Enter kabulü; tam ekran okuyucu kabulü değil |
| I08 | WCAG/ekran okuyucu ve kontrast denetimi | P | P2 | [tests/browser/accessibility-surfaces.cjs](../tests/browser/accessibility-surfaces.cjs) — axe-core 4.14: giriş + 8 rota, koyu/açık 17 taramada bulgu yok; gerçek ekran okuyucu/bağımsız WCAG kabulü açık |
| I09 | Mobil/yoğun veri ve uzun metin yerleşimi | P | P2 | [openreporting/static/app/app.css](../openreporting/static/app/app.css) — Önceki smoke var; bütün 30 tür mobil matrisi yok |
| I10 | Kaydetme çakışması ve sürüm geçmişi | V | P1 | [tests/test_datasources_engine.py](../tests/test_datasources_engine.py) — Optimistic locking ve sürümler testli |

## J — Gözlemlenebilirlik ve dayanıklılık

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| J01 | Tek worker sahipliği | V | P1 | [tests/test_platform_core.py](../tests/test_platform_core.py) — Aynı veri dizininde ikinci worker reddi |
| J02 | PostgreSQL worker bağlantı kaybında durma | V | P1 | [tests/test_postgres_store.py](../tests/test_postgres_store.py) — Sahiplik yeniden varsayılmıyor |
| J03 | Worker heartbeat ve stale görünümü | R | P1 | [openreporting/api/system.py](../openreporting/api/system.py) — 120 saniye stale; alarm entegrasyonu kuruma bağlı |
| J04 | Prometheus metrics localhost sınırı | R | P1 | [openreporting/api/system.py](../openreporting/api/system.py) — Proxy /metrics 404; yerel scrape |
| J05 | LDAP/SMTP tanılama mutasyonsuzluğu | V | P1 | [tests/test_smtp_transport.py](../tests/test_smtp_transport.py) — SMTP kontrolü MAIL/RCPT/DATA üretmez |
| J06 | Sır içermeyen gönderim hatası günlükleri | V | P1 | [tests/test_smtp_transport.py](../tests/test_smtp_transport.py) — Parola caplog çıktısında yok |
| J07 | Yapısal request kimliği ve gecikme metrikleri | V | P2 | [tests/test_http_telemetry.py](../tests/test_http_telemetry.py) — 5 kabul testi: sunucu IDsi, redakte JSON HTTP olayları, hata/reddetme, sınırlı etiketli süreç histogramı ve eksik yanıt; çok süreçli toplama kurum işi |
| J08 | SLO hata bütçesi ve alarm sahipliği | E | P1 | [docs/LINUX_DEPLOYMENT.md](../docs/LINUX_DEPLOYMENT.md) — Kurum SLO/on-call eşiği kabul edilmedi |
| J09 | Uçtan uca yük/soak ve p95 ölçümü | P | P1 | [docs/PERFORMANCE_ACCEPTANCE.md](../docs/PERFORMANCE_ACCEPTANCE.md) — Sentetik eşzamanlı HTTP p50/p95/p99 ölçümü var; uzun soak, gerçek kaynak ve eşzamanlı worker kabulü açık |
| J10 | Arıza ve incident müdahale runbooku | R | P1 | [docs/OPERATIONS_RUNBOOK.md](../docs/OPERATIONS_RUNBOOK.md) — 12 olay senaryosu, güvenli tanılama, kurtarma kabulü ve kapanış ölçütü yazıldı; gerçek nöbetçi/olay tatbikatı kurumda yapılacak |

## K — Yedek kurtarma ve dağıtım

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| K01 | Canlı SQLite WAL tutarlı yedek | V | P1 | [tests/test_database_backup.py](../tests/test_database_backup.py) — Online backup ve audit korunuyor |
| K02 | Yedek hedefinin yanlışlıkla ezilmesini reddetme | V | P1 | [tests/test_database_backup.py](../tests/test_database_backup.py) — Mevcut dosya ve aktif veri dizini korunuyor |
| K03 | Eksik/bozuk kaynaktan sahte yedek üretmeme | V | P1 | [tests/test_database_backup.py](../tests/test_database_backup.py) — CLI testli; deploy backup kaynak açma modu ayrıca gözden geçirilecek |
| K04 | Arşiv ve config yedeği | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — Gerçek Ubuntu yedek ve SHA doğrulaması |
| K05 | Logo gibi ek varlıkların yedeği | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — b51232f Ubuntu CI logo varlığını yedek tar içinde doğruladı |
| K06 | Tam geri yükleme kabul tatbikatı | V | P1 | [tests/test_backup_verification.py](../tests/test_backup_verification.py) — 10 izole kurtarma testi: DB/audit/arşiv/logo/anahtar ve geri açılan uygulamada API giriş/readiness, eski rapor indirme, logo ve yeni worker raporu; gerçek kurum RPO/RTO kabulü ayrıca açık |
| K07 | nginx TLS ve systemd kısıtları | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — Gerçek Ubuntu izin/HTTPS kabulü |
| K08 | Yükseltme ve veri koruyan kaldırma | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — Gerçek Ubuntu E2E yeşil |
| K09 | Başarısız schema yükseltmesinde geri dönüş | P | P1 | [deploy/upgrade.sh](../deploy/upgrade.sh) — Eski kod korunuyor; eşleşen DB/anahtar geri dönüşü manuel |
| K10 | Kurum RPO/RTO ve ayrı anahtar emanet planı | E | P1 | [docs/ENTERPRISE_DEPLOYMENT.md](../docs/ENTERPRISE_DEPLOYMENT.md) — Kurum sahipliği ve geri yükleme süresi ölçülecek |

## L — Tedarik zinciri ve teslim yönetişimi

| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |
| --- | --- | --- | --- | --- |
| L01 | Python sürüm matrisi | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — 3.11/3.12/3.13 testleri |
| L02 | Tarayıcı ES modüllerinin açık parse kontrolü | V | P1 | [tests/check_app_syntax.cjs](../tests/check_app_syntax.cjs) — Otomatik js mod seçimi hatası kapatıldı |
| L03 | Gerçek LDAP/PG ve Ubuntu CI kanıtı | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — 60f58d1 CI tüm işler başarılı |
| L04 | Bağımlılıkların tekrarlanabilir kilitlenmesi | P | P1 | [docs/DEPENDENCY_LOCK.md](../docs/DEPENDENCY_LOCK.md) — Runtime/build/test wheel SHA kilitleri; temiz offline kurulum, drift/CVE/SBOM ve aynı ortamda iki wheel SHA eşliği; host bootstrap/OS/runner/audit ortamı ve signed provenance açık |
| L05 | Bağımlılık zafiyet taraması | V | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — 30 Ekim 2026: 28 yerel runtime paketi pip-audit ile tarandı; cryptography 50.0.2 sonrası bilinen açık yok; yeni CI bekliyor |
| L06 | SBOM ve bileşen envanteri | V | P2 | [tools/runtime_requirements.py](../tools/runtime_requirements.py) — CycloneDX runtime SBOM üretildi; özel paket/yol aktarılmaz, test/audit closure dışında |
| L07 | İmzalı sürüm/provenance | O | P1 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) — CI action SHA sabitleme/checkout token koruması ve aynı ortam wheel tekrar kanıtı var; imzalı uygulama release/provenance attestasyonu yok |
| L08 | Güvenlik bildirim ve güncelleme politikası | P | P1 | [SECURITY.md](../SECURITY.md) — Bildirim/güncelleme ve olay ilk adımları yazıldı; kalıcı özel iletişim kanalı ve SLA sahibi kurum/maintainer tarafından tanımlanmalı |
| L09 | Uygulama lisansı ve hak sahipliği | E | P1 | [README.md](../README.md) — Karar kullanıcıda; lisans seçilmedi ve repo private |
| L10 | Gerçek kurum kabulü ve bağımsız güvenlik incelemesi | E | P1 | [docs/ENTERPRISE_DEPLOYMENT.md](../docs/ENTERPRISE_DEPLOYMENT.md) — İzole testler Google onayı veya bağımsız sertifika değildir |

