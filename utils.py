# -*- coding: utf-8 -*-
"""Dosya işlemleri, SSH bilgi toplama ve yardımcı fonksiyonlar."""

import os
import stat
import subprocess
import platform
import shutil
from pathlib import Path
from typing import Optional, Dict


def write_safe_file(filename: str, content: str) -> None:
    """
    İçeriği belirtilen dosyaya güvenli bir şekilde yazar.
    Klasör dışına çıkılmasına (Directory Traversal) izin vermez.

    Args:
        filename (str): Kaydedilecek dosyanın tam veya göreceli yolu.
        content (str): Dosyaya yazılacak içerik.
    """
    try:
        target_path = Path(filename).resolve()
        current_working_dir = Path.cwd().resolve()

        is_safe_path = False
        try:
            # Sadece geçerli dizin veya altındaki dosyalara izin ver
            if hasattr(target_path, 'is_relative_to'):
                is_safe_path = target_path.is_relative_to(current_working_dir)
            else:
                is_safe_path = str(target_path).startswith(str(current_working_dir))
        except Exception:
            is_safe_path = False

        if not is_safe_path:
            print(f"  GÜVENLİK HATASI: Hedef yol çalışma dizini dışında: '{target_path}'")
            return

        # Üst klasör yoksa oluştur
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with target_path.open("w", encoding="utf-8", newline='\n') as f:
            f.write(content)

        # Linux/macOS ortamında dosyalara çalıştırılabilirlik(executable) izni ver
        if hasattr(os, "chmod") and hasattr(stat, "S_IEXEC"):
            try:
                st = os.stat(target_path)
                os.chmod(target_path, st.st_mode | stat.S_IEXEC)
            except OSError:
                pass

        print(f"  [+] {target_path}")

    except PermissionError:
        print(f"  HATA: '{filename}' dosyasına yazma izniniz yok.")
    except IOError as e:
        print(f"  HATA ({filename}): {e}")


def print_ssh_usage(filename: str, router_ip: str = "192.168.1.1") -> None:
    """
    Oluşturulan betiği SSH üzerinden çalıştırmak için kullanım ipuçlarını terminale basar.

    Args:
        filename (str): SSH komutuyla gönderilecek dosyanın yolu.
        router_ip (str, optional): Hedef cihazın IP adresi. Defaults to "192.168.1.1".
    """
    try:
        local_path = Path.cwd().resolve() / filename
        remote = f"/tmp/{Path(filename).name}"
        cmd = (f'cat "{local_path}" | ssh root@{router_ip} '
               f'"cat > {remote} && chmod +x {remote} && {remote}"')
        print(f"      {cmd}\n")
    except Exception:
        pass


def ssh_cmd(host: str, cmd: str, user: str = "root", timeout: int = 10) -> str:
    """
    Hedef yönlendirici üzerinde SSH komutu çalıştırır ve çıktısını döndürür.

    Args:
        host (str): Hedef IP adresi.
        cmd (str): Çalıştırılacak shell komutu.
        user (str, optional): SSH kullanıcı adı. Defaults to "root".
        timeout (int, optional): Zaman aşımı süresi (saniye). Defaults to 10.

    Returns:
        str: Çalıştırılan komutun standart çıktısı (stdout).
    """
    ssh_binary = shutil.which("ssh")
    if not ssh_binary:
        return ""
    try:
        # Etkileşimsiz mod (BatchMode=yes) ile güvenli bir şekilde komutu çalıştır
        full_cmd = [
            ssh_binary, "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            f"{user}@{host}", cmd
        ]
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def gather_router_info(host: str) -> Optional[Dict[str, str]]:
    """
    SSH ile yönlendiriciye (router) bağlanır ve donanım/yapılandırma bilgilerini toplar.

    Args:
        host (str): Router IP adresi.

    Returns:
        Optional[Dict[str, str]]: Toplanan bilgilerin bulunduğu sözlük. Bağlantı kurulamazsa None döner.
    """
    print(f"\n  {host} adresine SSH ile bağlanılıyor...")
    test = ssh_cmd(host, "echo ok")
    if test != "ok":
        print(f"  SSH bağlantısı başarısız ({host}).")
        return None

    print("  SSH OK. Bilgiler toplanıyor...\n")
    info: Dict[str, str] = {}

    arch = ssh_cmd(host, "opkg print-architecture 2>/dev/null | grep -v 'all\\|noarch' | tail -1 | awk '{print $2}'")
    info["arch"] = arch or "aarch64_cortex-a76"

    ver = ssh_cmd(host, r"cat /etc/openwrt_release 2>/dev/null | grep DISTRIB_RELEASE | cut -d\"'\" -f2")
    info["openwrt_version"] = ver or "24.10"

    wan_dev = ssh_cmd(host, "uci -q get network.wan.device")
    info["wan_device"] = wan_dev or "eth0"

    lan_ip = ssh_cmd(host, "uci -q get network.lan.ipaddr")
    info["lan_ip"] = lan_ip or "192.168.1.1"

    fo = ssh_cmd(host, "uci -q get firewall.@defaults[0].flow_offloading")
    info["flow_offloading"] = fo or "0"

    return info


def detect_platform() -> str:
    """
    Betiklerin çalıştığı mevcut platformu (İşletim Sistemini) tespit eder.

    Returns:
        str: İşletim sistemi tanımı ("openwrt", "linux", "macos", "windows" veya "unknown").
    """
    system = platform.system().lower()
    if system == "linux":
        if os.path.exists("/etc/openwrt_release"):
            return "openwrt"
        return "linux"
    elif system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    return "unknown"