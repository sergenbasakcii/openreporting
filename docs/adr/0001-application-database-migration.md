# ADR 0001: Uygulama veritabanı geçişinin aşamaları

Tarih: 28 Ekim 2026. Durum: geçiş yönü kabul edildi; PostgreSQL uygulaması henüz yapılmadı.

## Bağlam

Uygulamanın kalıcı durumu SQLite üzerinde; PostgreSQL veri kaynağı desteği bu durum veritabanından bağımsız. PostgreSQL üretim desteği tek bir bağlantı değişikliğiyle sağlanamaz. Mevcut kod `?` parametreleri, hem ad hem indeksle satır erişimi, `BEGIN IMMEDIATE`, `INSERT OR IGNORE`, `COLLATE NOCASE` ve SQLite hata sınıfları kullanıyor. CLI yedekleme/doctor, anahtar kaybı kontrolü ve Ubuntu kurulum CI'ı da SQLite'a bağlı.

## Karar

SQLite geliştirme ve mevcut kurulumlar için korunacak. Üretim PostgreSQL desteği açık bir yapılandırmayla eklenecek; bağlantı hatasında başka veritabanına sessiz dönüş olmayacak. Veri kaynağı bağlantıları uygulama durumuna erişim için yeniden kullanılmayacak.

Önce mevcut şema geçişleri atomik ve sıralı hale getirilecek. Şema, sürüm kaydı ve sürüm numarası aynı işlem içinde yazılacak; başlangıç sürümü yazma kilidi alındıktan sonra okunacak. Hatalı geçişte mevcut veri korunacak. Sonraki adımlar:

1. Bağlantı, işlem ve satır sözleşmesini ayır; SQL çağrılarını ve sürücüye özel hata yakalamalarını taşı. Yeni bağımlılık kararı bu aşamada lisans ve bakım değerlendirmesiyle verilecek.
2. PostgreSQL şema ve sürüm geçişlerini, denetim zinciri için yazıcı serileştirmesini, kuyruk sahiplenmesini ve worker kilidini birlikte uygula. UUID/zaman/JSON tür dönüşümleri mevcut karma girdilerini değiştirmemeli.
3. Boş hedefe açıkça çalışan SQLite taşıma aracı geliştir; satır sayıları, ilişkiler ve denetim zincirini doğrula. Kaynak dosyayı değiştirme.
4. Yedek/geri yükleme, doctor, şifreleme anahtarı güvenliği ve Ubuntu kurulum/yükseltme/geri dönüş akışlarını taşı.
5. Her iki sürücüyle test matrisi, PostgreSQL üzerinde eşzamanlı iş alma ve gerçek Ubuntu kurulum/geri yükleme doğrulaması tamamlanmadan PostgreSQL üretim desteği hazır sayılmaz.

## İlk aşama doğrulaması

Yeni regresyon testleri başarısız ilk kurulumu, başarısız yükseltme sonrası veri ve denetim zincirini, yeniden denemeyi, eksik geçişi ve eşzamanlı başlangıcı kapsar. Bu aşama PostgreSQL desteği sunmaz; mevcut verinin sonraki geçişlere güvenle hazırlanmasını sağlar.
