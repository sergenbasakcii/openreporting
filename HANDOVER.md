# OpenReporting — Devir Dokümanı (Handover)

> **Bu doküman kime:** Projeyi devralan yapay zekâ asistanına (ChatGPT) ve projeyi sürdürecek herkese.
> **Tarih:** 27 Ekim 2026 · **Durum:** v1.0.0 yayınlandı, `main` dalında iki ek özellik var (masaüstü başlatıcı, rapor logosu).
> **Proje sahibi:** Sergen (GitHub: `sergenbasakcii`). Sahibi Türkçe yazar; açıklamaları Türkçe yap.
> **Okuma sırası:** Önce §1–§3 (kurallar, durum, açık işler), sonra işe göre ilgili bölüm. §11 yeni geliştirme planıdır.

---

## İçindekiler
1. [Değişmez kurallar (önce bunu oku)](#1-değişmez-kurallar-önce-bunu-oku)
2. [Ürün ve mevcut durum](#2-ürün-ve-mevcut-durum)
3. [Açık işler ve bekleyen kararlar](#3-açık-işler-ve-bekleyen-kararlar)
4. [Depo, dallar, sürümler, CI](#4-depo-dallar-sürümler-ci)
5. [Mimari](#5-mimari)
6. [Kod haritası (dosya dosya)](#6-kod-haritası-dosya-dosya)
7. [Veri modeli](#7-veri-modeli)
8. [HTTP API](#8-http-api)
9. [Güvenlik modeli ve korunması gereken değişmezler](#9-güvenlik-modeli-ve-korunması-gereken-değişmezler)
10. [Çalıştırma, test, dağıtım](#10-çalıştırma-test-dağıtım)
11. [Yeni geliştirme planı (sahibinin istekleri, doğru zemine oturtulmuş)](#11-yeni-geliştirme-planı)
12. [Bilinen sınırlamalar ve teknik borç](#12-bilinen-sınırlamalar-ve-teknik-borç)
13. [Geçmiş: bu noktaya nasıl gelindi](#13-geçmiş-bu-noktaya-nasıl-gelindi)
14. [Devralan için çalışma biçimi ve kontrol listesi](#14-devralan-için-çalışma-biçimi-ve-kontrol-listesi)

---

## 1. Değişmez kurallar (önce bunu oku)

1. **Şirkete ait hiçbir bilgi olmayacak — sentetik bile olsa.** Ürün tamamen özgün olmalı. Kod, doküman, test verisi,
   örnek dashboard, commit mesajı, ekran görüntüsü ve sürüm notlarında **gerçek şirket/müşteri adı, gerçek host/proxy adı,
   iç sistem adı/sürümü, IP adresi, iç alan adı, e-posta veya kimlik bilgisi bulunmaz.** Örneklerde yalnız `example.com`,
   `sirket.local`, `srv-app-01`, `wan-rtr-ist`, "Acme" gibi genel adlar kullan. Projenin geçmişi bu yüzden temizlenip tek
   commit'e indirildi; bu kuralı bozan bir commit geçmişi yeniden kirletir. Şüphedeysen ekleme.
2. **Grafana kodu kopyalanmaz (lisans).** Grafana'nın ana deposu **AGPL-3.0**'dır. Oradan kod kopyalamak/uyarlamak bu
   projeyi de AGPL'ye bağlar. İzinli yollar: (a) Grafana'yı **dokümantasyonundan ve davranışından** inceleyip kendi kodunu
   yazmak (clean-room), (b) Grafana deposundaki **Apache-2.0** lisanslı paketleri (`packages/` altındaki `@grafana/*`
   npm paketleri — her birinin LICENSE dosyasını kullanmadan önce doğrula) bağımlılık olarak kullanmak, (c) Apache-2.0
   lisanslı eklentilerden (ör. Grafana-Zabbix eklentisi) davranış örneği almak (atıf ve NOTICE ile). Lisans kararı §3'te.
3. **Kaynaklar salt-okunur.** Zabbix yalnız `*.get` metotları; SQL kaynakları `READ ONLY` işlem + zaman aşımı + satır
   sınırı. Hiçbir veri kaynağına yazılmaz. Yeni her veri kaynağı da bu kurala uyar.
4. **İzleyici (viewer) serbest sorgu çalıştıramaz.** Sunucu, izleyici isteklerinde tarayıcının gönderdiği sorguyu değil
   **kayıtlı panel tanımını** çalıştırır (§9). Bu değişmez bozulursa izleyici her veriyi okuyabilir hale gelir.
5. **Eksik veri sıfır sayılmaz.** Boş nokta `None` kalır; sorgu limiti aşılırsa veri sessizce kırpılmaz, açık hata verilir.
6. **Her değişiklik test + CI ile doğrulanır.** `pytest` (55 test), JS sözdizimi kontrolü, shellcheck ve gerçek Ubuntu
   kurulumu yapan uçtan uca CI işi yeşil olmadan "bitti" denmez.
7. **Sırlar koda girmez.** Parolalar/token'lar yalnız ortam dosyasında (`/etc/openreporting/openreporting.env`) veya
   Fernet ile şifreli veritabanı alanında durur. Sahibinin yönetici parolası geçmişte sohbete yazıldı; hiçbir yere yazma.
8. **Sahibinin tercihi:** "Bana soru sorma, best practice neyse onu yap." Teknik kararları kendin ver ve gerekçesini yaz;
   yalnızca geri alınamaz/dışa dönük işlemlerde (depo silme, public yapma, zorla push, veri silme) onay iste.

---

## 2. Ürün ve mevcut durum

**OpenReporting**, Zabbix ve SQL kaynakları için Grafana tarzı dashboard'lar ve **grup bazlı PDF/Excel/CSV raporlama**
platformudur. Hedef ortam: **tek bir Ubuntu sunucu** (24.04 önerilir, 22.04 destekli). Windows yalnızca yerel deneme içindir.

### Bugün çalışan özellikler
| Alan | Özellikler |
| --- | --- |
| Dashboard | 24 sütunlu sürükle-bırak ızgara, satırlar (daraltma), **satır/panel tekrarı** (değişken başına), klasörler, etiketler, yıldız, **sürüm geçmişi + geri alma** (son 50), iyimser kilit (409), paylaşım bağlantısı, kiosk/TV modu, panel görünümü, JSON dışa/içe aktarma, **Grafana dashboard JSON içe aktarma** (eski `graph`/`singlestat`, `__inputs`, Zabbix eklentisi `queryType` dönüştürme) |
| Paneller (10) | `timeseries`, `barchart`, `stat`, `gauge`, `bargauge`, `table`, `piechart`, `statusgrid` (durum ızgarası), `statetimeline`, `text` (güvenli markdown). Eşikler, değer eşlemeleri, geçersiz kılmalar (negatif-Y, eksen, renk, birim…), birimler, ortak imleç (`graphTooltip`) |
| Veri kaynakları (3) | **Zabbix** (JSON-RPC API; grup/host/item/etiket filtreleri, regex/glob, history/trend, item ID, son değerler, aktif problemler, isteğe bağlı SQL history modu, Bearer veya `auth` alanı, özel CA PEM), **PostgreSQL/TimescaleDB** (salt-okunur SQL, Grafana makroları `$__timeFilter` vb., sunucu tarafı LIMIT), **TestData** (sentetik Zabbix simülasyonu + sine/random walk/CSV/tablo) |
| Sorgu motoru | Tek ortak hat (tarayıcı ve rapor aynı kodu kullanır): değişken enterpolasyonu → veri kaynağı → **Grafana-Zabbix uyumlu fonksiyonlar** (`aggregateBy`, `groupBy`, `sumSeries`, `averageSeries`, `movingAverage`, `exponentialMovingAverage`, `rate`, `delta`, `scale`, `offset`, `top`/`bottom`, `percentile`, `timeShift`, `transformNull`, `setAlias`, `setAliasByRegex`, `replaceAlias`, `filterSeries`, `sortSeries`, `removeAbove/BelowValue`, `consolidateBy`, `trendValue` …) → **ifadeler** (güvenli matematik, AST beyaz liste, `eval` yok) → **dönüşümler** (`reduce` — `labelsToFields` seçeneğiyle, `reduceByLabel`, `seriesToColumns`/`joinByField`, `seriesToRows`, `filterByName`/`filterFieldsByName`, `filterByRefId`, `organize`, `sortBy`, `limit`, `calculateField`, `groupingToMatrix`, `renameByRegex`, `merge`) |
| Değişkenler | `query`, `custom`, `textbox`, `constant`, `interval`, `datasource` türleri; zincirleme bağımlılık, çoklu seçim, "Tümü", URL'de `var-*`; Grafana tarih matematiği (`now-6h`, `now/d`, `now-1M/M`), saat dilimi duyarlı |
| Raporlar | Dashboard'dan **vektör PDF** (ReportLab, kapak + içindekiler, ızgara veya akış düzeni, A4/A3/Letter, yatay/dikey, uzun tablolar sayfalara bölünür), **Excel** (openpyxl), **CSV**; **`split_by` ile her host/grup değeri için ayrı bölüm**; **müşteri logosu** (kapak sağ üst + sayfa başlığı); önizleme; anlık çalıştırma; **zamanlama** (saatlik/günlük/haftalık/aylık/yıllık, "önceki tam dönem", DST güvenli); e-posta (STARTTLS zorunlu, alıcı alan adı izin listesi, kısmi veride gönderim engeli); **SHA-256 manifest + denetim zinciri** ile doğrulanan arşiv; saklama süresi |
| Yönetim | Veri kaynağı yönetimi (kimlik bilgileri Fernet şifreli, bağlantı testi), kullanıcılar ve roller (`admin`, `editor`, `viewer`), profil/tercihler (tema, saat dilimi, ana sayfa dashboard), sunucu durumu, **denetim kaydı** (hash zinciri, yalnız yönetici), Prometheus `/metrics` (yalnız localhost) |
| İşletim | Ubuntu kurulum/yükseltme/geri dönüş/kaldırma betikleri, sertleştirilmiş systemd, nginx TLS + istek sınırları, gece yedeği (anahtar ayrı saklanır, GPG opsiyonu), `doctor`, Docker alternatifi, Windows başlatıcı + masaüstü kısayolu |

### Teknoloji yığını
- **Backend:** Python ≥ 3.11, FastAPI + uvicorn, **SQLite (WAL)** uygulama veritabanı, ReportLab (PDF), openpyxl (Excel),
  psycopg 3 (PostgreSQL kaynağı), cryptography (Fernet), `regex` (zaman aşımlı kullanıcı regex'i), Pillow (logo).
- **Frontend:** Derleme adımı **olmayan** vanilla ES modülleri (`openreporting/static/app`), yerel kopyalanmış **Apache ECharts 5.x**
  (`static/echarts.min.js`, Apache-2.0, NOTICE dosyası mevcut). Arayüz dili **Türkçe**.
- **Süreçler:** `openreporting-web` (API + arayüz, `127.0.0.1:8810`, çok işçi) ve **tek** `openreporting-worker`
  (zamanlama, PDF/Excel üretimi, e-posta; dosya kilidiyle tekil).

---

## 3. Açık işler ve bekleyen kararlar

| # | Konu | Durum / yapılacak |
| --- | --- | --- |
| K1 | **Kodun hak sahipliği** | Projenin ilk hali sahibinin iş ortamındaki bir projeden geldi; şirket bilgileri tamamen temizlendi. Depoyu **public** yapmadan önce sahibinin, temel kod parçaları için işvereninden hak/izin teyidi alması gerekiyor. **Bu teyit gelmeden depoyu public yapma.** |
| K2 | **Lisans** | Depoda henüz LICENSE yok (yasal olarak "herkes kullanabilir" demek değildir). Öneri: **Apache-2.0** (serbest + patent koruması, ECharts ve bağımlılıklarla uyumlu). Alternatif: Grafana kodundan yararlanmak isteniyorsa **AGPL-3.0** (bkz. §1 kural 2). Karar sahibinde. Seçilince: `LICENSE`, `NOTICE`, `pyproject.toml` `license` alanı, README rozetleri. |
| K3 | **Public hazırlığı** | Lisans + `SECURITY.md` + `CONTRIBUTING.md` + İngilizce README + commit e-postasını GitHub noreply'a çevirmek + dokümanlardaki örnek kullanıcı `sergen` → `admin`. |
| K4 | Yerel arşivde eski test raporu | Sahibinin bilgisayarında `%LOCALAPPDATA%\OpenReporting\archive\` altında adı `fea1facf` içeren, yeniden adlandırma öncesi üretilmiş bir test PDF/XLSX/JSON'u ürünün eski adını içeriyor. Yalnız yerelde; depoda değil. Sahibi silebilir; uygulama içinden "çalıştırma silme" özelliği yok (eklenebilir). |
| K5 | Sürüm etiketi | `v1.0.0` etiketi `d9ab1f9`'a işaret ediyor. `main`'de sonrasında **masaüstü başlatıcı** (`f5e59fc`) ve **rapor logosu** (`4a2b682`) var → bir sonraki sürüm **v1.1.0** olarak etiketlenmeli (CHANGELOG'a eklenerek). |
| K6 | Excel'de logo | Logo yalnız PDF'te. Excel özet sayfasına eklenmesi istenebilir (openpyxl `Image`, Pillow mevcut). |
| K7 | Güvenlik hijyeni | Sahibinin `sergen` parolası geçmişte sohbette paylaşıldı → sahibine yerelde ve sunucuda farklı/yeni parola kullanmasını hatırlat. Yerel test hesapları `viewer_test`/`editor_test` devre dışı (silinmedi; denetim geçmişi için kullanıcılar silinmez, pasifleştirilir). |
| K8 | Sunucu kurulumu | Henüz şirket sunucusuna kurulmadı. Depo özel olduğu için klon için **fine-grained token** (Contents: Read-only, yalnız bu depo) veya deploy key gerekir. Depo silinip yeniden oluşturulduğu için eski token'lar geçersiz olabilir. |
| K9 | Yerel klasör adı | Sahibinin bilgisayarındaki proje klasörü (`Belgeler` altında) hâlâ ürünün eski adını taşıyor (yalnız yerel; istenirse yeniden adlandırılabilir; sonra `.venv` yeniden oluşturulmalı ve masaüstü kısayolunun hedefi güncellenmeli). `build\` klasörü git'e girmeyen eski tek seferlik betikler ve önizleme PDF'leri içeriyor; silinebilir. `.venv`'e test için `pymupdf` kuruldu (bağımlılık değil). |

---

## 4. Depo, dallar, sürümler, CI

- **Depo:** `https://github.com/sergenbasakcii/openreporting` — **özel**. Varsayılan dal `main`. Başka dal yok.
- **Geçmiş:** Şirket bilgisinden arındırmak için geçmiş tek commit'e indirildi ve depo yeniden oluşturuldu.
  `d9ab1f9 OpenReporting 1.0.0` (etiket `v1.0.0`) → `f5e59fc feat(windows): one-click launcher…` → `4a2b682 feat(reports): customer logo…`.
- **Sürüm notları:** GitHub Releases'ta `v1.0.0`, gövde `CHANGELOG.md` 1.0.0 bölümünden üretilir.
- **Commit biçimi:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor!:` …), açıklayıcı gövde.
- **CI** (`.github/workflows/ci.yml`, her push'ta):
  1. `Tests (Python 3.11/3.12/3.13)` — `pytest`.
  2. `Shell and JS checks` — `shellcheck -x deploy/*.sh`, `bash -n`, `node --check` (tüm `static/app/*.js`).
  3. `End-to-end Ubuntu install` (Ubuntu 24.04 runner): gerçek kurulum betiği (self-signed TLS) → servisler aktif mi →
     nginx üzerinden HTTPS → `/metrics` dışarıya 404 → dosya izinleri (root:openreporting 640 anahtar, ayrıcalıksız
     kullanıcı okuyamaz) → API ile yönetici oluşturma + giriş + dashboard + rapor + **gerçek PDF üretimi** → `doctor` →
     yedek + SHA256 doğrulama (anahtar yedekte yok) → yükseltme → kaldırma (veri korunur).
- **Son CI:** tüm işler yeşil (tek commit'lik yeni depoda).

---

## 5. Mimari

```
Tarayıcı (vanilla ES modules, ECharts)                 Ubuntu sunucu
  │  HttpOnly çerez + X-CSRF-Token                       nginx (TLS, rate limit, /metrics kapalı)
  ▼                                                          │ proxy
FastAPI (openreporting.web:create_app) ◄────────────────────┘
  ├─ api/*.py           REST uçları (dashboards, datasources, reports, users, system)
  ├─ query_engine.run   TEK sorgu hattı ──► datasources/{zabbix,postgres,testdata}
  │      templating → datasource → series_functions → expressions → transformations
  ├─ dashboard_runtime  değişken çözümleme, tekrar genişletme
  ├─ reporting/*        collect → pdf / excel / csv → arşiv (manifest) → SMTP
  ├─ security, secrets_store (Fernet), safe_regex, timerange, units, frames
  └─ db.py              SQLite (WAL), audit hash zinciri
Worker (openreporting.worker:run_forever) — tek örnek, dosya kilidi
  zamanlama tick → kuyruktan iş al (lease) → build_outputs → arşiv → e-posta → heartbeat
```

**Temel tasarım kararları**
- **Tek sorgu hattı:** Ekrandaki panel ile PDF'teki panel aynı `query_engine.run()` çıktısını kullanır → rapor = ekran.
- **Veri çerçeveleri** (`frames.py`): zaman serisi `{"type":"timeseries","name","labels","unit","points":[[ms, değer|None]]}`,
  tablo `{"type":"table","columns":[{name,type,unit}],"rows":[...]}`. (Grafana DataFrame'in sadeleştirilmiş eşdeğeri.)
- **Dashboard modeli:** Grafana JSON şemasının alt kümesi (`panels[].gridPos`, `targets`, `fieldConfig.defaults/overrides`,
  `options`, `transformations`, `templating.list`, `repeat`). `dashboards.normalize()` içe aktarımı dönüştürür.
- **Değişken biçimlendirme:** hedefe göre (Zabbix için çapalı regex, SQL için kaçışlı tırnak). İzleyici isteklerinde
  `strict=True` → `${var:raw}` gibi biçimler güvenli biçime zorlanır.
- **Rapor arşivi:** atomik yazım, her çıktı için SHA-256, manifest denetim zincirine çapalanır; indirme öncesi hash doğrulanır.
- **Worker:** `dash_report_runs` kuyruğu, lease + sahip alanları; belirsiz SMTP durumu asla yeniden oynatılmaz
  (`needs_review`). Zamanlama, rapor/dashboard değişince pasife alınır ve yönetici yeniden etkinleştirir (onay kaydı).
- **Frontend:** `router.js` (her render ayrı konteyner + token; bayat sayfa global durumu değiştiremez), `api.js`
  (CSRF tek uçuş yenileme, sınırlı önbellek), `dom.js` (innerHTML yok; modal odak tuzağı, klavye menüleri).

---

## 6. Kod haritası (dosya dosya)

### Backend — `openreporting/`
| Dosya | Sorumluluk |
| --- | --- |
| `web.py` | Uygulama fabrikası, güvenlik başlıkları (CSP `script-src 'self'`), giriş/çıkış/oturum/CSRF yenileme, `/healthz`, `/readyz`, `/api/audit` (yönetici), SPA yönlendirme |
| `config.py` | `Settings` (tüm `OPENREPORTING_*` ortam değişkenleri, doğrulama) |
| `db.py` | Şema (sürüm 1), `init_db` (sıralı geçiş iskeleti), `connect` (WAL, FK açık), `transaction`, `audit` + `verify_audit` (hash zinciri) |
| `security.py` | scrypt parola, oturum belirteçleri (hash'li saklanır), CSRF, rol kontrolü, başarısız giriş sayacı, `create_user` (parola ≥ 14) |
| `secrets_store.py` | Fernet anahtarı (`/etc/openreporting/secret.key`), şifreli alanlar; anahtar kayıpken sessizce yeni anahtar üretmez |
| `domain.py` | `DomainError`, kimlik/hash/zaman yardımcıları, e-posta doğrulama |
| `cli.py` | `init`, `create-user`, `reset-password`, `disable-user`, `worker`, `worker-once`, `serve`, `doctor`, `export-dashboards`, `import-dashboards`, `verify-audit`, `backup` |
| `worker.py` | Zamanlama matematiği (`schedule_next`, `completed_period`), atomik yazım, tek worker kilidi, heartbeat, iş döngüsü |
| `portable.py` | Linux `flock` / Windows `msvcrt` kilidi, Unicode TTF font bulma (DejaVu/Arial…) |
| `query_engine.py` | `run()` ana sorgu hattı, eşzamanlılık sınırı, nokta bütçesi, `metric_find` |
| `templating.py` | Değişken enterpolasyonu ve biçimleri (`csv`, `pipe`, `regex`, `sqlstring`, `json`, `glob`, `raw`…) |
| `dashboard_runtime.py` | Değişken çözümleme (bağımlılık sırası), satır/panel tekrar genişletme |
| `dashboards.py` | CRUD, sürümler, klasörler, yıldızlar, arama, Grafana içe aktarma/normalize, izleyici değişken birleştirme |
| `datasources/__init__.py` | Kayıt defteri, tür tanımları, `provision` (TestData + ortamdan Zabbix), sağlık kontrolü |
| `datasources/base.py` | `QueryContext`, `DataSourceError`, filtre derleme (regex/glob/tam), kova ortalaması |
| `datasources/zabbix.py` | Zabbix JSON-RPC istemcisi (yalnız `*.get`, TLS, yönlendirme yok), hedef normalizasyonu, history/trend/SQL modu |
| `datasources/postgres.py` | `guard_sql` (tek ifade, yazma yok, tırnak hileleri reddi), makrolar, genişletilmiş protokol, sunucu LIMIT |
| `datasources/testdata.py` | Deterministik sentetik envanter (5 grup, 30 host) ve senaryolar |
| `series_functions.py` | Grafana-Zabbix uyumlu seri fonksiyonları, `bucketize` (saat dilimine çapalı) |
| `expressions.py` | Güvenli matematik ifadeleri (AST beyaz liste), etiket eşleştirme |
| `transformations.py` | Panel dönüşümleri |
| `frames.py`, `units.py`, `timerange.py`, `safe_regex.py` | Çerçeve yardımcıları/reducer'lar; birim biçimleme; Grafana tarih matematiği; zaman aşımlı regex |
| `api/dashboards.py` | Dashboard, klasör, arama, yıldız, sürüm, değişken çözümleme, içe aktarma, dışa aktarma (PDF/Excel) |
| `api/datasources.py` | Veri kaynağı CRUD/sağlık, `/api/ds/query` (izleyici için kayıtlı panel zorunluluğu), metric-find (editör), katalog |
| `api/reports.py` | Rapor tanımları, önizleme, çalıştırma, zamanlama, arşiv indirme (Türkçe dosya adı için RFC 6266), **logo yükleme** |
| `api/users.py` | Kullanıcılar, profil, tercihler, parola |
| `api/system.py` | `/api/health`, `/api/frontend/settings`, `/api/admin/stats`, `/api/time/resolve`, anotasyonlar, `/metrics` |
| `reporting/collect.py` | Bölüm × panel sorguları (`split_by`), kısmi veri izleme |
| `reporting/pdf.py` | ReportLab vektör çizim: tüm panel türleri, ızgara/akış düzeni, iki geçişli sayfalama, kapak, içindekiler, logo |
| `reporting/excel.py` | XLSX/CSV; formül enjeksiyonu ve kontrol karakteri temizliği |
| `reporting/fieldcfg.py` | Panel alan yapılandırması (eşik, eşleme, renk) sunucu tarafı |
| `reporting/logos.py` | Logo doğrulama (Pillow), yeniden PNG kodlama, içerik adresli saklama |
| `reporting/service.py` | Rapor CRUD, doğrulama, zamanlama, kuyruk/lease, üretim, arşiv, e-posta, saklama |

### Frontend — `openreporting/static/app/`
`main.js` (kabuk, menü, rotalar) · `router.js` · `api.js` · `dom.js` · `time.js` (zaman seçici, dashboard saat dilimi) ·
`variables.js` · `units.js` · `colors.js` · `markdown.js` · `icons.js` ·
`dashboard/` (`layout.js` ızgara/sıkıştırma, `panelview.js` panel yaşam döngüsü, `editor.js` panel düzenleyici, `settings.js`) ·
`panels/` (`registry.js` panel kayıtları/seçenek şemaları, `timeseries.js`, `charts.js`, `dompanels.js`, `common.js`) ·
`query/editors.js` (sorgu/dönüşüm düzenleyicileri) ·
`pages/` (`home`, `browse`, `dashboard`, `explore`, `datasources`, `reports`, `admin`, `samples`). Stil: `app.css` (koyu/açık tema).

### Diğer
`deploy/` (kurulum, yükseltme, kaldırma, yedek, admin betiği, systemd, nginx, env örneği) · `windows/` (kurulum, başlatma,
test, yönetici oluşturma, **masaüstü başlatıcı** `Open-OpenReporting.ps1` + `OpenReporting.ico`) · `docs/` (`ARCHITECTURE.md`,
`LINUX_DEPLOYMENT.md`, `USER_GUIDE.md`) · `Dockerfile`, `docker-compose.yml` · `tests/` (6 dosya, 55 test).

---

## 7. Veri modeli

Uygulama veritabanı **SQLite** (`<data_dir>/state.sqlite3`, WAL). Şema sürümü `PRAGMA user_version` = **1**
(`db.py` → `SCHEMA`). Yeni değişiklik = `init_db` içine numaralı yeni adım + `CURRENT_VERSION` artışı + test.

| Tablo | Amaç |
| --- | --- |
| `users` | kullanıcı, scrypt hash, rol (`admin`/`editor`/`viewer`), aktif, e-posta, görünen ad, son giriş |
| `sessions` | oturum belirteci hash'i, CSRF hash'i, son kullanma |
| `login_failures` | kullanıcı başına başarısız giriş sayacı |
| `audit` | denetim kaydı; `prev_hash` + `entry_hash` zinciri (`verify_audit`) |
| `worker_runtime` | tekil worker heartbeat satırı |
| `user_prefs` | tema, saat dilimi, ana sayfa dashboard |
| `datasources` | tür (`zabbix`/`postgres`/`testdata`), URL, `json_data`, **şifreli** `secure_json`, varsayılan, provizyon |
| `folders`, `dashboards`, `dashboard_versions`, `dashboard_stars`, `annotations` | dashboard katmanı |
| `dash_reports` | rapor tanımı (`config_json` + SHA-256 + revizyon) |
| `dash_report_schedules` | zamanlama + onay kaydı (`approved_config_sha256`, `approved_dashboard_version`, `approved_by`) |
| `dash_report_runs` | kuyruk/çalıştırma, idempotency anahtarı, lease, dosyalar, uyarılar, teslim durumu |

Dosyalar: `<data_dir>/archive/` (rapor çıktıları + manifest), `<data_dir>/logos/<sha256>.png`, `<data_dir>/worker.lock`.
Linux'ta `data_dir=/var/lib/openreporting`, Windows'ta `%LOCALAPPDATA%\OpenReporting`.

---

## 8. HTTP API

Kimlik: `POST /api/login` → HttpOnly `openreporting_session` çerezi + yanıtta `csrf`. Değiştiren tüm isteklerde
`X-CSRF-Token` başlığı zorunlu. Roller: **viewer** (kayıtlı dashboard/rapor görüntüleme), **editor** (+ oluşturma/düzenleme,
Keşfet, anlık çalıştırma, pasif zamanlama), **admin** (+ veri kaynakları, kullanıcılar, zamanlamayı etkinleştirme, denetim).

```
Oturum     POST /api/login · POST /api/logout · GET /api/session · POST /api/session/csrf
Kullanıcı  GET /api/user · PUT /api/user/preferences · PUT /api/user/password
           GET/POST /api/users · PATCH /api/users/{id} · POST /api/users/{id}/password
Dashboard  GET /api/search · GET /api/dashboards/tags · POST /api/dashboards/db · POST /api/dashboards/import
           GET/DELETE /api/dashboards/uid/{uid} · GET /api/dashboards/uid/{uid}/versions[/{v}] · POST …/restore
           POST /api/dashboards/variables/resolve · POST /api/dashboards/export (PDF/Excel)
           POST/DELETE /api/user/stars/dashboard/{uid} · GET/POST/PUT/DELETE /api/folders[/{uid}]
           GET/POST/DELETE /api/annotations[/{id}]
Sorgu      POST /api/ds/query · POST /api/datasources/{uid}/metric-find · GET /api/query/catalog · GET /api/time/resolve
Kaynak     GET/POST /api/datasources · GET/PUT/DELETE /api/datasources/{uid} · POST /api/datasources/{uid}/health
           GET /api/datasources/types
Rapor      GET/POST /api/dash-reports · GET/PUT/DELETE /api/dash-reports/{id} · POST /api/dash-reports/preview
           POST /api/dash-reports/logos · GET /api/dash-reports/logos/{logo_id}
           GET/POST /api/dash-reports/{id}/runs · GET /api/report-runs · GET /api/report-runs/{run_id}/files/{kind}
           GET/POST /api/dash-reports/{id}/schedules · PUT …/schedules/{sid} · GET /api/report-schedules
           DELETE /api/report-schedules/{sid}
Sistem     GET /api/health · GET /healthz · GET /readyz · GET /api/frontend/settings · GET /api/admin/stats
           GET /api/audit (admin) · GET /metrics (yalnız 127.0.0.1)
```
OpenAPI şeması bilinçli olarak kapalı (`docs_url=None`); §11'de belgelenmiş public API hedefi var.

---

## 9. Güvenlik modeli ve korunması gereken değişmezler

1. **İzleyici sorgu izolasyonu:** `/api/ds/query` izleyiciden `dashboardUid` + `panelId` ister; sunucu kayıtlı panelin
   hedeflerini/dönüşümlerini kullanır, tarayıcının gönderdiği hedefleri yok sayar; değişken *tanımları* da kayıtlı
   dashboard'dan gelir, yalnız seçili değerler tarayıcıdan alınır ve **katı** biçimlendirilir. Değişken çözümleme de
   izleyicide `uid` ile kayıtlı tanımı kullanır. metric-find ve Keşfet editöre özeldir. (Testler: `tests/test_review_fixes.py`.)
2. **SQL:** tek ifade, yalnız SELECT/WITH, `E''`/`U&''`/`$tag$` gibi tırnak hileleri reddedilir, `READ ONLY` işlem,
   `statement_timeout`, sunucu tarafı `LIMIT`, parametre bağlama.
3. **Zabbix:** yalnız `*.get` beyaz listesi, TLS doğrulaması, yönlendirme takibi yok.
4. **SSRF / ağ:** HTTP veri kaynakları varsayılan kapalı (`OPENREPORTING_ALLOW_HTTP_DATASOURCES`). Yeni kaynaklarda da
   aynı politika + özel ağ izin listesi tasarlanmalı.
5. **XSS:** frontend'de veri için `innerHTML` yok (`dom.js` `h()` yalnız `textContent`), markdown güvenli alt küme,
   renk değerleri doğrulanır, CSP `script-src 'self'`.
6. **CSRF + çerez:** `HttpOnly; Secure; SameSite=Strict`, değişikliklerde `X-CSRF-Token`.
7. **Regex DoS:** kullanıcı regex'leri `regex` modülü ile zaman aşımlı ve boyut sınırlı (`safe_regex.py`).
8. **Rapor çıktısı:** Excel/CSV formül enjeksiyonu nötrlenir; logolar yeniden kodlanır; dosya adları RFC 6266.
9. **Sırlar:** Fernet anahtarı ayrı dosyada (root:openreporting 0640), yedeğe varsayılan olarak girmez.
10. **Denetim:** önemli tüm değişiklikler `audit` zincirine yazılır; kullanıcılar silinmez, pasifleştirilir.
11. **Dağıtım:** systemd `ProtectSystem=strict`, `NoNewPrivileges`, syscall filtresi, yalnız veri dizini yazılabilir;
    nginx istek sınırları; `/metrics` yalnız localhost.

---

## 10. Çalıştırma, test, dağıtım

### Geliştirme (Linux/macOS)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
OPENREPORTING_DATA_DIR=./data OPENREPORTING_COOKIE_SECURE=false openreporting init
OPENREPORTING_DATA_DIR=./data openreporting create-user admin --role admin
OPENREPORTING_DATA_DIR=./data OPENREPORTING_COOKIE_SECURE=false openreporting serve --host 127.0.0.1 --port 8810
OPENREPORTING_DATA_DIR=./data openreporting worker        # ayrı terminal
pytest -q                                                 # 55 test
find openreporting/static/app -name '*.js' -print0 | xargs -0 -n1 node --check
shellcheck -x -s bash deploy/*.sh
```

### Sahibinin Windows ortamı (yalnız deneme)
- Klasör: sahibinin `Belgeler` klasöründeki proje klasörü (bkz. K9), sanal ortam `.venv`, veri `%LOCALAPPDATA%\OpenReporting`.
- Başlatma: masaüstündeki **OpenReporting** kısayolu (`windows\Open-OpenReporting.ps1`; çalışmıyorsa küçültülmüş pencerede
  başlatır, sonra tarayıcıda `http://127.0.0.1:8810` açar). Elle: `.\windows\Start-OpenReporting.ps1`.
- Yönetici: `sergen` (parolası burada yok ve yazılmamalı).

### Ubuntu üretim kurulumu
```bash
git clone --branch v1.0.0 https://github.com/sergenbasakcii/openreporting.git /tmp/openreporting   # token gerekir
cd /tmp/openreporting
sudo ./deploy/install-ubuntu.sh --domain openreporting.sirket.local --self-signed --admin admin --open-firewall
sudo /opt/openreporting/app/deploy/openreporting-admin.sh doctor
```
Ayrıntılar: `docs/LINUX_DEPLOYMENT.md` (yollar, ayarlar, Zabbix bağlantısı, SMTP, yedek/geri yükleme, yükseltme, sorun giderme).
Anahtar `/etc/openreporting/secret.key` sunucu dışında güvenli saklanmalı.

### Ortam değişkenleri (özet)
`OPENREPORTING_DATA_DIR`, `_COOKIE_SECURE`, `_SESSION_HOURS`, `_MAX_ROWS`, `_QUERY_TIMEOUT_MS`, `_QUERY_CONCURRENCY`,
`_MAX_SERIES_POINTS`, `_REPORT_RETENTION_DAYS`, `_PROVISION_TESTDATA`, `_PUBLIC_URL`, `_PROXY_HEADERS`, `_WEB_WORKERS`,
`_SECRET_KEY_FILE`, `_ALLOW_HTTP_DATASOURCES`, `_MAIL_ENABLED`, `_SMTP_HOST/_PORT/_STARTTLS/_USER/_PASSWORD/_FROM`,
`_ALLOWED_RECIPIENT_DOMAINS`, `_ZABBIX_URL/_TOKEN_FILE/_CA_FILE`, `_PDF_FONT_FILE`, `_PDF_BOLD_FONT_FILE`,
yedek: `_BACKUP_INCLUDE_KEY`, `_BACKUP_GPG_RECIPIENT`, `_BACKUP_KEEP_DAYS`. Kaynak: `config.py`, `deploy/openreporting.env.example`.

---

## 11. Yeni geliştirme planı

### 11.0 Sahibinin istekleri (aynen)
> - Çok daha fazla grafik seçeneği.
> - Grafana best practice neyse en azından onun kadar kod ve mimari açıdan sağlam.
> - Grafana'daki tüm datasource seçenekleri burada da eklenebilir olmalı.
> - Raporlama aracı her anlamda kullanıcı dostu olmalı ve mükemmel seviyede çalışmalı.
> - Kurulum çok basit olmalı; Ubuntu sunucuya kurulurken uygulama **kendi PostgreSQL veritabanından** beslenmeli (kendi DB'si).
> - Kısacası Grafana'nın üst seviyesi gibi ama tamamen ücretsiz; Grafana'nın kaynak kodlarına bakıp bizim yapımıza
>   uygulamalı; aşırı derecede profesyonel, mükemmel, optimize çalışan bir uygulama olmalı.

### 11.1 Zemin: bu istekler nasıl doğru yorumlanmalı
- **"Grafana'nın kaynak koduna bakıp uygulamak":** Grafana çekirdeği AGPL-3.0 → kod kopyalamak projeyi AGPL yapar.
  **Doğru yöntem:** Grafana'nın *mimari kavramlarını* (DataFrame, plugin SDK sözleşmesi, panel/field config şeması,
  provisioning, RBAC modeli, sorgu önbelleği) **dokümanlardan ve davranıştan** inceleyip kendi kodumuzla yazmak; Apache-2.0
  lisanslı `@grafana/*` paketlerini veya Apache-2.0 eklentileri (lisanslarını tek tek doğrulayarak) kullanmak. Karar
  K2 (lisans) ile birlikte verilir. Her yeni dış bağımlılık için lisans kontrolü ve `NOTICE` güncellemesi zorunlu.
- **"Grafana'daki tüm datasource'lar":** Grafana'nın 100+ kaynağı tek seferde yapılamaz. Doğru zemin: önce sağlam bir
  **veri kaynağı eklenti (plugin) SDK'sı**, sonra kaynakları öncelik sırasıyla bu SDK üzerine eklemek (§11.5). Her kaynak
  salt-okunur, zaman aşımlı, sınırlı ve test edilmiş olmalı.
- **"Grafana'nın üst seviyesi":** Ölçülebilir hedeflere çevrilmeli (§11.9). Grafana'nın sahip olduğu ama bizde olmayan
  büyük alanlar (alerting, SSO, org/takım RBAC, eklenti ekosistemi) aşamalı yol haritasına konur; **bizim farkımız**
  güçlü, kurulumu basit, sunucu tarafı **grup bazlı PDF/Excel raporlama** (Grafana'da bu Enterprise özelliğidir).
- **Ücretsiz:** Tüm özellikler açık kaynak lisansla (K2) ve ücretli katman olmadan.

### 11.2 Aşama 0 — Temel kararlar ve iskelet (önce)
1. Lisansı netleştir (K2), hak teyidini bekle (K1). `LICENSE`, `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md`, İngilizce README.
2. **Mimari karar kayıtları (ADR)** klasörü aç: `docs/adr/0001-...md`. Aşağıdaki her büyük karar bir ADR olsun.
3. Kodlama standartları: Python `ruff` + `mypy --strict` (kademeli), frontend TypeScript (11.6), `pre-commit`.
4. Test hedefi: backend satır kapsamı ≥ %80, kritik modüllerde ≥ %90; CI'a kapsam raporu ve eşik.

### 11.3 Aşama 1 — Uygulamanın kendi PostgreSQL veritabanı (sahibinin açık isteği)
**Hedef:** Ubuntu kurulumunda uygulama durumu SQLite yerine **yerel PostgreSQL** üzerinde. Windows/geliştirme için SQLite
isteğe bağlı kalabilir (tek kod tabanı, iki sürücü) veya tamamen PostgreSQL'e geçilir — ADR ile karar ver; öneri: **üretim
PostgreSQL zorunlu, SQLite yalnız geliştirme/test**.
1. **Veri erişim katmanı:** `db.py`'deki ham `sqlite3` kullanımını soyutla. Öneri: **SQLAlchemy 2.x Core** (ORM şart değil)
   + **Alembic** geçişleri. Tüm SQL'i taşınabilir yaz (`?` yerine bağlı parametre, `INSERT … ON CONFLICT`, `RETURNING`).
2. **Şema:** §7 tabloları PostgreSQL'e (TEXT kimlikler → `uuid`, zamanlar → `timestamptz`, JSON alanları → `jsonb`,
   `CHECK` kısıtları, gerekli indeksler). `audit` için ekleme-yalnız tetikleyici/izin (UPDATE/DELETE yasak).
3. **Eşzamanlılık:** worker iş alma `SELECT … FOR UPDATE SKIP LOCKED`; tek worker kilidi dosya kilidi yerine
   **`pg_advisory_lock`** → ileride çoklu sunucu/HA mümkün olur. Oturum ve sayaçlar satır kilitleriyle.
4. **Kurulum betiği:** `install-ubuntu.sh` PostgreSQL'i (`postgresql` paketi, Ubuntu 24.04'te 16) kurar, `openreporting`
   rolü + veritabanını oluşturur, **rastgele güçlü parola** üretip yalnız `openreporting.env`'e (0640) yazar, yalnız
   `localhost` (veya unix soket + peer) erişimi, `scram-sha-256`. Kullanıcıya hiçbir şey sorulmaz.
5. **Yedek/geri yükleme:** `pg_dump -Fc` + arşiv klasörü; geri yükleme belgelenmiş ve CI'da test edilmiş.
   Yükseltmede önce yedek, sonra `alembic upgrade head`, hata olursa geri dönüş.
6. **Taşıma aracı:** `openreporting migrate-sqlite-to-postgres --sqlite <yol>` (mevcut kurulumlar ve Windows denemeleri
   için), sonunda satır sayısı ve denetim zinciri doğrulaması.
7. **Bağlantı havuzu:** psycopg pool; `statement_timeout`; sağlık kontrolünde DB gecikmesi.
8. **CI:** PostgreSQL servisiyle test matrisi; uçtan uca kurulum işinde PostgreSQL'in kurulup kullanıldığını doğrula.

**Kabul ölçütü:** Temiz Ubuntu 24.04'te tek komutla kurulum → uygulama PostgreSQL kullanıyor; tüm testler PostgreSQL'de
yeşil; yedek → silme → geri yükleme → denetim zinciri geçerli.

### 11.4 Aşama 2 — Grafana seviyesinde sağlam mimari
1. **Veri kaynağı eklenti SDK'sı** (en kritik iş): Python arayüzü
   `class DataSourcePlugin: check_health() · query(QueryRequest) -> QueryResponse · metric_find() · resources() · schema()`
   + JSON Schema ile tanımlı yapılandırma/gizli alanlar + frontend sorgu düzenleyici sözleşmesi. Mevcut Zabbix/PostgreSQL/
   TestData bu SDK'ya taşınır. Eklentiler giriş noktası (entry point) ile keşfedilir; gizli alanlar otomatik şifrelenir.
2. **Veri çerçevesi standardı:** Grafana DataFrame'e yakın, sütun tabanlı (alanlar, tipler, birimler, etiketler, meta);
   büyük veride Apache Arrow IPC opsiyonu. Tüm paneller/dönüşümler/rapor bu modeli kullanır.
3. **Sorgu katmanı:** sorgu önbelleği (anahtar: kaynak + sorgu + zaman kovası, TTL), istek birleştirme (aynı sorgu tek
   kez), kaynak başına eşzamanlılık ve hız sınırı, iptal (istemci bağlantısı kesilince), zaman aşımı, nokta bütçesi,
   sunucu tarafı aşağı örnekleme (LTTB).
4. **Yetkilendirme:** organizasyon → takım → kullanıcı; klasör/dashboard/veri kaynağı izinleri (görüntüle/düzenle/yönet);
   **servis hesapları ve API token'ları**; oturum yönetimi (cihaz listesi, iptal).
5. **Kimlik:** yerel + **OIDC** (Keycloak, Azure AD, Google), **LDAP/Active Directory**, isteğe bağlı SAML; MFA (TOTP).
6. **Provisioning (kod olarak yapılandırma):** YAML ile veri kaynakları, klasörler, dashboard'lar, rapor tanımları;
   sunucu açılışında idempotent uygulama.
7. **Gözlemlenebilirlik:** yapılandırılmış JSON loglar, **OpenTelemetry** izleri, zengin Prometheus metrikleri
   (sorgu süresi/hata/önbellek isabeti, rapor süreleri), sağlık uçları.
8. **Public API:** sürümlenmiş (`/api/v1`), OpenAPI belgeli (yetkili kullanıcıya), geriye dönük uyumluluk politikası.
9. **Uyarı (alerting) — sonraki aşama:** kural motoru (eşik/anomali), bildirim kanalları (e-posta, Teams, Slack,
   webhook), susturma ve bakım pencereleri. Rapor zamanlayıcıyla aynı worker altyapısı.
10. **Diğer Grafana kavramları:** kütüphane panelleri, dashboard anlık görüntüleri (snapshot), public/paylaşımlı
    dashboard (salt-okunur, süreli bağlantı), playlist, dashboard JSON şema sürümleme ve geçişleri, sürüm farkı (diff).

### 11.5 Aşama 3 — Veri kaynakları (eklenti SDK'sı üzerinde, öncelik sırasıyla)
Mevcut: Zabbix, PostgreSQL/TimescaleDB, TestData.
1. **Öncelik 1 (izleme ekosistemi):** Prometheus (PromQL; Mimir/Thanos/VictoriaMetrics uyumlu), InfluxDB (InfluxQL, Flux,
   SQL/v3), Elasticsearch / OpenSearch, Loki (LogQL), MySQL/MariaDB, Microsoft SQL Server, **Infinity tarzı HTTP JSON/CSV/XML**
   (REST API'ler için genel kaynak), Graphite.
2. **Öncelik 2:** ClickHouse, Oracle, Google BigQuery, Snowflake, MongoDB, Redis, OpenTSDB, Alertmanager (anotasyon/uyarı
   görünümü), SNMP/NetFlow tabanlı kaynaklar (ağ izleme odağı için değerlendir).
3. **Öncelik 3 (bulut/izleme):** AWS CloudWatch, Azure Monitor / Log Analytics, Google Cloud Monitoring, Tempo/Jaeger/Zipkin
   (izler), Pyroscope (profil).
4. **Her kaynak için zorunlu:** salt-okunur, TLS doğrulama, SSRF korumalı HTTP istemcisi (yönlendirme yok, izin listesi),
   gizli alan şifreleme, sağlık kontrolü, metric-find (değişkenler için), sorgu düzenleyici (görsel kurucu + ham sorgu),
   zaman aşımı/sınır, değişken biçimlendirme, **birim testleri + kayıt/oynatma (fixture) entegrasyon testleri**, dokümantasyon.

### 11.6 Aşama 4 — Frontend mimarisi
- Bugünkü vanilla JS hızlı ama büyümeye uygun değil. Öneri: **TypeScript + React + Vite**, derleme çıktısı Python paketine
  dahil (sunucuda Node gerekmez, kurulum basit kalır). Durum yönetimi (ör. Zustand/Redux Toolkit), `@tanstack/react-query`
  ile veri çekme, sanal listeler (büyük tablolar).
- Bileşen kütüphanesi: Apache-2.0 `@grafana/ui` (lisansı doğrula) veya kendi tasarım sistemi; erişilebilirlik WCAG 2.2 AA.
- Grafik motoru: ECharts (Apache-2.0) devam; gerekirse uPlot (MIT) çok büyük zaman serileri için.
- Testler: **Vitest** (birim), **Playwright** (uçtan uca, CI'da gerçek tarayıcıyla giriş → dashboard → rapor akışları),
  görsel regresyon (panel ekran görüntüleri).
- **i18n:** Türkçe + İngilizce (anahtar tabanlı çeviri dosyaları), tarih/sayı biçimleri yerel ayarlı.
- Geçiş stratejisi: sayfa sayfa (önce dashboard + panel düzenleyici), API'yi bozmadan.

### 11.7 Aşama 5 — Grafik seçenekleri (çok daha fazla)
Mevcut 10 panel. Eklenecekler (öncelik sırası) — **her panel hem tarayıcıda hem PDF/Excel raporda** çalışmalı:
1. **Grafana çekirdek eşdeğerleri:** Heatmap, Histogram, XY Chart (saçılım), Trend, Candlestick, Bar chart geliştirmeleri
   (yığın/yüzde, yatay), Status history (tam), Geomap (harita, açık kaynak harita katmanları), Node graph (topoloji),
   Logs, Traces, Flame graph, Canvas (serbest yerleşim), Dashboard list, Alert list, Annotations list, News/Text geliştirmeleri.
2. **Ek grafikler (ECharts ile):** Sankey (trafik akışı), Treemap, Sunburst, Radar, Funnel, Boxplot, Calendar heatmap,
   Gauge varyantları, Scatter/bubble, Waterfall, Liquid fill, Ağ topolojisi (ağ izleme için öne çıkar).
3. **Alan/seçenek sistemi:** Grafana `fieldConfig` eşdeğeri tam set (renk şemaları, gradyan, eşik stilleri, değer eşleme
   türleri, link/drill-down, birim kategorileri), panel başına JSON şeması → otomatik seçenek arayüzü.
4. **PDF stratejisi:** yeni paneller için ya ReportLab vektör çizimi ya da **sunucu tarafı başsız tarayıcı (Chromium,
   Playwright) ile render** → PNG/PDF (Grafana image renderer eşdeğeri, tamamen yerel/çevrimdışı). Öneri: çekirdek paneller
   vektör kalsın (kalite + hız), egzotik paneller başsız tarayıcıyla; ADR yaz. Her iki yolda da metin seçilebilirliği ve
   Türkçe karakterler test edilmeli.

### 11.8 Aşama 6 — Kullanıcı dostu ve kolay kurulum
- **İlk çalıştırma sihirbazı:** yönetici oluştur → ilk veri kaynağı (bağlantı testli) → hazır şablon dashboard → ilk rapor.
- **Rapor sihirbazı:** dashboard seç → bölümleme (host/grup) → biçim/düzen/logo → zamanlama → alıcılar → önizleme.
- Şablon galerisi (ağ, sunucu, veritabanı, uygulama; tümü sentetik/genel), arama ve komut paleti (Ctrl+K), klavye
  kısayolları, geri al/yinele, taslak otomatik kaydetme, sürüm farkı, sorgu denetleyici, anlaşılır hata mesajları
  (çözüm önerili), boş durum ekranları, mobil uyumluluk, karanlık/aydınlık tema.
- **Kurulum:** (1) tek komut `curl …/install.sh | sudo bash` (imzalı betik, internet varsa), (2) **.deb paketi**
  (`apt install ./openreporting_x.y.z_amd64.deb`, bağımlılık olarak postgresql/nginx), (3) Docker Compose (uygulama +
  PostgreSQL + isteğe bağlı nginx), (4) çevrimdışı paket (wheel'ler + deb'ler). `openreporting setup` etkileşimli kurulum
  (alan adı, TLS: Let's Encrypt/kurum sertifikası/self-signed). Yükseltme tek komut + otomatik yedek + geri dönüş.
- Belgeler: kurulum, yönetici kılavuzu, kullanıcı kılavuzu, API belgesi, eklenti geliştirme kılavuzu (TR + EN).

### 11.9 Ölçülebilir kalite hedefleri ("mükemmel seviyede çalışma" tanımı)
| Alan | Hedef |
| --- | --- |
| Performans | 20 panelli dashboard ilk yükleme < 2 sn (önbellekli < 1 sn); API p95 < 300 ms (sorgu süresi hariç); 100 bölümlü PDF < 60 sn; 50 eşzamanlı kullanıcı tek sunucuda (4 vCPU/8 GB) |
| Ölçek | 10.000 host / 1M nokta yanıt bütçesi sınırlarında kırpma yerine açık hata; büyük tablolarda sanal kaydırma |
| Güvenilirlik | Worker çökmesinde iş kaybı yok; belirsiz e-posta asla tekrarlanmaz; yükseltme başarısızsa otomatik geri dönüş |
| Güvenlik | OWASP ASVS L2; bağımlılık taraması (pip-audit, npm audit), SBOM (CycloneDX), imzalı sürümler, gizli tarama (gitleaks) CI'da |
| Kalite | Kapsam ≥ %80; CI'da birim + entegrasyon + Playwright E2E + yük testi (k6/locust, sürüm öncesi) |
| Erişilebilirlik | WCAG 2.2 AA (klavye, kontrast, ekran okuyucu) |
| Kurulum | Temiz Ubuntu'da tek komut, < 10 dk, soru sormadan çalışır durumda |

### 11.10 Önerilen sıra ve sürümler
`v1.1` mevcut iki özellik + lisans/public hazırlığı → `v1.2` PostgreSQL uygulama DB + taşıma aracı + kurulum →
`v1.3` eklenti SDK'sı + mevcut kaynakların taşınması + Prometheus/InfluxDB/MySQL/MSSQL/HTTP-JSON →
`v2.0` TypeScript/React frontend + i18n + yeni paneller (ilk dalga) + başsız tarayıcı render →
`v2.x` RBAC/org/takım + OIDC/LDAP + provisioning + public API → `v3.0` alerting + kalan kaynak/panel dalgaları.
Her sürüm: CHANGELOG, etiket, GitHub Release, CI yeşil, yükseltme testi.

---

## 12. Bilinen sınırlamalar ve teknik borç
- Uygulama DB'si SQLite (tek sunucu, HA yok) → §11.3.
- Yalnız 3 veri kaynağı, 10 panel; eklenti sistemi yok.
- Org/takım, klasör/dashboard izinleri, servis hesapları, API token'ları, SSO/LDAP/MFA, alerting, playlist, kütüphane
  paneli, snapshot, public dashboard **yok**.
- Frontend derlemesiz vanilla JS; JS için yalnız sözdizimi kontrolü var, **JS birim/E2E tarayıcı testi yok**.
- Arayüz yalnız Türkçe; OpenAPI belgesi kapalı.
- PDF yalnız ReportLab vektör; yeni panel türleri için PDF karşılığı ayrıca yazılmalı. Excel'de logo yok (K6).
- Uygulama içinden rapor çalıştırması silme yok (K4).
- `users.role` CHECK kısıtı `admin/editor/viewer`; rol modeli genişletilirken şema adımı gerekir.
- Sorgu önbelleği yok; her panel yenilemesi kaynağa gider (eşzamanlılık ve nokta bütçesi ile sınırlı).

---

## 13. Geçmiş: bu noktaya nasıl gelindi
1. Başlangıç: sahibinin verdiği küçük bir rapor uygulaması paketi (FastAPI + SQLite). Windows'ta çalışır hale getirildi.
2. Grafana benzeri platforma dönüştürüldü: sorgu motoru, veri kaynakları, dashboard modeli, SPA arayüz, rapor motoru,
   Ubuntu dağıtımı, dokümanlar, CI.
3. Bağımsız güvenlik, backend ve frontend incelemeleri yapıldı; bulgular düzeltildi (izleyici sorgu izolasyonu, SQL
   koruması, regex zaman aşımı, saat dilimi, yarış durumları, erişilebilirlik vb.) ve regresyon testleri yazıldı.
4. Ürün adı **OpenReporting** olarak belirlendi; eski adla ilgili her şey değiştirildi.
5. Önceki uygulamadan kalan, şirkete özgü bir modül ve ona bağlı rol tamamen kaldırıldı.
6. Şirket bilgisi taraması yapıldı; tüm izler temizlendi, geçmiş tek commit'e indirildi, GitHub deposu silinip temiz
   olarak yeniden oluşturuldu. Veritabanı şeması sürüm 1'den başlayan temiz bir başlangıç şemasına indirildi.
7. Masaüstü başlatıcı ve rapor PDF'ine müşteri logosu eklendi.

---

## 14. Devralan için çalışma biçimi ve kontrol listesi
**Her görevde:**
1. İlgili bölümü ve kodu oku; varsayma, doğrula.
2. Değişikliği küçük ve tutarlı yap; mevcut kod stiline uy (yorum yoğunluğu, adlandırma).
3. Test yaz/güncelle (yeni davranış + regresyon). `pytest`, `node --check`, `shellcheck` yerelde yeşil.
4. Güvenlik değişmezlerini (§9) kontrol et; yeni uçlarda rol + CSRF + denetim kaydı.
5. **Şirket bilgisi taraması** (commit öncesi): gerçek ad, host, IP, alan adı, e-posta yok.
   Örnek: `git grep -nIiE "<şüpheli terimler>"`; örnek verilerde yalnız genel adlar.
6. Lisans kontrolü: yeni bağımlılığın lisansı Apache-2.0/MIT/BSD/MPL uyumlu mu; AGPL/GPL kod kopyalama yok.
7. Dokümanları ve CHANGELOG'u güncelle; Conventional Commit; push; **CI'ın tamamı yeşil** olmadan bitmiş sayma.
8. Geri alınamaz/dışa dönük işlemlerde (public yapma, depo silme, zorla push, veri silme) sahibinden onay al.

**Devralırken ilk yapılacaklar:**
- [ ] Depoya erişim (sahibinden GitHub erişimi veya `git archive -o openreporting.zip HEAD` ile kod paketi).
- [ ] §10'daki geliştirme ortamını kur, 55 testi çalıştır.
- [ ] K1/K2 kararlarını sahibinden al (hak teyidi, lisans).
- [ ] `v1.1.0` sürümünü çıkar (K5).
- [ ] §11.3 PostgreSQL geçişi için ADR yaz ve başla.
