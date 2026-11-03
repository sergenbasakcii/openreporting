# 03 · Dashboard sürüm farkı

| | |
| --- | --- |
| Durum | Uygulandı |
| Modül | `openreporting/dashboard_diff.py` (saf, G/Ç yok), `dashboards.version_diff` |
| API | `GET /api/dashboards/uid/{uid}/diff?base=<sürüm>[&target=<sürüm>]` (target yoksa güncel) |
| Arayüz | Dashboard ayarları → Sürümler → **Değişiklikleri gör** |
| Testler | `tests/test_dashboard_diff.py` |

## Amaç

Zamanlama onayı, onaylanan rapor ve dashboard sürümüne bağlıdır; değişiklikten sonra yeniden onay gerekir.
Onaylayan yönetici neyin değiştiğini ham JSON yerine okunur satırlarla görmelidir.

## Algoritma

- Dashboard alanları (başlık, açıklama, etiketler, zaman, yenileme, saat dilimi) değer karşılaştırmasıyla.
- Değişkenler **ada** göre eşlenir; tür, veri kaynağı, sorgu, regex, çoklu seçim, "Tümü" vb. alanlar.
  Değişkenin o anki seçimi (`current`) ve çözülmüş seçenekleri çalışma zamanı durumudur, yok sayılır.
- Paneller **kimliğe** göre eşlenir; daraltılmış satırların içindeki paneller de dahildir. Başlık, tür, veri
  kaynağı, sorgular, dönüşümler, alan ayarları, seçenekler, tekrar değişkeni, açıklama, konum.
- Çıktı: `{"kind": "added"|"removed"|"changed", "scope": "dashboard"|"variable"|"panel", "text": "…"}` listesi.

Klasör izni hem eski hem yeni sürümü okurken uygulanır.
