# Veri kaynakları ve yeni görselleştirmeler

Mevcut oluşturma akışı korunur. Veri kaynağı yönetimindeki tür seçicisinden kaynak, panel editöründeki mevcut görselleştirme seçicisinden grafik seçilir. Seçeneklerde ara alanı grafik adlarını da süzer.

## Kaynaklar

Mevcut Zabbix, PostgreSQL/TimescaleDB ve TestData yanında dört seçenek vardır:

| Kaynak | Bağlantı | Sorgu |
|---|---|---|
| Prometheus | Sunucu kök URL, isteğe bağlı Bearer token/CA | PromQL, zaman aralığı ve adım otomatik |
| Loki | Sunucu kök URL, isteğe bağlı Bearer token/CA | LogQL; log tablosu veya metrik serisi |
| HTTP JSON | Tam uç nokta URL, isteğe bağlı token/CA | Nesne listesi; gerekirse data.items gibi kök alanı |
| HTTP CSV | Tam uç nokta URL, isteğe bağlı token/CA | Başlık satırlı UTF-8 CSV tablosu |

Prometheus sorguları [resmî query_range API](https://prometheus.io/docs/prometheus/latest/querying/api/), Loki sorguları [resmî Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/) üzerinden GET ile okunur. Prometheus uyumlu Mimir/VictoriaMetrics uç noktaları da aynı protokolle kullanılabilir; bütün dağıtım seçenekleri ayrı ayrı canlı test edilmedi.

HTTP kaynaklarında HTTPS doğrulaması açıktır; özel CA verilebilir. Yönlendirme izlenmez, yanıt 8 MB ile sınırlandırılır, metadata/link-local ağ adresleri engellenir. İç ağ kaynakları için adminin kaydettiği host kullanılabilir. Sorgu kullanıcısı adres veya yolu değiştiremez. HTTP yalnız sunucu yöneticisinin OPENREPORTING_ALLOW_HTTP_DATASOURCES seçeneğiyle açılır. Parolalar URL'de tutulmaz; Bearer token şifreli saklanır.

PromQL/LogQL değişkenleri çift tırnaklı etiket değerleri içinde kullanılmalıdır: `up{job=~"$job"}`. Değerler regex ve tırnak kaçışından geçer. İlk sürümde otomatik metrik/etiket keşfi ve tenant başlıkları yoktur. JSON/CSV kaynakları tablolar döndürür; dönüşümlerle alan seçilebilir. Satır/nokta sınırına erişim açık hata verir; eksik sayısal değer sıfır yapılmaz.

## Eklenen 20 seçenek (toplam 30)

| Görselleştirme | Girdi |
|---|---|
| Isı haritası | Zaman serileri; boş noktalar boş kalır |
| Histogram | Sayısal örnekler; 1–50 aralık |
| XY dağılım | En az iki sayısal tablo sütunu |
| Balon grafik | İlk iki sayısal sütun X/Y, üçüncüsü büyüklük; üçüncü yoksa sabit boy |
| Kutu grafiği | Seri veya sayısal tablo sütunları; min/Q1/medyan/Q3/max |
| Mum grafiği | İlk dört sayısal sütun: açılış, kapanış, düşük, yüksek |
| Radar | İndirgenmiş seri/sütun değerleri |
| Huni | Negatif olmayan indirgenmiş değerler |
| Ağaç haritası | Negatif olmayan indirgenmiş değerler |
| Hiyerarşi halkası | İlk seri etiketine göre grup ve alt değerler |
| Sankey akışı | source, target, value sütunları; döngüler reddedilir |
| Bağlantı grafiği | source, target, value sütunları |
| Takvim ısı haritası | UTC gününe göre örnek ortalaması |
| Şelale | İşaretli indirgenmiş değerlerin kümülatif adımları |
| Kutupsal çubuk | İndirgenmiş değerler |
| Paralel koordinatlar | En az iki sayısal tablo sütunu |
| Halka grafik | Negatif olmayan indirgenmiş değerler |
| Gül grafiği | Negatif olmayan indirgenmiş değerler |
| Yığılmış alan | Zaman serileri |
| Basamak grafiği | Zaman serileri |

Uygun sütun yoksa açıklama gösterilir; örnek koordinat/bağlantı uydurulmaz. Yeni grafiklerde 100.000 satır/nokta üstünde sorgunun daraltılması istenir; sessiz veri kırpılmaz.

## Raporlar

Excel ve CSV bütün yeni panel türlerinin sorgu verisini aynı aktarım hattıyla içerir. PDF'de halka, basamak, yığılmış alan, histogram, XY dağılım, balon, kutu ve mum grafikleri vektör çizilir. Diğer 12 yeni tür PDF'de açıkça **Grafik verisi · tablo görünümü** etiketiyle veriyi sunar; ekran görüntüsüyle birebir çizim iddia edilmez. Özel grafiklerin tam vektör PDF karşılıkları sonraki geliştirmedir.

## Veri geçişi

Şema v2 yalnız veri kaynağı tür kısıtını genişletir. SQLite geçişi atomik tablo kopyalama, PostgreSQL geçişi CHECK kısıtı değişimi yapar. Kayıtlı UID, şifreli alanlar ve denetim zinciri korunur. v2 ile açılmış bir veritabanını eski v1 koduyla açmayın; geri dönüş için yükseltme öncesi yedeği kullanın.
