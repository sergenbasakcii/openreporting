# 14 — Tek komutla Docker kurulumu (`kurulum.sh`)

## Amaç

Docker kurulumu daha önce on kadar elle adım istiyordu: ayar dosyası, sertifika üretimi, `chown root:101`,
uid 10001 yedek klasörü, derleme, ilk yönetici, anahtar kopyası, cron, çıkış kilidi. Hepsi artık tek komutla yapılıyor:

```bash
git clone https://github.com/sergenbasakcii/openreporting.git ~/openreporting && cd ~/openreporting
sudo ./kurulum.sh
```

## Davranış

| Alt komut | İş |
| --- | --- |
| `kur` (varsayılan) | Docker kontrolü/kurulumu → ayar dosyası → sertifika → derle/başlat → ilk yönetici → anahtar kopyası → gece yedeği → çıkış kilidi → saat ve `doctor` kontrolü |
| `guncelle` | Çıkış kilidini geçici kaldırır (derleme internet ister), yedek alır, `git pull --ff-only`, yeniden derler, kontrol eder, kilidi geri koyar (`trap`) |
| `durum` | `docker compose ps`, worker heartbeat, son yedek, kilit durumu |
| `yedek` | Yedek görevini hemen çalıştırır |

Sorulan yalnızca: adres (varsayılan `hostname -f`), HTTPS portu (443), yönetici adı ve parolası (konteyner içindeki
`create-user` getpass ile sorar; parola betikten geçmez), iç ağlar (isteğe bağlı).

## Tasarım kararları

- **Tekrar çalıştırılabilir (idempotent):** var olan `openreporting.env`, sertifika, kullanıcılar, anahtar kopyası ve
  kilit birimi korunur; yarım kalan kurulum aynı komutla tamamlanır. Kullanıcı varlığı veritabanından sayılır.
- **Sertifika:** kurum PEM'i (`OR_SERTIFIKA`/`OR_ANAHTAR` ya da `certs/` içine önceden konmuş) yoksa kendinden imzalı;
  SAN'a adres ve sunucunun birincil IP'si girer. Aynı IP `OPENREPORTING_ALLOWED_HOSTS`'a eklenir.
- **Anahtar:** `/root/openreporting-anahtar/secret.key` (0700/0600); betik kullanıcıya sunucu dışına taşımasını söyler.
  Yedeklere varsayılan olarak girmez (değişmedi).
- **Gece yedeği:** `/etc/cron.d/openreporting-yedek` (root, sabit `PATH`), günlük `/var/log/openreporting-yedek.log`.
- **Çıkış kilidi:** yalnız iç ağ listesi verilirse uygulanır (boş liste veri kaynaklarını keserdi);
  `openreporting-cikis-kilidi.service` systemd birimi kalıcılığı sağlar.
- **Otomasyon:** `OR_EVET=1` ile hiçbir şey sorulmaz; parola `OR_PAROLA` ortam değişkeniyle konteynere `-e` ile geçer,
  komut satırında görünmez.

## Doğrulama

- `shellcheck -x -s bash kurulum.sh` (CI lint işine eklendi).
- Yeni CI işi **One-command installer (kurulum.sh)** — temiz Ubuntu 24.04: soru sormadan kurulum, HTTPS `/readyz`,
  yönetici girişi (200), anahtar kopyası, cron dosyası, kilit birimi etkin ve REJECT kuralı, ikinci çalıştırmanın hiçbir
  şeyi yeniden oluşturmaması, `yedek` ve `durum`.

## Belgeler

`README.md` hızlı başlangıcı ve `docs/DOCKER.md` Bölüm 2/5 tek komuta göre yeniden yazıldı; elle adımlar
"Elle kurulum (isteğe bağlı)" altında duruyor. Teknik PDF'te Bölüm 4 üç adıma indi, elle adımlar Ek F'ye taşındı.
