# Değişiklik günlüğü

## Yayınlanmamış

### Güvenlik ve sağlamlık
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
