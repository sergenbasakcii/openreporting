# Sentetik performans kabul kaydı

30 Ekim 2026 02:51:46 UTC ölçümü. Ham, sır içermeyen kanıt:
[load-2026-10-30-windows.json](evidence/load-2026-10-30-windows.json).
Kayıt kaynak dosyası SHA-256'larını ve paket sürümlerini de içerir.

Gerçek loopback HTTP, tek Uvicorn web süreci, ayrı geçici SQLite, 16 eşzamanlı sentetik
viewer oturumu, 120 saniye. Her sorgu kayıtlı panel tanımından sekiz TestData serisi ve
toplam 2.880 nokta döndürdü. Kaynaklar veya kullanıcının 8811/8810 kurulumları kullanılmadı.
Windows/Python 3.13.9; işletim sistemi 16 mantıksal CPU bildirdi. HTTP JSON olayları dosyaya yazıldı.
Bu, temiz tahsis edilmiş donanım veya üretim ortamı değildir.

Trafik karışımı: sorgu, sorgu, dashboard okuma, DB sağlığı, sorgu. Oturum oluşturma ve
ısınma ölçüm öncesindedir. İstemciler kapalı döngüdür; yanıtı bekleyip sonraki isteği üretir.
Bu nedenle talep patlaması, açık döngü kuyruk büyümesi veya bütün kullanıcı davranışı modellenmez.

| Akış | İstek | p50 ms | p95 ms | p99 ms | En büyük ms |
| --- | --- | --- | --- | --- | --- |
| Kayıtlı panel sorgusu | 4.445 | 317,362 | 445,654 | 518,903 | 618,383 |
| Dashboard okuma | 1.481 | 143,793 | 299,774 | 369,459 | 524,644 |
| DB sağlık kontrolü | 1.478 | 190,836 | 303,505 | 357,353 | 436,685 |

Toplam **7.404 istek, 0 hata**, tüm durumlar HTTP 200; 120,144 saniyede 61,626 istek/sn.
Sorgu içinde hata, boş frame ve eksik sunucu istek kimliği de başarısızlık sayılır.
Bu değerler kabul edilen bir kurum SLO'su veya “şu kadar kullanıcı desteklenir” garantisi değildir.

## Tekrarlama

Uygulamanın test bağımlılıkları olan ayrı QA ortamında:

```text
python tools/load_acceptance.py --users 16 --seconds 120 --output build/load-16-viewers-120s.json
```

Araç kendi geçici dizinini, rastgele portunu ve sentetik kimliklerini oluşturur. Mail/LDAP ve
gerçek kaynak kullanılmaz; parola/çerezler kayda yazılmaz. Sunucu test sonunda kendi graceful
shutdown sinyaliyle kapanır. `--users` 1..32, `--seconds` 1..300, `--series` 1..50,
`--points` 10..20.000 ile sınırlıdır. Kullanıcı mevcut önizlemesini durdurmaz veya yeniden başlatmaz.
Çıktı ile aynı kökte `.http.jsonl` tanılama dosyası oluşur; burada yalnız redakte HTTP olayları vardır.

CI Python 3.13 üzerinde dört viewer / beş saniyelik ayrı HTTP smoke çalıştırıp JSON kanıtını
artefakt olarak saklar. CI geçiş ölçütü işlevsel hata olmamasıdır; paylaşılan runner süreleri
üzerinden kırılgan bir mutlak performans eşiği konulmaz. Ölçüm yapılması tek başına kapasite kabulü değildir.

## Açık kabul kapsamı

- Gerçek Zabbix/SQL/Prometheus/Loki/HTTP kaynak ağı ve kaynak sunucusunun maliyeti ölçülmedi.
- nginx/TLS, LDAP/SMTP, çok web süreci ve eşzamanlı ayrı rapor worker'ı bu testte bulunmaz.
- Uzun gece soak, bellek sızıntısı, ağır PDF/Excel ve tarayıcı çizim maliyeti doğrulanmadı.
- Disk/DB arızası, kaynak yavaşlaması ve sürekli gelen açık döngü yük altında SLO kabulü yapılmadı.
- Kuruma ait yük profili, hata bütçesi ve donanım kararı dış kabul olarak kalır.

Bu boşluklar `ENTERPRISE_REVIEW.md` A09/J09 kapsamında **kısmi** durumdadır.
