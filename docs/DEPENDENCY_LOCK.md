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

## Güncelleme süreci

1. Ayrı Windows QA ortamında aday runtime sürümlerini kurun; ana uygulama/kurum verisine dokunmayın.
2. Bütün testler, eski Fernet verisi ve bağımlılık CVE taraması geçsin.
3. `python tools/lock_runtime.py` ile bu doğrulanmış kurulu kapanışın wheel hashlerini alın.
   Bu araç çözücü değildir ve aday sürüm seçmez; mevcut kurulu sürümleri sabitler.
   Windows-only kökü kaybetmemek için `tzdata` bulunmayan üretim/Linux ortamında üretimi reddeder.
4. Değişen paket ve hash listesini gözden geçirin. Kilit dosyasını otomatik ve incelemesiz yeniden üretmeyin.
5. `python tools/check_runtime_lock.py`, bütün Python/Ubuntu testleri ve kurulum kabulünü çalıştırın.
   Yeni platforma özgü bağımlılık varsa generator/marker desteği ve kabul matrisi birlikte güncellenmelidir.
6. Onaylı kaynak ağacı ve kilidi birlikte dağıtın. Release/merge ve imza kararı ayrı yetkidir.

## İnternetsiz kurulum

Hedefle aynı işletim sistemi, mimari ve Python sürümünde, internet erişimli QA makinesinde:

```text
python -m pip download --require-hashes --only-binary=:all: -r requirements-runtime.lock -d wheels
python -m pip wheel --no-deps -w wheels .
python -m pip wheel -w wheels pip setuptools wheel
```

Kaynak ağacı/kilit ve wheelhouse birlikte taşınır; Ubuntu betiğine `--wheelhouse /yol/wheels`
verilir. Runtime wheel'leri hedefte tekrar hash kontrolünden geçer. Windows wheelhouse'u
Linux'a veya farklı Python ABI'sine uygun varsaymayın. Kurulum araçları ayrıca temin edilmelidir.

## Kanıt ve kabul sınırı

Yerel Windows/Python 3.13 QA'da 28 paket kilitten indirildi ve yeni sanal ortama
**offline/hash doğrulamalı** kuruldu; uygulama `--no-deps` kuruldu, `pip check` ve kapanış
eşleşmesi geçti. Bilerek yanlış SHA-256 verilen gerçek wheel'i pip kurulum öncesinde reddetti.
Linux/Python matrisi ve Ubuntu üretim betiğinin sonucu ilgili commitin CI kaydındadır.

Bu kilit yalnız **uygulamanın runtime kapanışıdır**. pip/setuptools/wheel build ortamı,
pytest/httpx/pip-audit QA araçları, Python/OS/apt paketleri, Docker temel imajı ve uygulamanın
kendi release wheel'i hashli hermetik build kapsamına alınmadı. Bunlar için imzalı
artefakt/provenance ve ayrı build-tool kilidi açık iştir; L04 bu yüzden kısmi kalır.
Docker örneğinin güncellenmesi tek başına Docker imaj kabulü değildir.

İncelenmiş yerel hash, ondan sonraki farklı dosyayı reddeder; ilk güvenilen PyPI upload'ının
güvenli kod olduğunu, registry'nin geçmişte hiç etkilenmediğini veya sıfır gün bulunmadığını
kanıtlamaz. CVE taraması, kaynak/değişiklik incelemesi ve dağıtım yetkisi ayrıca korunur.
