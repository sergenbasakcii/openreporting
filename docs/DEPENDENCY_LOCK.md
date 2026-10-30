# Runtime paket kilidi ve kurulum doğrulaması

`requirements-runtime.lock`, test edilmiş 28 runtime paketinin sürümünü ve o sürümlerin
PyPI'daki yanked olmayan wheel dosyalarının SHA-256 değerlerini saklar. `tzdata` yalnız
Windows marker'ıyla kurulur; Linux kapanışı 27 pakettir. Özel index, hesap, token veya yerel yol yoktur.

Ubuntu kurulum/yükseltme, Windows başlatıcı kurulumu ve Docker örneği önce
`--require-hashes --only-binary=:all:` ile runtime kurar; uygulama sonra `--no-deps` ile
kurulur ve `pip check` çalışır. Uyumlu wheel yoksa kaynak derlemesine sessiz fallback yapılmaz.
Hash uyuşmazsa kurulum başarısız olur. Var olan önizlemeyi bu değişiklik otomatik yeniden başlatmaz.
Yaklaşım [pip güvenli kurulum belgesine](https://pip.pypa.io/en/stable/topics/secure-installs/) dayanır.

CI Python 3.11/3.12/3.13'te ve LDAP/PostgreSQL/audit işlerinde aynı runtime snapshot'ını kurar.
`tools/check_runtime_lock.py` kurulu gerçek runtime kapanışını kilitle karşılaştırır;
pyproject değişip kilit unutulursa veya test/audit araçları runtime sürümünü değiştirirse kontrol başarısız olur.
Ubuntu uçtan uca kurulum/yükseltme kabulü de üretim betiğinin hash yolunu kullanır.

## Build ve test araçları

`requirements-build.lock` pip 26.2.2, setuptools 84.2.1, wheel 0.48.0 ve packaging 26.3
kapanışını; `requirements-test.lock` 13 Windows / 12 Linux QA paketini sabitler. Ubuntu,
Windows ve CI gerekli araçları hash kontrolüyle kurar. Uygulama `--no-build-isolation`
ile bu hazırlanmış backend'i kullanır; build sırasında farklı bir setuptools/wheel indirilmez.
Bu seçenek araçların önceden kurulmasını gerektirir; [pip build arayüzü](https://pip.pypa.io/en/stable/reference/build-system/#disabling-build-isolation)
kuralları uygulanır. Docker build aşaması da kilitli backend'i kullanır; runtime imajına
build araçları ayrıca kopyalanmaz.

`check_runtime_lock.py --scope build` ve `--scope test` kurulu gerçek kapanışları denetler.
CI üç ayrı kapsam için CVE taraması ve CycloneDX SBOM üretir. Yerelde dört build ve 13 QA
paketinin taramasında bilinen zafiyet bulunmadı; bu sıfır gün veya kaynak kod onayı değildir.

`tools/check_wheel_repro.py` aynı checkout/interpreter ve kilitli build araçlarıyla iki kez
`--no-index --no-deps --no-build-isolation` wheel üretir. Git commit zamanı veya açık
`--source-date-epoch` ZIP zamanını sabitler. İki wheel SHA'sı eşleşmelidir; CI Python3.13
bu kanıtı JSON artefakt olarak saklar. Bu yalnız **aynı ortamdaki** tekrar üretim kanıtıdır;
Windows/Linux eşdeğerliği, bütün hostun hermetikliği veya imzalı provenance değildir.
Git metadata'sı olmayan kaynak paketinde epoch açıkça verilmelidir.

## Güncelleme süreci

1. Ayrı Windows QA ortamında aday runtime sürümlerini kurun; ana uygulama/kurum verisine dokunmayın.
2. Bütün testler, eski Fernet verisi ve bağımlılık CVE taraması geçsin.
3. `python tools/lock_runtime.py` ile bu doğrulanmış kurulu kapanışın wheel hashlerini alın.
   Bu araç çözücü değildir ve aday sürüm seçmez; mevcut kurulu sürümleri sabitler.
   Windows-only kökü kaybetmemek için `tzdata` bulunmayan üretim/Linux ortamında üretimi reddeder.
4. Değişen paket ve hash listesini gözden geçirin. Kilit dosyasını otomatik ve incelemesiz yeniden üretmeyin.
5. Build/test kökleri değişirse uygun QA ortamında `lock_runtime.py --scope build --output requirements-build.lock`
   veya `--scope test --output requirements-test.lock` ile aday kilitleri üretin. Üç kapsamın
   `check_runtime_lock.py` kontrolü, CVE taraması, wheel tekrarı ve bütün Python/Ubuntu kabulü geçsin.
   Yeni platforma özgü bağımlılık varsa generator/marker desteği ve kabul matrisi birlikte güncellenmelidir.
6. Onaylı kaynak ağacı ve kilidi birlikte dağıtın. Release/merge ve imza kararı ayrı yetkidir.

## İnternetsiz kurulum

Hedefle aynı işletim sistemi, mimari ve Python sürümünde, internet erişimli QA makinesinde:

```text
python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
python -m pip download --require-hashes --only-binary=:all: -r requirements-build.lock -d wheels
python -m pip download --require-hashes --only-binary=:all: -r requirements-runtime.lock -d wheels
python -m pip wheel --no-deps --no-build-isolation -w wheels .
# Windows test/QA akışı da taşınacaksa:
python -m pip download --require-hashes --only-binary=:all: -r requirements-test.lock -d wheels
```

Kaynak ağacı/kilit ve wheelhouse birlikte taşınır; Ubuntu betiğine `--wheelhouse /yol/wheels`
verilir. Runtime wheel'leri hedefte tekrar hash kontrolünden geçer. Windows wheelhouse'u
Linux'a veya farklı Python ABI'sine uygun varsaymayın. Kurulum araçları ayrıca temin edilmelidir.

## Kanıt ve kabul sınırı

Yerel Windows/Python 3.13 QA'da 28 paket kilitten indirildi ve yeni sanal ortama
**offline/hash doğrulamalı** kuruldu; uygulama `--no-deps` kuruldu, `pip check` ve kapanış
eşleşmesi geçti. Bilerek yanlış SHA-256 verilen gerçek wheel'i pip kurulum öncesinde reddetti.
Linux/Python matrisi ve Ubuntu üretim betiğinin sonucu ilgili commitin CI kaydındadır.

Üç kilit runtime, build backend ve test kapanışını kapsar. İlk Python/pip bootstrap'ı,
CI action/runner, pip-audit tarayıcısının bütün transitif ortamı, Python/OS/apt paketleri,
Docker temel imajı ve uygulamanın release imzası bu kapsamın dışındadır. Bunlar için
imzalı artefakt/provenance ve host/build güven kökü kabulü açık iştir; L04 kısmi kalır.
Docker örneğinin güncellenmesi tek başına Docker imaj kabulü değildir.

İncelenmiş yerel hash, ondan sonraki farklı dosyayı reddeder; ilk güvenilen PyPI upload'ının
güvenli kod olduğunu, registry'nin geçmişte hiç etkilenmediğini veya sıfır gün bulunmadığını
kanıtlamaz. CVE taraması, kaynak/değişiklik incelemesi ve dağıtım yetkisi ayrıca korunur.
