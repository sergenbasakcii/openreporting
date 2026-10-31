# PostgreSQL salt okunur kurulum kontrolü

`openreporting check-postgres` yapılandırılmış **uygulama durumu veritabanını**
kontrol eder. PostgreSQL veri kaynağı sorgusu veya genel `doctor` komutu değildir.
DSN, mevcut servis ortamındaki `OPENREPORTING_DATABASE_URL` üzerinden alınır;
komut satırına parola yazılması gerekmez. DSN, sunucu/ad/kullanıcı/parola veya
sorgu metni çıktıya konmaz. Şirket ortamına bağlanarak bu geliştirme sırasında
kontrol yapılmadı; gerçek sunucu testleri yalnız CI'ın geçici veritabanındadır.

Komut dizin, anahtar, kullanıcı, oturum veya tablo oluşturmaz; migration, arşiv,
gönderim ve worker başlatmaz. Ayrı `REPEATABLE READ, READ ONLY` işlemi kullanır;
PostgreSQL'in kendisi kalıcı uygulama tablolarına yazmayı reddeder. Şema eski,
yeni, aralıklı veya eksikse düzeltme/yükseltme denemeden başarısız sonuç verir.

JSON `checks` alanı şunları bildirir:

- Salt okunur snapshot; birincil sunucu ve varsayılan olarak yazılabilir oturum.
- Güncel şema; uygulama tablolarının gerçekten tablo olması ve okunabilmesi.
- İşletimde gereken veri DML hakları ve denetim identity dizisinin kullanım hakkı.
  Bu, migration/DDL hakkı talep etmez ve gerçek INSERT/UPDATE/DELETE denemesi yapmaz.
- Denetim zinciri ve etkin yerel kurtarma yöneticisinin varlığı.
- Hem oturum hem etkin rol ve üyeliklerinde superuser, CREATEDB, CREATEROLE,
  REPLICATION veya BYPASSRLS yetkilerinin olmaması. Üyelik kontrolü muhafazakârdır;
  SET/INHERIT ayrıntısı nedeniyle kullanılamayan bir üyeliği de işaretleyebilir.
- TCP'de etkin TLS ile `sslmode=verify-full`; Unix socket yerel OS sınırı olarak
  ayrı bildirilir. Socket dizini/peer erişimi ayrıca işletmeci tarafından doğrulanır.

TLS olması tek başına sunucu kimliğinin doğrulandığını göstermez; `require`,
`prefer` ve `verify-ca` bu kontrolü geçmez. CA ve sunucu adı kontrolünün farkı
[resmî libpq SSL belgesinde](https://www.postgresql.org/docs/current/libpq-ssl.html),
rol/nesne yetki sorguları ise [PostgreSQL bilgi fonksiyonlarında](https://www.postgresql.org/docs/current/functions-info.html)
tanımlıdır. Yeni bir TLS kapatma seçeneği eklenmedi ve mevcut bağlantı ayarları
bu komut tarafından değiştirilmez. TLS/rol hatalı olsa da uygulamanın mevcut
başlatma yolu otomatik değiştirilmez; bu araç bir ön kontrol raporudur.

Tüm kontroller geçtiğinde çıkış kodu `0`; eksik kontrol, SQLite seçimi veya
güvenle tamamlanamayan incelemede `2` olur. `inspection_failed` hata ayrıntılarını
redakte eder; yanlışlıkla bağlantı bilgisi basmaz. İnceleme yetkisi eksikse sırf
kontrol geçsin diye superuser verilmemelidir. Başarısız sonucu gerçek veride
otomatik rol değiştiren veya migration yapan bir sarmalayıcıyla aşmayın.

`ok=true` yalnız bu kontrollerin geçtiğini gösterir; JSON'da
`production_ready=false` her zaman korunur. Fiziksel bütünlük taraması, şema
sahibine karşı denetim güvenliği, arşiv/anahtar doğrulaması, pg_dump/pg_restore,
SQLite taşıma, geri dönüş, yüksek erişilebilirlik ve kurum kabulü değildir.
PostgreSQL üretim işletim/taşıma kontrolü A05 **açık** kalır.

Kanıt: `tests/test_postgres_check.py` TCP doğrulama koşulları, redaksiyon ve
CLI'ın kurulum yapmamasını sınar. `tests/test_postgres_store.py` gerçek sunucuda
metadata snapshot'ı, şema4'ü değiştirmeme ve aynı bağlantı içindeki bir INSERT'in
PostgreSQL tarafından reddini doğrular. CI'ın standart TCP servisi TLS/superuser
bulgularını doğru biçimde başarısız raporlar; gerçek şirketin verify-full CA
kurulumunun burada onaylandığı iddia edilmez.
