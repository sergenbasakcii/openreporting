# İki adımlı giriş ve hesap kurtarma

Yerel ve LDAP hesapları, parolaya ek olarak TOTP doğrulayıcı kodu kullanabilir.
Profildeki **İki adımlı giriş** kartı kurulum, kurtarma kodlarını yenileme ve kapatma
işlemlerini sunar. Ana menü veya dashboard tasarımı değişmez. Yeni bir üyelik,
SMS/e-posta hizmeti veya ücretli doğrulayıcı gerekmez; mevcut kurum doğrulayıcısı
RFC 6238, SHA-1, 6 hane ve 30 saniyelik TOTP desteklemelidir.

## Kurulum ve politika

HTTPS altında giriş yapın, profil kartından mevcut parolayı doğrulayın ve ekrandaki **QR kodu**
doğrulayıcı uygulamanızla okutun (QR sunucuda üretilir; dış servis kullanılmaz). Okutulamazsa
"Anahtarı elle girin" bölümündeki anahtar kullanılır. Onay için uygulamadaki 6 haneli kod girilir.
Anahtar yalnız bu kurulum yanıtında gösterilir;
kurulum 10 dakika geçerlidir. Ekranı kapatıp yeniden başlatmak eski bekleyen anahtarı
geçersiz kılar. İlk kodla onaydan sonra **10 kurtarma kodunu ayrı güvenli emanete alın**.
Kodlar sonradan okunamaz; her biri yalnız bir kez geçerlidir. Etkinleştirme tüm
oturumları kapatır. Yeniden girişte parolaya ek güncel TOTP veya kurtarma kodu gerekir.
Az önce kullanılan 30 saniyelik kod tekrar kabul edilmez; bir sonraki kodu bekleyin.

`OPENREPORTING_MFA_REQUIRED_ROLES=admin` yeni Ubuntu kurulum şablonunun varsayılanıdır.
`admin,editor,viewer` ile kapsam genişletilir; boş değer isteğe bağlı kurulum sağlar.
Mevcut kurulumun ayarı otomatik değiştirilmez. Etkin faktör, politika boşaltılsa da
girişte zorunludur. Politikaya tabi henüz kurulum yapmamış hesap yalnız 10 dakikalık
**kurulum oturumu** alır: session/CSRF/logout ve kendi MFA setup/confirm uçları dışında
iş API'lerine erişemez. Arayüz de dashboard/rapor verisini yüklemeden kurulum ekranında
durur. Politikayı değiştirirken eski parolalı oturumlar da bu sınıra tabi olur.

Kapatma veya kurtarma kodlarını yenileme mevcut parola ve yeni TOTP/kullanılmamış
kurtarma kodunu tekrar ister; işlem bütün oturumları iptal eder. Zorunlu rolde kapatma
bir sonraki girişte tekrar kurulum gerektirir. Parola sıfırlama faktörü kaldırmaz.
LDAP adımında aynı sabit dizin kimliği ve aynı rol tekrar doğrulanır; yerel hesabı
dizin hesabına dönüştürmez. Gerçek kurum grupları/CA/saat senkronizasyonu ayrıca kabul edilmelidir.

### Doğrulayıcı uygulamada alan eşleşmesi

QR okutmak en güvenli yoldur; anahtarı elle yazmak yalnız kamera kullanılamıyorsa gerekir.

| Uygulama | Yol | Uygulamadaki alan → OpenReporting |
| --- | --- | --- |
| Google Authenticator | **+** → *QR kodu tara* (veya *Kurulum anahtarı gir*) | *Hesap adı*: serbest (ör. OpenReporting) · *Anahtarınız*: **Kurulum anahtarı** · tür: *Zamana dayalı* |
| Microsoft Authenticator | **+** → *Diğer hesap* → *QR kodu tara* (veya *Kodu el ile girin*) | *Hesap adı*: serbest · *Gizli anahtar*: **Kurulum anahtarı** |

Uygulamanın gösterdiği **6 haneli ve 30 saniyede değişen** sayı, ekrandaki
*2. Uygulamada görünen 6 haneli kod* alanına yazılır. Kurulum anahtarı bu alana yazılmaz;
alan yalnız rakam kabul eder. Kod sürekli reddediliyorsa telefonun saatinin otomatik
(ağdan) ayarlı olduğunu kontrol edin: sunucu ±30 saniyelik sapmayı kabul eder, daha
fazlasını etmez. Kurulumun 10 dakikalık süresi dolarsa ekran **Yeni QR kod al** düğmesini
gösterir; uygulamadaki eski kaydı silip yeni QR'ı okutun.

### Yönetici erişimi ve kurtarma

Arayüzden: *Yönetim → Kullanıcılar* listesinde iki adımlı girişi açık kullanıcıların yanında
**İki adımlı girişi sıfırla** düğmesi vardır. Neden seçilir ve yönetici kendi parolasıyla onaylar;
kullanıcının faktörü ve oturumları silinir, parolası değişmez. Yönetici kendi faktörünü buradan
sıfırlayamaz (Profil sayfasını kullanır). Zorunlu MFA rolleri *Sistem ayarları → Güvenlik*
sekmesinden değiştirilir.

Sunucu operatörü (arayüze erişim yoksa):

```bash
# Parolayı unutan kullanıcı (faktör korunur, bütün oturumlar kapanır)
sudo /opt/openreporting/app/deploy/openreporting-admin.sh reset-password <kullanıcı>
# Telefonu kaybolan / kurtarma kodu kalmayan kullanıcı (parola değişmez)
sudo /opt/openreporting/app/deploy/openreporting-admin.sh reset-mfa <kullanıcı> --reason lost-device
```

`--reason` değerleri: `lost-device`, `compromise`, `recovery`; işlem denetim kaydına yazılır.
Sıfırlamadan sonra kullanıcı girişte yeniden QR ile kurulum yapar. Bir kurulum anahtarı ekran
görüntüsü veya mesajla paylaşıldıysa o kurulumu tamamlamayın; `reset-mfa --reason compromise`
ile sıfırlayıp yeniden kurun.

## Sunucu korumaları

160 bit rastgele seed kullanıcı kimliğine bağlı yükle Fernet ile şifrelenir.
Yalnız kurulumda seed gösterilir; GET durum yanıtı yalnız etkinlik/politika/kalan kod
sayısını döndürür. 128 bit rastgele kurtarma kodlarının kullanıcıya bağlı SHA-256
özetleri saklanır. Kodlar, parola veya seed denetim/HTTP kaydına yazılmaz.
CSRF, mevcut parola ile adım yükseltme ve HTTPS (yerel loopback test istisnasıyla)
mutasyonlarda zorunludur. TOTP ±1 zaman penceresinde atomik sayaçla tek kullanımlıdır;
kurtarma kodu da tek transaction içinde tüketilir. Parola ve faktör başarısızlıkları
ortak 5 deneme/15 dakika kapısını kullanır. Scrypt/LDAP pahalı işleri süreç başına
4 ile sınırlıdır; ters proxy hız limiti ayrıca gerekir. NTP ve saat izleme işletmeci sorumluluğudur.

## Bakım, anahtar ve yedek

Şema **4**, `user_mfa` ve doğrulanmış oturum bağını tutan `mfa_sessions` tablolarını ekler.
Önce tüm eski web/worker süreçlerini durdurun; tutarlı DB/arşiv/logo ve ayrı anahtar
yedeği alın; eşleşen yeni kod/bağımlılıklarla yükseltin. Çalışan şema-3 sürümün üstünde
kontrolsüz ikinci sürüm açmayın. Yeni şema eski kodla açılmaz; geri dönüş eşleşen
DB/anahtar/kod yedeğiyle olur. Mevcut yerel önizleme hesabı otomatik kaydedilmez veya değiştirilmez.

[Anahtar bakımı](KEY_ROTATION.md) hem kaynak sırlarını hem MFA seedlerini aynı atomik
işlemde yeniden şifreler; retirement ikisinin de primary anahtarla açılmasını doğrular.
[Yedek doğrulayıcı](../openreporting/backup_verify.py) seedin kullanıcıya bağlılığını ve anahtarla
açılmasını kontrol eder (`encrypted_factors` sayacı). Yalnız MFA kaydı kalmışken de
kayıp anahtarın yerine yeni anahtar üretilmez. Çalışan süreç anahtarı bellekte tutar;
dosya değişiminde bütün servisler bakım penceresinde yeniden başlatılmalıdır.

Cihaz ve kurtarma kodlarının ikisi de kayıpsa, kimlik ve yetki kurum prosedürüyle
doğrulandıktan sonra yetkili OS işletmecisi:

```bash
sudo /opt/openreporting/app/deploy/openreporting-admin.sh reset-mfa kullanici \
  --reason lost-device
```

Desteklenen nedenler: `lost-device`, `compromise`, `recovery`. Komut eşleşen şema ve
geçerli denetim zinciri ister, otomatik migration yapmaz; faktörü ve oturumları kaldırır,
parolayı değiştirmez, sır içermeyen işletmeci denetimi ekler. Zorunlu rol tekrar kurar.
OS erişimi bu kurtarma yetkisini içerir; ayrıcalıklı işletmeci ve kimlik onayı kayıtları
kurumda korunmalıdır. Kurtarma kodlarını destek taleplerine/repoya koymayın.

## Kabul sınırı ve kaynaklar

TOTP **kimlik avına dayanıklı değildir**. SAML/OIDC/Kerberos SSO, WebAuthn/passkey,
merkezi cihaz/faktör attestation ve kurumun risk temelli erişim politikası uygulanmış değildir.
Bu uygulama veya bu testler Google kabulü, bağımsız sertifikasyon ya da NIST AAL
uyumluluğu iddiası oluşturmaz. B10 bu nedenle kısmi kalır.

Testler: `tests/test_mfa.py` RFC vektörleri, API kurulum/yenileme/kapatma, parola/faktör
kapısı, replay/yarış, LDAP adım yükseltme, kurulum izolasyonu, şema geçişi ve gerçek
anahtar/yedek roundtrip; `tests/test_postgres_store.py` ayrı PostgreSQL kabulü;
`tools/mfa_browser_acceptance.py` yalnız geçici loopback uygulamasında gerçek Chromium
akışları ve iki tema erişilebilirlik taraması. Bu araç canlı uygulamada çalıştırılmaz.

Referanslar: [RFC 6238](https://www.rfc-editor.org/info/rfc6238/),
[PyOTP](https://pyauth.github.io/pyotp/),
[OWASP MFA Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html).
