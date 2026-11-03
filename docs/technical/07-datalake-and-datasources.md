# 07 · Veri gölü ve yeni veri kaynakları

| | |
| --- | --- |
| Durum | Uygulandı (şema 9: yeni tür kısıtı) |
| Sunucu | `datasources/sql_engines.py` (Trino/Presto, Databricks, ClickHouse), `datasources/search_tsdb.py` (Elasticsearch/OpenSearch, InfluxDB, Graphite), `http_sources.HTTPSource.fetch` (POST, kimlik, aynı köken), `postgres.DIALECTS` |
| Tarayıcı | `pages/datasource-forms.js` (bağlantı formları), `query/engine-editors.js` (sorgu editörleri) |
| Testler | `tests/test_new_datasources.py` (36 test, HTTP kaydedici ile) |

## Eklenen kaynaklar

| Tür | Ürün | Protokol | Salt-okunur güvencesi |
| --- | --- | --- | --- |
| `trino` | **Veri gölü** · Trino / Presto / Starburst (Hive, Iceberg, Delta Lake, S3/HDFS) | REST `POST /v1/statement` + `nextUri` sayfalama | Tek SELECT/WITH (`guard_sql`) + salt-okunur rol önerisi |
| `databricks` | **Lakehouse** · Databricks SQL warehouse (Unity Catalog, Delta) | Statement Execution API, INLINE/JSON_ARRAY, yoklama + parça okuma | Tek SELECT/WITH + PAT/servis sorumlusu yetkisi |
| `clickhouse` | ClickHouse | HTTP arayüzü, `JSONCompact` | Sunucuda `readonly=2`, `max_result_rows`, `result_overflow_mode=throw` |
| `elasticsearch` | Elasticsearch / OpenSearch | Yalnız `/<indeks>/_search` | Uç sabit; indeks deseni doğrulanır (`..`, `/`, `?`, `_` ile başlama yok) |
| `influxdb` | InfluxDB 1.x / 2.x (v1 uyumluluk) / 3.x | `GET /query` InfluxQL | Yalnız SELECT/SHOW, `INTO` ve çoklu ifade reddi |
| `graphite` | Graphite-web / carbonapi | `GET /render?format=json` | Okuma API'si |

Önceden var olanlar: Zabbix, PostgreSQL/TimescaleDB, Prometheus/Mimir/VictoriaMetrics, Loki, HTTP JSON/CSV, TestData.
Hiçbiri yeni bağımlılık gerektirmez (sürücüsüz, standart kütüphane HTTP istemcisi).

## Ortak güvenlik kuralları

- **Adres sabit:** Sorgu, URL/yol seçemez; yalnız yöneticinin kaydettiği kök adres kullanılır. Sunucunun
  döndürdüğü takip adresleri (Trino `nextUri`, Databricks parça bağlantıları) aynı şema/host/port'ta
  olmalıdır; aksi halde izlenmez.
- **SSRF korumaları** (`safe_peer`): link-local, metadata, varsayılan olarak loopback engelli; HTTPS ve sertifika
  doğrulaması zorunlu (iç CA için PEM).
- **Başlık enjeksiyonu:** kullanıcı/katalog/anahtar gibi başlığa giden değerlerde kontrol karakteri reddedilir.
- **Bütçeler:** satır sınırı (`OPENREPORTING_MAX_ROWS`), nokta bütçesi, toplam süre sınırı; aşımda sessiz kırpma
  yerine açık hata. Trino/Databricks'te zaman aşımında sorgu iptal edilir.
- **Hata metinleri:** yalnız HTTP durumu veya motorun kısa hata mesajı (≤300 karakter) gösterilir; yanıt gövdesi
  kimlik bilgisi yansıtabileceği için loglanmaz.
- **Değişken biçimleri:** ClickHouse ve Databricks ters eğik çizgiyi kaçış sayar → `sqlstring_escaped`;
  InfluxQL regex'inde `/` sınırlayıcıdır → `influxregex`; Elasticsearch → `lucene`. Kayıtlı olmayan
  (güvenilmeyen) dashboard'larda yalnız bu güvenli biçimlere izin verilir.

## SQL makroları (lehçeli)

`$__timeFilter(sütun)`, `$__timeGroup(sütun, 5m)`, `$__timeFrom()`, `$__timeTo()`, `$__interval_s`,
`$__unixEpochFilter(sütun)` her motorda kendi sözdizimine çevrilir (`postgres.DIALECTS`):

| Lehçe | Zaman sabiti | Gruplama |
| --- | --- | --- |
| postgres | `'…'::timestamptz` | `to_timestamp(floor(extract(epoch …)))` |
| trino | `from_iso8601_timestamp('…')` | `from_unixtime(floor(to_unixtime(c)/s)*s)` |
| clickhouse | `parseDateTime64BestEffort('…', 3, 'UTC')` | `toStartOfInterval(c, INTERVAL s SECOND)` |
| databricks | `to_timestamp('…')` | `timestamp_seconds(floor(unix_timestamp(c)/s)*s)` |

Sonuçlar PostgreSQL kaynağıyla aynı kurala göre çerçeveye dönüşür: `time` sütunu (+ isteğe bağlı `metric`)
→ zaman serisi, aksi halde tablo. Motorun tür adları (`timestamp(3)`, `Nullable(UInt64)`, `DOUBLE` …)
sayı/zaman/metin olarak sınıflandırılır; saat dilimi verilmeyen zaman damgaları UTC kabul edilir.

## Elasticsearch / OpenSearch sorgusu

Metrik görünümü: `date_histogram` (panel aralığı), isteğe bağlı metrik (`avg/sum/min/max/cardinality`) ve
`terms` ile gruplara ayırma (en çok 50). Log görünümü: son 500 kayıt, ilk 30 alan sütun olur; iç içe değerler
JSON metni. Shard hatası varsa eksik sonuç gösterilmez.

## Kimlik doğrulama

| Kaynak | Seçenekler |
| --- | --- |
| Trino/Presto | Basic (kullanıcı + parola) veya Bearer/JWT; `X-Trino-*` / `X-Presto-*` başlıkları |
| Databricks | Bearer PAT / servis sorumlusu anahtarı |
| ClickHouse | `X-ClickHouse-User` / `X-ClickHouse-Key` / `X-ClickHouse-Database` |
| Elasticsearch | Yok, Basic, `ApiKey`, Bearer |
| InfluxDB | Yok, Basic (1.x), `Token` (2.x/3.x) |
| Graphite | Yok, Basic, Bearer |

Gizli alanlar (`password`, `token`) Fernet ile şifrelenir, tarayıcıya yalnız "yapılandırıldı" bilgisi döner.
