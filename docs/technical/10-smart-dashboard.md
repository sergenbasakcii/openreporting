# 10 · Akıllı dashboard (canlı PDF sayfası üzerinde sürükle-bırak)

| | |
| --- | --- |
| Durum | Uygulandı |
| Sunucu | `smart_layout.py` (doğrulama, PDF yerleşimi), `dashboards.normalize` → `smart_layout.normalize`, `reporting/pdf.plan_grid` / `render_pdf` |
| Tarayıcı | `pages/smart.js` (liste + oluşturucu), `smart/canvas.js` (sayfa tuvali), `smart/keywords.js` (anahtar kelime / drill-down) |
| Testler | `tests/test_smart_dashboard.py`; tarayıcıda uçtan uca deneme (sürükle, seç, kaydet, PDF) |

## Amaç

Teknik sorgu bilgisi olmadan, birkaç dakikada rapora hazır bir dashboard kurmak. Kullanıcı A4/A3/Letter
sayfası görür, soldaki görselleştirmeleri sayfaya sürükler, panelin üstündeki **Grup · Host · Anahtar kelime**
kutularına tıklayıp açılan pencereden seçim yapar; paneller canlı veriyle hemen çizilir; **PDF indir** ekranda
görüleni birebir basar.

## Veri modeli

Akıllı dashboard normal bir dashboard'dur (izinler, sürümler, raporlar, zamanlamalar aynen çalışır):

```json
{
  "tags": ["akıllı"],
  "smart": {"version": 1, "paper": "A4", "orientation": "portrait", "rows": 32, "pages": 2, "cover": false, "subtitle": ""},
  "panels": [{"type": "stat", "smartPos": {"page": 0, "x": 0, "y": 0, "w": 6, "h": 5}, "gridPos": {"x": 0, "y": 0, "w": 6, "h": 5}}]
}
```

- Sayfa 24 sütun × `rows` satırdır (dikey 32, yatay 20). `gridPos`, `smartPos`'tan türetilir
  (`y = page × rows + y`), bu yüzden aynı dashboard normal görünümde de açılır.
- Sunucu her kayıtta değerleri sınırlar (`smart_layout.normalize`): geçersiz kâğıt → A4, taşan konum içeri
  çekilir, bozuk `smartPos` varsayılana döner, en fazla 50 sayfa.

## PDF ile birebir eşleşme

Tuval, reportlab sayfasının aynı geometrisini kullanır: kenar boşluğu 26 pt, başlık bandı 30 pt, alt bilgi
16 pt. Paneller yüzde ile konumlanır, böylece pencere boyutu değişse de oran korunur. PDF tarafında
`plan_grid`, akıllı dashboard'larda her paneli kendi sayfasına ve hücresine yerleştirir
(`smart_layout.plan`); kâğıt, yön ve kapak ayarı dışa aktarma varsayılanlarını geçersiz kılar
(`report_overrides`). Planlanmış raporlar da aynı düzeni kullanır.

Tuvaldeki sayfalar uygulama teması ne olursa olsun **Porselen** (açık) temasında çizilir; grafik renkleri
artık `chartTheme(container)` ile panelin bulunduğu alt ağaçtan okunur.

## Anahtar kelime ve drill-down

Zabbix ve TestData kaynaklarında her panelin üstünde üç kutu bulunur:

1. **Grup** → kaynaktaki host grupları
2. **Host** → seçilen gruptaki hostlar
3. **Anahtar kelime** → seçilen host(lar)daki item'lar

Pencerede arama kutusu listeyi daraltır; yazılan kelime için "“kelime” içeren tümü" seçeneği büyük/küçük harf
duyarsız bir regex'e (`/kelime/i`) dönüşür; listeden bir seçenek tam eşleşme olur. Bir metrik seçilene kadar
panel sorgu çalıştırmaz (tüm hostların tüm item'larını çekmek anlamsız ve pahalıdır) ve bir ipucu gösterir.
Başlık, seçimden otomatik üretilir ("cpu · srv-web-01"); kullanıcı başlığı değiştirirse kilitlenir.
Diğer kaynaklarda (Prometheus, SQL, veri gölü …) "Sorgu" düğmesi o kaynağın normal sorgu editörünü açar.

## Etkileşim

- Sürükle-bırak (HTML5) veya tıklayarak ekleme; ilk boş yere yerleşir, sayfa doluysa yeni sayfa açılır.
- Taşıma: sol üst tutamaç (sayfalar arası da); boyutlandırma: sağ alt köşe; dolu alana bırakılan panel geri döner.
- Sağ panel: sayfa ayarları (başlık, alt başlık, varsayılan kaynak, kâğıt, yön, sayfa ekle/kaldır) veya seçili
  panelin ayarları (başlık, görselleştirme, veri kaynağı, birim, gelişmiş sorgu, metin).
- Yön değiştirildiğinde panel yükseklik/konumları yeni satır sayısına orantılanır.
- PDF / Excel indirme önce kaydeder. Normal dashboard menüsünde "Akıllı düzenleyicide aç" bulunur.

## PDF iyileştirmesi (bu çalışmada)

Stat panelinde değer sayısı okunabilir hücre kapasitesini (64×34 pt) aşınca değerler üst üste basılıyordu.
Artık sığan kadar gösterilir, son hücre "+N değer daha · tam liste Excel/CSV'de" yazar.
