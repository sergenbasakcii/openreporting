# 13 · Önceki dönemle karşılaştırma ve akıllı özet

| | |
| --- | --- |
| Durum | Uygulandı |
| Sunucu | `query_engine.with_previous_period` / `mark_previous`, `api/datasources.py` (`compare`), `reporting/collect.py`, `reporting/compare.py`, `reporting/narrative.py`, `reporting/pdf.py` |
| Tarayıcı | `panels/common.js` (`comparisonDeltas`, `deltaLabel`), `panels/dompanels.js`, `panels/timeseries.js`, `panels/narrative.js`, `smart/inspector.js`, `smart/templates.js` |
| Testler | `tests/test_compare_narrative.py` |

## Önceki dönemle karşılaştırma

Panel seçeneği `options.compare = "previous"`. İstek `compare: "previous"` taşıdığında sorgu motoru, gizli
olmayan her sorgunun bir kopyasını (`refId + "__prev"`) panel aralığının uzunluğu kadar geri kaydırarak
çalıştırır (`timeShift <süre>s`; panelin kendi `timeShift`'i yerini bu kaymaya bırakır). Kopya çerçeveleri
`meta.previous = true` ve ad sonuna " (önceki dönem)" alır ve geçerli pencereye hizalanır.

- **Güvenlik / tutarlılık:** izleyiciler için bayrak kayıtlı panelden okunur (tarayıcının gönderdiği değer
  kullanılmaz); raporlar `collect` içinde aynı bayrağı kullanır. Sorgu sınırı (26) kopyalarla birlikte uygulanır.
- **Stat:** değerin altında "▲ %12,5 önceki döneme göre". `options.compareGood` → `down` (azalış iyi: CPU,
  hata, gecikme), `up` (artış iyi) veya `neutral` renklendirmeyi seçer. Eşleştirme seri adına göre, ad
  geçersiz kılınmışsa aynı sıraya göre yapılır.
- **Zaman serisi / çubuk:** önceki dönem kesikli ve dolgusuz çizilir (ekran ve PDF).
- **Diğer görselleştirmeler:** indirgeyiciler (`reducedValues`, `reduced_items`) önceki dönem çerçevelerini
  dışarıda bırakır; çubuk gösterge, pasta, tablo gibi paneller değişmeden kalır.

## Akıllı özet (`narrative`)

Bir sorguya bağlı, cümleler üreten panel türü. Yalnızca veriden çıkan gerçekler yazılır:

1. Ortalama, en yüksek (host ve zaman) ve en düşük değer.
2. Birden çok seri varsa en yüksek ve en düşük ortalamalı seri, incelenen seri sayısı.
3. Dönemin ikinci yarısı ile ilk yarısı karşılaştırması (%5 altı "kararlı").
4. Eşik tanımlıysa en üst eşiği son değerde aşan seriler (en çok 5 ad + "ve N diğer").
5. Karşılaştırma açıksa önceki döneme göre ortalama değişimi.

Birim ve ondalık panel ayarından gelir. Aynı kurallar tarayıcıda (`narrative.js`) ve PDF'te (`narrative.py`)
uygulanır, böylece ekranda okunan cümle raporda da aynıdır. Konu metni `options.subject` veya panel başlığı.

## Şablonlar

"Yönetici özeti" şablonu artık bir CPU özet paneli, önceki dönemle karşılaştırmalı "Ortalama CPU" KPI'ı ve
önceki dönem çizgili CPU eğilimi içerir.

## PDF rötuşu

Boş bırakılmış görsel öğesi teslim edilen raporda yer tutucu basmaz (rapor logosu varsa onu basar); yalnızca
seçilmiş ama artık bulunamayan bir görsel için küçük bir uyarı yazılır.

## En yüksek / en düşük N

`options.topN` (ve `options.topOrder = "desc" | "asc"`) indirgeyen panellerde (çubuk gösterge, pasta, halka,
durum ızgarası, stat, gösterge) değeri en yüksek veya en düşük N öğeyi sıralı olarak bırakır; boş değerler
sıralamaya girmez. Tarayıcıda `topN()` (`panels/common.js`), PDF'te `fieldcfg.top_n` aynı kuralla çalışır.
Yönetici özeti şablonu "En yüksek bellek kullanımı · ilk 10" kullanır.
