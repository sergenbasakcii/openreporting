# OpenReporting 1.1 — Kullanım Kılavuzu

## 1. Roller

| Rol | Yetki |
| --- | --- |
| İzleyici (viewer) | Kayıtlı dashboard’ları görüntüleme, rapor arşivini indirme, dashboard’u PDF/Excel indirme |
| Editör (editor) | + Keşfet (serbest sorgu), dashboard / klasör / rapor oluşturma ve düzenleme, anlık rapor çalıştırma, pasif zamanlama |
| Yönetici (admin) | Her şey + veri kaynakları, kullanıcılar, zamanlamayı etkinleştirme, sunucu durumu |

## 2. Dashboard

- **Yeni dashboard**: *Dashboard’lar → Yeni dashboard → Ekle → görselleştirme*. Panel başlığından sürükleyerek taşıyın,
  sağ alt köşeden boyutlandırın. **Kaydet** (Ctrl+S) her kayıtta yeni sürüm oluşturur; *Ayarlar → Sürümler* ile geri dönün. **Değişiklikleri gör** o sürümden bu yana neyin değiştiğini (panel sorgusu, değişken, eşik, başlık…) okunur biçimde listeler — değişen bir raporun zamanlamasını yeniden onaylamadan önce kullanın.
- **Satırlar**: *Ekle → Satır*. Başlığa tıklayarak daraltın; satır ayarlarından “değişkene göre tekrarla” seçilirse
  satır ve altındaki paneller her değer (ör. her host) için çoğaltılır.
- **Panel tekrarı**: Panel düzenleyici → *Panel seçenekleri → Değişkene göre tekrarla* → `host`. Yön (yatay/dikey) ve satır başına adet seçilebilir.
- **Zaman**: sağ üstteki zaman seçici (Son 6 saat, Dün, Geçen hafta, mutlak aralık), ok tuşlarıyla kaydırma, büyüteçle
  uzaklaştırma. Zaman serisi grafiğinde **fareyle bir aralık seçmek** yakınlaştırır. Otomatik yenileme menüden seçilir.
- **Paylaşım**: Panel menüsü → *Bağlantı paylaş* veya dashboard menüsü → *Paylaş*; URL zaman aralığını ve değişkenleri taşır
  (`?from=now-24h&to=now&var-host=srv-01`). *TV / kiosk modu* menüleri gizler (Esc ile çıkış).
- **İçe/dışa aktarma**: *Dashboard’lar → İçe aktar* Grafana JSON’unu kabul eder (eski `graph`/`singlestat` panelleri dönüştürülür,
  Zabbix eklentisi sorguları aynen çalışır). Dashboard menüsü → *JSON dışa aktar*.

## 3. Zabbix sorguları (grup bazlı metrik)

Panel düzenleyicide *Sorgular* sekmesi:

| Alan | Örnek | Açıklama |
| --- | --- | --- |
| Grup | `Linux servers`, `/^Network/`, `$group` | Host grubu (tam ad, `*` joker veya `/regex/`) |
| Host | `/.*/`, `srv-web-*`, `$host` | Gruptaki hostlar |
| Etiket | `component: cpu`, `interface` | Item etiketi (Zabbix 5.4+; eski sürümlerde uygulama) |
| Item | `CPU utilization`, `/Bits (received|sent)/` | Item adı veya anahtarı |

*Sorgu türü*: **Metrikler** (zaman serisi), **Son değerler** (tablo; grubun anlık durumu için hızlıdır),
**Item ID**, **Aktif problemler** (önem filtresiyle). *Veri* seçeneği: Otomatik (aralık uzunsa trend), Ham history, Trend.

Çoklu seçilen değişkenler otomatik olarak `/^(?:a|b)$/` regex’ine dönüştürülür.

### Fonksiyonlar (sıralı uygulanır)

| Fonksiyon | Kullanım |
| --- | --- |
| `aggregateBy(5m, avg)` | Gruptaki tüm hostları **tek seriye** indirger (grup ortalaması / toplamı / max) |
| `groupByLabel(group, avg)` | Serileri etikete göre birleştirir (ör. grup başına ortalama) |
| `sumSeries()`, `averageSeries()`, `maxSeries()` | Kova bazında toplulaştırma |
| `percentileAgg(1h, 95)` | Grup 95. yüzdelik |
| `top(5, mean)`, `bottom(5, max)` | En yüksek/düşük N host |
| `filterSeries(max, >, 80)` | Koşulu sağlayan seriler (ör. eşiği aşan hostlar) |
| `groupBy(1h, avg)` | Her seriyi zaman aralığında toplulaştırır |
| `scale(8)`, `offset(-1)`, `rate()`, `delta()` | Dönüşümler (bayt→bit, sayaç→hız) |
| `movingAverage(5)`, `percentile(1h, 95)` | Yumuşatma ve yüzdelik |
| `setAlias({{host}})`, `replaceAlias(/(.*):(.*)/, $2)` | Seri adı (`{{host}}`, `{{item}}`, `{{group}}`, `$__zbx_host_name`) |
| `timeShift(1d)` | Dünkü veriyi bugüne hizalar (karşılaştırma) |
| `trendValue(max)` | Trend sorgusunda min/avg/max sütunu |

### İfadeler

*İfade ekle* → `Matematik`: `$A / $B * 100`, `abs($A - $B)`, `$A > 80`. Çok serili sorgular host etiketine göre eşleşir;
tek seri tüm serilere uygulanır. Ara sorguları gizlemek için göz ikonunu kullanın.
`Tek değere indir` (reduce) ve `Yeniden örnekle` (resample) türleri de vardır.

### Dönüşümler (*Dönüşümler* sekmesi)

- **Etikete göre matris (host × metrik)**: satır = host, sütun = item, hücre = ortalama/max/son… → **grup özet tablosu**.
- **Seriyi tek değere indir**: her seri bir satır (Ortalama, En yüksek, Son değer…), etiketler sütun olur.
- **Zamana göre birleştir**, **Serileri satırlara çevir**, **Sırala**, **Satır sınırı**, **Hesaplanan sütun** (satır toplamı, `A / B`),
  **Sütunları düzenle**, **Ada/sorguya göre filtrele**, **Gruplama matrisi**.

## 4. PostgreSQL / TimescaleDB sorguları

```sql
SELECT $__unixEpochGroupAlias(clock, $__interval), avg(value) AS "CPU"
FROM history WHERE itemid IN ($items) AND $__unixEpochFilter(clock)
GROUP BY 1 ORDER BY 1
```

Zaman serisi biçiminde `time` sütunu (+ isteğe bağlı `metric` sütunu) döndürün. Makrolar: `$__timeFilter(ts)`,
`$__timeGroupAlias(ts, 5m)`, `$__unixEpochFilter(clock)`, `$__unixEpochGroupAlias(clock, 1h)`, `$__timeFrom()`, `$__timeTo()`,
`$__interval`, `$__interval_s`. Değişkenler SQL’e varsayılan olarak tırnaklı/kaçışlı (`'a','b'`) girer; ham değer için `${var:raw}`.

## 5. Değişkenler

*Dashboard ayarları → Değişkenler → Değişken ekle*:

- **Sorgu**: veri kaynağı + tür (Host grubu / Host / Item / Item etiketi) + filtreler. Örn. `group` = tüm gruplar;
  `host` = `Grup filtresi: $group` (zincirleme). Metin sorgusu da desteklenir: `{Linux servers}{*}`.
- **Özel liste**: `Üretim : prod, Test : test`. **Metin kutusu**, **Sabit** (gizli), **Aralık** (`1m,5m,1h`), **Veri kaynağı**.
- *Çoklu seçim*, *“Tümü” seçeneği*, *Regex* (`/^srv-(.*)$/` yakalama grubu), *Sıralama*, *Yenile: zaman değişince*.
- Panel başlıklarında da kullanılabilir: `CPU · $host`.

## 6. Raporlar (grup bazlı)

1. *Raporlar → Yeni rapor* (veya dashboard menüsü → *Bu dashboard’dan rapor oluştur*).
2. **Zaman aralığı**: Dün / Geçen hafta / Geçen ay / Son N … veya **Takvim** düğmesiyle başlangıç ve bitiş gününe tıklayarak
   sabit bir aralık (ör. 1–15 Kasım). Göreli ifade de yazılabilir (`now-1M/M` → `now-1M/M` = geçen takvim ayı).
3. **Değişken değerleri**: rapor için sabitleyin (ör. Host grubu = WAN Routers, Host = Tümü).
4. **Grup bazlı bölümleme**: `$host` seçilirse gruptaki **her host için başlıklı bir bölüm** ve kapakta içindekiler üretilir.
   Bağımlı değişkenler her bölüm için yeniden çözülür.
5. **Paneller**: tamamı veya seçilenler. **Düzen**: dashboard ızgarası (birebir) veya akış (her panel tam genişlik, uzun tablolar sayfalara bölünür).
6. **Biçimler**: PDF (vektör grafik), Excel (her panel ayrı sayfa, tüm satırlar), CSV (uzun format).
7. **PDF önizle / Excel önizle** ile ilk 3 bölümü anında görün; **Kaydet**, sonra **Şimdi çalıştır** veya **Zamanlama ekle**.

Zamanlama: Saatlik / Günlük / Haftalık (gün) / Aylık (ayın günü) / Yıllık; rapor dönemi varsayılan olarak **önceki tam dönemdir**
(günlük → dün 00:00–24:00, haftalık → geçen Pazartesi–Pazartesi, aylık → geçen ay). Kesinti sonrası kaçırılan pencereler toplu
olarak tekrar çalıştırılmaz.

**Kısmi veri**: Bir panelde sorgu hatası veya `NO DATA` varsa çalıştırma “Kısmi veri” olarak işaretlenir, PDF kapağında
uyarı kutusu çıkar ve (rapor ayarında aksi belirtilmedikçe) e-posta gönderilmez.

Arşivdeki her dosya indirilirken manifest SHA-256 özeti ve denetim zinciriyle doğrulanır.

### Rapor hatası bildirimleri

Bir rapor çalışması başarısız olduğunda, e-postası gönderilemediğinde veya teslimi belirsiz kaldığında,
ya da zamanlama kendini kapattığında (rapor/dashboard onaydan sonra değişti, onaylayan yöneticinin
yetkisi kalmadı, hata, servis kesintisi nedeniyle atlanan çalışma) ilgili kişilere e-posta gider:
raporun sahibi ile zamanlamayı oluşturan ve onaylayan yönetici. Yalnız etkin, e-posta adresi tanımlı,
izinli alan adında olan ve raporu hâlâ açabilen kullanıcılar bildirim alır; e-postada rapor verisi
bulunmaz, yalnız rapor adı, olay ve bağlantı vardır. **Profil → Tercihler** bölümünden kapatılabilir.
Son 30 günün olayları SMTP kapalı olsa da **Raporlar** sayfasının üstünde listelenir.

## 7. Yönetim ayarları (yönetici)

- **Sistem ayarları**: E-posta (SMTP), LDAP / Active Directory, Güvenlik, Sorgu ve rapor sınırları,
  Veri kaynağı politikası sekmeleri. Değiştirdiğiniz alanlar **Kaydet** ile mevcut parolanız sorularak
  kaydedilir ve birkaç saniye içinde geçerli olur. **Bağlantıyı test et** formdaki değerleri kaydetmeden
  dener (SMTP'de e-posta gönderilmez). Parolalar kayıtlı olsa da gösterilmez; değiştirmek için yenisini yazın.
  *Sunucu* sekmesi yalnız sunucu dosyasından değişen ayarları gösterir.
- **Kullanıcılar**: ekleme, rol, devre dışı bırakma, parola sıfırlama ve telefonunu kaybeden kullanıcı için
  **İki adımlı girişi sıfırla**.
- **Profil** (herkes): tema (Aurora, Porselen, Grafit, Kum, Yüksek kontrast, Sistem), saat dilimi, ana sayfa, kendi parolanızı değiştirme ve iki adımlı giriş.

## 8. Akıllı dashboard (hızlı rapor)

Teknik sorgu bilgisi gerektirmeden rapora hazır sayfalar hazırlamak için **Akıllı dashboard** menüsünü
kullanın.

1. **Şablon seçin:** Boş sayfa, Yönetici özeti, Host sağlık raporu, Ağ ve erişilebilirlik, Kapasite planlama.
2. **Öğe ekleyin:** soldaki listeden grafiği sayfaya sürükleyin veya tıklayın. Sayfa öğeleri: metin, logo /
   görsel, ayırıcı (bölüm başlığı), rapor bilgisi, **akıllı özet** (veriden otomatik cümleler).
3. **Ne gösterileceğini seçin:** panelin üstündeki **Grup · Host · Anahtar kelime** kutularına tıklayın.
   Listeden seçebilir veya bir kelime yazıp "… içeren tümü"nü seçebilirsiniz. Anahtar kelime seçilene kadar
   panel sorgu çalıştırmaz.
4. **Ayarlayın (sağ panel):** birim, ondalık, gösterilen değer (son / ortalama / en yüksek …), **tek seri**
   (KPI için ortalama/toplam), renk eşikleri, **en yüksek / en düşük N**, **önceki dönemle karşılaştırma**
   (▲/▼ yüzde), **panele özel tarih aralığı** (ör. 24 saatlik raporda "son 1 yıl"), grafik altı **açıklama**.
5. **Rapor ayarları:** başlık, alt başlık, logo (sayfa başında), alt bilgi, kapak, **filigran** (GİZLİ, TASLAK
   …), kâğıt ve yön, **rapor filtresi** (Grup / Host seçimi tüm grafikleri birlikte değiştirir).
6. **Çıktı:** *Önizle* gerçek PDF'i açar; *İndir* → PDF, **her host için ayrı sayfalar**, Excel, CSV;
   *Zamanla* raporu e-postayla düzenli gönderir.

Düzenleme: tutamaçtan sürükleyerek taşıyın, sağ alt köşeden boyutlandırın; ok tuşları kaydırır (Shift ile 4
hücre), Ctrl+D çoğaltır, Delete siler, Ctrl+Z / Ctrl+Y geri alır / yineler. Sayfa araçları: yukarı / aşağı
taşı, **otomatik düzenle**, çoğalt, sil. Kaydedilmemiş çalışma tarayıcıda taslak olarak tutulur.

Normal bir dashboard'u **⋮ → Akıllı rapora dönüştür** ile sayfalara yerleştirebilir; Keşfet'te bulduğunuz bir
grafiği **Akıllı rapora ekle** ile yeni bir rapora gönderebilirsiniz.

## 9. Takımlar ve izinler (yönetici)

- **Yönetim → Takımlar:** kullanıcıları gruplayın (ör. NOC ekibi, Finans).
- **Klasör menüsü → Klasör izinleri:** klasörü kısıtlayıp takımlara veya kişilere *Görüntüleme* / *Düzenleme*
  verin.
- **Dashboard → ⋮ → İzinler:** tek bir dashboard'u yalnız seçilen takım ve kişilere açın; kısıtlı bir klasördeki
  tek dashboard'u bir ekiple paylaşmak için de kullanılır. Düzenleme için kullanıcının rolü de editör olmalıdır.

## 10. Veri kaynakları

Zabbix, PostgreSQL/TimescaleDB, Prometheus/Mimir/VictoriaMetrics, Loki, HTTP JSON/CSV ve TestData'ya ek olarak:
**veri gölü (Trino / Presto / Starburst)**, **Databricks SQL**, **ClickHouse**, **Elasticsearch / OpenSearch**,
**InfluxDB**, **Graphite**. Tüm bağlantılar salt-okunurdur; HTTPS ve sertifika doğrulaması zorunludur.
Her kaynak için yalnız okuma yetkili bir hesap kullanın.

**Ekleme:** Yönetim → Veri kaynakları → **Veri kaynağı ekle**. Türler kategorilere ayrılmıştır (İzleme ve metrik, SQL,
**Veri gölü / Lakehouse**, Log ve arama, HTTP / dosya, Test); üstteki kutuya "veri gölü", "s3", "iceberg", "postgres" gibi
bir kelime yazarak arayabilirsiniz. Türü seçince bağlantı formu açılır; **Oluştur ve test et** bağlantıyı dener.

## 11. Arama ve kısayollar

Her sayfada **Ctrl+K** (veya üstteki *Ara…*) komut paletini açar: dashboard, akıllı dashboard, sayfa ve
işlemleri yazarak bulun (Türkçe karakter gerekmez: "yonetici ozet" → "Yönetici özeti"). **?** tuşu tüm
kısayolları gösterir.

## 12. Klavye kısayolları

| Kısayol | İşlem |
| --- | --- |
| Ctrl+S | Dashboard’u kaydet |
| Esc | Panel düzenleyiciden / tek panel görünümünden / kiosk modundan çık |
| Ctrl+Enter | Keşfet’te sorguyu çalıştır |
| Lejantta tıklama | Yalnız bu seriyi göster (Ctrl+tıklama: seriyi aç/kapa) |
| Ctrl+K | Komut paleti (her yerde) |
| ? | Kısayol listesi |
| Ctrl+Z / Ctrl+Y | Akıllı dashboard'da geri al / yinele |
| Ctrl+D, Delete, ok tuşları | Akıllı dashboard'da seçili öğeyi çoğalt, sil, kaydır |
