# 16 — Tıklanabilir tarih aralığı takvimi

## Amaç

Rapor formunda "Başlangıç / Bitiş" alanları ve dashboard zaman seçicisindeki mutlak aralık elle yazılıyordu
(`now-1d/d`, `2026-11-01 00:00`). Artık bir takvimden iki tıklamayla seçiliyor.

## Nerede

| Ekran | Giriş |
| --- | --- |
| Raporlar → rapor formu | "Zaman aralığı" seçicisinin yanındaki **Takvim** düğmesi |
| Dashboard zaman seçicisi | Açılır pencerede **Takvimden seç** |
| Akıllı dashboard → panel → Tarih aralığı → Panele özel | **Takvim** düğmesi (ör. 24 saatlik raporda tek panel için "2–20 Ekim") |

## Davranış (`static/app/calendar.js`)

- Yan yana iki ay, pazartesi ile başlayan hafta, Türkçe ay/gün adları; bugün çerçeveli, gelecek günler seçilemez.
- İlk tıklama başlangıç, ikinci tıklama bitiş; fareyle gezinirken aralık önizlenir; özet satırı "1 Ekim 2026 – 10 Ekim 2026 · 10 gün".
- **Tüm gün** (varsayılan): başlangıç günü 00:00 → bitişten sonraki gün 00:00. Kapatılırsa başlangıç/bitiş saati girilir (23:59 bitiş o dakikayı içerir).
- Günler raporun/dashboard'un **saat diliminde** duvar saatidir; yaz saati geçişleri doğru hesaplanır (Berlin'de geçiş günü 23/25 saat).
- Göreli bir aralıktan ("Dün", "Son 1 yıl") açılınca takvim o aralığın günlerini gösterir ama saatlerini almaz (`daysOnly`).
- Klavye: ok tuşları gün/hafta, PageUp/PageDown ay, Enter/Space seçer; tek odak noktalı (roving tabindex) ızgara.
- Sonuç, sunucunun her zaman aralığında kabul ettiği mutlak epoch-ms değerleridir; API değişmedi.

## Rapor formu

- Alanlar mutlak değerleri okunur gösterir (`2026-11-01 00:00:00`), göreli ifadeler aynen kalır.
- Yazılan değer `parseUserTime` ile doğrulanır (göreli ifade, `YYYY-AA-GG SS:DD`, `GG.AA.YYYY`); geçersizse uyarı verilir ve eski değer geri gelir
  (daha önce geçersiz metin sessizce kaydediliyordu).
- Saat dilimi değişince alanlar yeni dilime göre yeniden yazılır.
- Not: takvimle seçilen sabit tarihler anlık çalıştırma ve önizleme içindir; zamanlanmış çalıştırmalar "önceki tam dönem"i kullanır.

## Okunur etiketler

`rangeLabel()` tam günlü mutlak aralıkları "2 Ekim 2026 – 20 Ekim 2026" diye yazar (önceden
"02.10.2026 00:00:00 → 21.10.2026 00:00:00"); akıllı dashboard yan panelindeki seçici dar alanda taşmaz.

## Testler

- `tests/test_calendar.mjs`: İstanbul gece yarısı, ay uzunluğu, Berlin ekim/mart geçişleri, Türkçe tarih.
- `tests/browser/calendar-flow.cjs` (CI'da `tools/folder_browser_acceptance.py` içinde): rapor formunda fare ve klavye ile seçim,
  tam gün varsayılanı, alanlara yazılan değerler, geçersiz değer uyarısı, dashboard seçicisinde URL'nin iki tam güne dönmesi, 5 temada axe.
