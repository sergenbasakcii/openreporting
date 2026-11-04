# 12 · Akıllı dashboard v2: şablonlar, logo, rapor filtresi, panel tarih aralığı

| | |
| --- | --- |
| Durum | Uygulandı |
| Tarayıcı | `pages/smart.js` (oluşturucu), `smart/inspector.js`, `smart/templates.js`, `smart/history.js`, `smart/canvas.js`, `smart/keywords.js`, `panels/layout.js` |
| Sunucu | `smart_layout.py` (marka alanları), `reporting/layout_pdf.py` (yeni öğeler), `reporting/collect.py` (panel dönemi, bölüm değişkenleri), `reporting/service.py` (görseller, logo), `api/reports.py` (`split_by`), `safe_regex.py` |
| Testler | `tests/test_smart_reports.py`, `tests/test_smart_dashboard.py`, `tests/browser/new-surfaces.cjs` (5 tema axe taraması) |

## İlham alınan raporlama araçları

| Araç | Aldığımız fikir |
| --- | --- |
| Power BI (rapor + paginated) | Rapor geneli dilimleyici (filtre), KPI kartı, sayfa bazlı düzen, abonelik/zamanlama |
| Tableau | Hazır şablonla başlama, öğeyi sürükle-bırak, hızlı yerleşim (tam/yarı genişlik) |
| Looker Studio | Sayfa üstü marka başlığı, logo/görsel ve metin öğeleri, sayfa çoğaltma |
| Grafana (rapor) | Panel bazında zaman aralığı geçersiz kılma, değişkenle tekrar (host başına) |
| SSRS / Crystal Reports | Rapor bilgisi kutusu (dönem, oluşturulma, parametreler), alt bilgi metni, kapak |
| Metabase | "Soru"yu hızlı kurma: kelime yaz → seçenekten seç |
| Qlik Sense | Seçimlerin (filtre) raporda görünmesi |
| Zoho Analytics / Domo | Yönetici özeti ve kapasite şablonları, tek tık e-posta zamanlama |
| Figma / Canva | Geri al-yinele, klavye kısayolları, ok tuşlarıyla kaydırma, yakınlaştırma |

## Yeni yetenekler

### Şablonlar
`/smart` sayfası şablon galerisi gösterir: **Boş sayfa, Yönetici özeti, Host sağlık raporu, Ağ ve
erişilebilirlik, Kapasite planlama**. Şablon küçük resmi gerçek yerleşimi çizer. Şablon panelleri anahtar
kelime ile tanımlıdır (ör. `/CPU utilization/i`), KPI kartları tek seri (ortalama / en yüksek) kullanır.

### Sayfa öğeleri
| Tür | Ne yapar |
| --- | --- |
| `image` | Logo veya görsel (PNG/JPEG/WebP/GIF ≤ 1 MB, sunucuda doğrulanıp PNG'ye çevrilir). Boş bırakılırsa rapor logosu basılır. |
| `divider` | Bölüm başlığı + çizgi (marka gradyanı / düz / ince). Başlıkta `$host` gibi değişkenler. |
| `reportinfo` | Rapor dönemi, saat dilimi, oluşturulma, filtre seçimleri ve not. Host bazında PDF'te o bölümün hostunu yazar. |
| `text` | Markdown metin (önceden vardı). |

Bu türler sorgu çalıştırmaz (`NO_QUERY_TYPES`), Excel/CSV'de atlanır, PDF'te `layout_pdf.draw` ile çizilir.

### Marka
Rapor ayarlarında **logo** (sayfa başında; isteğe bağlı her sayfada), **alt bilgi metni** ve **kapak**.
Logo kaydedilmiş raporlarda da kullanılır (rapor kendi logosunu seçmediyse).

### Rapor filtresi ve host bazında PDF
"Grup / host seçimi rapor genelinde olsun" açıldığında `group` ve `host` değişkenleri oluşturulur, sayfanın
üstünde seçiciler çıkar ve paneller `$group` / `$host` kullanır (anahtar kelime penceresinde "Rapor
filtresini kullan"). **İndir → PDF · her host için ayrı sayfalar** `split_by=host` ile her host için akıllı
sayfaları yeniden basar; sayfa başında "Host: …" yazar, bölüm başlığı yerleşimi kaydırmaz.

### Panel bazında tarih aralığı
Her grafik kendi dönemini taşıyabilir: `panel.timeRange = {from, to}` — göreli (`now-1y`, `now/y`,
`now-1M/M` …) veya mutlak tarih. Örnek: 24 saatlik bir raporda "Arayüz trafiği · son 1 yıl".
- Denetçide **Rapor aralığı / Panele özel** seçimi, hızlı seçenekler (son 7/30/90 gün, 6 ay, 1 yıl, bu yıl,
  geçen yıl, geçen ay) ve takvimli seçici.
- Panel başlığında ve panel üstündeki çipte dönem yazar; PDF'te başlığın sağında tarih aralığı basılır.
- Göreli dönemler **raporun bitiş anına** göre hesaplanır: geçmiş bir dönem için üretilen zamanlanmış rapor,
  render anına değil o döneme göre "son 1 yıl"ı gösterir.
- Sunucu kayıtta dönemi doğrular (çözümlenemeyen veya bitişi başlangıçtan önce olan aralık reddedilir).

### Panel stilleri
Birim, ondalık, gösterilen değer (son/ortalama/en yüksek/en düşük/toplam), **seriler** (ayrı ayrı veya tek
seri: ortalama/toplam/en yüksek/en düşük → `averageSeries` vb.), renk eşikleri (hazır: yüksek kötü 70/90,
düşük kötü 30/10; değerler düzenlenebilir), stat renk kullanımı, açıklama (liste/tablo/gizli).

### Düzenleme verimliliği
- **Geri al / yinele** (100 adım), **Ctrl+Z / Ctrl+Y**, **Ctrl+D** çoğalt, **Delete** sil, ok tuşları (Shift ile
  4 hücre) kaydır, **Ctrl+S** kaydet, **Esc** seçimi kaldır.
- **Taslak kurtarma:** her değişiklik tarayıcıda taslak olarak saklanır; sekme kapanırsa bir sonraki açılışta
  "Taslağı geri yükle" önerilir.
- Kaydetme durumu ("Kaydedildi · 2 dk önce" / "Kaydedilmemiş değişiklikler").
- Yakınlaştırma (sığdır, %75–150), sayfa araçları (yukarı/aşağı taşı, çoğalt, sil), hızlı yerleşim
  (tam genişlik, sol/sağ yarı, üçte bir, ortala, yükselt/alçalt).
- **Önizle** gerçek PDF'i yeni sekmede açar; **Zamanla** rapor sayfasına bu dashboard seçili gider.

## Bu çalışmada bulunan ve düzeltilen hatalar

- **Regex zaman aşımı:** kullanıcı regex'lerinin 50 ms duvar-saati sınırı, eşzamanlı sorgularda basit
  desenlerde bile "çok karmaşık" hatası veriyordu. Sınır 250 ms, bir kez yeniden deneme ve
  `concurrent=True` (eşleşme sırasında GIL bırakılır). Felaket desenler yine reddedilir.
- **Dışa aktarma `split_by`:** alan yanlış modele eklenmişti (500); `DashboardExportIn`'e taşındı.
- **Kâğıt üzerinde renkler:** stat/tablo/çubuk gösterge renkleri belge temasından okunuyordu; artık panelin
  kendi yüzeyinden okunur (koyu temada açık kâğıt).
- **Etiket renkleri:** 12 tonun bazıları beyaz yazıyla 4.5:1 altındaydı; marka uyumlu, hepsi AA geçen yeni palet.
- **Durum ızgarası:** kaydırılabilir alan klavyeyle odaklanabilir.

## Dönüştürme ve Keşfet'ten gönderme (sonradan eklendi)

- **Normal dashboard → akıllı rapor:** dashboard menüsündeki "Akıllı rapora dönüştür" panelleri yatay A4
  sayfalara yerleştirir (`layoutFromGrid`): sütun ve genişlik korunur, ızgara sayfa yüksekliğinde bantlara
  bölünür, sayfadan uzun paneller kısaltılır, çakışmalar ilk boş yere taşınır, satır başlıkları bölüm
  ayırıcısına dönüşür. Kaydedilene kadar orijinal dashboard değişmez; kaydedilen her sürüm geçmişte kalır.
- **Keşfet → akıllı rapor:** Keşfet'teki "Akıllı rapora ekle" sorguyu, görünümü ve Keşfet'te seçilen zaman
  aralığını (panelin kendi dönemi olarak) yeni bir akıllı dashboard'un ilk öğesi yapar.
