# 02 · Rapor hatası bildirimleri (işlemsel giden kutusu)

| | |
| --- | --- |
| Durum | Uygulandı (şema 7) |
| Modül | `openreporting/reporting/notifications.py` |
| Tetikleyiciler | `openreporting/reporting/service.py` (8 nokta) |
| API | `GET /api/report-notifications`, `PUT /api/user/preferences` (`notify_report_failures`) |
| Testler | `tests/test_notifications.py` |

## Sorun

Zamanlanmış bir rapor başarısız olduğunda veya zamanlama kendini kapattığında (rapor/dashboard onaydan sonra
değişti, onaylayan yöneticinin yetkisi kalmadı, hata, servis kesintisinde kaçırılan pencere) yalnız denetim
kaydına satır düşüyordu; kimse haberdar olmuyordu.

## Tasarım: transactional outbox

`notify(db, event, report_id, …)` olayı, durumu değiştiren **aynı veritabanı işleminde** `notification_outbox`
tablosuna yazar. İşlem geri alınırsa bildirim de yoktur; işlem tamamlanırsa olay kaybolmaz. Worker her
döngüde `deliver_pending` ile en fazla 50 olayı işler.

```sql
CREATE TABLE notification_outbox(
 id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, report_id TEXT NOT NULL,
 schedule_id TEXT, run_id TEXT, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','skipped','failed')),
 attempts INTEGER NOT NULL DEFAULT 0, sent_at TEXT);
ALTER TABLE user_prefs ADD COLUMN notify_report_failures INTEGER NOT NULL DEFAULT 1;
```

Olaylar: `run_failed`, `run_blocked`, `delivery_failed`, `delivery_unknown`, `schedule_disabled_changed`,
`schedule_disabled_authorization`, `schedule_failed_disabled`, `schedule_missed_window`,
`schedules_disabled_report_changed`.

## Alıcı kuralları (gönderim anında çözülür)

Raporun sahibi ile zamanlamayı oluşturan ve onaylayan kişi. Yalnız: etkin hesap, e-posta adresi tanımlı,
adres izinli alıcı alan adlarında, bildirimi kapatmamış ve raporu **hâlâ açabilen** (klasör izni) kullanıcılar.
E-posta rapor verisi içermez: rapor adı, olay, UTC zamanı, kısa ayrıntı ve bağlantı.

## Teslim

En az bir kez (at-least-once); SMTP hatasında en fazla 3 deneme, sonra `failed`. E-posta kapalıysa olaylar
`skipped` olur ama **Raporlar** sayfasında son 30 gün listelenir. Tamamlanmış kayıtlar 90 gün sonra silinir.
