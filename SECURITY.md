# Güvenlik ve güvenlik güncellemeleri

OpenReporting tek kurum için dashboard/rapor uygulamasıdır. Geliştirme dalı bağımsız güvenlik
sertifikası veya Google tarafından kabul edilmiş ürün değildir. Açık riskler ve kanıtlar
[kurumsal değerlendirmede](docs/ENTERPRISE_REVIEW.md) tutulur.

## Bildirim

Güvenlik açığını, erişim bilgilerini veya gerçek şirket verisini herkese açık issue/PR, ekran
görüntüsü veya örnek log ile paylaşmayın. Depo sahibiyle mevcut özel iletişim kanalından iletişim
kurun; yalnız sentetik veriyle tekrar üretim, etkilenen kod sürümü ve olası etkiyi iletin.
Kamuya açılmadan önce depo sahibi kalıcı bir özel bildirim kanalı ve yanıt sorumlusu tanımlamalıdır.
Bu belge kullanıcı adına bir hizmet seviyesi veya yasal taahhüt oluşturmaz.

## Sürüm ve bağımlılıklar

- Kurumsal LDAP/SMTP ve son güvenlik değişiklikleri henüz yayınlanmamış geliştirme dalındadır.
  Eski v1.0.0 etiketi bu özellikleri/düzeltmeleri içermez. Canlı kurulumda yalnız doğrulanmış
  commit/paket ve o sürüme eşleşen geri yükleme planı kullanılmalıdır.
- CI uygulamanın gerçek kurulu runtime bağımlılıklarını tarar. Test/audit araçları runtime
  closure'a dahil olmadıkça SBOM'a girmez. Özel repo yolu, uygulama sırları veya yerel paket URL'si
  tarama servisine aktarılmaz. CycloneDX ve sürüm envanteri özel CI artifact'inde 14 gün saklanır.
- Tarama, o anda veri tabanında bilinen duyuruları kapsar; sıfır gün veya uygulama iş mantığı
  güvenliği için garanti değildir. Veri tabanına erişim/toplama hatası başarılı tarama sayılmaz.
- 30 Ekim 2026 taramasında önceki `cryptography==46.0.7` için bulunan duyurular nedeniyle
  `cryptography>=50.0.2,<51` kullanılır. Kullanılan Fernet biçimi korunur; anahtarlar değiştirilmez.
  Kaynak: [Cryptography değişiklik günlüğü](https://cryptography.io/en/latest/changelog/).
- [pip-audit](https://github.com/pypa/pip-audit) ücretsiz QA aracıdır; uygulama runtime'ına eklenmez.
  Kilitli/hashli tüm platform bağımlılık paketi ve imzalı release provenance hâlâ ayrı açık iştir.

## Olayda ilk adımlar

1. Şüpheli hesabı yönetici ekranından pasifleştirin; oturumları iptal edilir. Dizin grubunu da
   düzeltin. Son yerel kurtarma yöneticisini koruyun; dizin arızasında yetkileri gevşetmeyin.
2. Kaynak kimlik bilgisi sızdıysa kaynağın kendi yönetiminde iptal/yenileme yapıp uygulamada
   yeniden kaydedin. SMTP/LDAP servis parolalarını kurum kasası/korumalı dosyada yenileyip web
   ve worker'ı birlikte yeniden başlatın. Sırları günlük veya issue'ya kopyalamayın.
3. Worker `unknown` veya `partial_rejected` teslimatında otomatik tekrar göndermeyin. Önce
   posta sunucusu kaydından hangi alıcıların aldığını belirleyin.
4. Audit/manifest hatasında ilgili arşivi güvenilir kabul etmeyin; orijinal yedek ve logları
   koruyun, `verify-audit`/`verify-backup` ile araştırın. Canlı DB'yi elde düzeltip hash zincirini
   geçerliymiş gibi yeniden yazmayın.
5. Kurtarmayı önce izole kopyada doğrulayın; canlı değişim için bakım penceresi, eşleşen kod/DB,
   ayrı anahtar ve kurumun RPO/RTO kabulü gerekir. Sunucu/backup/anahtar emanetinden kurum sorumludur.
