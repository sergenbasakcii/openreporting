# OpenReporting Reporting Platform — Windows 10/11 local evaluation

**Sürüm 1.0 / Aynı Python uygulaması ve aynı web arayüzü.** Linux sürümündeki dashboard’lar, veri kaynakları, sorgu motoru, PDF/Excel/CSV raporları, arşiv, denetim kaydı ve zamanlama kodu burada da kullanılır. Ayrı veya azaltılmış bir Windows kopyası değildir.

Bu paket kişisel Windows bilgisayarında **yerel değerlendirme** içindir. Yönetici izni, WSL, Docker, Nginx, S3, MinIO, Redis, Celery ya da Node.js servisi gerekmez. Uygulama yalnızca `127.0.0.1` üzerinde dinler. Raporlar ve kullanıcı kayıtları mevcut Windows hesabınız altında tutulur. Şirket kaynak sistemlerine yalnızca okuma erişimi olmalıdır.

## 1. Ön hazırlık

- Windows 10/11, 64-bit Python **3.11 / 3.12 / 3.13** (3.12 önerilir), `pip` ve `venv`.
- Windows PowerShell 5.1 veya PowerShell 7.
- İlk kurulumda Python bağımlılıklarını yüklemek için PyPI erişimi veya kurumun onayladığı Python paket deposu.
- Zabbix bağlanacaksa HTTPS URL + sadece gerekli host gruplarına `get`/read yetkili Zabbix API token'ı. Windows bilgisayarınızın Zabbix'e ağ erişimi ve doğru CA zinciri olmalıdır.
- PostgreSQL/TimescaleDB veri kaynağı eklenecekse yalnız `SELECT` yetkili hesap ve TLS sertifika zinciri.

Sıkıştırılmış dosyayı örneğin `C:\Users\<kullanıcı>\Documents\OpenReporting-Windows` klasörüne çıkarın. PowerShell'i bu klasörde açın. Kurumsal PowerShell script yürütme ilkesi engelliyorsa kurumsal IT onayı alın; politikayı sistem genelinde değiştirmeyin.

## 2. Kurulum (bir kere)

```powershell
.\windows\Install-OpenReporting.ps1
```

Python Launcher (`py`) yoksa veya farklı bir Python sürümü kullanmak isterseniz:

```powershell
.\windows\Install-OpenReporting.ps1 -PythonExe 'C:\Path\To\Python312\python.exe'
```

İşlem `.venv` Python ortamını oluşturur, bağımlılıkları yükler, **boş** SQLite veritabanını hazırlar ve mevcut `windows\Settings.local.ps1` dosyası varsa ona dokunmaz.

## 3. Yönetici hesabı

```powershell
.\windows\New-Admin.ps1 -Username sergen
```

Güçlü parolayı komut isteminde iki kere girin (en az 14 karakter). Parola script'e, URL'ye veya komut satırı geçmişine yazılmaz. Daha önce aynı kullanıcıyı açtıysanız yeniden çalıştırmayın.

## 4. Testleri çalıştırın

```powershell
.\windows\Test-OpenReporting.ps1
```

Test paketi mock verilerle uygulama işlevlerini denetler; **Zabbix veya PostgreSQL üzerinde veri değiştirmez**. Yerel audit zincirini de doğrular. Linux üzerinde geçirilen testler Windows testi yerine geçmez: Windows PC'nizde bu komutun başarılı olmasını bekleyin.

## 5. Uygulamayı açın

```powershell
.\windows\Start-OpenReporting.ps1
```

Arayüz adresi: **http://127.0.0.1:8810**

Worker ayrı Python alt süreci, web API ise mevcut PowerShell penceresinde çalışır. Başlatıcı worker'ı tek seferde kilitler, başlatılan alt süreci uygulama durduğunda kapatır. PowerShell penceresini açık tutun; **Ctrl+C** ile kapatın. Her yeni çalıştırmada worker logu `%LOCALAPPDATA%\OpenReporting\logs` altında ayrı dosyaya kaydedilir.

Tek tıkla açmak için masaüstü kısayolu: hedefi
`powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<klasör>\windows\Open-OpenReporting.ps1"`,
simgesi `windows\OpenReporting.ico` olan bir kısayol oluşturun. Uygulama çalışmıyorsa küçültülmüş bir pencerede başlatılır,
ardından tarayıcıda açılır; o pencere kapatılınca uygulama durur.

Tarayıcıyı otomatik açmadan çalıştırma:

```powershell
.\windows\Start-OpenReporting.ps1 -NoBrowser
```

Windows uyku/oturum kapatma durumunda worker durabileceği için zamanlanmış raporların sürekli işletimi için **Linux sunucu sürümü** tercih edilmelidir. Bu Windows dağıtımı kişisel test kurulumudur.

## 6. Gerçek Zabbix bağlantısı (isteğe bağlı)

En kolay yol arayüzdür: **Yönetim → Veri kaynakları → Ekle → Zabbix** (URL, salt-okunur API token’ı, gerekirse kurum CA’sı). Token şifreli saklanır. Alternatif olarak veri kaynağını ortam ayarıyla tanımlamak için `windows\Settings.local.ps1` dosyasına şu satırları ekleyin:

```powershell
$env:OPENREPORTING_ZABBIX_URL = 'https://zabbix.example.internal/api_jsonrpc.php'
$env:OPENREPORTING_ZABBIX_TOKEN_FILE = Join-Path $env:OPENREPORTING_DATA_DIR 'secrets\zabbix-token.txt'
```

Gizli token'ı PowerShell komut geçmişine yazmadan bir metin editörüyle `%LOCALAPPDATA%\OpenReporting\secrets\zabbix-token.txt` dosyasına koyun. `secrets` klasörünü önce oluşturun ve NTFS izinlerini kendi Windows hesabınızla sınırlandırın. Token dosyası tek satır, sonu boşluksuz olsun.

Kurum sertifikası işletim sistemi güven deposunda bulunmuyorsa PEM biçimindeki CA dosyasını ayrıca verin:

```powershell
$env:OPENREPORTING_ZABBIX_CA_FILE = 'C:\certificates\corporate-ca.pem'
```

**HTTPS doğrulamasını kapatmayın.** Sunucuya bağlanamazsa ağ/VPN, DNS, CA ve token yetkilerini kontrol edin. Zabbix API izni `hostgroup.get`, `host.get`, `item.get`, `history.get`, `trend.get` için yeterli salt-okunur kapsamda olmalıdır. Uygulamayı yeniden başlattığınızda **Veri kaynakları** listesinde “Zabbix (ortam ayarı)” görünür; panel sorgu düzenleyicisinde grup → host → item seçebilirsiniz.

## 7. E-posta ve takvimler

SMTP **devre dışı** gelir. Yerel test sırasında gerçek müşteri adreslerine rapor gitmemesi için bunun böyle kalmasını öneriyoruz. Onaylı test SMTP hesabı, izinli domain listesi ve `Settings.local.ps1` alanları tamamlandığında, test e-postası göndermeyi bilinçli seçmek için:

```powershell
.\windows\Start-OpenReporting.ps1 -AllowEmail
```

Bu bayrak, yapılandırılmamış SMTP'yi kendiliğinden etkinleştirmez. Raporlar uygun değilse veya kapsam eksikse uygulama otomatik göndermeyi engeller. SMTP teslimatı canlı ortamda ayrıca doğrulanmalıdır.

## 8. Nerede saklanıyor?

| İçerik | Windows yolu |
| --- | --- |
| Uygulama kodu | ZIP'i açtığınız klasör |
| Sanal Python | `.venv\` |
| SQLite | `%LOCALAPPDATA%\OpenReporting\state.sqlite3` |
| PDF / CSV / JSON | `%LOCALAPPDATA%\OpenReporting\archive\` |
| Worker logları | `%LOCALAPPDATA%\OpenReporting\logs\` |
| API token'ı | Kullanıcının oluşturduğu `secrets\` klasörü |

State ile archive klasörünü birlikte yedekleyin. Kod ZIP'ini yeniden açmanız veritabanını silmez. **Linux ve Windows aynı şema revizyonunu** kullanır; fakat canlı Linux kurulumuna Windows test veritabanını doğrudan kopyalamayın. Dashboard’ları `openreporting export-dashboards` / `import-dashboards` ile aktarın.

## 9. İşlevsel sınırlar

- Linux ile aynı platform: dashboard’lar, değişkenler, grup bazlı PDF/Excel/CSV raporlar, zamanlama, denetim ve salt-okunur kaynaklar.
- Sorgu başına item sınırı (veri kaynağı ayarı, varsayılan 500) ve yanıt başına nokta bütçesi (`OPENREPORTING_MAX_SERIES_POINTS`). Aşımda veri sessizce kırpılmaz; sorgu açık bir hatayla reddedilir.
- Linux'un `flock` kilidi Windows'ta `msvcrt` byte-range lock ile karşılanır; ikisi de tek worker kuralını uygular.
- Türkçe PDF için Windows Arial/Segoe UI gibi yerel TrueType fontları kullanılır; font yoksa yanlış karakter üretmek yerine hata döner.
- Windows'taki IANA saat dilimi adları için `tzdata` Python bağımlılığı vardır; `Europe/Istanbul` dahil takvimler aynı kodu çalıştırır.
- Çok kiracılı (müşteri bazlı) erişim, SSO/OIDC ve yüksek erişilebilirlik (HA) henüz **uygulanmadı**.

