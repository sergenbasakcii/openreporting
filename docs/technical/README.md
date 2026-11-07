# OpenReporting teknik dokümantasyonu

Her geliştirme için bir belge yazılır; numara uygulanma sırasıdır. Belgeler tasarım kararını, veri modelini,
API'yi, güvenlik kurallarını ve testleri anlatır. Kurulum ve işletim rehberleri `docs/` kökündedir.

| No | Belge | Konu |
| --- | --- | --- |
| 01 | [Kalite kapıları ve yeniden düzenleme](01-quality-gates.md) | ruff, biçim, kapsam eşiği, lockout/MFA/CLI yeniden düzenlemesi |
| 02 | [Rapor hatası bildirimleri](02-report-notifications.md) | İşlemsel giden kutusu, alıcı kuralları, teslim |
| 03 | [Dashboard sürüm farkı](03-dashboard-version-diff.md) | Okunur yapısal fark, onay akışı |
| 04 | [REST API ve API anahtarları](04-api-and-tokens.md) | Servis hesapları, Bearer anahtar, OpenAPI |
| 05 | [Eklenti sistemi](05-plugins.md) | Veri kaynağı (Python entry point) ve panel (ES modülü) eklentileri |
| 06 | [Tema sistemi ve görsel kimlik](06-themes.md) | Beş özgün tema, token mimarisi, WCAG kontrast testi |
| 07 | [Veri gölü ve yeni veri kaynakları](07-datalake-and-datasources.md) | Trino/Presto, Databricks, ClickHouse, Elasticsearch/OpenSearch, InfluxDB, Graphite |
| 08 | [Keşfet, API sayfası ve arayüz düzeltmeleri](08-explore-api-ui.md) | Adım adım Keşfet, tek API sayfası, araç çubuğu, görselleştirme ikonları |
| 09 | [Takımlar ve dashboard izinleri](09-teams-and-dashboard-permissions.md) | Kullanıcı grupları, takıma klasör izni, dashboard bazında kullanıcı/takım izni |
| 10 | [Akıllı dashboard](10-smart-dashboard.md) | Canlı PDF sayfası, sürükle-bırak, anahtar kelime / drill-down, birebir PDF |
| 11 | [PDF ve Excel çıktı tasarımı](11-export-design.md) | Marka paleti, kapak/başlık/tablo, Excel stilleri |
| 12 | [Akıllı dashboard v2](12-smart-dashboard-v2.md) | Şablonlar, logo/görsel, rapor filtresi, host bazında PDF, panel bazında tarih aralığı, geri al |
| 13 | [Önceki dönemle karşılaştırma ve akıllı özet](13-compare-and-narrative.md) | KPI ▲/▼ değişim, kesikli önceki dönem, veriden cümle üreten özet paneli |
| 14 | [Tek komutla Docker kurulumu](14-one-command-installer.md) | `kurulum.sh`: kur, güncelle, durum, yedek; CI ile doğrulanır |
| 15 | [Uçtan uca tarama ve düzeltmeler](15-full-scan-fixes.md) | Veri kaynağı tür seçicisi, akıllı dashboard araç çubuğu, dönüşüm sağlamlığı, metin düzeltmeleri |

## İlgili belgeler

- Mimari özet: [../ARCHITECTURE.md](../ARCHITECTURE.md)
- Kullanım: [../USER_GUIDE.md](../USER_GUIDE.md)
- Kurulum: [../LINUX_DEPLOYMENT.md](../LINUX_DEPLOYMENT.md), [../DOCKER.md](../DOCKER.md), [../KUBERNETES.md](../KUBERNETES.md)
- Güvenlik: [../THREAT_MODEL.md](../THREAT_MODEL.md), [../MFA.md](../MFA.md), [../KEY_ROTATION.md](../KEY_ROTATION.md)
