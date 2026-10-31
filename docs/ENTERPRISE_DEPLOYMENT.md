# Kurumsal LDAP ve SMTP kurulumu

Bu özellikler henüz yayınlanmamış geliştirme dalındadır; eski v1.0.0 paketi LDAP içermez.
Kurulumda bu değişiklikleri içeren, testleri geçen kaynak paketini kullanın. Desteklenen
sunucu düzeni Ubuntu 24.04 + nginx HTTPS + systemd web/worker + yerel SSD üzerinde SQLite'tır.
Windows başlatıcısı yerel deneme içindir; şirket kullanıcıları sunucuya tarayıcıyla bağlanır.
PostgreSQL uygulama veritabanı işletim/geri yükleme desteği hâlâ deneyseldir.

## Kurulum sırası

1. [Linux kurulumunu](LINUX_DEPLOYMENT.md) kurumun DNS adı ve güvenilen HTTPS sertifikasıyla yapın.
   `--self-signed` yalnız deneme içindir. API portunu (8810) dış ağa açmayın.
2. Ayrı bir **yerel kurtarma yöneticisi** oluşturun ve parolasını kurum kasasında saklayın.
   LDAP hesapları mevcut yerel hesapların yerini almaz; son yerel yönetici korunur.
3. `/etc/openreporting/openreporting.env` dosyasını düzenleyin. Parolaları kaynak koduna,
   komut satırına veya sohbete yazmayın. Dizin/SMTP hesabı, grup DN'leri ve alıcı alan adları
   kuruma göre yapılandırılır; uygulama bunları kendiliğinden keşfetmez.
4. Dizin ve SMTP sunucularının DNS adı, portu, sertifika zinciri ve ağ erişimini doğrulayın.
   Sunucu saatini NTP ile eşitleyin. Sertifikanın SAN alanı kullanılan DNS adıyla eşleşmelidir.
5. Aşağıdaki ayarları yaptıktan sonra web ve worker servislerini **birlikte** yeniden başlatın.
6. Bağlantı ve kabul kontrollerini tamamlayıp küçük bir deneme raporunu onaylı test alıcısına gönderin.

HTTP sınırı: `OPENREPORTING_PUBLIC_URL` yalnız gerçek HTTP(S) origin olmalıdır; kullanıcı/parola,
path prefix, query veya fragment içermez. Secure cookie açıkken HTTPS gerekir. Loopback ve bu
URL'nin hostname'i otomatik izinlidir. Ek kurum DNS/IP adlarını `OPENREPORTING_ALLOWED_HOSTS`
ile virgülle ayırın; port, URL veya wildcard kullanmayın. Bilinmeyen Host başlıkları ve cross-origin
tarayıcı mutasyonları reddedilir. Proxy'nin `X-Forwarded-Proto` ayarı ve uygulamanın yalnız
loopback proxy'ye güveni korunmalıdır; HTTPS kurulumunda Origin/protokol uyumunu test edin.
Origin göndermeyen CLI/API istemcileri mevcut cookie+CSRF/rol kontrolünü kullanır; CORS açılmaz.

```bash
sudo systemctl restart openreporting-web openreporting-worker
sudo /opt/openreporting/app/deploy/openreporting-admin.sh doctor --check-integrations
sudo /opt/openreporting/app/deploy/openreporting-admin.sh check-ldap reader
```

`doctor --check-integrations` TLS, servis hesabı, LDAP arama tabanı ve SMTP EHLO/AUTH/NOOP
kontrolü yapar; e-posta göndermez. `check-ldap` parolayı etkileşimli ister, grup rolünü
doğrular; kullanıcı veya oturum oluşturmaz. Yönetim → Sunucu durumu → Kurumsal bağlantılar
aynı bağlantı kontrollerini sunar. Yalnız yöneticiler kullanabilir; test sonucu denetim kaydına girer.

## Active Directory / LDAP

Salt okunur bir dizin servis hesabına yalnız kullanıcıları, kalıcı kimliklerini ve üyeliklerini
okuma izni verin. Domain Admin veya parola değiştirme/yazma yetkisi gerekmez.

```ini
OPENREPORTING_LDAP_ENABLED=true
OPENREPORTING_LDAP_URL=ldaps://directory.example.com:636
OPENREPORTING_LDAP_BIND_DN=CN=ReportReader,OU=ServiceAccounts,DC=example,DC=com
OPENREPORTING_LDAP_BIND_PASSWORD_FILE=/etc/openreporting/ldap-password
OPENREPORTING_LDAP_BASE_DN=DC=example,DC=com
OPENREPORTING_LDAP_USER_FILTER='(&(objectClass=user)(sAMAccountName={username}))'
OPENREPORTING_LDAP_ID_ATTRIBUTE=objectGUID
OPENREPORTING_LDAP_GROUP_ATTRIBUTE=memberOf
OPENREPORTING_LDAP_GROUP_ROLES='{"CN=ReportReaders,OU=Groups,DC=example,DC=com":"viewer","CN=ReportEditors,OU=Groups,DC=example,DC=com":"editor"}'
OPENREPORTING_LDAP_CA_FILE=/etc/openreporting/corporate-ca.pem
OPENREPORTING_LDAP_TIMEOUT=10
OPENREPORTING_LDAP_SESSION_MINUTES=60
```

`ldaps://` bağlantısı baştan TLS kullanır. `ldap://directory.example.com:389` seçilirse
**kimlik bilgileri gönderilmeden önce StartTLS zorunludur**. Güvensiz bağlantıya geri dönüş,
sertifika doğrulamasını kapatma ve otomatik referral takibi yoktur. Sistem güven deposu kullanılır;
özel kurum CA zinciri PEM dosyasıyla belirtilebilir. TLS 1.2 veya üzeri gerekir.

- Giriş adı varsayılan AD filtresinde `sAMAccountName` değeridir (`reader`). UPN veya
  `DOMAIN\reader` dönüştürülmez. UPN gerekiyorsa filtreyi `userPrincipalName={username}` ile
  açıkça değiştirin ve aynı kişi için tek giriş adı biçimi kullanın.
- OpenLDAP için filtre `(&(objectClass=inetOrgPerson)(uid={username}))`, kimlik alanı
  `entryUUID` olabilir. Dizin `memberOf` sağlamalıdır (ör. memberOf overlay).
- Filtrede tam bir `{username}` yer tutucusu bulunur; kullanıcı girdisi LDAP filtresine
  güvenli biçimde kaçırılır. Arama tek kullanıcı döndürmelidir; sıfır veya birden fazla eşleşme reddedilir.
- Grup DN'leri **doğrudan üyelik** üzerinden karşılaştırılır (büyük/küçük harfe duyarsız).
  İç içe grup zinciri ve AD birincil grup çözümlemesi yapılmaz. İzin verilen gruba doğrudan üye ekleyin.
- Eşleşen grubu olmayan kullanıcı giriş yapamaz. Birden çok eşleşmede `admin > editor > viewer`
  sırası geçerlidir. Yönetici yetkisini ancak açıkça bir DN'yi `admin` ile eşleyerek verin.
- Başarılı kullanıcı bind'inden sonra yerel bir profil otomatik oluşturulur. LDAP parolası saklanmaz;
  profil `objectGUID`/`entryUUID` ile bağlanır. Yerel kullanıcı adı çakışması hesabı devralamaz.
  Kalıcı kimliğin farklı giriş adıyla tekrar kaydı reddedilir; dizin yeniden adlandırmaları işletmeci
  tarafından veri/denetim geçmişi korunarak ayrıca planlanmalıdır.
- Rol ve profil bilgisi her başarılı LDAP girişinde güncellenir. Rol değişince eski oturumlar kapatılır.
  Yerel yönetici kullanıcıyı pasifleştirirse mevcut oturumları da hemen kapanır; sonraki LDAP girişi
  yerel pasifliği geri alamaz. LDAP parolası/rolü yerel kullanıcı ekranından değiştirilemez.
- Dizin hizmeti kesilirse LDAP girişinde 503 hatası verilir; yerel parolaya dönüş yoktur.
  Ayrı yerel yönetici hesabı kullanılabilir. Beş başarısız giriş 15 dakika kilit uygular.
- Dizin hesabının kapatılması veya grup üyeliğinin kaldırılması yeni girişi engeller.
  Mevcut oturumlar en çok `LDAP_SESSION_MINUTES` (varsayılan 60; aralık 5–240 dakika) sürer;
  dizin her HTTP isteğinde sorgulanmaz. Acil iptal için uygulamada hesabı pasifleştirin.
  `LDAP_ENABLED=false` yapılıp servis yeniden başlatıldığında LDAP oturumları da reddedilir.
- Kerberos/Windows bütünleşik SSO ve LDAP parola değiştirme desteklenmez. Yerel/LDAP hesaplarında
  doğrulayıcı ve kurtarma kodlarıyla [iki adımlı giriş](MFA.md) kullanılabilir; TOTP kimlik avına dayanıklı değildir.

## SMTP / kurum relay'i

```ini
OPENREPORTING_MAIL_ENABLED=true
OPENREPORTING_SMTP_HOST=smtp.example.com
OPENREPORTING_SMTP_PORT=587
OPENREPORTING_SMTP_SECURITY=starttls
OPENREPORTING_SMTP_USER=reporter
OPENREPORTING_SMTP_PASSWORD_FILE=/etc/openreporting/smtp-password
OPENREPORTING_SMTP_FROM=reports@example.com
OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS=example.com
OPENREPORTING_SMTP_CA_FILE=/etc/openreporting/corporate-ca.pem
OPENREPORTING_SMTP_TIMEOUT=30
OPENREPORTING_SMTP_LOCAL_HOSTNAME=openreporting.example.com
```

| Senaryo | Ayar |
| --- | --- |
| STARTTLS submission / relay | `SMTP_SECURITY=starttls`, genellikle port 587 veya TLS destekli 25 |
| Başlangıçtan TLS | `SMTP_SECURITY=tls`, genellikle port 465 |
| IP izinli relay (SMTP AUTH yok) | `SMTP_USER` ve parola/parola dosyası birlikte boş; TLS yine zorunlu |
| Kurum CA'sı | CA zincirini `SMTP_CA_FILE` ile yükleyin; sertifika ve DNS adı doğrulanır |

Port ve bağlantı türü kurum posta yöneticisinin ayarına göre eşleşmelidir. Şifresiz SMTP,
STARTTLS desteklemeyen sunucuya geri dönüş veya sertifika denetimini kapatma desteklenmez.
Eski kurulumlardaki `SMTP_STARTTLS=true` uyumluluğu korunur; `SMTP_SECURITY` verilirse önceliklidir.
SMTP AUTH kullanıcı adı/parola desteklenir; OAuth2 veya Graph gönderimi uygulanmamıştır.
Yalnız OAuth2 kabul eden hizmetlerde kurumun onaylı TLS relay'i gerekir.

Alıcı izin listesi tam alan adı eşleşmesi kullanır; `*.example.com` jokeri yoktur.
Alt alan adlarını ayrı ekleyin. `SMTP_FROM` yetkisi ve gerekiyorsa gönderici relay izinleri posta
yöneticisinde tanımlanmalıdır. Küçük bir test raporuyla zarf göndericisi, alıcı, teslimat ve
karantina/SPF/DKIM/DMARC davranışını kurum tarafında doğrulayın.

Eksik veri içeren raporlar varsayılan olarak gönderilmez. Ham eklerin toplamı 20 MB ile sınırlıdır;
MIME kodlaması boyutu artırdığı için relay limiti buna göre yeterli olmalıdır.
Gönderici/kimlik doğrulama/alıcı/DATA açık reddi `failed`, bazı alıcıların reddi `partial_rejected`,
kabul yanıtı kaybolan gönderim `unknown` olarak kaydedilir. Son iki durumda bazı alıcılar
mesajı almış olabilir. Otomatik tekrar gönderim yoktur; posta sunucusu kaydını kontrol edin.

## Sır dosyaları, yükseltme ve işletim

LDAP ve SMTP parolaları ya doğrudan ortam değişkeninde ya da `*_PASSWORD_FILE` dosyasında tutulur;
ikisi birlikte verilirse başlangıç reddedilir. Parola dosyalarının son satır sonu temizlenir.
Linux'ta dosyaları `/etc/openreporting/` altında `root:openreporting`, `0640` olarak saklayın;
home dizinleri sertleştirilmiş servislerden erişilemez. Windows denemelerinde NTFS ACL'lerini
yalnız çalıştıran kullanıcıyla sınırlandırın. `windows/Settings.local.ps1` örnek ayarları alabilir;
SMTP için başlatıcıda mevcut `-AllowEmail` seçeneği gerekir.

Şema v3 `external_identities`, v4 ise MFA ve faktör doğrulanmış oturum tablolarını
ekler; kullanıcı/parola/rapor kayıtları korunur. Eski bütün web/worker süreçleri durdurulmuş
bakım penceresi gerekir. Yükseltmeden önce tutarlı DB yedeği, arşiv, şifreleme anahtarı
ve ayrı entegrasyon sırlarının kurtarma kopyasını alın. Yeni şemayı eski uygulama sürümüyle açmayın;
geri dönüşte birbiriyle eşleşen kod/DB yedeği ve anahtar gerekir. Genel dizin taşımalarında yeni
kimliklerin eski profillerle eşleştirilmesi ayrıca planlanmalıdır.

Kabul testleri: yerel kurtarma girişi; doğru/yanlış LDAP parolası; grup üyeliği ve rol düşürme;
izleyicinin serbest sorguya erişememesi; dizin kesintisi; güvenilmeyen/yanlış adlı sertifika;
SMTP bağlantı testi; küçük raporun gerçek test alıcısına ulaşması; worker/saklama/yedek ve
geri yükleme kontrolü. Gerçek kurum AD/relay'ine erişilmeden bunların o ortamda tamamlandığı
iddia edilmez. CI, izole OpenLDAP ve yerel TLS SMTP sunucularını kullanır.

Uygulama LDAP davranışı [ldap3 TLS](https://ldap3.readthedocs.io/en/latest/ssltls.html) ve
[bağlantı belgelerine](https://ldap3.readthedocs.io/en/latest/connection.html), SMTP davranışı
[Python smtplib](https://docs.python.org/3/library/smtplib.html) belgelerine dayanır.
