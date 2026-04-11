# -*- coding: utf-8 -*-
"""Dosya işlemleri, SSH bilgi toplama ve Fabric tabanlı otomasyon fonksiyonları."""

import os
import stat
import subprocess
import platform
import shutil
import getpass
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

try:
    import paramiko
    from fabric import Connection
    from invoke.exceptions import UnexpectedExit
    FABRIC_AVAILABLE = True
except ImportError:
    FABRIC_AVAILABLE = False


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
            if hasattr(target_path, 'is_relative_to'):
                is_safe_path = target_path.is_relative_to(current_working_dir)
            else:
                is_safe_path = str(target_path).startswith(str(current_working_dir))
        except Exception:
            is_safe_path = False

        if not is_safe_path:
            print(f"  GÜVENLİK HATASI: Hedef yol çalışma dizini dışında: '{target_path}'")
            return

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

    except PermissionError:
        print(f"  HATA: '{filename}' dosyasına yazma izniniz yok.")
    except IOError as e:
        print(f"  HATA ({filename}): {e}")


def print_ssh_usage(filename: str, router_ip: str = "192.168.1.1") -> None:
    """
    Oluşturulan betiği manuel olarak SSH üzerinden çalıştırmak için kullanım ipuçlarını basar.
    
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


def deploy_and_run_via_fabric(host: str, local_filepath: str, remote_dir: str = "/tmp") -> bool:
    """
    Fabric kullanarak yerel shell betiğini OpenWrt cihazına aktarır, çalıştırır ve temizler.
    
    Args:
        host (str): Hedef IP adresi.
        local_filepath (str): Gönderilecek yerel dosyanın yolu.
        remote_dir (str): Dosyanın atılacağı uzak sunucu dizini. Varsayılan olarak "/tmp".
        
    Returns:
        bool: İşlem başarılıysa True, aksi halde False.
    """
    if not FABRIC_AVAILABLE:
        print("  [Hata] Fabric kütüphanesi yüklü değil. Kurmak için: pip install fabric")
        return False

    print(f"\n  [SSH Otomasyonu] {host} adresine bağlanılıyor...")
    password = getpass.getpass(f"  root@{host} parolası (şifre yoksa boş bırakıp Enter'a basın): ")
    
    # Paramiko bağlantı ayarları
    connect_kwargs: Dict[str, Any] = {
        "look_for_keys": True,
        "allow_agent": True,
    }
    
    if password:
        connect_kwargs["password"] = password
        
    filename = os.path.basename(local_filepath)
    remote_path = f"{remote_dir}/{filename}"

    try:
        # Yönlendiriciye bağlantı kur
        with Connection(host=host, user="root", connect_kwargs=connect_kwargs) as conn:
            
            if not conn.is_connected:
                conn.open()
                
            print(f"  [+] Bağlantı başarılı! Dosya aktarılıyor: {filename}")
            
            with open(local_filepath, "r", encoding="utf-8") as f:
                script_content = f.read()
            
            execute_fast_ssh_command(conn.client, f"cat > {remote_path}", script_content)
            
            print("  [+] Çalıştırılabilir (executable) yetkisi veriliyor...")
            conn.run(f"chmod +x {remote_path}", hide=True)
            
            print(f"\n{'='*60}\n  BETİK ÇIKTISI BAŞLANGICI\n{'='*60}")
            conn.run(remote_path, pty=True)
            print(f"{'='*60}\n  BETİK ÇIKTISI SONU\n{'='*60}")
            
            print("  [+] Temizlik yapılıyor (Geçici dosya siliniyor)...")
            conn.run(f"rm -f {remote_path}", hide=True)
            
        print("  [✅] Otomatik kurulum işlemi başarıyla tamamlandı!")
        return True
        
    except UnexpectedExit as e:
        print(f"\n  [HATA] Betik çalıştırılırken sunucuda bir hata oluştu. Çıkış Kodu: {e.result.exited}")
        return False
    except Exception as e:
        error_str = str(e)
        print(f"\n  [BAĞLANTI HATASI] Router ile iletişim kurulamadı:")
        print(f"  Ayrıntı: {error_str}")
        
        if "Authentication" in error_str or "authentication methods" in error_str.lower() or "Bad authentication type" in error_str:
            print("\n  💡 ÇÖZÜM İPUCU:")
            print("  1. BOŞ ŞİFRE KISITLAMASI: OpenWrt terminalden (CMD) boş şifre ile erişime izin verse de,")
            print("     kullandığımız Python SSH kütüphanesi (Paramiko) yerel güvenlik politikaları gereği")
            print("     bazı durumlarda şifresiz (none auth) bağlantıları reddedebilir.")
            print("     Çözüm: LuCI (Web) arayüzünden cihaza gecici bir 'root' şifresi belirleyip tekrar deneyin.")
            print("  2. ŞİFRE YANLIŞLIĞI: Eğer zaten şifreniz varsa, klavye düzenine dikkat ederek doğru girdiğinizden emin olun.")
            print("  3. MANUEL KURULUM: SSH kütüphanesi ile uğraşmak istemiyorsanız, betiği iptal edip")
            print("     ekranda verilen komutu kopyalayarak kendi terminalinizden yapıştırabilirsiniz.")
            
        return False


def ssh_cmd(host: str, cmd: str, user: str = "root", timeout: int = 10) -> str:
    """
    Eski alt seviye (subprocess) SSH komut çalıştırıcısı (Geriye uyumluluk için).
    
    Args:
        host (str): Hedef cihazın IP adresi.
        cmd (str): Çalıştırılacak olan komut.
        user (str, optional): Bağlanılacak kullanıcı. Varsayılan 'root'.
        timeout (int, optional): Zaman aşımı süresi (saniye). Varsayılan 10.
        
    Returns:
        str: Komutun stdout çıktısı. Başarısızlıkta boş string döner.
    """
    ssh_binary = shutil.which("ssh")
    if not ssh_binary:
        return ""
    try:
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
    SSH ile yönlendirici (router) üzerinden cihaz ve donanım bilgilerini toplar.
    
    Args:
        host (str): Hedef cihazın IP adresi.
        
    Returns:
        Optional[Dict[str, str]]: Başarılı olursa toplanan bilgilerin sözlüğü, başarısızlıkta None.
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
    Betiklerin çalıştırıldığı mevcut yerel işletim sistemini (OS) tespit eder.
    
    Returns:
        str: İşletim sistemi tanımı ('openwrt', 'linux', 'macos', 'windows' veya 'unknown').
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


def execute_fast_ssh_command(ssh_client: 'paramiko.SSHClient', command: str, input_data: str = "") -> Tuple[str, str]:
    """Uzak sunucuda komut çalıştırır ve büyük verileri maksimum hızda aktarır.
    
    Paramiko'nun varsayılan küçük TCP pencere boyutlarını (window size) ve paket 
    boyutlarını maksimize ederek, 'cat' ile atılan devasa shell betiklerinin
    veya yapılandırma metinlerinin saniyeler içinde aktarılmasını sağlar.
    
    Args:
        ssh_client (paramiko.SSHClient): Aktif ve doğrulanmış SSH bağlantı nesnesi.
        command (str): Uzak sunucuda çalıştırılacak komut (örn: 'cat > /tmp/file.sh').
        input_data (str, optional): Standart girdiye (stdin) basılacak veri. Varsayılan "".
        
    Returns:
        Tuple[str, str]: Komutun standart çıktısı (stdout) ve hata çıktısı (stderr).
        
    Raises:
        RuntimeError: Paramiko kütüphanesi yüklü değilse fırlatılır.
        paramiko.SSHException: SSH kanalı açılamazsa veya komut işletilemezse fırlatılır.
    """
    if not FABRIC_AVAILABLE:
        raise RuntimeError("HATA: Paramiko/Fabric kütüphanesi yüklü değil. 'pip install paramiko' ile kurunuz.")

    transport = ssh_client.get_transport()
    if transport is None or not transport.is_active():
        raise paramiko.SSHException("SSH bağlantısı aktif değil veya transport nesnesi bulunamadı.")

    # Maksimum TCP pencere boyutu (2GB) ve paket boyutu (32KB)
    channel = transport.open_session(window_size=2147483647, max_packet_size=32768)
    
    try:
        channel.exec_command(command)

        if input_data:
            channel.sendall(input_data.encode('utf-8'))
            channel.shutdown_write()

        stdout_file = channel.makefile('r', -1)
        stderr_file = channel.makefile_stderr('r', -1)

        stdout_text = stdout_file.read()
        stderr_text = stderr_file.read()

        return stdout_text, stderr_text

    finally:
        channel.close()