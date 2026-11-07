# 15 — Uçtan uca tarama ve düzeltmeler (7 Kasım 2026)

## Nasıl tarandı

Geçici, ayrı bir kopyada (kendi veri klasörü, MFA kapalı test yöneticisi) başsız Chromium ile:

| Tarama | Kapsam |
| --- | --- |
| Rota taraması | 20 sayfa: sayfa/konsol hataları, 4xx/5xx istekleri, ekranda görünen `null`/`undefined`/`NaN` metni, yatay taşma |
| İçerik taraması | Örnek dashboard'lar, panel düzenleyicileri, 3 biçimde dışa aktarma (PDF/Excel/CSV), 5 akıllı dashboard şablonu |
| Tıklama taraması | Rapor PDF/Excel önizleme, "Şimdi çalıştır", akıllı dashboard kaydet/önizle, Keşfet sorgusu, Ctrl+S |
| Bulanık test | Tüm dönüşüm ve ifade türleri: bozuk seçenekler, metin hücreleri, boş girdiler |
| Mevcut setler | pytest (517), node testleri (23), axe erişilebilirlik ve tema setleri (5 tema) |

## Bulunan ve düzeltilen hatalar

| # | Hata | Düzeltme |
| --- | --- | --- |
| 1 | **Veri gölü kaynağı bulunamıyordu.** Tür seçimi 13 seçenekli düz bir menüydü; liste sayfasının açıklaması hâlâ "Zabbix, PostgreSQL, Prometheus, Loki, HTTP JSON/CSV" diyordu. | "Yeni veri kaynağı" artık kategorili ve aranabilir bir tür seçicisiyle açılıyor (İzleme, SQL, **Veri gölü / Lakehouse**, Log, HTTP, Test). "datalake", "s3", "iceberg", "veri golu" gibi kelimeler Trino/Databricks'i buluyor. Açıklama türlerden üretiliyor; listede tür kodu yerine adı gösteriliyor; "provisioned" → "otomatik". |
| 2 | Akıllı dashboard düzenleyicisinde "Grup · Host · Anahtar kelime" çubukları ve araç düğmeleri tüm panellerde aynı anda duruyor; küçük KPI panellerinde değerler görünmüyordu. | Çubuk panelin üstünde yüzen bir araç çubuğu oldu; yalnız fareyle üzerine gelince, seçilince, klavyeyle odaklanınca veya metrik henüz seçilmemişse görünür. Sağ yarıdaki paneller çubuğu sola doğru açar. |
| 3 | Dönüşüm hataları: metin sütunuyla hesaplama, sayı olmayan satır sınırı, geçersiz hesaplama türü, bozuk seçenek yapısı. Bozuk seçenek yapısı (`AttributeError`) sorgu isteğinin tamamını 500 ile düşürüyordu. | Metin/boş hücreler hesapta boş sayılır; geçersiz seçenekler açık Türkçe mesaj verir ("Satır sınırı bir sayı olmalı", "Bilinmeyen hesaplama: …"); `AttributeError` da yakalanır. 11 regresyon testi eklendi. |
| 4 | Rapor düzenleme ekranında logo alanının altında "null" yazısı. | Yerel `replaceChildren()` null'u metin olarak basıyordu; null çocuklar ayıklanıyor. |
| 5 | E-posta kapalı uyarısı `/etc/openreporting/openreporting.env` dosyasını düzenlemeyi söylüyordu (Docker'da yanlış). | Uyarı "Yönetim → Sistem ayarları → E-posta" yolunu gösteriyor; sunucu durumu rozeti de öyle. |
| 6 | Küçük logo kutusunda yer tutucu metin kesiliyordu. | "Görsel yok" + ipucu. |
| 7 | PostgreSQL açıklamasında "Grafana makroları". | "zaman makroları". |
| 8 | README/kılavuz başlığı 1.0, README girişi "Grafana benzeri", tehdit modeli "yedi kaynak". | 1.1, güncel kaynak listesi, "on üç tür". |
| 10 | **Yükseltmeden sonra 502.** Web konteyneri yeniden oluşturulunca (`--build`, `kurulum.sh guncelle`) yeni iç IP alıyor, nginx eski IP'ye bağlanmaya devam ediyordu. | Web'e sabit iç IP (`OPENREPORTING_WEB_IP`, 172.30.88.11). CI web'i yeniden oluşturup proxy üzerinden sağlığı doğruluyor. |
| 9 | `tests/browser/theme-surfaces.cjs` tema sistemi öncesinden kalmıştı (`data-theme=dark/light`); açılır menüsüz bir dashboard'la çalıştığı için bunu hiç fark etmemişti. | Gerçek temalara (Aurora/Porselen, `data-scheme`), yeni tür seçicisine ve profil tema kartlarına uyarlandı; PDF önizleme penceresi açılış rengini sabit RGB yerine açan sayfanın arka planıyla karşılaştırıyor. |

## Sorun olmadığı doğrulananlar

İki sekmeyle çalışmak: CSRF belirteci her sayfa açılışında yenilense de istemci 403'te belirteci yenileyip isteği
bir kez tekrarlar (taramadaki 403'ler tarama betiğinin eski belirtecindendi). İfade türlerinde (math/reduce/resample)
bulanık testte çökme yok. Örnek dashboard'larda, ilk 12 panel düzenleyicisinde ve 5 şablonda panel hatası yok; tüm
dışa aktarmalar geçerli dosya üretiyor.

## API değişikliği

`GET /api/datasources/types` yanıtına `categories` listesi; her türe `category` ve `keywords` alanları eklendi
(geriye dönük uyumlu: var olan alanlar değişmedi).
