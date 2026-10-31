# Klasör içerik izinleri

Bu özellik tek kurulumdaki dashboard ve rapor içeriğini kullanıcı bazında sınırlar.
Çok kiracılı veri kaynağı izolasyonu değildir. Admin tüm klasörlere kurtarma erişimini
korur. Editörlerin mevcut salt okunur serbest veri kaynağı sorgulama yetkisi sürer;
aynı kaynak verisinin farklı sorguyla okunmasını klasör izni engellemez. Birbirine
güvenmeyen kurumlar için ayrı kurulum ve ayrı kaynak hesapları gerekir.

## Kullanım

Yönetici, Dashboard’lar sayfasındaki klasör menüsünden **Klasör izinleri** seçer.
Paylaşılan klasörler önceki davranışı korur. Kısıtlama açıldığında yalnız yönetici
ve açıkça seçilen etkin kullanıcılar erişir. `Görüntüleme` içeriği, kayıtlı panel
sorgularını ve dışa aktarmayı açar. `Düzenleme` ayrıca içerik değişikliğini açar;
uygulamadaki rol üst sınırdır: viewer hesabı edit izni verilse de düzenleyemez.
Genel/root klasör paylaşılandır. Yeni klasörler başlangıçta paylaşılandır.

İzinler yalnız yönetici tarafından CSRF korumalı API ile değiştirilebilir.
İki yönetici aynı revizyonu kaydettiğinde biri 409 alır; tekrar açıp güncel izinleri
görmelidir. Bilinmeyen/etkin olmayan veya yinelenen kullanıcılar kaydedilmez.
Değişiklik ve izin verilen kullanıcı kimlikleri denetim zincirine yazılır.
LDAP kullanıcılarına yerel kullanıcı kimlikleri üzerinden izin verilir; dizin
grup/rol güncellemesi uygulamadaki global rol sınırını korur. LDAP grup ACL eşlemesi
ve tenant tanımı bu sürümün kapsamında değildir.

## Korunan yollar

- Dashboard listesi, klasör/sayı/etiketler; sürüm içeriği ve geçmişi; yıldızlar;
  dashboard notları, silme, geri yükleme, import ve overwrite.
- Kaydetme/taşıma işleminde aynı yazma işlemi içinde hem eski hem hedef klasörün
  düzenleme izni gerekir. Erişim filtresi SQL sıralama/limitinden önce uygulanır.
- Kayıtlı viewer paneli ve değişken çözümleme, rapor önizlemesi ve PDF/XLSX/CSV
  dışa aktarma; editör isteğinde kayıtlı UID verilirse o içerik de kontrol edilir.
- Rapor tanımı, zamanlamalar, çalışma listesi ve hash doğrulamalı arşiv indirme
  bağlı dashboard üzerinden kontrol edilir. Çalışması olan rapor başka dashboard'a
  bağlanamaz: geçmiş özel arşivleri yeni bir paylaşılan dashboard üzerinden açmamak
  için yeni rapor oluşturulur.
- Ana sayfa tercihi izinsiz dashboard'a ayarlanamaz; izin kaybında `/api/user`
  tercihi `null` döndürür. Kullanıcının kalıcı tercih kaydı zorla değiştirilmez.

Küresel dashboard notları ve yüklenen rapor logoları kurulumun paylaşılan
kaynaklarıdır. Logolara hassas veri koymayın. Bu sınır içerik ACL ile otomatik
tenant depolaması veya serbest metin anonimleştirmesi sağlandığı anlamına gelmez.

## Arka plan işleri ve yetki iptali

Klasör izin değişikliği o klasöre bağlı etkin zamanlamaları kapatır; yönetici
raporu tekrar inceleyip etkinleştirir. Manuel kuyruk işleri güncel başlatan
hesabı, zamanlanmış işler güncel yönetici onayını kullanır. Örtük sistem/admin
kimliği yoktur. Klasör düzenleme izni, hesap ve rol; sorgu/render öncesi, render
sonrası arşiv yazımına başlamadan ve SMTP `sending` devrinde tekrar kontrol edilir.
Render sırasında izin kaybı arşivlenmemiş çıktıyı bırakmaz ve iş `blocked` olur.
Arşiv indirme her yeni istekte güncel izin ister.

Yetki iptali, başlamış bir HTTP yanıtını veya salt okunur dış sorguyu geri alamaz.
`sending` devrinden sonra SMTP sunucusunun kabul ettiği mesaj geri çağrılamaz.
`unknown` teslimat otomatik tekrar edilmez. DB yazma işlemleri SQLite yazma kilidi
ve PostgreSQL işlem kilidi altında yapılır; çok sunuculu genel tenant kontrolü
ve dış servislerle dağıtık atomiklik iddiası yoktur.

## Şema ve doğrulama

Şema 5, mevcut altı sütunlu klasör tablosunu değiştirmeden `folder_policy` ve
`folder_user_grants` tablolarını ekler. Eksik politika paylaşılan kabul edilir;
mevcut kullanıcı, parola, MFA, anahtar, oturum ve içerik değerleri korunur.
Yükseltme önce yedek ve izole kopyada denenmelidir; eski çalışan önizleme verisine
bu geliştirme sırasında migration uygulanmadı. Eski sunucu feature flag'i
döndürmüyorsa yeni statik arayüz izin menüsünü göstermez.

Kanıtlar: `tests/test_folder_access.py`, gerçek PostgreSQL sözleşmesindeki
klasör/revizyon/worker testi ve yalnız geçici veride çalışan
`tools/folder_browser_acceptance.py` / `tests/browser/folder-flow.cjs`.
Yerel genel test ve CI sonuçları teslim kaydında ayrı belirtilir; gerçek kurum
kabulü, kaynak bazlı haklar ve tenant izolasyonu halen açık değerlendirmelerdir.
