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

## Sorgu taşınabilirliği

Liste sıralamaları SQLite'a özel `COLLATE NOCASE` yerine `LOWER(alan), kimlik` kullanır. ASCII adlarda mevcut harf duyarsız sıra korunur; eşit normalleştirilmiş adlarda kimlik ikinci anahtardır. Unicode harf dönüşümü veritabanının dil/yerel ayarına bağlıdır; iki sürücü için tam Türkçe eşdeğerlik henüz taahhüt edilmez.

Dashboard yıldız filtresi WHERE içinde SELECT takma adı kullanmak yerine kullanıcıya bağlı EXISTS alt sorgusu kullanır. Metin aramasında iki taraf LOWER ile karşılaştırılır; yüzde, alt çizgi ve ters eğik çizgi değerleri bağlı parametrede kaçırılır. PostgreSQL'e geçişte kalan parametre biçimi ve veri türü farklılıkları ayrıca ele alınmalıdır.

## PostgreSQL bağlantı öncülü

`postgres_store.py` mevcut psycopg bağımlılığıyla bağlantı, bağlı parametre, satır ve işlem ilkellerini sağlar. Henüz `db.py` sürücü seçimine bağlanmaz; uygulama SQLite kullanmaya devam eder. Tam şema, kilit ve işletim desteği gelmeden DSN ayarı etkinleştirilmez.

İç uygulama SQL'indeki `?` işaretleri, tırnaklar ve yorumlar korunarak `$n` biçimine çevrilir; değerler SQL metnine eklenmez. Yüzde karakterlerinin değişmemesi için psycopg RawCursor seçildi ([resmî cursor belgesi](https://www.psycopg.org/psycopg3/docs/advanced/cursors.html)). Bu dar uyumluluk katmanı kullanıcı SQL'i veya PostgreSQL JSON soru işareti operatörleri için kullanılmaz. Satır fabrikası isim/sıra ve `dict(row)` erişimini birlikte sunar ([resmî satır fabrikası belgesi](https://www.psycopg.org/psycopg3/docs/advanced/rows.html)). Yeni bağımlılık eklenmedi.

Bağlantı/statement/lock zaman aşımı sınırlıdır; bağlantı bütün çıkışlarda kapanır. İşlemler psycopg transaction bağlamıyla geri alınır. Birim testlerinden ayrı gerçek sunucu sözleşme testi `OPENREPORTING_TEST_POSTGRES_DSN` gerektirir; CI'da izole PostgreSQL 16 servisiyle ayrı iş eklendi. Yerelde bu test sunucu bulunmadığında atlanır ve bu durum entegrasyon başarısı sayılmaz.
