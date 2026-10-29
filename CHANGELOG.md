# Değişiklik günlüğü

## Yayınlanmamış

### Kurumsal kimlik ve posta bağlantıları
- LDAP/Active Directory: doğrulanan LDAPS veya zorunlu StartTLS, salt okunur servis hesabı,
  güvenli kullanıcı araması, kalıcı dizin kimliği ve doğrudan grup üyeliğinden rol eşleme.
- Şema v3 dizin profillerini yerel hesaplardan ayırır; parola saklanmaz, yerel hesap devralınamaz.
  Rol değişiminde oturum iptali ve son yerel kurtarma yöneticisinin korunması eklendi.
- SMTP: STARTTLS ve başlangıçtan TLS, kurum CA zinciri, süre sınırı, AUTH veya TLS relay,
  açık ret/kısmi ret/belirsiz teslimat ayrımı ve güvenli parola dosyaları.
- Sunucu durumunda LDAP/SMTP bağlantı kontrolü; `doctor --check-integrations` ve `check-ldap`.
  Kurulum ve kabul sınırları docs/ENTERPRISE_DEPLOYMENT.md içinde.

### Tema düzeltmeleri
- Açılır seçim listeleri ve seçenek yüzeyleri koyu/açık temanın renklerini kullanır.
- Yeni grafiklerin ipuçlarındaki beyaz arka plan giderildi; tema değişiminde açık paneller
  mevcut veriyle yeniden çizilir, ek veri sorgusu yapılmaz. Sistem teması değişiklikleri izlenir.
- PDF önizleme hazırlanırken açılan boş beyaz sekme yerine mevcut temaya uygun bekleme ekranı gösterilir.

### Veri kaynakları ve görselleştirmeler
- Şelale, huni, ağaç haritası, hiyerarşi halkası, gül ve paralel koordinat panellerine vektör PDF eklendi; kalan tablo karşılığı sayısı 6 oldu.
- Histogram, XY, balon, kutu ve mum grafiklerine yerel vektör PDF çizimi eklendi; tabloya aktarılan yeni tür sayısı 17’den 12’ye indi.
- Prometheus, Loki, HTTP JSON ve HTTP CSV veri kaynakları eklendi (toplam 7 tür).
- Mevcut panel seçicisine 20 görselleştirme eklendi (toplam 30); mevcut arama grafik adlarını da süzer.
- Tasarım ve oluşturma akışı korundu. Yeni HTTP kaynakları salt okunur, TLS doğrulamalı, sabit origin ve yanıt bütçeli; metadata adresleri/yönlendirmeler engellenir.
- Şema v2 mevcut kaynakları koruyarak tür kısıtını genişletir. PDF yeni türlerin on dördünde vektör, diğerlerinde açık etiketli veri tablosu sunar; Excel/CSV aktarımı korunur.
- Veri biçimleri ve sınırlar: docs/EXTRA_SOURCES_AND_PANELS.md.


### Geliştirme altyapısı
- PostgreSQL worker için veritabanı oturumuna bağlı tekil sahiplik eklendi. Sahiplik bağlantısı kaybolursa
  iş aşamaları ve e-posta gönderimi durur; otomatik yeniden bağlantıyla sahiplik varsayılmaz.
- `OPENREPORTING_DATABASE_URL` ile deneysel PostgreSQL uygulama bağlantısı seçilebilir; yapılandırma
  çıktısı DSN parolasını gizler ve bağlantı hatasında SQLite'a dönülmez. PostgreSQL dosya yedeği henüz
  desteklenmediği için açık hatayla engellenir. API giriş/dashboard/rapor kuyruğu entegrasyon testi eklendi.
- PostgreSQL başlangıç şeması, atomik sürüm geçişleri, transaction kapsamlı yazıcı kilidi ve
  denetim kayıtları için UPDATE/DELETE/TRUNCATE koruması eklendi; gerçek sunucu regresyonları genişletildi.
- PostgreSQL uygulama sürücüsünün bağlantı/parametre/satır/işlem ilkelleri ve izole PostgreSQL CI sözleşme testi
  eklendi. Bu ilkeller henüz uygulama veritabanı seçimine bağlı değildir; üretim PostgreSQL desteği tamamlanmadı.

### Güvenlik ve sağlamlık
- Rapor üretimi bitmiş olsa da e-posta `sending` durumunda yarıda kaldıysa yeniden başlangıçta
  `needs_review/unknown` yapılır; belirsiz teslimat tekrar kuyruğa alınmaz.
- Dashboard, klasör, veri kaynağı ve rapor listeleri taşınabilir `LOWER` sıralaması kullanır;
  aynı ada sahip kayıtlar kimlikle kararlı sıralanır. Dashboard yıldız filtresi SELECT takma adına
  bağlı kalmaz; metin araması açıkça büyük/küçük harf duyarsızdır ve joker karakterleri kaçırır.
- SQLite bağlantı, işlem, sürüm/bütünlük kontrolü ve yedekleme işlemleri ayrı sürücü modülüne taşındı;
  CLI artık bu ayrıntıları çoğaltmıyor. Yedekleme eksik kaynak dosyası oluşturmaz, hedefi özel izinlerle
  ve üzerine yazmadan açar; başarısız yeni yedeği temizler. Canlı WAL verileri geri yükleme testiyle doğrulandı.
- Anahtar kayıpken mevcut veritabanı okunamıyorsa yeni şifreleme anahtarı oluşturulmaz;
  kimlik bilgisi kontrolü salt okunur bağlantıyla yapılır ve veritabanını oluşturmaz.
- Rapor kuyruğu tekrarları yalnız idempotency anahtarı çakışmasında mevcut işi kullanır;
  dashboard yıldızları da açık çakışma hedefi kullanır. SQLite'a özel genel hata bastırma kaldırıldı.
- Veritabanı şema geçişleri, sürüm kaydı ve sürüm numarası artık aynı atomik işlemde uygulanır;
  başarısız geçiş mevcut veriyi korur ve sonraki başlangıçta yeniden denenebilir.
- Birden fazla web worker'ın aynı anda ilk açılışında şema sürümü kilit alındıktan sonra okunur;
  SQLite WAL başlatma kilitleri sınırlı süreyle yeniden denenir.

## 1.0.0 — 2026-10-27

### Yeni
- Grafana benzeri arayüz (derleme gerektirmeyen ES modülleri + yerel ECharts): dashboard’lar, klasörler, etiketler,
  yıldızlar, sürüm geçmişi, paylaşım, kiosk modu, Keşfet, profil/tercihler, açık/koyu tema.
- 24 sütunlu sürükle-bırak ızgara, satırlar, satır/panel tekrarı, 10 görselleştirme türü, eşikler, değer eşlemeleri,
  geçersiz kılmalar (negatif-Y trafik), panel zaman geçersiz kılma ve kaydırma.
- Sorgu motoru: Zabbix (grup/host/etiket/item filtreleri, history/trend, item ID, son değerler, problemler, SQL history modu),
  PostgreSQL/TimescaleDB (salt-okunur SQL + Grafana makroları), TestData (Zabbix simülasyonu).
- Grafana-Zabbix uyumlu fonksiyonlar, güvenli matematik ifadeleri, 13 dönüşüm, dashboard değişkenleri (zincirleme, çoklu, Tümü).
- Grafana dashboard JSON içe aktarma.
- Dashboard tabanlı raporlar: PDF/Excel/CSV, kapak + içindekiler, `split_by` ile host/grup bölümleri, önizleme, zamanlama,
  e-posta, doğrulanmış arşiv, saklama süresi, tek tıkla dashboard’u PDF/Excel indirme.
- Veri kaynağı yönetimi (Fernet ile şifreli kimlik bilgileri), kullanıcı yönetimi arayüzü, sunucu durumu, Prometheus metrikleri.
- Ubuntu dağıtımı: kurulum/yükseltme/kaldırma betikleri, sertleştirilmiş systemd servisleri, nginx TLS, gece yedeği, Docker.
- CLI: `doctor`, `export-dashboards`, `import-dashboards`, çoklu işçili `serve`.

### Güvenlik ve sağlamlık
- İzleyiciler yalnızca kayıtlı dashboard panellerini çalıştırır (sunucu kayıtlı sorguyu kullanır); Keşfet ve
  metric-find editörlere özeldir. İzleyici değişkenleri kaçışlı (katı) biçimlendirilir.
- PostgreSQL: genişletilmiş protokol, sunucu tarafı LIMIT, E''/U&''/$$ tırnak hilelerinin reddi, oturum düzeyinde salt-okunur.
- Kullanıcı regex’leri zaman aşımlı ve boyut sınırlı; Excel/CSV formül enjeksiyonu ve kontrol karakterleri temizlenir.
- Günlük kovalar dashboard saat dilimine göre hizalanır; elle girilen mutlak zamanlar dashboard saat diliminde yorumlanır.
- Rapor/dashboard değişince zamanlamalar pasife alınır; onay kaydı (yapılandırma özeti, sürüm, onaylayan) tutulur.
- Roller: Yönetici, Editör, İzleyici. Parola en az 14 karakter (scrypt).
- Arayüz: sayfa geçişlerinde yarış durumları, sürükle/boyutlandır, satır daraltma, panel düzenleyici iptali, oturum
  süresi dolunca tek seferlik çıkış, klavye ile menü/diyalog/satır/tablo sıralama erişilebilirliği.
- Dağıtım: nginx istek sınırları, systemd sistem çağrısı filtresi, şifreleme anahtarı varsayılan olarak yedek dışı,
  GPG ile şifreli yedek seçeneği, salt-okunur Docker konteynerleri.
