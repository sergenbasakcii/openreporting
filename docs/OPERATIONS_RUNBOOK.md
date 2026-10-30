# İşletim ve olay müdahalesi

Bu yönerge tek Ubuntu host + nginx HTTPS + systemd + yerel SQLite tabanı içindir.
Windows önizleme ve deneysel PostgreSQL için üretim kabulü sayılmaz. Komutlar işletmeci
tarafından yetkili bakım penceresinde uygulanır; bu dosya canlı sistemde işlem başlatmaz.
Kurumun olay sorumlusu, nöbetçi, alarm hedefi, RPO/RTO ve duyuru kanalı henüz tanımlanmadı.

## İlk inceleme ve kanıt

1. Etkiyi ayırın: giriş, dashboard okuma, kaynak sorgusu, rapor üretimi, posta veya tüm servis.
   İlk hata zamanı, uygulama sürümü, HTTP durumu ve yanıtın `X-Request-ID` değerini kaydedin.
2. `systemctl status openreporting-web openreporting-worker nginx` ve sınırlı
   `journalctl -u openreporting-web -u openreporting-worker --since '-15 min'` çıktısını inceleyin.
   Günlükleri paylaşmadan önce sır/kişisel veri incelemesi yapın; ortam değişkenlerini dökmeyin.
3. `curl --fail http://127.0.0.1:8810/healthz` süreç canlılığını,
   `curl --fail http://127.0.0.1:8810/api/health` DB/şemayı kontrol eder.
   `/readyz` yönetici oturumu gerektirir ve audit zincirini tarar; sık public probe olarak kullanılmaz.
4. Yetkili yöneticiyle Sunucu durumu, worker yaşı, disk ve entegrasyon kontrolünü inceleyin.
   `openreporting-admin.sh doctor` ve `verify-audit` mevcut bakım arayüzleridir.
5. Nedeni bilmeden kuyruk/kayıt silmeyin veya belirsiz postayı yeniden göndermeyin.
   Önce tutarlı yedek ve ilgili olay kanıtını koruyun. Kanıt saklama/erişim süresini kurum belirler.

## Senaryolar

| Belirti | Ayırıcı kontrol | Müdahale ve başarı ölçütü |
| --- | --- | --- |
| nginx 502, uygulama kapalı | Servis durumu, başlangıç hatası, son sürüm/ayar değişikliği | Hatalı ayar veya eşleşmeyen kod/şemayı düzeltin. Web canlılığı, DB sağlığı ve yönetici readiness tekrar başarılı olmalı. |
| `/api/health` 503 | Disk, DB dosyası/izinleri, şema sürümü; hata mesajı yerine durum kontrolü | Kaynağı koruyun. Eksik DB yerine boş DB üretmeyin. Gerekirse doğrulanmış yedekten eşleşen sürüme bakım dönüşü yapın. |
| Audit zinciri bozuk | `verify-audit`; hangi ID'de bozulduğunu sınırlı yetkiyle kaydedin | Yazımları durdurma kararını olay sorumlusu alır. Hashleri yeniden hesaplayıp olayı gizlemeyin. Güvenilen yedek ve bağımsız kayıtlarla araştırın. |
| Worker 120 saniyeden eski veya işler kuyrukta | Worker servisi, son tick, çalışan iş ve disk | İkinci worker açmadan mevcut sahipliği doğrulayın. Başarılı yeni heartbeat ve küçük test raporunun tamamlanması gerekir. |
| Disk dolu / arşiv yazılamıyor | Disk boşluğu, servis izinleri, başarısız rapor durumu | Yedek/arşiv saklama kararını kurum uygular. Rastgele dosya veya DB satırı silmeyin. Alan/izin düzelince yeni raporla doğrulayın. |
| LDAP kullanılamıyor veya kimlik reddi | Sunucu durumundaki güvenli LDAP kontrolü, CA/DNS/saat, bind arama ve doğrudan grup eşlemesi | TLS doğrulamasını kapatmayın; kurum CA/kimlik/grup ayarını düzeltin. Yetkili yerel kurtarma yöneticisini koruyun; dizin kullanıcısına sessiz yerel fallback yok. |
| SMTP hata / kısmi ret / unknown | Gönderim durumu, alıcı domain izni, güvenli SMTP bağlantı kontrolü ve relay kayıtları | NOOP bağlantı kontrolü posta göndermez. `unknown` ve kısmi ret otomatik tekrar edilmez; relay kayıtlarıyla kesinleşmeden tekrar göndermeyin. Gerçek test alıcısı kabulü kurum işidir. |
| Kaynak sorgusu yavaş / 422 / 429 | Kaynak erişimi, filtre/nokta bütçesi, sorgu süresi, nginx limitleri, kaynak hesabının salt okunurluğu | Sınırları topluca kapatmak yerine pahalı paneli daraltın. Viewer izolasyonu ve kaynağın READ ONLY/GET sözleşmesi korunur. |
| HTTP 400/403 sonrası giriş yapılamıyor | `PUBLIC_URL`, açık Host alias'ları, proxy scheme/port, Secure cookie, Origin | Gerçek HTTPS origin/alias ayarını düzeltin. Wildcard Host/CORS açmayın, üretim çerez politikasını gevşetmeyin. |
| Beklenmeyen 500 / kesilen yanıt | `X-Request-ID` ile JSON HTTP olayı, durum ve route şablonu, incomplete sayacı | Gövde/başlık/sırları loglamadan etkiyi belirleyin. Gerekirse izole sentetik kopyada yeniden üretin. HTTP 500 genel mesajı exception ayrıntısını istemciye taşımaz. |
| Anahtar kayıp / şifreli kaynak açılamıyor | Ayrı anahtar emaneti ve eşleşen yedek; dosya izinleri | Yeni anahtarla mevcut sırların üstüne yazmayın. Eşleşen anahtarı yetkili emanetten kurtarın. Kontrollü değişim için [offline rotasyon yönergesi](KEY_ROTATION.md) kullanılır. |
| Yükseltme başarısız | Yükseltme öncesi yedek, `app.prev`, şema sürümü, kurulu bağımlılıklar | Kod geri dönüşü DB downgrade değildir. DB/anahtar/arşiv/logo ve eşleşen kod birlikte bakım planıyla kurtarılır; eski kod yeni şemayı reddeder. |

## Kurtarma kabulü

`verify-backup` önce SHA manifestini ve izinli içerikleri denetleyip geçici dizinde DB,
audit, tamamlanmış raporlar, PNG logolar ve şifreli kaynakları doğrular. Ayrı saklanan anahtarı
`--key-file` ile sağlayın; parola/anahtar değerini komut satırına yazmayın.
Bu kontrol canlı verinin üstüne yazmaz. Canlıya geri dönüş bakım penceresi ve ayrı işletmeci kararıdır;
[Linux dağıtım yönergesi](LINUX_DEPLOYMENT.md) kullanılır.

Kurtarma sonrası giriş, readiness, eski rapor indirme, logo, küçük yeni rapor ve worker
başarısı kontrol edilir. Sentetik kabul `tests/test_backup_verification.py` içinde çalışır;
gerçek kurumun RPO/RTO tatbikatı ve posta teslimat kabulü bununla tamamlanmış sayılmaz.

## HTTP gözlemlenebilirliği

Web yanıtında sunucunun ürettiği `X-Request-ID` vardır; istemcinin gönderdiği ID'ye güvenilmez.
CLI ham URL içeren Uvicorn access kaydı yerine `http_request` JSON olayı üretir: ID,
worker kimliği, HTTP metodu, kayıtlı route şablonu, durum, toplam yanıt süresi, byte ve tamamlanma.
Ham URL/query, başlık, gövde, cookie, IP ve kullanıcı adı bu olayda bulunmaz.
Başarılı statik dosya/health/metrics kayıtları gürültüyü azaltmak için bastırılır; hatalar kaydedilir.
Bu, tüm uygulama/vekil/host günlüklerinin sır içermediği garantisi değildir; nginx/OS/driver günlükleri
ve kurumun log erişim/saklama ayarları ayrıca incelenmelidir.

`/metrics` yalnız gerçek loopback istemciye açıktır ve nginx üzerinden 404 döner. HTTP sayaç,
inflight, incomplete ve gecikme histogramı **web süreci başınadır**; `worker_id` ile ayrılır.
Çok web sürecinde tek portu rastgele scrape etmek tüm worker'ları kapsamaz. Birleşik HTTP SLO
için kurum log toplayıcısı veya her worker'ı kapsayan ayrı scrape topolojisi gerekir;
mevcut uç çok süreçli toplam trafik ölçümü diye sunulmaz. Yeniden başlatmada süreç sayaçları sıfırlanır.
Histogramda route/ID/kullanıcı/veri kaynağı etiketi bulunmaz; istekle seri sayısı büyütülemez.

Pahalı scrypt/LDAP giriş işi her web sürecinde en fazla dört eşzamanlı çağrıya alınır;
sınırda DB/hash/dizin çağrısına girmeden HTTP 429 ve `Retry-After: 1` döner. Hata dahil
her tamamlanmada slot bırakılır. Bu kaynak kabul sınırı, nginx IP limitinin veya dağıtık
kullanıcı/cihaz risk değerlendirmesinin yerine geçmez; web süreç sayısıyla toplam artar.

Alarm eşikleri ve hata bütçesi kurumla kabul edilmedi. En azından DB/şema sağlığı,
worker yaşlanması, disk, 5xx, kesilen yanıtlar ve yedek doğrulama hatası izlenmelidir.
Olay kapanışı: normal akışın küçük kabulü, veri bütünlüğü, yinelenen posta kontrolü,
etki/zaman çizelgesi ve takip işi kaydı. Bu yönerge bağımsız olay tatbikatı değildir.
