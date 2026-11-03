# 09 · Takımlar (kullanıcı grupları) ve dashboard izinleri

| | |
| --- | --- |
| Durum | Uygulandı (şema 10) |
| Sunucu | `teams.py`, `dashboard_access.py`, `folder_access.py` (`visible_dashboards_sql`, `dashboard_allowed`), `api/teams.py` |
| Tarayıcı | `pages/teams.js` (Yönetim → Takımlar), `access.js` (ortak izin penceresi: klasör + dashboard) |
| Testler | `tests/test_teams_permissions.py`, `tests/test_folder_access.py` |

## Model

```
teams(id, name UNIQUE, description)            team_members(team_id, user_id)
folder_team_grants(folder_id, team_id, view|edit)
dashboard_policy(dashboard_id, restricted, revision)
dashboard_grants(dashboard_id, principal_type user|team, principal_id, view|edit)
```

## Kurallar

1. **Yöneticiler** her şeyi görür ve düzenler.
2. **Klasör:** paylaşılan klasörü herkes görür. Kısıtlı klasörü yalnızca doğrudan veya **takım üzerinden**
   izin verilen kullanıcılar görür.
3. **Dashboard:** kısıtlanmamış dashboard klasörünü izler. Kısıtlanmış dashboard'u yalnızca kendi kullanıcı/takım
   izinleri belirler. Bu hem paylaşılan bir klasörde tek dashboard'u daraltmaya hem de kısıtlı bir klasördeki tek
   bir dashboard'u bir ekibe açmaya izin verir.
4. **Düzenleme** için hem `edit` izni hem editör/yönetici rolü gerekir. İzleyici bir takımın üyesiyse takıma
   `edit` verilse de yalnız görüntüler (rol üst sınırdır).
5. Takımdan çıkarılan üye veya silinen takım erişimini **hemen** kaybeder. Takım silinince dashboard izinleri de
   silinir (`dashboard_grants` iki tür kimlik taşıdığından yabancı anahtar yerine açık temizlik).
6. İzin değişikliği o dashboard'un/klasörün rapor zamanlamalarını kapatır; zamanlanmış teslim yeniden onay ister.
7. Değişiklikler iyimser eşzamanlılıkla (revision) korunur; eski pencereden kayıt 409 döner. Tümü denetim
   kaydına yazılır (`team.*`, `folder.permissions_changed`, `dashboard.permissions_changed`).

Kural 3 tek bir SQL koşuluna (`visible_dashboards_sql`) dönüştürülür ve arama, etiketler, raporlar,
zamanlamalar, çalıştırma arşivi ile worker yeniden doğrulamasında aynı koşul kullanılır. Bu koşul sıralama ve
`LIMIT`'ten önce uygulandığı için görünmeyen kayıtlar sonuç sınırını tüketmez.

## API

| Uç | Yetki |
| --- | --- |
| `GET /api/teams` | Yönetici (okuma) — takımlar ve üyeleri |
| `POST /api/teams`, `PUT/DELETE /api/teams/{id}` | Yönetici |
| `PUT /api/teams/{id}/members` `{user_ids: []}` | Yönetici |
| `GET/PUT /api/folders/{uid}/permissions` `{restricted, revision, grants[], team_grants[]}` | Yönetici |
| `GET/PUT /api/dashboards/uid/{uid}/permissions` `{restricted, revision, grants[{principal_type, principal_id, permission}]}` | Yönetici |

## Arayüz

- **Yönetim → Takımlar:** takım kartları, üye avatarları; "Üyeler" penceresinde aranabilir onay kutulu liste.
- **Klasör menüsü → Klasör izinleri** ve **Dashboard → ⋮ → İzinler:** aynı pencere; takımlar ve kullanıcılar
  aranabilir tek listede, her biri için "İzin yok / Görüntüleme / Düzenleme".
