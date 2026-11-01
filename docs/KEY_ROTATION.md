# Veri kaynağı anahtarının kontrollü değişimi

Kapsam: desteklenen tek host SQLite üretim tabanında **veri kaynağı `secure_json`,
kullanıcıya bağlı MFA `secret_json` seedleri ve Sistem ayarları sayfasında kaydedilen
SMTP/LDAP parolaları (`app_settings.secure_json`)**. Hepsi aynı transaction içinde yenilenir;
sonuç ayrı `sources_rekeyed` / `mfa_secrets_rekeyed` / `settings_secrets_rekeyed` sayıları döndürür.
Kullanıcı parolaları/oturumları, LDAP/SMTP ayrı parola dosyaları, disk şifreleme veya KMS/HSM
rotasyonu değildir. Deneysel PostgreSQL için bu bakım komutları yazma yapmadan reddedilir.
Mevcut tek satırlık Fernet anahtarı yeni kodda çalışmaya devam eder; otomatik geçiş yoktur.

Yeni biçim `openreporting-fernet-keyring-v1`: birinci anahtar yeni yazımların primary'sidir,
önceki anahtarlar eski şifreli kayıtları açmak için tutulur. En fazla sekiz anahtar ve 16 KiB
dosya kabul edilir; bozuk sürüm/kimlik/tekrar veya bilinmeyen alanlar reddedilir.
Anahtar kimliği SHA-256'nın kısa tanıtıcısıdır; sır veya bağımsız imza değildir.
Şifreleme, çözme ve zaman damgasını koruyan yeniden şifreleme
[Cryptography MultiFernet](https://cryptography.io/en/latest/fernet/#cryptography.fernet.MultiFernet)
ile yapılır; yeni kripto algoritması yazılmaz.

## Hazırlık: mevcut anahtarı ve DB'yi değiştirmez

Bu komutlar işletmecinin yetkili bakım akışıdır; geliştirme sırasında kullanıcının aktif
önizleme anahtarı veya hesabı değiştirilmez. Önce DB/arşiv/logo ve mevcut anahtarı ayrı güvenli
emanette yedekleyin; `verify-backup` ile eşleşmelerini doğrulayın. SMTP/LDAP parolalarının
ayrı kurtarma kopyaları da kurum politikasına göre korunur.

Standart Ubuntu kurulumunda yönetim wrapper'ı servis kullanıcısıyla çalışır. Yazılabilir,
özel staging dosyası kullanın; mevcut çıktı dosyası asla üstüne yazılmaz:

```bash
sudo /opt/openreporting/app/deploy/openreporting-admin.sh prepare-key-rotation \
  --output /var/lib/openreporting/keyring-next.json
```

Komut yeni rastgele primary + eski anahtarlarla **yeni** dosya üretir, fsync uygular ve
yalnız primary kimliği/anahtar sayısını döndürür. Dosya 0600 oluşturulur; Windows'ta NTFS
ACL ayrıca ayarlanmalıdır. Aktif dosya, ayar ve DB değişmez. Anahtarı terminale yazdırmayın.

## Bakım penceresi: bütün web süreçleri ve worker durmalı

`--services-stopped` işletmecinin ön koşulu bildirmesidir; araç uzaktaki/tüm süreçlerin
durduğunu teknik olarak kanıtlamaz. Çok süreçli hot reload veya sıfır kesintili rotasyon
desteklenmez. Anahtar nesnesi süreçte cache'lenir; kademeli değişimde eski süreç yeni
ciphertext'i açamayabilir. Bu nedenle bütün web/worker süreçleri birlikte bakımda olmalıdır.

1. Önceden doğrulanan yedek ve bakım planıyla servisleri durdurun. Çalışan rapor/posta
   olmadığını doğrulayın; belirsiz gönderimi yeniden oynatmayın.
2. Hazırlanan dosyayı farklı, sürümlü bir `/etc/openreporting/` yoluna `root:openreporting`
   ve 0640 izinleriyle kurun. Eski dosya korunur. `OPENREPORTING_SECRET_KEY_FILE` ayarını
   yeni dosyaya çevirin. Yeni format için bu özelliği içeren uygulama kodu gerekir.
3. Aynı üretim ayarını alan wrapper ile:

   ```bash
   sudo /opt/openreporting/app/deploy/openreporting-admin.sh rekey-secrets --services-stopped
   ```

   Eşleşen şema ve audit zinciri zorunludur. SQLite tek yazma işlemi içinde bütün kaynaklar
   primary'ye geçirilir; primary ile doğrulanır ve sır içermeyen audit eklenir. Hatalı token,
   DB veya audit yazma hatasında **bütün değişiklikler rollback olur**. Zaten primary'de
   olan kayıtlar tekrar yazılmaz; komut tekrarında değişen kaynak sayısı sıfır olur.
   Eksik DB/anahtar oluşturulmaz, migration çalıştırılmaz.
4. Önce yeni ring ile eşleşen yeni yedeği doğrulayın; eski yedeğin eski anahtarla da
   kurtarılabildiğini koruyun. Gerekli kabul tamamlanana kadar eski anahtarlar ring'de kalabilir.

## Eski anahtarları aktif kullanımdan çıkarma

Servisler hâlâ durmuşken:

```bash
sudo /opt/openreporting/app/deploy/openreporting-admin.sh prepare-key-retirement \
  --services-stopped --output /var/lib/openreporting/keyring-primary-only.json
```

Bu komut DB'yi salt okunur snapshot içinde inceler. Her şifreli kaydın yalnız primary ile
açıldığı doğrulanmadan çıktı üretmez. Başarılıysa **başka yeni dosyada** yalnız primary
bulunur; aktif dosya/DB yine değiştirilmez. İşletmeci bu dosyayı farklı sürümlü `/etc` yoluna
kurup ayarı ona çevirebilir. Eski ring/dosyalar otomatik silinmez.

Bütün servisleri yeni ayarla başlatın. Yerel kurtarma girişi, readiness/audit, küçük kaynak
okuması, eski rapor/logo indirme ve yeni rapor üretimi kabulünü yapın. Yeni DB + yeni keyring
yedeği doğrulanmalıdır. `OPENREPORTING_BACKUP_INCLUDE_KEY=true` seçilirse yedek betiği
ayardaki etkin raw anahtar/keyring dosyasını `secret.key` adıyla, servis kimliğiyle okuyarak
dahil eder; eski sabit dosyayı varsaymaz. Varsayılan yine ayrı anahtar emanetidir. Eski yedekler **eski anahtarı/ring'i** gerektirebilir; aktiften
çıkarma eski kurtarma emanetini silme izni değildir. Saklama/imha kararını kurum verir.

## Geri dönüş ve sınırlar

Hazırlık aşamasında iptal etmek aktif sisteme dokunmaz. Rekey sonrası yalnız eski anahtara
dönmek yeni ciphertext'i açmaz; önceki raw anahtar ile önceki DB ve eşleşen kod yedeği birlikte
kurtarılmalıdır. Eski uygulama kodu yeni keyring formatını okuyamaz. DB şeması değişmemesi,
her eski kod/anahtar kombinasyonunun uyumlu olduğu anlamına gelmez.

Testler eski token okuma, primary yazımı, tam rollback, audit hatası, tekrar çalıştırma,
hesap/oturum/parola koruma, erken retirement reddi, dosya/format/symlink sınırı, eksik DB,
schema ve PostgreSQL reddini kapsar. Yedek testleri eski yedeğin eski/ring anahtarıyla,
yeni yedeğin primary-only anahtarıyla kurtarılmasını doğrular. Gerçek kurumda bakım,
yedek emaneti, servis izinleri ve felaket kurtarma tatbikatı ayrıca kabul edilmelidir.
