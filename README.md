# OpenReporting 1.0 — Gözlem, Dashboard ve Grup Bazlı Raporlama Platformu

OpenReporting; Zabbix ve SQL (PostgreSQL/TimescaleDB) kaynaklarından **Grafana benzeri dashboard’lar** kurmanızı,
host grupları üzerinde **sorgu bazlı metrik** çekmenizi ve bunları **PDF / Excel / CSV raporlara** dönüştürüp
zamanlamanızı sağlar. Tek bir Ubuntu sunucuda çalışır; Redis, Node, CDN veya harici bulut servisi gerektirmez.

> Kaynak sistemlere **yalnızca okuma** yapılır. Veri olmayan noktalar asla sıfır kabul edilmez; eksik veri içeren
> raporlar “kısmi” olarak işaretlenir ve varsayılan olarak e-postayla gönderilmez.

## Öne çıkanlar

| Alan | Yetenek |
| --- | --- |
| Dashboard | 24 sütunlu sürükle-bırak ızgara, satırlar (daralt/genişlet), panel ve satır **tekrarı** (`$host` başına), sürüm geçmişi ve geri yükleme, klasörler, etiketler, yıldızlar, paylaşım linki, TV/kiosk modu, JSON modeli, **Grafana JSON içe aktarma** (Zabbix eklentisi sorguları dahil) |
| Görselleştirme | Zaman serisi (çizgi/alan/çubuk, yığın, çift eksen, eşik çizgi/alanı, **negatif-Y giriş/çıkış trafiği**, lejant tablosu), çubuk grafik, stat, gösterge, çubuk gösterge, tablo (renkli hücre, gösterge hücresi, alt toplam), pasta/halka, **durum ızgarası** (grup sağlık görünümü), durum zaman çizelgesi, Markdown metin |
| Sorgu | Zabbix: grup / host / item etiketi / item filtreleri (tam ad, `*` joker, `/regex/`), history/trend otomatik seçimi, item ID, son değerler tablosu, aktif problemler. PostgreSQL: salt-okunur SQL + Grafana makroları (`$__timeFilter`, `$__unixEpochGroupAlias` …). TestData: sentetik Zabbix simülasyonu |
| Fonksiyonlar | `groupBy`, `aggregateBy`, `sumSeries`, `averageSeries`, `percentileAgg`, `groupByLabel`, `top/bottom`, `filterSeries`, `scale`, `rate`, `delta`, `movingAverage`, `timeShift`, `setAlias`, `replaceAlias`, `trendValue` … (Grafana-Zabbix eklentisiyle aynı adlar) |
| İfadeler & dönüşümler | `$A / $B * 100` gibi güvenli matematik ifadeleri (host etiketine göre eşleştirme), reduce / resample; host × metrik matrisi, özet tablosu, birleştirme, sıralama, sınır, hesaplanan sütun, gruplama matrisi |
| Değişkenler | Sorgu (Zabbix/SQL), özel liste, metin kutusu, sabit, aralık, veri kaynağı; çoklu seçim + “Tümü”, zincirleme (`$group` → `$host`), regex, sıralama, URL ile paylaşım |
| Raporlar | Dashboard’dan **PDF (vektör)**, **Excel**, **CSV**; kapak + içindekiler; dashboard ızgarası veya akış düzeni; **`split_by` ile her host / grup için ayrı bölüm**; zamanlama (saatlik/günlük/haftalık/aylık/yıllık, “önceki tam dönem”); e-posta; SHA-256 manifest + denetim zinciriyle doğrulanan arşiv; saklama süresi |
| Yönetim | Veri kaynakları (şifreli kimlik bilgisi, bağlantı testi), kullanıcılar ve roller, tercihler (tema, saat dilimi, ana sayfa), sunucu durumu, denetim kaydı, Prometheus `/metrics` |
| İşletim | Ubuntu kurulum betiği, sertleştirilmiş systemd servisleri, nginx TLS, günlük yedekleme zamanlayıcısı, yükseltme + geri dönüş, `openreporting doctor`, Docker alternatifi |


## Hızlı başlangıç — Ubuntu sunucu (üretim)

```bash
# Paketi sunucuya kopyalayın (git clone veya zip) ve:
sudo ./deploy/install-ubuntu.sh --domain openreporting.sirket.local --self-signed --admin sergen
```

Kurulum; servis kullanıcısını, `/opt/openreporting` (kod + venv), `/var/lib/openreporting` (veri), `/etc/openreporting` (ayar + anahtar)
dizinlerini, `openreporting-web` / `openreporting-worker` servislerini, nginx HTTPS ters vekilini ve gece yedeğini hazırlar.
Ayrıntılar: **[docs/LINUX_DEPLOYMENT.md](docs/LINUX_DEPLOYMENT.md)**.

İlk girişten sonra:
1. **Yönetim → Veri kaynakları → Veri kaynağı ekle → Zabbix**: `https://zabbix.../api_jsonrpc.php` + salt-okunur API token.
2. **Dashboard’lar → Yeni dashboard** veya Grafana JSON’unu **İçe aktar**.
3. **Raporlar → Yeni rapor**: dashboard’u seçin, `$host` ile bölümleyin, PDF/Excel önizleyin, zamanlayın.

Kullanım kılavuzu: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

## Yerel deneme — Windows 10/11

```powershell
.\windows\Install-OpenReporting.ps1
.\windows\New-Admin.ps1 -Username sergen
.\windows\Start-OpenReporting.ps1      # http://127.0.0.1:8810
```

Ayrıntılar: [README_WINDOWS.md](README_WINDOWS.md). Windows yalnızca kişisel değerlendirme içindir; zamanlanmış
raporların sürekli çalışması için Ubuntu kurulumunu kullanın.

## Mimari (özet)

```
Tarayıcı (ES modülleri + ECharts, derleme yok)
   │  HTTPS (nginx)  ──  CSRF başlığı + HttpOnly oturum çerezi
   ▼
openreporting-web  (FastAPI/uvicorn, 127.0.0.1:8810)
   ├─ /api/ds/query  → query_engine: değişkenler → veri kaynağı → fonksiyonlar → ifadeler → dönüşümler
   ├─ dashboards / folders / versions / annotations / users / datasources
   └─ /api/dash-reports (önizleme, anlık çalıştırma, zamanlama, arşiv)
openreporting-worker  (tek zamanlayıcı, dosya kilidi)
   └─ zamanlanmış raporlar → aynı sorgu hattı → PDF (ReportLab) / XLSX (openpyxl) / CSV → arşiv → SMTP
SQLite (WAL, /var/lib/openreporting/state.sqlite3) · rapor arşivi · Fernet şifreleme anahtarı (/etc/openreporting/secret.key)
```

Dashboard ekranı ve PDF raporu **aynı sunucu tarafı sorgu hattını** kullanır; ekranda gördüğünüz grup özet tablosu
raporda birebir aynıdır. Ayrıntılar: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Komut satırı

```text
openreporting init                         # şema oluştur/yükselt
openreporting create-user NAME --role admin|editor|viewer
openreporting reset-password NAME | disable-user NAME
openreporting serve --host 127.0.0.1 --port 8810 [--workers 2] [--proxy-headers]
openreporting worker                       # rapor zamanlayıcı/üretici (tek örnek)
openreporting doctor                       # kurulum kontrolü
openreporting export-dashboards DIR | import-dashboards DIR   # dashboard’ları kod olarak sakla
openreporting backup /yedek/state.sqlite3 | verify-audit
```

Ubuntu’da bu komutları servis kullanıcısıyla çalıştırmak için: `sudo /opt/openreporting/app/deploy/openreporting-admin.sh <komut>`.

## Güvenlik ilkeleri

- Kaynaklara yalnızca okuma: Zabbix’te yalnız `*.get` yöntemleri izinli; SQL her zaman `READ ONLY` işlem + `statement_timeout` + satır sınırıyla.
- Kimlik bilgileri (Zabbix token, DB parolası) sunucuda Fernet ile şifreli; tarayıcıya asla gönderilmez.
- scrypt parola özeti, giriş deneme sınırı, `SameSite=Strict` HttpOnly çerez, CSRF başlığı, sıkı CSP, HSTS.
- Tüm değişiklikler SHA-256 hash zincirli denetim kaydında; rapor dosyaları indirilirken manifest özetiyle doğrulanır.
- systemd sandbox: `ProtectSystem=strict`, yalnızca `/var/lib/openreporting` yazılabilir, yetki yok.

## Test

```bash
.venv/bin/python -m pytest -q
```
