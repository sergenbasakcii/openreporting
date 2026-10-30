# Oracle Linux kurulumu ve doğrulama kapsamı

OpenReporting Ubuntu'ya bağlı değildir. Uygulama Python 3.11+ kullanır; dağıtım farkı
paket kurulumunda, nginx yollarında ve host güvenlik politikasındadır. Bu sürüm
`install-linux.sh` ortak akışını ve `install-oracle-linux.sh` girişini ekler.
Ubuntu/Debian girişi korunur; mevcut Windows önizlemesi değiştirilmez.

## Hedef matris

| Ortam | Hedef Python | Kabul kapsamı |
| --- | --- | --- |
| Oracle Linux 8.10, x86_64 | Resmî paralel python3.11 | Oracle container paket/API/nginx/unit kontrolü; tam VM ve SELinux Enforcing kabulü ayrıca gerekli |
| Oracle Linux 9, x86_64 | Resmî paralel python3.11 | Aynı kapsam; güncel resmî AppStream depoları gerekli |
| Oracle Linux 10, x86_64 | Dağıtım python3, 3.12+ | Aynı kapsam; işletim sisteminin CPU gereksinimleri geçerli |
| ARM/aarch64 | Uygun Python 3.11+ wheel'leri | Bu matris için gerçek ARM kabulü yapılmadı |
| Oracle Linux 7 ve daha eski / 8.10 öncesi | — | Yerel kurulum betiği reddeder; uyumluluk iddia edilmez |
| FIPS etkin host | — | Mevcut scrypt/kripto kapanışı doğrulanmadı; kurulum FIPS/kripto politikasını değiştirmeden durur |

CI `oraclelinux:8`, `:9`, `:10` resmî kullanıcı alanı imajlarını ayrı geçici container'larda
çalıştırır; kullanılan gerçek RepoDigest kanıta yazılır. Bu imajlar sabitlenmiş release
provenance veya tam host/kernel testi sayılmaz. CI Ubuntu çekirdeğini paylaşır; systemd
PID1 ile boot, UEK/RHCK, gerçek SELinux enforcing ve firewalld arayüz politikası **henüz
doğrulanmış değildir**. Başarılı CI gerçek kurum kabulünün yerine geçmez.

## Kurulum

Kaynakları ayrı bir dizine çıkarın. Örnek, mevcut şirket bilgisi içermez:

```bash
sudo ./deploy/install-oracle-linux.sh --domain openreporting.example.com \
  --cert /etc/pki/tls/certs/openreporting.pem \
  --key /etc/pki/tls/private/openreporting.key \
  --configure-selinux --admin yonetici
```

`--open-firewall` yalnız etkin firewalld'in varsayılan zone'unda HTTP/HTTPS hizmetlerini
açar; arayüzün doğru zone'a bağlılığını işletmeci doğrular. Firewall etkin değilse
kurulum onu başlatmaz. Üretimde kurumun imzalı TLS sertifikası gerekir; `--self-signed`
yalnız kontrollü deneme içindir. Mevcut nginx siteleri kaldırılmaz; 80/443 ve hostname
çakışmaları kurulum öncesi incelenmelidir. Uygulamaya ait olmayan aynı adlı site dosyası
üzerine yazılmaz. TLS dosyalarının kurumca onaylı PKI yollarında bulunması önerilir.

OL8/9'da sistem Python'u/alternatives/DNF Python'u değiştirilmez; `python3.11` yan yana
kurulur. OL10 dağıtımın `python3` sürümünü kullanır. Paketler DNF ve mevcut resmî
depolardan alınır; PPA, ULN aboneliği veya yeni ücretli hizmet eklenmez. `--python`
uygun başka bir yorumlayıcı seçebilir. Uygulama kendi venv'inde hashli runtime/build
kilitleriyle kurulur; eksik uyumlu wheel'de sessiz kaynak derlemesi yapılmaz.

## SELinux ve servis koruması

SELinux kapatılmaz veya Permissive moda geçirilmez. Enforcing/Permissive durumda nginx
relay ve backend 8810 port etiketi hazır değilse, `--configure-selinux` olmadan kurulum
açık hatayla durur. Opt-in yalnız `httpd_can_network_relay` boolean'ını kalıcı etkinleştirir
ve 8810/tcp'yi `http_port_t` olarak ekler. Başka bir açık port türünün üzerine `-m`
ile yazmaz. Bu boolean HTTP servis etki alanı için ortaktır; kurum SELinux yöneticisinin
politikasıyla uyumlu olmalıdır. Genel `httpd_can_network_connect`, `setenforce 0` veya
kripto politikasını LEGACY'ye çekme kullanılmaz.

SELinux özel uygulama servis etki alanı/policy modülü sağlanmış değildir. Gerçek hostta
AVC kayıtları ve servislerin çalışması ayrıca kabul edilmelidir; hatayı gidermek için
SELinux'u kapatmayın veya bütün AVC'leri körlemesine `audit2allow` ile izinlendirmeyin.

systemd >=239 gerekir. OL8'in eski systemd sürümünde bulunmayan `ProtectHostname`,
`ProtectKernelLogs`, `ProtectProc`, `ProcSubset` yalnız sürüm sınırlarına göre çıkarılır;
kurulum bunu bildirir. `NoNewPrivileges`, ayrı servis kullanıcısı, salt okunur sistem,
sınırlı yazma yolları, boş capability seti ve syscall kısıtları korunur. Bu eski hostun
Ubuntu24/OL9/10 ile aynı ek korumaları sunduğu iddia edilmez.

## İşletim ve kabul

Aynı `upgrade.sh`, yedek/restore, anahtar bakımı ve yönetim wrapper'ı kullanılır.
Servis yolları `/opt/openreporting`, `/etc/openreporting`, `/var/lib/openreporting` ve
`/var/backups/openreporting` olarak kalır. nginx site yolu Oracle'da `conf.d/` olur.
Kaldırma, paylaşılan SELinux/firewall izinlerini otomatik geri almaz. Yeniden kurulum
mevcut state'in anahtarı kayıpsa yeni anahtar üretmez; önce eşleşen anahtar kurtarılmalıdır.

Tam kurumsal canlı kabulünden önce Oracle VM/fiziksel sunucuda:

- SELinux Enforcing ile web/worker, reboot sonrası systemd açılışı ve hizmet kısıtları;
- Kurum TLS/CA, LDAP/MFA, SMTP ve gerçek readonly kaynak hesapları;
- PDF/XLSX/CSV, zamanlama, ayrı anahtar ile yedekten dönüş ve başarısız yükseltme geri dönüşü;
- Firewall zone'u, erişim sınırları, kapasite ve kurum işletim sahipliği doğrulanmalıdır.

Bu işletim sistemi desteği, henüz açık olan klasör/tenant ACL ve diğer
[kurumsal kabul eksiklerini](ENTERPRISE_REVIEW.md) kapatmış sayılmaz.

Kaynaklar: [Oracle Python paketleri](https://yum.oracle.com/oracle-linux-python.html),
[OL10 Python](https://docs.oracle.com/en/operating-systems/oracle-linux/10/python/python-AboutPython.html),
[Oracle nginx ve SELinux relay](https://docs.oracle.com/en-us/iaas/oracle-linux/balancing/balancing-setting-up-load-balancing-by-using-nginx.htm),
[systemd direktif sürümleri](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html).
