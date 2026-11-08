# 17 — Herkese açık depo ve Linux kurulum dokümanı

- Depo herkese açıldı; `LICENSE` (MIT) eklendi. Paketlenmiş ECharts kendi Apache-2.0 lisansıyla kalır.
- Açmadan önce 123 commit'in tamamı (silinmiş dosyalar dahil) özel anahtar, token, parola ataması, genel IP ve iç alan adı için tarandı; sır veya kurum bilgisi bulunmadı.
- `kurulum.sh`, Docker yoksa resmi depodan kurar: apt (Ubuntu, Debian, Kali), dnf (RHEL, Oracle Linux, Rocky, Alma, Fedora; Podman onayla kaldırılır), zypper (SUSE). CI, 14 dağıtım imajında bu kurulumu dener (`deploy/docker/ci-distro-docker.sh`).
- `docs/KURULUM-LINUX.md` ve `docs/OpenReporting-Linux-Kurulum.pdf`: kontrol listesi, dağıtıma göre hazırlık, proxy/SSL denetimi, Kubernetes (k3s ve PostgreSQL hazırlığı dahil), sorun giderme. İkisi aynı içeriktir.
- Test sınırı: uçtan uca kurulum Ubuntu 24.04'te, Kubernetes kind kümesinde test edilir; k3s ve PostgreSQL VM adımları CI'da yoktur.
