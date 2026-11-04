# 11 · PDF ve Excel çıktı tasarımı

| | |
| --- | --- |
| Durum | Uygulandı |
| Dosyalar | `reporting/pdf.py`, `reporting/excel.py`, `reporting/fieldcfg.py` (seri renkleri, bkz. 06) |

Çıktılar Grafana dönemindeki turuncu vurgu ve koyu gri kapakta kalmıştı. Uygulama temasıyla (Porselen,
bkz. 06) aynı görsel dile taşındılar.

## PDF

| Öğe | Önce | Şimdi |
| --- | --- | --- |
| Palet | Turuncu `#ff7f00`, gri mürekkep | Camgöbeği `#0d9488` → çivit `#4f46e5`, mürekkep `#141a2a`, açık ton `#eaf6f4` |
| Sayfa başı | Düz turuncu şerit | Marka gradyan şeridi, "O" marka karosu + başlık, sağda dönem ve saat dilimi |
| Kapak | Koyu gri bant, turuncu etiket | Gece laciverti bant, yumuşak marka ışıması, gradyan şerit, camgöbeği etiket, bilgiler açık tonlu kartta |
| Panel çerçevesi | 3 pt köşe | 6 pt köşe, başlık önünde marka vurgu çubuğu |
| Bölüm başlığı | Gri bant | Açık ton bant + marka kenarı |
| Tablo başlığı | Gri zemin, mavi yazı | Açık ton zemin, koyu camgöbeği yazı, daha yumuşak satır bantları |
| Stat | Çok değer üst üste | Kapasite sınırı + "+N değer daha" (bkz. 10) |

Gradyan, ince dilimlerle çizilir (`_gradient`); her PDF görüntüleyicide aynı görünür, ek bağımlılık yok.
İçerik yapısı (sayfalama, tablo devamları, kısmi veri uyarısı, logo yerleşimi) değişmedi.

## Excel

- Özet sayfası: büyük başlık, etiket sütunu, panel dizini başlığı camgöbeği zeminde beyaz, ince kenarlıklar,
  durum sütunu renkli (Tamam yeşil, hata kırmızı), dondurulmuş başlık.
- Veri sayfaları: başlık satırı camgöbeği, satır bantları, ince kenarlıklar, tek bloklu sayfalarda otomatik
  filtre, yazdırma ayarı yatay ve sayfa genişliğine sığdır.
- Hücre konumları ve değerler değişmedi (otomasyonlar ve testler aynı hücreleri okur).

## CSV

Makine tarafından okunan uzun biçim (bölüm, panel, blok, satır, sütun, değer, birim) ve UTF-8 BOM aynen
korunur; tasarım değişikliği yapılmadı (entegrasyonları bozmamak için).

## PDF yer imleri (sonradan eklendi)

Her PDF'te görüntüleyicinin kenar çubuğunda bir anahat (outline) bulunur: raporun başı ve her bölüm (ör. host
bazında raporda her host) için bir giriş. 30 sayfalık host raporunda istenen hosta tek tıkla gidilir.
