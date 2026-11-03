"""Host-free shell boundary tests: package routing and fail-closed SELinux decisions."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash")
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required; never launch WSL implicitly")


def run(script, tmp_path):
    env = dict(os.environ, TEST_LOG=str(tmp_path / "calls"), OPENREPORTING_INSTALL_LOG=str(tmp_path / "install.log"))
    source = "set -euo pipefail\nsource deploy/lib.sh\nsource deploy/platform.sh\n"
    return subprocess.run([BASH, "-c", source + script], cwd=ROOT, env=env, text=True, encoding="utf-8", capture_output=True, timeout=15)


@pytest.mark.parametrize("version", ["8.10", "9.4", "9.8", "10.0", "10"])
def test_oracle_platform_uses_native_paths(version, tmp_path):
    result = run(f'detect_platform ol {version}\nprintf "%s\\n" "$PLATFORM_FAMILY" "$NGINX_SITE" "$TLS_KEY_DEFAULT"', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["oracle", "/etc/nginx/conf.d/openreporting.conf", "/etc/pki/tls/private/openreporting.key"]


@pytest.mark.parametrize("id", ["ubuntu", "debian", "kali"])
def test_debian_family_uses_debian_paths(id, tmp_path):
    result = run(f'detect_platform {id} 2025.3\nprintf "%s\\n" "$PLATFORM_FAMILY" "$NGINX_SITE"', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["debian", "/etc/nginx/sites-available/openreporting.conf"]


@pytest.mark.parametrize("id,version", [("ol", "7.9"), ("ol", "8.9"), ("ol", "8"), ("ol", "9.3"), ("ol", "9"), ("ol", "11.0"), ("unknown", "9")])
def test_unsupported_os_fails_before_any_package_action(id, version, tmp_path):
    result = run(f'detect_platform {id} {version}\nprintf mutation > "$TEST_LOG"', tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / "calls").exists()


@pytest.mark.parametrize(
    "id,version,package_command,python_package",
    [
        ("ol", "8.10", "dnf", "python3.12-pip"),
        ("ol", "9.4", "dnf", "python3.12-pip"),
        ("ol", "10.0", "dnf", "python3-pip"),
        ("ubuntu", "24.04", "apt", "python3-venv"),
        ("kali", "2025.3", "apt", "python3-venv"),
    ],
)
def test_distribution_package_selection_without_host_install(id, version, package_command, python_package, tmp_path):
    result = run(
        'dnf(){ printf "dnf %s\\n" "$*" >> "$TEST_LOG"; }; apt-get(){ printf "apt %s\\n" "$*" >> "$TEST_LOG"; };\n'
        f"detect_platform {id} {version}\ninstall_platform_packages 1 0",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "calls").read_text()
    assert all(line.startswith(package_command + " ") for line in calls.splitlines())
    assert python_package in calls and "nginx" in calls


# apt-get mock: simulation prints $PLAN, update prints $UPDATE, install fails when $FAIL_INSTALL is set.
MOCK_APT = """
apt-get(){
  case " $* " in
    *" -s "*) printf '%b' "${PLAN:-}" ;;
    *" update "*) printf 'apt update %s\n' "$*" >> "$TEST_LOG"; printf '%b' "${UPDATE:-}" ;;
    *) printf 'apt install %s\n' "$*" >> "$TEST_LOG"; [ -z "${FAIL_INSTALL:-}" ] || { echo 'E: Sub-process /usr/bin/dpkg returned an error code (1)'; return 100; } ;;
  esac
}
detect_platform kali 2025.3
"""


def test_apt_plan_counts_new_upgraded_and_removed(tmp_path):
    plan = "Inst nginx (1.26 Kali:kali-rolling [amd64])\nInst libc6 [2.40-1] (2.41-1 Kali)\nConf nginx\nRemv python3-old [1.0]\n"
    result = run(f"printf '%b' '{plan}' | apt_plan_counts", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1", "1", "1"]


def test_apt_removal_is_blocked_before_anything_is_installed(tmp_path):
    result = run(MOCK_APT + "PLAN='Inst nginx (1)\nRemv apache2 [2]\n' install_platform_packages 1 0", tmp_path)
    assert result.returncode != 0
    assert "kaldırılacak: apache2" in result.stderr and "--allow-package-removal" in result.stderr
    assert "apt install" not in (tmp_path / "calls").read_text()


def test_apt_removal_proceeds_only_with_explicit_opt_in(tmp_path):
    result = run(MOCK_APT + "PLAN='Remv apache2 [2]\n' install_platform_packages 1 0 1", tmp_path)
    assert result.returncode == 0, result.stderr
    installs = [line for line in (tmp_path / "calls").read_text().splitlines() if line.startswith("apt install")]
    assert len(installs) == 2 and "--download-only" in installs[0] and "Acquire::Retries=3" in installs[1]


def test_failed_index_fetch_stops_with_mirror_guidance(tmp_path):
    result = run(
        MOCK_APT + "UPDATE='W: Failed to fetch http://http.kali.org/dists/kali-rolling/InRelease  Connection failed\n' install_platform_packages 1 0", tmp_path
    )
    assert result.returncode != 0
    assert "Failed to fetch" in result.stderr and "otomatik DEĞİŞTİRİLMEDİ" in result.stderr and "https://" in result.stderr
    assert "apt install" not in (tmp_path / "calls").read_text()


def test_install_failure_names_stage_exit_code_and_log_tail(tmp_path):
    result = run(MOCK_APT + "FAIL_INSTALL=1 install_platform_packages 1 0", tmp_path)
    assert result.returncode != 0
    assert "Başarısız adım" in result.stderr and "çıkış kodu 100" in result.stderr and "dpkg returned an error" in result.stderr
    assert str(tmp_path / "install.log") in result.stderr


MOCK_SELINUX = """
detect_platform ol 9.4
getenforce(){ echo Enforcing; }
getsebool(){ echo 'httpd_can_network_relay --> off'; }
semanage(){ if [ "$*" = 'port -l' ]; then echo 'http_port_t tcp 80, 443, 88100'; else printf 'port:%s\\n' "$*" >> "$TEST_LOG"; fi; }
setsebool(){ printf 'boolean:%s\\n' "$*" >> "$TEST_LOG"; }
setenforce(){ exit 99; }
"""


def test_selinux_never_disables_enforcement_and_requires_opt_in(tmp_path):
    result = run(MOCK_SELINUX + "configure_selinux_proxy 0", tmp_path)
    assert result.returncode != 0 and "8810/http_port_t" in result.stderr
    assert not (tmp_path / "calls").exists()


def test_selinux_opt_in_only_labels_backend_and_enables_relay(tmp_path):
    result = run(MOCK_SELINUX + "configure_selinux_proxy 1", tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == ["port:port -a -t http_port_t -p tcp 8810", "boolean:-P httpd_can_network_relay on"]


def test_selinux_prepared_host_needs_no_mutation(tmp_path):
    result = run(
        MOCK_SELINUX
        + """
getsebool(){ echo 'httpd_can_network_relay --> on'; }
semanage(){ echo 'http_port_t tcp 80, 443, 8800-8820'; }
configure_selinux_proxy 0
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "calls").exists()


def test_selinux_port_conflict_stops_without_overwriting_or_enabling_relay(tmp_path):
    result = run(
        MOCK_SELINUX
        + """
semanage(){ if [ "$*" = 'port -l' ]; then echo 'other_port_t tcp 8810'; else return 1; fi; }
configure_selinux_proxy 1
""",
        tmp_path,
    )
    assert result.returncode != 0 and "8810 etiketi" in result.stderr
    assert not (tmp_path / "calls").exists()


@pytest.mark.parametrize("version,has_proc,has_logs", [(239, False, False), (243, False, False), (246, False, True), (247, True, True), (252, True, True)])
def test_systemd_compatibility_preserves_core_isolation(version, has_proc, has_logs, tmp_path):
    result = run(f"render_unit deploy/systemd/openreporting-web.service {version}", tmp_path)
    assert result.returncode == 0, result.stderr
    assert ("ProtectProc=invisible" in result.stdout) == has_proc
    assert ("ProtectKernelLogs=true" in result.stdout) == has_logs
    for setting in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectClock=true",
        "CapabilityBoundingSet=",
        "User=openreporting",
        "ReadWritePaths=/var/lib/openreporting",
    ):
        assert setting in result.stdout
