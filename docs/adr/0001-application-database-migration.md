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

## PostgreSQL şeması ve yazıcı güvenliği

İlk PostgreSQL şeması yalnız bilinen v1 başlangıç ifadelerinden hazırlanır: SQLite'ın 64 bit INTEGER değerleri BIGINT, denetim kimliği identity olur. Sonraki PostgreSQL geçişleri açık ifade listeleriyle eklenir. Kimlik/zaman/JSON alanları ilk geçişte TEXT kalır; UUID/timestamptz/jsonb dönüşümü ayrı bir veri geçişi gerektirir. Bu tercih mevcut denetim karma girdilerinin biçimini korur.

Şema DDL ve sürüm geçmişi aynı transaction içinde uygulanır. Eksik, ilerideki veya aralıklı sürüm geçmişi reddedilir. İlk aşamada yazıcılar transaction kapsamlı ortak advisory kilitle sıraya girer; bu SQLite'ın tek yazıcı davranışını ve denetim zincirini korur. Kilit transaction bittiğinde bırakılır ([PostgreSQL kilit belgesi](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)). Bu bilinçli başlangıç sınırı ileride kuyruk satır kilitleriyle daraltılabilir.

Denetim tablosunda UPDATE/DELETE/TRUNCATE işlemleri statement trigger ile reddedilir ([CREATE TRIGGER](https://www.postgresql.org/docs/16/sql-createtrigger.html)). Bu koruma şemayı değiştirme yetkili veritabanı yöneticisine karşı güvenlik sınırı değildir; üretimde migration/uygulama rol ayrımı ayrıca sağlanmalıdır.

Gerçek sunucu regresyonları her test için yeni ve rastgele adlı izole şema kullanır: atomik ilk kurulum/yeniden deneme, başarısız yükseltmede veri ve hash koruması, yabancı anahtarlar, büyük milisaniye değerleri, append-only davranışı ve eşzamanlı başlangıç/20 audit eklemesi. Test yalnız kendi oluşturduğu şemayı temizler.

## Deneysel uygulama yönlendirmesi

`OPENREPORTING_DATABASE_URL` boşken SQLite kullanılır; PostgreSQL URL'si verildiğinde DB facade bağlantı/işlem/şema/şifreli veri kontrollerini PostgreSQL'e yönlendirir. Hatalarda SQLite'a dönüş yapılmaz, `db_path` erişimi de reddedilir. URL repr çıktısından gizlenir. Gerçek sunucu API testi yanlış/doğru giriş, dashboard kaydı, rapor kuyruğu ve audit zincirini doğrular; SQLite dosyası oluşmadığını kontrol eder.

Bu ayar geliştirme/entegrasyon içindir, üretim desteği değildir. PostgreSQL worker sahipliği henüz uygulanmadığından worker başlaması açık hatayla engellenir. Dosya yedeği de PostgreSQL için reddedilir; yanlış bir SQLite dosyası yedeklenmez. Doctor PostgreSQL için fiziksel bütünlük taraması yerine bağlantı/şema metadata kontrolünü doğru adla sunar. Worker sahipliği, pg_dump/restore, taşıma ve kurulum tamamlanana kadar mevcut üretim kurulum yolu SQLite kalır.

## PostgreSQL worker sahipliği

Worker artık ayrı ve ömrü worker bağlamına bağlı PostgreSQL oturumunda `pg_try_advisory_lock` alır. İkinci worker farklı yerel veri dizini kullansa da aynı veritabanında başlamaz. Oturum kapanması kilidi bırakır; eski worker yeniden bağlanıp sahipliği varsaymaz. ContextVar ile taşınan guard ana iş parçacığındaki DB erişimi, worker aşamaları, çıktı yazımı ve SMTP gönderiminden önce oturumu kontrol eder. Sahiplik kaybı iş aşamalarının normal hata izolasyonundan çıkar ve worker'ı durdurur.

SMTP ile veritabanı arasında atomik commit yoktur. Ağ kaybı gönderimin ortasında olabilir; bu yüzden gönderimden önce kalıcı `sending` işareti yazılır. Yeniden başlangıç hem çalışan işleri hem üretimi bitmiş fakat `sending` kalan teslimatları `needs_review/unknown` yapar. Yeni worker bunları tekrar göndermez; eski worker da sahiplik kaybından sonra DB durumunu yazamaz. PostgreSQL gerçek-sunucu testleri tekillik/serbest bırakma/bağlantı kaybı, tam CSV üretimi ve belirsiz e-posta durumunun tekrar oynatılmamasını kapsar. Pg_dump/restore, veri taşıma ve Ubuntu PostgreSQL kurulumu hâlâ ayrı teslim işleridir.
