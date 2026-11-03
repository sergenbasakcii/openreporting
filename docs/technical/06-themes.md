# 06 · Tema sistemi ve görsel kimlik

| | |
| --- | --- |
| Durum | Uygulandı |
| Tarayıcı | `static/app/themes.css` (tokenlar), `static/app/themes.js` (liste, çözümleme), `app.css` (yalnız token okur), `pages/admin.js` (`themePicker`) |
| Sunucu | `openreporting/themes.py`, `api/users.py` (tercih doğrulama), `reporting/fieldcfg.py` (PDF seri renkleri) |
| Testler | `tests/test_themes.mjs` (kimlik eşleşmesi + WCAG kontrast), `tests/test_theme_preferences.py` |

## Amaç

Arayüz önceden Grafana'nın renklerini (turuncu vurgu, mavi birincil, klasik seri paleti) ve keskin köşeli
görünümünü taşıyordu. OpenReporting artık kendi görsel diline sahiptir: katmanlı yüzeyler, yumuşak köşeler
(6/12 px), hap biçimli gezinme öğeleri, yarı saydam üst çubuk, panel gölgeleri ve her temaya özgü bir seri paleti.

## Temalar

| Kimlik | Ad | Şema | Karakter | Vurgu |
| --- | --- | --- | --- | --- |
| `aurora` | Aurora | koyu | Varsayılan koyu. Lacivert yüzeyler. | Camgöbeği `#2dd4bf`, ikincil çivit |
| `porcelain` | Porselen | açık | Varsayılan açık. Sıcak beyaz, mürekkep metin. | Koyu camgöbeği `#0d9488` |
| `graphite` | Grafit | koyu | Nötr kömür grisi; izleme odası / duvar ekranı. | Kehribar `#f59e0b` |
| `dune` | Kum | açık | Kâğıt tonları; uzun rapor okuma. | Kiremit `#c2410c` |
| `contrast` | Yüksek kontrast | koyu | Siyah zemin, beyaz metin, kalın kenarlar. | Sarı `#ffd60a` |
| `system` | Sistem | — | İşletim sistemi ayarına göre Aurora ↔ Porselen. Yeni kullanıcıların varsayılanı. | — |

Eski değerler kalıcı olarak okunur: `dark` → `aurora`, `light` → `porcelain` (kayıtta da dönüştürülür).

## Mimari

- **Tokenlar tek yerde.** Her tema `themes.css` içinde bir `[data-theme="…"]` bloğudur. Bileşenler sabit renk
  kullanmaz; yalnız `--bg*`, `--text*`, `--primary*`, `--accent*`, `--brand-a/b`, `--panel-shadow`,
  `--login-glow`, `--series` gibi tokenları okur. Yarı saydam durum renkleri `color-mix()` ile tokenlardan türetilir.
- **Kök öznitelikler.** `<html data-theme="aurora" data-scheme="dark">`. `data-scheme` yerel denetimleri
  (`color-scheme`), hızlı açık/koyu geçişini ve önizleme penceresini yönetir.
- **Seri paleti.** `--series` 10 renk içerir. `themes.js#syncSeriesPalette` bunları okuyup `colors.js#setPalette`
  ile canlı `PALETTE` bağına yazar; tükenince klasik renkler eklenir. Tema değişince
  `openreporting:themechange` olayı panelleri yeniden çizer. Dashboard JSON'undaki adlandırılmış renkler
  (`green`, `red` …) ve eşik renkleri içe aktarma uyumluluğu için değişmez.
- **PDF raporları** beyaz kâğıda basıldığından Porselen seri renklerini kullanır (`fieldcfg.SERIES`).
- **Seçici.** Profil sayfasında renk örnekli kart grubu (`role="radiogroup"`, ok tuşlarıyla gezinme).
  Kullanıcı menüsündeki hızlı geçiş, aynı ailedeki karşı şemaya geçer (Aurora↔Porselen, Grafit↔Kum).

## Yeni tema ekleme

1. `themes.css` içine `aurora` bloğundaki tüm tokenları tanımlayan yeni bir blok ekleyin.
2. `themes.js#THEMES` listesine kimlik, ad, şema, açıklama ve 4 renklik örnek ekleyin.
3. `openreporting/themes.py#THEME_IDS` içine aynı kimliği aynı sırada ekleyin.
4. `node --test tests/test_themes.mjs` çalıştırın: eksik token, kimlik uyuşmazlığı veya 4.5:1 altındaki
   metin/bağlantı/buton kontrastı testi kırar.

## Erişilebilirlik

Her temada `--text`, `--text-strong`, `--text-muted`, `--text-faint`, `--primary-text`, `--success-text` ve
`--error-text`, `--bg`/`--bg-panel`/`--bg-elevated` üzerinde; `--on-primary` ise `--primary` üzerinde en az
WCAG AA (4.5:1) kontrast sağlar. Kontrol, saydamlık arka plana harmanlanarak hesaplanır ve CI'da çalışır.

## Testler

`tests/test_themes.mjs`: istemci/CSS/sunucu kimlik eşleşmesi, tam token kümesi, 10 geçerli seri rengi, kontrast,
eski değer ve bilinmeyen kimlik çözümlemesi, karşı şema geçişi. `tests/test_theme_preferences.py`: yeni kullanıcının
`system` alması, tüm temaların kaydedilip okunması, `dark`/`light` dönüşümü, geçersiz değerlerin 422 ile reddi.

## Tarayıcı erişilebilirlik kabulü

`tests/browser/themes.cjs` tema listesini paylaşır; `mfa-flow`, `folder-flow` ve `accessibility-surfaces`
betikleri her ekranı beş temanın hepsinde axe-core ile tarar (tema değişiminden sonra geçişlerin oturması beklenir).
Bu çalışmada bulunan ve düzeltilen bulgular:

- Tema değişirken renk geçişleri (`transition`) ara karışık renkler üretiyordu → geçiş sırasında kökte
  `.theme-switching` sınıfı tüm geçişleri kapatır; `prefers-reduced-motion` de saygı görür.
- Tabloda "renkli metin" hücreleri ham eşik rengini kullanıyordu (açık temada 2.2:1) → `readableColor` ile
  panel zeminine göre koyulaştırılır.
- Panel başlıkları artık `h2` (dashboard `h1` → panel `h2` → markdown `h3`); başlıksız panelde başlık
  erişilebilirlik ağacından gizlenir.
- Otomatik yenileme düğmesinin erişilebilir adı görünen aralığı içerir ("1m otomatik yenileme").
- Kaydırılabilir seri göstergeleri klavyeyle odaklanabilir (`tabindex=0`, `role=group`).
- Menü ilk öğeye eşzamanlı odaklanır; açılır açılmaz basılan End/Home/ok tuşları menüye gider.

Sonuç: 8 rota × 5 tema + giriş ekranı, ciddi/kritik bulgu yok (panel düzenleyicide bir "moderate"
başlık sırası notu kalır).
