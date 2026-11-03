# 01 · Kalite kapıları, kod biçimi ve yeniden düzenleme

| | |
| --- | --- |
| Durum | Uygulandı |
| Dosyalar | `pyproject.toml` (`[tool.ruff]`, `[tool.coverage]`), `requirements-test.lock`, `.github/workflows/ci.yml`, `.git-blame-ignore-revs` |
| Yeni modüller | `openreporting/lockout.py`, `openreporting/messages.py` |

## CI'da zorunlu kapılar

| Kapı | Araç | Kural |
| --- | --- | --- |
| Statik analiz | ruff (`F`, `E9`, `W605`, `B`, `PLE`) | Kullanılmayan import/değişken, geç bağlanan döngü değişkeni, geçersiz kaçış, çalışma zamanı hataları |
| Kod biçimi | `ruff format --check` | Tüm Python kodu tek biçimde; biçim commit'i `git blame`'den hariç |
| Test kapsamı | coverage (dal kapsamı) | `--fail-under=75`; eşik yalnız yükseltilir |
| Bağımlılık bütünlüğü | hash'li kilit dosyaları | test araçları dahil |

FastAPI'nin `Depends()` kalıbı bugbear tarafından "değiştirilemez çağrı" olarak tanımlandı (B008 yanlış alarmı).

## Yeniden düzenlemeler

- **`lockout.py`**: başarısız kimlik doğrulama sayaçları (kullanıcı+istemci 5, kullanıcı geneli 50, oturum içi
  onay ayrı sayaç) ve kilit kararı. `security` ile `mfa` arasındaki döngüsel import kaldırıldı.
- **`mfa._step_up`**: kurulum başlatma, onay, kurtarma kodu yenileme ve kapatma için tek bağlam yöneticisi:
  yeniden kimlik doğrulama → hesap değişmedi kontrolü → kilit kontrolü → (başarısızlık aynı işlemde sayılır)
  → 403 işlem tamamlandıktan sonra. Üç kopya akış kaldırıldı.
- **CLI**: `main()` 202 satır / 42 daldan komut başına fonksiyonlara ve `COMMANDS` tablosuna indi. Her
  komutun **aşaması** vardır: `raw` (hiçbir şey yüklemez: taşıma, sağlık, yedek doğrulama), `maintenance`
  (ayarları yükler, şemaya dokunmaz: anahtar rotasyonu, MFA sıfırlama, PostgreSQL ön kontrolü), `app` (önce
  şemayı hazırlar). Aşamalar testle sabitlenir (`tests/test_container.py`).
- **Mesajlar**: kullanıcıya dönen İngilizce hata metinleri Türkçeye çevrildi; ortak olanlar `messages.py`'de.
  CSRF mesajı istemcinin yeniden deneme için aradığı "CSRF" kelimesini korur.
- **Ölü kod**: hiç çağrılmayan 6 tanım silindi (`reduce_points`, `AGG_FUNCS`, `used_variables`, `describe`,
  `now_utc`, `domain_errors`).
