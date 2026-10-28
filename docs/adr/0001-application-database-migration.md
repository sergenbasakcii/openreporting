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

İkinci adımda şifreli veri varlığı kontrolü `db.has_encrypted_secrets` sınırına alındı; mevcut SQLite dosyası salt okunur açılır. Veritabanı hatası anahtar oluşturma izni sayılmaz. PostgreSQL sürücüsü bu kontrolü uygulama veritabanı bağlantısı üzerinden sağlamalıdır.

Rapor kuyruğunda bütünlük hatası yakalayıp aynı işlemde yeniden SELECT yapmak yerine `ON CONFLICT(idempotency_key) DO NOTHING` kullanılır. Bu, PostgreSQL'de hatadan sonra işlemin iptal durumuna geçmesine dayalı bir tuzağı kaldırır. Dashboard yıldızlarında da `INSERT OR IGNORE` yerine belirli birincil anahtar çakışması hedeflenir. Parametre biçimi ve diğer sürücü farkları sonraki adımlarda kalır.

## Sürücü sınırı

SQLite bağlantı/işlem, sürüm okuma/yazma, bütünlük kontrolü, şifreli veri varlığı ve yedekleme işlemleri `sqlite_store.py` içindedir. Uygulama ve CLI bunlara `db.py` üzerinden erişir. Şema geçişleri ve denetim zinciri uygulama DB katmanında kalır. Henüz sürücü seçimi ve PostgreSQL bağlantısı eklenmedi.

Yeni sürücü mevcut çağrı sözleşmesini korumalı veya çağrıları birlikte taşımalıdır:

- `connect(settings)` bağlantıyı her durumda kapatır; işlemler açıkça `transaction(connection)` ile commit/rollback olur.
- `execute(sql, parameters)` bağlı parametreleri değer olarak işler; cursor `rowcount`, `fetchone`, `fetchall` ve satır gezintisi sağlar.
- Satırlar hem alan adı hem sıra ile okunur; `dict(row)` kullanılabilir. Mevcut JSON ve zaman metinlerinin dönüşümü denetim zincirindeki baytları değiştiremez.
- `schema_version`, `set_schema_version`, `check_integrity`, `has_encrypted_secrets` ve `backup_database` sürücüye özgü davranışı kapatır. PostgreSQL fiziksel bütünlük kontrolü SQLite PRAGMA eşdeğeri gibi sunulmamalıdır.
- Yedek mevcut hedefi değiştirmez, eksik kaynak oluşturmaz, canlı commit edilmiş veriyi içerir. Arşiv ve anahtar ayrı kalır.
