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

## İlgili belgeler

- Mimari özet: [../ARCHITECTURE.md](../ARCHITECTURE.md)
- Kullanım: [../USER_GUIDE.md](../USER_GUIDE.md)
- Kurulum: [../LINUX_DEPLOYMENT.md](../LINUX_DEPLOYMENT.md), [../DOCKER.md](../DOCKER.md), [../KUBERNETES.md](../KUBERNETES.md)
- Güvenlik: [../THREAT_MODEL.md](../THREAT_MODEL.md), [../MFA.md](../MFA.md), [../KEY_ROTATION.md](../KEY_ROTATION.md)
