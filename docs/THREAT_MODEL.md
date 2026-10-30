# Tehdit modeli ve güven sınırları

İnceleme kapsamı: tek Ubuntu host, nginx HTTPS, ayrı web ve tek worker süreci, yerel SQLite,
isteğe bağlı LDAP ve SMTP, yedi salt okunur kaynak ve tarayıcı/PDF/Excel/CSV çıktıları.
Deneysel PostgreSQL uygulama deposu için işletim/geri yükleme desteği tamamlanmadan üretim kabulü verilmez.

## Varlıklar ve yetkiler

Korunacak varlıklar: kaynak sırları ve Fernet anahtarı, LDAP/SMTP servis kimliği, oturum/CSRF
belirteçleri, kullanıcı/rol kayıtları, dashboard ve rapor tanımları, rapor verisi, audit zinciri,
arşiv/manifest ve yedekler. Kimlik bilgileri kaynakta salt okunur ve en az kapsamlı olmalıdır.

| Sınır | Güven kararı | Kalan sınır |
| --- | --- | --- |
| Tarayıcı → nginx → API | HTTPS, kısıtlı proxy güveni, CSRF, sunucu rol kontrolü, gövde bütçesi | Host/Origin matrisi ve yük testi genişletilmeli |
| Viewer → kayıtlı panel | Tarayıcı target/dönüşüm yerine kayıtlı tanım; güvenli değişken biçimi | Genel roller tüm kurum kapsamındadır; tenant/klasör ACL yok |
| Editör → veri kaynağı | Ad hoc okuma sorgusu izinli, kaynakta READ ONLY/get/GET | Kaynak hesabının erişebildiği kapsam editöre güven sınırıdır |
| Yönetici → kaynak/entegrasyon | Kaynak origin ve rol eşlemesi ayrıcalıklı yapılandırmadır | Admin kötü niyeti ve hatalı kaynak hesabı yetkisi uygulama tarafından tümüyle çözülemez |
| API/worker → LDAP | Zincir/DNS doğrulamalı TLS, salt okunur servis araması, kullanıcı bind, sabit grup eşlemesi | İç içe grup, SSO, MFA yok; mevcut oturumun dizin değişimine tepki üst sınırı var |
| API/worker → SMTP | Zorunlu TLS, alıcı domain listesi, belirsizlikte otomatik tekrar yok | Relay teslim/karantina ve OAuth2 kurum entegrasyonuna bağlı |
| Worker → dosya/audit | Atomik dosya, SHA manifesti, audit çapası ve tek worker | Dosya+SMTP+DB tek dağıtık işlem değildir; unknown durumu korunur |
| Yedek → izole doğrulama | Hash, DB/audit, arşiv/logo, anahtar kontrolü; yol/link/cihaz reddi | SHA zinciri bağımsız imza değildir; canlı restore işletmeci işlemidir |

## Kötüye kullanım senaryoları ve kanıt

| Senaryo | Önlem / kanıt | Açık iş |
| --- | --- | --- |
| Viewer başka sorgu veya raw değişken yollar | tests/test_review_fixes.py, kayıtlı panel izolasyonu | Kuruma özel veri erişimi kabulü |
| JSON gövdesi başlığı atlayarak belleği büyütür | tests/test_request_limits.py, gerçek ASGI chunk toplamı ve endpoint'e ulaşmama | Çok kullanıcılı soak/slow-upload ölçümü |
| SQL/regex/PromQL enjeksiyonu | READ ONLY, tek ifade, quote/context escape, regex timeout testleri | Gerçek kaynak hesabı izinlerinin kabulü |
| HTTP kaynağıyla metadata/redirect hedeflenir | Sabit origin, gerçek peer metadata reddi, redirects kapalı | Yöneticiye verilen dahili ağ erişiminin kurumda sınırlandırılması |
| LDAP adı yerel admini devralır veya pasifliği kaldırır | Kalıcı kimlik ve yerel hesap çakışma/pasiflik testleri | Dizin yeniden adlandırma işletimi |
| Dizin/DB arızası geniş yetki veya sahte yeşil sağlık üretir | LDAP fallback reddi; auth/health/readiness 503 testleri | Kurum alarm ve on-call sahipliği |
| Rapor metni Excel formülü veya HTML çalıştırır | Güvenli hücre/DOM/Markdown, CSP ve regression testleri | Tam bağımsız XSS/a11y incelemesi |
| Logo veya arşiv açma yoluyla host dosyası yazılır | Logo yeniden kodlama; restore whitelist, boyut ve link reddi testleri | Üretim yedek emanet/erişim izinleri |
| SMTP yanıtı kaybolduğunda çift gönderim | unknown/partial_rejected, replay etmeyen worker testleri | Posta sunucusu kayıtlarının gerçek kabulü |
| Zafiyetli kripto bağımlılığı kurulur | Runtime CVE taraması, sürüm alt sınırı, SBOM ve eski Fernet uyumu | Hashli lock, imzalı build/release, sıfır gün incelemesi |

## Tehdit modelinin sınırları

Root veya web/worker servis hesabının tamamen ele geçirilmesi, aynı hostta tutulan DB ve
anahtarı erişilebilir kılabilir. Fernet tam disk veya uygulamanın bütün verisi için şifreleme
değildir. Host güvenliği, ayrı yedek/anahtar emaneti, ağ segmentasyonu ve gerçek kurum kabulü
gereklidir. Audit hash zinciri ayrıcalıklı DB/yedek saldırganına karşı bağımsız dijital imza sayılmaz.

Referans yaklaşım: [OWASP ASVS](https://asvs.owasp.org/), [NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final),
[Google SRE üretime hazırlık incelemesi](https://sre.google/sre-book/evolving-sre-engagement-model/).
Bu model, o kuruluşların uygulamayı onayladığı veya bütün standart maddelerinin sağlandığı iddiası değildir.
