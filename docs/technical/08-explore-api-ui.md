# 08 · Keşfet, API sayfası ve arayüz düzeltmeleri

| | |
| --- | --- |
| Durum | Uygulandı |
| Dosyalar | `pages/explore.js`, `pages/apikeys.js`, `viz-icons.js`, `icons.js`, `time.js`, `query/editors.js`, `app.css` |

## Keşfet (Explore)

Sorun: sayfa doğrudan teknik sorgu editörüyle açılıyordu; TestData'nın "Senaryo" alanı ne olduğu anlaşılmadan
görünüyordu. Yeni akış üç adımdır ve sayfada açıkça yazar:

1. **Veri kaynağı** — kaynaklar kart olarak listelenir (tür adıyla). Varsayılan, TestData olmayan ilk kaynaktır.
   Seçilen türe göre "ne yazmalıyım" ipucu gösterilir; TestData seçilirse "gerçek veri değildir" uyarısı.
2. **Sorgu** — mevcut sorgu editörü; değişiklikten 600 ms sonra sonuç kendiliğinden yenilenir (Ctrl+Enter da çalışır).
3. **Sonuç** — görünüm seçici (zaman serisi, çubuk, tek değer, gösterge, pasta, tablo), zaman aralığı ve
   "Dashboard'a panel olarak kaydet".

TestData editöründe "Senaryo" etiketi **"Örnek veri"** oldu.

## API sayfası

Sorun: "API anahtarları" menüsü servis hesabı kavramını öne çıkarıyordu; kullanıcı "API desteği" istemişti.
Artık tek bir **Yönetim → API** sayfası var:

- **Genel bakış:** API'nin ne yaptığı, 3 adım (anahtar oluştur → başlığa ekle → çağır), temel adres, gerçek
  uçlarla `curl` örnekleri, OpenAPI JSON indirme (Postman/Insomnia/kod üreticileri için).
- **Uç noktalar:** `/api/openapi.json`'dan aranabilir liste.
- **Erişim anahtarları:** "Yeni erişim anahtarı" tek pencerede uygulama adı, yetki (Okuma / Okuma+yazma),
  süre ve parola onayı ister; arka planda `svc-<uygulama>` servis hesabını oluşturur (yoksa) ve anahtarı
  bir kez gösterir. Liste uygulama, yetki, durum, son kullanım ve iptal/durdur işlemlerini gösterir.

Sunucu modeli değişmedi (bkz. 04): anahtarlar hesap/oturum/yönetim uçlarında çalışmaz. Eski `/admin/api-keys`
adresi aynı sayfanın anahtarlar sekmesini açar.

## Dashboard araç çubuğu

Zaman aralığı ve otomatik yenileme düğmeleri "yalnız ikon" düğme sınıfıyla (sabit 32 px genişlik) oluşturulup
sonradan metin eklendiği için metin ikonun üstüne taşıyordu. Metinli düğmelerde bu sınıf kaldırıldı; etiket
240 px'te üç noktayla kısalır.

## Görselleştirme ikonları

20 ek görselleştirmenin hepsi aynı çubuk grafik ikonunu kullanıyordu. `viz-icons.js` her tür için ayrı bir
24×24 ikon tanımlar (ısı haritası, histogram, XY dağılım, balon, kutu, mum, radar, huni, ağaç haritası,
hiyerarşi halkası, Sankey, bağlantı grafiği, takvim ısı haritası, şelale, kutupsal çubuk, paralel koordinatlar,
halka, gül, yığılmış alan, basamak). İkonlar `currentColor` kullanır, temaya uyar.

## Komut paleti ve kısayollar (sonradan eklendi)

- **Ctrl+K / ⌘K** veya üst çubuktaki "Ara…" kutusu komut paletini açar: dashboard'lar, akıllı dashboard'lar,
  sayfalar ve işlemler (yeni dashboard, şablondan akıllı dashboard, rapor zamanla …) tek listede.
  Sonuçlar `/api/search`'ten gelir; izinler sunucuda uygulanır. Arama bulanıktır ve Türkçe karakter/aksan
  duyarsızdır ("yonetici ozet" → "Yönetici özeti"; `fuzzy.js`, `tests/test_fuzzy.mjs`). ↑/↓, Enter, Esc.
- **?** tuşu tüm kısayolların listesini açar.
- Ana sayfa yeni akışı anlatır: akıllı dashboard ile hızlı rapor, dashboard, zamanlanmış rapor.
- Akıllı dashboard sayfa araçlarına **Otomatik düzenle** eklendi: sayfadaki boşluklar kapanır, öğeler sütun
  ve sıra korunarak yukarı toplanır (`compactPage`).
