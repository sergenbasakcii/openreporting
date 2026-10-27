# OpenReporting Reporting Platform — tasarım kararları

## v1.0 mimarisi (24 Ekim 2026)

**Tek sorgu hattı.** Tarayıcıdaki her panel ve sunucudaki her rapor sayfası aynı fonksiyonu kullanır:
`query_engine.run()` → değişken enterpolasyonu (`templating.py`, hedefe göre biçim: Zabbix için çapalı regex, SQL için
kaçışlı tırnak) → veri kaynağı eklentisi (`datasources/zabbix.py`, `postgres.py`, `testdata.py`) → sorgu fonksiyonları
(`series_functions.py`) → ifadeler (`expressions.py`, `ast` beyaz listesi, `eval` yok) → panel dönüşümleri
(`transformations.py`). Böylece ekrandaki grup özet tablosu ile PDF’teki tablo aynı koddan çıkar.

**Veri modeli.** `frames.py`: zaman serisi (`points=[[ms, değer|None]]`, etiketler `host/item/group/...`) ve tablo
(`columns`, `rows`). Eksik örnek `None` olarak kalır; hiçbir aşama boşluğu sıfıra çevirmez (yalnız kullanıcı açıkça
`transformNull` eklerse).

**Dashboard modeli.** Grafana JSON şemasının alt kümesi (`panels[].gridPos`, `templating.list`, `fieldConfig.defaults/overrides`,
`options`, `transformations`, `repeat`). `dashboards.normalize()` içe aktarılan Grafana JSON’unu (eski `graph`/`singlestat`,
`__inputs` veri kaynağı yer tutucuları, Zabbix eklentisi `queryType` değerleri) dönüştürür. Her kayıt yeni sürüm yazar
(son 50 sürüm), iyimser kilit (`version`) çakışmayı 409 ile bildirir.

**Değişkenler ve tekrar.** `dashboard_runtime.resolve_variables()` değişkenleri bağımlılık sırasıyla sunucuda çözer
(tarayıcı da aynı uç noktayı kullanır); `expand()` satır/panel tekrarını ve dikey sıkıştırmayı uygular. Raporlarda `split_by`
her değer için bağımlı değişkenleri yeniden çözerek ayrı bölüm üretir.

**Raporlar.** `reporting/collect.py` (bölüm × panel sorguları) → `reporting/pdf.py` (ReportLab vektör çizim; iki geçişli
sayfalama: önce yerleşim + içindekiler sayfa numaraları, sonra çizim) / `reporting/excel.py` (openpyxl, formül enjeksiyonu
nötrlenir) → arşiv (atomik yazım, SHA-256 manifest, denetim zinciri çapası) → SMTP (fail-closed; belirsiz gönderim tekrar edilmez).
`reporting/service.py` zamanlama matematiği (DST güvenli, önceki tam dönem) ve worker entegrasyonunu içerir.

**Güvenlik.** Kimlik bilgileri `secrets_store.py` ile Fernet şifreli (`/etc/openreporting/secret.key`); API yalnız
`secureJsonFields: {token: true}` döndürür. Zabbix yalnız `*.get` yöntemleri; SQL `READ ONLY` işlem + zaman aşımı + satır
sınırı + tek ifade kontrolü. Tüm mutasyonlar CSRF başlığı + rol kontrolü + denetim kaydı ister. CSP `script-src 'self'`
(grafik ipuçları için `style-src 'unsafe-inline'`), çerez `HttpOnly; Secure; SameSite=Strict`.

**Dağıtım.** `deploy/` — Ubuntu kurulum/yükseltme betikleri, sertleştirilmiş systemd (`ProtectSystem=strict`, yalnız
`/var/lib/openreporting` yazılabilir), nginx TLS, gece yedeği. Tek worker kuralı dosya kilidiyle korunur; web katmanı çok işçili
çalışabilir (SQLite WAL, tek host).

**Şema.** `db.py` tek bir başlangıç şeması (sürüm 1) içerir; sonraki değişiklikler numaralı adımlar olarak eklenir ve
uygulama açılışında sırayla, otomatik uygulanır. Uygulama kendinden yeni bir şemayı açmayı reddeder.
