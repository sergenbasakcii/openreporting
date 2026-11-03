# 05 · Eklenti sistemi (veri kaynağı ve panel eklentileri)

| | |
| --- | --- |
| Durum | Uygulandı (şema 8: `x-` veri kaynağı türleri) |
| Sunucu | `openreporting/plugins.py`, `datasources._validate_plugin`, `web.py` (`/api/plugins`, `/api/admin/plugins`, `/plugins/{id}/…`) |
| Tarayıcı | `static/app/plugins.js`, `panels/registry.js` (`plugin()`), `query/editors.js` (`pluginQueryEditor`), `pages/plugins.js` |
| Örnekler | `examples/datasource-plugin/` (Python paketi), `plugins/examples/x-bullet/` (panel) |
| Testler | `tests/test_plugins.py` |

## İlkeler

1. **Açık izin listesi.** Yalnız `OPENREPORTING_PLUGINS` (virgülle ayrılmış) içindeki eklentiler yüklenir.
   Kurulu ama listede olmayan eklenti "izin listesinde değil" olarak görünür, yüklenmez.
2. **Ad alanı.** Eklenti kimlikleri `x-` ile başlar (`^x-[a-z0-9][a-z0-9-]{1,39}$`); yerleşik türleri asla
   gölgeleyemez. Veritabanı kısıtı da `type LIKE 'x-%'` dışında bilinmeyen türü kabul etmez.
3. **Hata yalıtımı.** Bozuk eklenti atlanır, hatası Yönetim → Eklentiler sayfasında görünür; uygulama açılmaya
   devam eder. Tarayıcıda da bir eklentinin hatası diğerlerini etkilemez.
4. **Veri korunur.** Eklentisi kapatılan paneller dashboard'da silinmez veya dönüştürülmez; arayüz "eklenti yüklü
   değil" uyarısı, PDF "Grafik verisi · tablo görünümü" gösterir.
5. **Güven modeli.** Eklentiler uygulamanın yetkileriyle çalışır (sunucuda Python süreci, tarayıcıda aynı köken).
   Kurulum ve izin listesi işletmeci kararıdır; CSP gevşetilmez (modüller aynı kökenden sunulur).

## Veri kaynağı eklentisi (sunucu)

Python paketi olarak uygulamanın sanal ortamına kurulur ve `openreporting.datasources` giriş noktası grubunu
kullanır. Giriş noktası adı türe eşittir.

```toml
[project.entry-points."openreporting.datasources"]
x-static-table = "openreporting_plugin_static:StaticTableDataSource"
```

```python
from openreporting.datasources.base import DataSource, DataSourceError, QueryResult
from openreporting.frames import table_frame

class StaticTableDataSource(DataSource):
    type = "x-static-table"              # giriş noktası adıyla aynı olmalı
    display_name = "Statik tablo"
    description = "…"
    secure_fields = []                    # şifreli saklanacak alanlar (ör. ["token"])

    @classmethod
    def validate_config(cls, url, json_data, settings):   # isteğe bağlı
        return url, clean_json_data       # hata için DataSourceError

    def query(self, target, ctx):         # ctx: QueryContext (aralık, aralık adımı, değişkenler)
        return QueryResult(frames=[table_frame(self.name, ["a"], [[1]])])

    def health(self):
        return {"status": "ok", "message": "…"}
```

`validate_config` yoksa platform adresin `https://` olmasını ister. Ayarlar 16 KB ile sınırlıdır. Gizli alanlar
diğer veri kaynakları gibi Fernet ile şifrelenir ve tarayıcıya dönmez. Yüklenen sınıf `DataSource` alt sınıfı
değilse veya `type` giriş noktası adıyla aynı değilse eklenti reddedilir.

**Kurulum:** `/opt/openreporting/venv/bin/pip install <paket>` → `openreporting.env` içine
`OPENREPORTING_PLUGINS=x-static-table` → web ve worker'ı yeniden başlatın. Docker/Kubernetes'te eklentiyi
imaja ekleyen küçük bir `FROM openreporting:…` katmanı oluşturun.

## Panel eklentisi (tarayıcı)

Eklenti klasörü: `OPENREPORTING_PLUGIN_DIR` (varsayılan `<veri dizini>/plugins`). Her eklenti kendi klasöründedir:

```
plugins/x-bullet/
  plugin.json   {"id": "x-bullet", "type": "panel", "name": "…", "version": "1.0.0", "module": "module.js", "style": "style.css"}
  module.js     export function register(api) { api.registerPanel('x-bullet', { name, icon, defaults, sections, render }) }
  style.css     isteğe bağlı
```

`api` yalnız şunları sunar: `registerPanel(id, tanım)`, `registerQueryEditor(veriKaynağıTürü, fn)` ve güvenli
DOM yardımcıları `dom.h` / `dom.clear` (HTML metni enjekte eden bir yol yoktur). `render(container, frames, panel, ctx)`
çağrısı yerleşik panellerle aynıdır; `sections` panel düzenleyicisindeki seçenek formunu tanımlar.

Sunucu yalnız etkin eklentilerin `.js .css .json .svg .png` dosyalarını, eklenti klasörünün içinden ve oturum
açmış kullanıcılara sunar; klasör dışına çıkan yollar 404 döner.

## API

| Uç | Yetki | Açıklama |
| --- | --- | --- |
| `GET /api/plugins` | Oturum/anahtar | Tarayıcının yükleyeceği panel eklentileri (`module_url`, `style_url`) |
| `GET /api/admin/plugins` | Yönetici | İzin listesi ve tüm eklentilerin durumu (`loaded`, `disabled`, `error` + ayrıntı) |
| `GET /plugins/{id}/{dosya}` | Oturum | Etkin panel eklentisinin dosyası |

## Testler

Gerçek örnek eklentiyle kayıt, doğrulama ve sorgu; izin listesi zorunluluğu; bozuk, tür uyuşmazlığı ve öneksiz
eklentilerin reddi; kurulu olmayan türün reddi; panel eklentisinin listelenmesi ve sunulması; izinsiz dosya türü,
klasör dışı yol, kapalı eklenti ve oturumsuz erişimde 404/401; eklenti panel türünün kayıtta korunması.
