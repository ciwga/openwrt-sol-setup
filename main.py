#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenWrt Ağ Yöneticisi - CLI

Raspberry Pi 5 üzerinde OpenWrt için yapılandırma betikleri üretir.

Çıktı klasör yapısı:
  kurulum_dosyalari/   → Kurulum betikleri
  kaldirma_dosyalari/  → Kaldırma betikleri
"""

import os
import sys
from typing import Dict, List, Tuple, Callable, Optional
from manager import Manager
from utils import write_safe_file, print_ssh_usage, detect_platform, FABRIC_AVAILABLE, deploy_and_run_via_fabric

BANNER: str = """
============================================================
  OpenWrt Ağ Yöneticisi
  Raspberry Pi 5 | Superonline | TV+ IPTV
============================================================
  WAN | TV+ | DNS | Zapret | Tailscale | IPv6 | Disk | Fan
============================================================
"""


KURULUM_DIR: str = "kurulum_dosyalari"
KALDIRMA_DIR: str = "kaldirma_dosyalari"


def ensure_dirs() -> None:
    """
    Betiklerin kaydedileceği çıktı klasörlerini güvenli bir şekilde oluşturur.
    Klasörler halihazırda mevcutsa hata vermez.
    """
    os.makedirs(KURULUM_DIR, exist_ok=True)
    os.makedirs(KALDIRMA_DIR, exist_ok=True)


def save_setup(filename: str, content: str, router_ip: str) -> None:
    """
    Kurulum betiğini kurulum klasörüne kaydeder ve SSH kullanım talimatını ekrana basar.

    Args:
        filename (str): Kaydedilecek dosyanın adı.
        content (str): Dosyanın içeriği (Shell betiği).
        router_ip (str): Kullanıcının yönlendirici (router) IP adresi.
    """
    path = os.path.join(KURULUM_DIR, filename)
    write_safe_file(path, content)
    print_ssh_usage(path, router_ip)


def save_uninstall(filename: str, content: str) -> None:
    """
    Kaldırma betiğini ilgili klasöre kaydeder.

    Args:
        filename (str): Kaydedilecek kaldırma betiğinin adı.
        content (str): Kaldırma betiğinin içeriği.
    """
    path = os.path.join(KALDIRMA_DIR, filename)
    write_safe_file(path, content)


def ask(prompt: str, default: str = "", validate_fn: Optional[Callable] = None, validate_key: str = "") -> str:
    """
    Kullanıcıdan terminal üzerinden veri girmesini ister. Hatalı girişte tekrar sorar.

    Args:
        prompt (str): Kullanıcıya gösterilecek soru metni.
        default (str): Kullanıcı boş geçerse kullanılacak varsayılan değer.
        validate_fn (Optional[Callable]): Girdiyi doğrulayacak fonksiyon.
        validate_key (str): Doğrulama fonksiyonuna iletilecek anahtar kelime.

    Returns:
        str: Kullanıcının girdiği ve doğrulanmış veri.
    """
    while True:
        try:
            display = f"{prompt} [{default}]: " if default else f"{prompt}: "
            val = input(display).strip()
            final = val if val else default
            # Doğrulama fonksiyonu verilmişse girdiyi kontrol et
            if validate_fn and validate_key:
                final = validate_fn(validate_key, final)
            return final
        except ValueError as e:
            print(f"  Hata: {e}")
        except (EOFError, KeyboardInterrupt):
            print("\n\nİşlem iptal edildi.")
            sys.exit(0)


def ask_choice(prompt: str, options: List[str]) -> str:
    """
    Kullanıcıdan belirli seçenekler arasından birini seçmesini ister.

    Args:
        prompt (str): Kullanıcıya gösterilecek soru metni.
        options (List[str]): Geçerli seçeneklerin listesi.

    Returns:
        str: Kullanıcının geçerli seçimi.
    """
    while True:
        try:
            val = input(prompt).strip()
            if val in options:
                return val
            print(f"  Geçerli seçenekler: {', '.join(options)}")
        except (EOFError, KeyboardInterrupt):
            print("\n\nİşlem iptal edildi.")
            sys.exit(0)


# ---- Bilgi Toplama İşlevleri ----

def collect_wan_config(mgr: Manager) -> Dict[str, str]:
    """
    WAN (PPPoE) kurulumu için kullanıcıdan gerekli bilgileri toplar.

    Args:
        mgr (Manager): Konfigürasyon ve varsayılan değerler yöneticisi.

    Returns:
        Dict[str, str]: Toplanan WAN yapılandırma bilgileri.
    """
    d = mgr.wan_defaults
    config: Dict[str, str] = {}

    print("\n--- PPPoE WAN Ayarları ---")
    print("  Fabrika sıfırlaması sonrası ilk kurulum.\n")

    config["pppoe_user"] = ask("PPPoE Kullanıcı Adı")
    config["pppoe_pass"] = ask("PPPoE Şifre")
    config["wan_phys"] = ask("WAN Fiziksel Port", str(d["wan_phys"]))

    print("\n--- WAN MAC Adresi (Klonlama) ---")
    print("  Superonline gibi bazı ISP'ler internete çıkış (PPPoE) için")
    print("  orijinal modemin WAN MAC adresini arayabilir.")
    print("  Emin değilseniz veya gerekmiyorsa boş bırakabilirsiniz.\n")
    config["wan_mac_address"] = ask(
        "Orijinal Modem WAN MAC Adresi (boş bırakılabilir)", 
        str(d.get("wan_mac_address", "")), 
        mgr.validate_input, 
        "wan_mac_address"
    )

    print("\n--- WAN VLAN ---")
    print("  Superonline: PPPoE VLAN yok, bölgeye göre değişebilir. Yoksa boş bırakın.")
    print("  Türk Telekom: PPPoE, VLAN 35 üzerinden — '35' girin.")
    print("  Diğer ISP: ISP'nizin WAN VLAN ID'sini girin, yoksa boş bırakın.\n")
    config["wan_vlan_id"] = ask("WAN VLAN ID (boş=VLAN yok)", str(d.get("wan_vlan_id", "")))
    config["lan_ip"] = ask("LAN IP", "192.168.1.1", mgr.validate_input, "lan_ip")

    print("\n--- Firewall Zone İsimleri ---")
    config["wan_zone_name"] = ask("WAN Zone ismi", str(d.get("wan_zone_name", "wan")))
    config["lan_zone_name"] = ask("LAN Zone ismi", str(d.get("lan_zone_name", "lan")))

    print("\n--- IPv6 ---")
    print("  otomatik: ISP destekliyorsa IPv6 aktif olur")
    print("  açık:     IPv6 zorla aktif (DHCPv6 + SLAAC)")
    print("  kapalı:   IPv6 tamamen devre dışı\n")
    config["ipv6_mode"] = ask("IPv6 modu (otomatik/açık/kapalı)", "kapalı")
    while config["ipv6_mode"] not in ("otomatik", "açık", "kapalı"):
        print("  Geçerli: otomatik, açık, kapalı")
        config["ipv6_mode"] = ask("IPv6 modu", "kapalı")

    print("\n--- USB Ethernet (r8152 / RTL8156B) Fix ---")
    print("  Bu yongalar (özellikle RPi5'te) yeniden başlatma sonrası uykuya dalabilir.")
    print("  Adaptörünüz varsa arayüz adını girin (örn: eth1).")
    print("  İhtiyacınız yoksa 'yok' yazın.\n")
    config["usb_eth"] = ask("USB Ethernet arayüzü", str(d["usb_eth"]), mgr.validate_input, "usb_eth")

    print("\n--- DNS ---")
    print("  Boş bırakırsanız ISP DNS kullanılır. Örnek: 1.1.1.1,8.8.8.8\n")
    config["custom_dns"] = ask("DNS sunucuları (virgülle ayırın, boş=ISP)", "")

    config["timezone"] = str(d["timezone"])
    config["timezone_code"] = str(d["timezone_code"])
    return config


def collect_tvplus_config(mgr: Manager) -> Dict[str, str]:
    """
    TV+ IPTV modülü için kullanıcıdan gerekli bilgileri toplar.

    İki mod desteklenir:
      - bridge (L2 Köprü): TV portu direkt ISP VLAN'ına köprülenir (Önerilen).
      - proxy (IGMP Proxy): Geleneksel routing/firewall üzerinden geçirilir.

    Args:
        mgr (Manager): Konfigürasyon yöneticisi.

    Returns:
        Dict[str, str]: IPTV yapılandırma değerleri sözlüğü.
    """
    d = mgr.tvplus_defaults
    config: Dict[str, str] = {}

    print("\n--- TV+ IPTV Ayarları ---")
    print("\n--- IPTV Mimari Seçimi ---")
    print("  'bridge': (ÖNERİLEN) OpenWrt aradan çekilir, TV direkt santrale bağlanır. SIFIR DONMA.")
    print("  'proxy' : (ESKİ) Yönlendirme ve Firewall üzerinden geçer (Sadece tek portlular için).\n")
    
    config["iptv_mode"] = ask("IPTV Modu (bridge/proxy)", "bridge", mgr.validate_input, "iptv_mode")

    for key, label in [
        ("vlan_id",       "VLAN ID"),
        ("wan_interface", "WAN Fiziksel Portu (ISP'ye bağlı, örn: eth1)"),
        ("lan_interface", "LAN Mantıksal Arayüzü (örn: lan)"),
        ("lan_zone",      "LAN Firewall Zone"),
        ("iptv_interface","IPTV Arayüz İsmi"),
        ("tv_zone_name",  "TV Firewall Zone İsmi"),
        ("igmp_version",  "IGMP Sürümü (2/3)"),
    ]:
        config[key] = ask(label, str(d.get(key, "")), mgr.validate_input, key)

    if config["iptv_mode"] in ("bridge", "köprü"):
        print("\n--- IPTV Kimlik Bilgileri (MAC Klonlama) ---")
        print("  ✅ [BİLGİ] 'bridge' (L2 Köprü) modunda DHCP Option klonlamaya gerek yoktur.")
        print("  Ancak Superonline santrali (OLT) VLAN arayüzünde TV kutunuzun veya Orijinal Modemin")
        print("  MAC adresini arıyorsa, aşağıya yazabilirsiniz. Gerekmiyorsa BOŞ bırakın.\n")
        config["mac_address"] = ask("VLAN MAC Adresi (boş bırakılabilir)", "", mgr.validate_input, "mac_address")
        
        # Gereksiz DHCP verileri temiz bırakılır
        config["client_id"] = ""
        config["vendor_id"] = ""
        config["host_name"] = ""
    else:
        print("\n--- IPTV Kimlik Bilgileri ---")
        print("  NOT: 'proxy' modunda ISP'yi kandırmak için orijinal modem bilgileri gerekebilir.\n")
        for key, label in [
            ("mac_address",   "Orijinal Modem MAC Adresi"),
            ("client_id",     "Option 61 Client ID"),
            ("vendor_id",     "Option 60 Vendor Class ID"),
            ("host_name",     "Option 12 Hostname"),
        ]:
            config[key] = ask(label, str(d.get(key, "")), mgr.validate_input, key)

    print("\n--- Fiziksel Port (İzolasyon / Köprü) ---")
    print("  TV kutusuna bağlı ayrı bir portunuz (örn: eth2) varsa girin.")
    print("  'bridge' modunda bu port direkt ISP'ye köprülenir (Zorunludur).")
    print("  'proxy' modunda TV izole subnet'e alınır.\n")
    tv_eth2 = ask("TV için ayrı port var mı? Arayüz adı (örn: eth2, yoksa boş bırakın)", "")
    config["tv_eth2_port"] = tv_eth2.strip()

    print("\n--- IPTV IPv6 ---")
    print("  Sorun yaşıyorsanız 'hayır' seçin.\n")
    config["iptv_ipv6"] = ask("IPTV IPv6 aktif olsun mu? (evet/hayır)", str(d["iptv_ipv6"]))

    print("\n--- IPTV MTU ---")
    print("  'otomatik' bırakırsanız OpenWrt kendi belirler.\n")
    config["mtu_value"] = ask("IPTV MTU (otomatik/1492/1500)", str(d["mtu_value"]))

    if config["iptv_mode"] not in ("bridge", "köprü"):
        print("\n--- Dinamik Multicast (Altnet) Tespiti ---")
        print("  IGMP yayınları için 169.254.x.x ve DHCP rotalarındaki IP'ler")
        print("  bulunduğunda sisteme yük bindirmeden IGMP Proxy'e otomatik eklenir.\n")
        config["auto_multicast"] = ask(
            "Otomatik Altnet Ekleme aktif olsun mu? (evet/hayır)",
            str(d["auto_multicast"]),
            mgr.validate_input,
            "auto_multicast",
        )
    else:
        config["auto_multicast"] = "hayır"

    for key in ("timezone", "timezone_code", "ntp_server"):
        config[key] = str(d[key])
    return config


def collect_dns_config(mgr: Manager) -> Dict[str, str]:
    """
    DNS Zinciri kurulumu için gerekli yapılandırma bilgilerini alır.

    Args:
        mgr (Manager): Konfigürasyon yöneticisi.

    Returns:
        Dict[str, str]: DNS yapılandırma değerleri.
    """
    d = mgr.dns_defaults
    config: Dict[str, str] = {}
    print("\n--- DNS Zinciri Ayarları ---")
    config["lan_ip"] = ask("Router LAN IP", str(d["lan_ip"]), mgr.validate_input, "lan_ip")
    
    print("\n--- DoH (DNS-over-HTTPS) Motoru Seçimi ---")
    print("  AdGuard Home internete çıkarken DoH kullanır. Bunu kimin yapacağını seçin:")
    print("  hdnsp : (Varsayılan) Ayrı bir https-dns-proxy servisi çalışır.")
    print("  agh   : DoH işlemini doğrudan AdGuard Home yapar (Daha sade sistem, tavsiye edilen).\n")
    config["doh_backend"] = ask("DoH Motoru (hdnsp/agh)", str(d.get("doh_backend", "hdnsp")), mgr.validate_input, "doh_backend")

    config["agh_dns_port"] = ask("AdGuard DNS portu", str(d["agh_dns_port"]), mgr.validate_input, "agh_dns_port")
    config["agh_web_port"] = ask("AdGuard Web portu", str(d["agh_web_port"]), mgr.validate_input, "agh_web_port")
    
    if config["doh_backend"] == "hdnsp":
        config["hdnsp_port"] = ask("HTTPS-DNS-Proxy portu", str(d["hdnsp_port"]), mgr.validate_input, "hdnsp_port")
    else:
        config["hdnsp_port"] = str(d["hdnsp_port"])

    print("\n--- TV+ Kutusu DNS Bypass ---")
    print("  TV+ kutusunun superonlinetv.com gibi domainleri ISP DNS üzerinden")
    print("  çözmesi gerekir. AdGuard bu domainler için ISP DNS'e yönlendirir.")
    print("  TV+ KURULU DEĞİLSE veya bypass istemiyorsanız boş bırakın.\n")
    print("  NOT: TV kutusu izole subnet'teyse (192.168.2.x) IP'yi ona göre girin.")
    print("       Örn: MAC=AA:BB:CC:DD:EE:FF, IP=192.168.2.X\n")
    config["tvplus_stb_mac"] = ask("TV+ kutusu MAC (boş=bypass yok)", str(d["tvplus_stb_mac"]), mgr.validate_input, "tvplus_stb_mac")
    
    if config["tvplus_stb_mac"]:
        # IP önerisi: TV izole subnet'teyse (192.168.2.x) oradan, değilse LAN'dan
        default_ip = config["lan_ip"].rsplit(".", 1)[0] + ".200" if config["lan_ip"] else "192.168.1.200"
        config["tvplus_stb_ip"] = ask("TV+ sabit IP", default_ip, mgr.validate_input, "tvplus_stb_ip")
        config["isp_dns"] = ask("ISP DNS", str(d.get("isp_dns", "213.74.0.1,213.74.1.1")), mgr.validate_input, "isp_dns")
        if not config["isp_dns"]:
            config["isp_dns"] = "213.74.0.1,213.74.1.1"
    else:
        # MAC boş olsa bile ISP DNS mutlaka dolu olmalıdır, yoksa AdGuard config dosyası YAML hatası verir ve çöker!
        config["tvplus_stb_ip"] = ""
        config["isp_dns"] = str(d.get("isp_dns", "213.74.0.1,213.74.1.1"))
        print("    > DNS bypass atlandı — TV+ kurulu değil veya bypass gerekmiyor. (Split-DNS için varsayılan kullanılacak)")
        
    return config


def collect_zapret_config(mgr: Manager) -> Dict[str, str]:
    """
    Zapret (DPI Bypass) modülü için alan adları listesini kullanıcıdan alır.

    Args:
        mgr (Manager): Konfigürasyon yöneticisi.

    Returns:
        Dict[str, str]: Zapret yapılandırma değerleri.
    """
    config: Dict[str, str] = {}
    print("\n--- Zapret DPI Bypass ---")
    config["zapret_domains"] = ask("Alan adları (boşlukla ayırın)", mgr.zapret_defaults["zapret_domains"])
    return config


def collect_tailscale_config(mgr: Manager) -> Dict[str, str]:
    """
    Tailscale VPN yapılandırma bilgilerini toplar.

    Args:
        mgr (Manager): Konfigürasyon yöneticisi.

    Returns:
        Dict[str, str]: Tailscale yapılandırma değerleri.
    """
    d = mgr.tailscale_defaults
    config: Dict[str, str] = {}
    print("\n--- Tailscale VPN ---")
    config["tailscale_auth_key"] = ask("Auth Key (tskey-auth-...)", "")

    print("\n--- Subnet Yayını (advertise-routes) ---")
    print("  Ev LAN\'ına uzaktan erişmek için subnet(leri) yazın.")
    print("  Birden fazla subnet varsa virgülle ayırın.")
    print("  Örnek tek subnet : 192.168.1.0/24")
    print("  Örnek çift subnet: 192.168.1.0/24,192.168.2.0/24  (TV izole subnet de varsa)\n")
    config["lan_subnet"] = ask("Advertise edilecek subnet(ler)", str(d["lan_subnet"]))

    config["advertise_exit_node"] = ask("Exit node? (evet/hayır)", str(d["advertise_exit_node"]))

    print("\n--- DNS ---")
    print("  evet: Tailscale MagicDNS kullan (Tailscale admin\'dan DNS ayarlanır)")
    print("  hayır: Mevcut DNS zincirini koru (AdGuard varsa önerilen)\n")
    config["accept_dns"] = ask("Tailscale DNS kabul et? (evet/hayır)", str(d["accept_dns"]))

    print("\n--- Wake-on-LAN (WoL) ---")
    print("  etherwake kurulursa Tailscale üzerinden SSH ile uzaktan cihaz açabilirsiniz.")
    print("  Kullanım: ssh root@<tailscale-ip> \"etherwake -i br-lan <MAC_ADRESI>\"\n")
    config["wol_enabled"] = ask("WoL için etherwake kurulsun mu? (evet/hayır)", str(d.get("wol_enabled", "hayır")))

    if config["accept_dns"] == "hayır":
        print("\n--- MagicDNS (opsiyonel) ---")
        print("  accept-dns=hayır seçildi. Tailscale hostname\'lerini çözmek için")
        print("  tailnet adınızı girin (örn: myname.ts.net veya tail1234.ts.net).")
        print("  Tailscale admin → DNS → Tailnet DNS name\'de bulabilirsiniz.")
        print("  Boş bırakırsanız sadece IP ile bağlanabilirsiniz.\n")
        config["tailnet_name"] = ask("Tailnet adı (boş=MagicDNS devre dışı)", str(d.get("tailnet_name", "")))
    else:
        config["tailnet_name"] = ""
    return config


# ---- Betik Üretme ve Kaydetme İşlevleri ----

def generate_and_save(mgr: Manager, config: Dict[str, str], mode: str) -> None:
    """
    Kullanıcının seçtiği mod ve konfigürasyona göre ilgili betikleri üretir ve diske yazar.

    Args:
        mgr (Manager): Betik oluşturma fonksiyonlarını barındıran yönetici.
        config (Dict[str, str]): Kullanıcıdan toplanan yapılandırma sözlüğü.
        mode (str): Seçilen işlem/kurulum modu.
    """
    ensure_dirs()
    rip = config.get("lan_ip", "192.168.1.1")

    # Seçilen moda göre ilgili betik üretimi ve kaydedilmesi sağlanır
    if mode == "wan":
        save_setup("setup_wan.sh", mgr.generate_wan_setup(config), rip)
        save_uninstall("uninstall_wan.sh", mgr.generate_wan_uninstall(config))

    if mode in ("tvplus", "all"):
        save_setup("setup_tvplus.sh", mgr.generate_tvplus_setup(config), rip)
        save_uninstall("uninstall_tvplus.sh", mgr.generate_tvplus_uninstall(config))

    if mode in ("dns", "all"):
        save_setup("setup_dns_chain.sh", mgr.generate_dns_setup(config), rip)
        save_uninstall("uninstall_dns_chain.sh", mgr.generate_dns_uninstall(config))

    if mode in ("zapret", "all"):
        save_setup("setup_zapret.sh", mgr.generate_zapret_setup(config), rip)
        save_uninstall("uninstall_zapret.sh", mgr.generate_zapret_uninstall(config))

    if mode == "tailscale":
        save_setup("setup_tailscale.sh", mgr.generate_tailscale_setup(config), rip)
        save_uninstall("uninstall_tailscale.sh", mgr.generate_tailscale_uninstall(config))

    if mode == "all":
        save_setup("setup_all.sh", mgr.generate_full_setup(config), rip)
        save_uninstall("uninstall_all.sh", mgr.generate_full_uninstall(config))

    if mode == "ipv6":
        save_setup("disable_ipv6.sh", mgr.generate_ipv6_disable(config), rip)
        save_setup("enable_ipv6.sh", mgr.generate_ipv6_enable(config), rip)

    if mode == "disk":
        save_setup("expand_disk.sh", mgr.generate_disk_expand(config), rip)
        save_setup("disk_status.sh", mgr.generate_disk_status(config), rip)

    if mode == "fan":
        save_setup("setup_argon_fan.sh", mgr.generate_argon_fan_setup(config), rip)
        save_uninstall("uninstall_argon_fan.sh", mgr.generate_argon_fan_uninstall(config))

    if mode == "usb_fix":
        save_setup("setup_usb_fix.sh", mgr.generate_usb_fix_setup(config), rip)
        save_uninstall("uninstall_usb_fix.sh", mgr.generate_usb_fix_uninstall(config))


# ---- CLI Ana Metodu ----

def run_cli() -> None:
    print(BANNER)
    plat = detect_platform()
    if plat == "openwrt":
        print("  UYARI: Bu araç bilgisayarınızda (yerel makinede) çalıştırılmalıdır!\n")

    mgr = Manager()

    print("NE YAPMAK İSTİYORSUNUZ?")
    print("  1. WAN (PPPoE + IPv6 + USB Fix)           ← Önce bu kurulmalı")
    print("  2. TV+ IPTV")
    print("  3. DNS Zinciri (AdGuard + DoH)")
    print("  4. Zapret (DPI Bypass)")
    print("  5. Tailscale VPN")
    print("  6. Komple Kurulum (WAN + TV+ + DNS + Zapret + Tailscale)")
    print("  7. Disk Genişletme (Raspberry Pi 5)")
    print("  8. Argon ONE V3 Fan Kontrol")
    print("  9. IPv6 Kapat / Aç")
    print("  10. USB Ethernet Boot Fix (Sadece Servisi Kur / Güncelle)")
    print("")
    print("  ÖNEMLİ: Tüm modüller internet gerektirir — 1 olmadan diğerleri çalışmaz.")
    print("  Hepsini tek seferde kurmak için: 6 (Komple Kurulum)")
    print("")
    print("  NOT (rtl8152 USB Adaptör): Eğer adaptörünüz önceden takılıysa,")
    print("  ilk kurulumda sürücünün doğru tetiklenmesi için Ethernet kablosunu")
    print("  cihaz açıldıktan sonra BİR DEFAYA MAHSUS söküp tekrar takınız.")
    print("")

    choice = ask_choice("Seçiminiz (1-10): ", [str(i) for i in range(1, 11)])
    config: Dict[str, str] = {}

    if choice in ("1", "6"): config.update(collect_wan_config(mgr))
    if choice in ("2", "6"): config.update(collect_tvplus_config(mgr))
    if choice in ("3", "6"): config.update(collect_dns_config(mgr))
    if choice in ("4", "6"): config.update(collect_zapret_config(mgr))
    if choice in ("5", "6"): config.update(collect_tailscale_config(mgr))

    for key, val in mgr.defaults.items():
        if key not in config:
            config[key] = str(val)

    try:
        mgr.check_conflicts(config)
    except ValueError as e:
        print(f"\n  YAPILANDIRMA HATASI: {e}")
        sys.exit(1)

    mode_map = {
        "1": "wan", "2": "tvplus", "3": "dns", "4": "zapret", "5": "tailscale", 
        "6": "all", "7": "disk", "8": "fan", "9": "ipv6", "10": "usb_fix"
    }
    mode = mode_map[choice]
    
    print("\n" + "=" * 50)
    generate_and_save(mgr, config, mode)
    print("=" * 50)

    rip = config.get("lan_ip", "192.168.1.1")
    print(f"\n  Dosyalar yerel diske oluşturuldu:")
    print(f"    📁 {KURULUM_DIR}/   → Kurulum betikleri")
    print(f"    📁 {KALDIRMA_DIR}/  → Kaldırma betikleri")

    # Kullanıcıya seçenek sunmak için dinamik yapılandırma
    available_scripts: List[Tuple[str, str, str]] = []

    if mode == "wan":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_wan.sh"), "setup_wan.sh", "WAN Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_wan.sh"), "uninstall_wan.sh", "WAN Kaldırma Betiği")
        ]
    elif mode == "tvplus":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_tvplus.sh"), "setup_tvplus.sh", "TV+ Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_tvplus.sh"), "uninstall_tvplus.sh", "TV+ Kaldırma Betiği")
        ]
    elif mode == "dns":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_dns_chain.sh"), "setup_dns_chain.sh", "DNS Zinciri Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_dns_chain.sh"), "uninstall_dns_chain.sh", "DNS Zinciri Kaldırma Betiği")
        ]
    elif mode == "zapret":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_zapret.sh"), "setup_zapret.sh", "Zapret Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_zapret.sh"), "uninstall_zapret.sh", "Zapret Kaldırma Betiği")
        ]
    elif mode == "tailscale":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_tailscale.sh"), "setup_tailscale.sh", "Tailscale Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_tailscale.sh"), "uninstall_tailscale.sh", "Tailscale Kaldırma Betiği")
        ]
    elif mode == "all":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_all.sh"), "setup_all.sh", "Komple Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_all.sh"), "uninstall_all.sh", "Komple Kaldırma Betiği")
        ]
    elif mode == "ipv6":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "enable_ipv6.sh"), "enable_ipv6.sh", "IPv6 Açma Betiği"),
            (os.path.join(KURULUM_DIR, "disable_ipv6.sh"), "disable_ipv6.sh", "IPv6 Kapatma Betiği")
        ]
    elif mode == "disk":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "expand_disk.sh"), "expand_disk.sh", "Disk Genişletme Betiği"),
            (os.path.join(KURULUM_DIR, "disk_status.sh"), "disk_status.sh", "Disk Durumu Raporlama Betiği")
        ]
    elif mode == "fan":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_argon_fan.sh"), "setup_argon_fan.sh", "Argon Araçları (Fan) Kurulum Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_argon_fan.sh"), "uninstall_argon_fan.sh", "Argon Fan Kaldırma Betiği")
        ]
    elif mode == "usb_fix":
        available_scripts = [
            (os.path.join(KURULUM_DIR, "setup_usb_fix.sh"), "setup_usb_fix.sh", "USB Fix Kurulum/Güncelleme Betiği"),
            (os.path.join(KALDIRMA_DIR, "uninstall_usb_fix.sh"), "uninstall_usb_fix.sh", "USB Fix Kaldırma Betiği")
        ]

    # Otomasyon akışı ve betik seçimi
    if available_scripts:
        print("\n  🤖 [SSH Otomasyon] İşlem yapılacak betiği seçin:")
        for idx, (path, name, desc) in enumerate(available_scripts, start=1):
            print(f"    {idx}. {name} ({desc})")
        print("    0. Hiçbiri (Manuel işlem yapacağım)")

        valid_script_choices = [str(i) for i in range(len(available_scripts) + 1)]
        script_ans = ask_choice("\n  Seçiminiz: ", valid_script_choices)

        if script_ans != "0":
            selected_idx = int(script_ans) - 1
            selected_path, selected_name, selected_desc = available_scripts[selected_idx]

            if FABRIC_AVAILABLE:
                auto_ans = ask_choice(f"\n  🤖 [SSH Otomasyon] '{selected_name}' router'a ({rip}) gönderilip hemen ÇALIŞTIRILSIN MI? (E/h): ", ["E", "e", "H", "h", ""])
                if auto_ans.lower() in ('e', ''):
                    deploy_and_run_via_fabric(rip, selected_path)
                else:
                    print(f"\n  [Manuel İşlem] Terminalden çalıştırmak için kopyalayın:")
                    print_ssh_usage(selected_path, rip)
            else:
                print("\n  [Bilgi] 'fabric' modülü yüklü olmadığı için otomatik gönderim devre dışı.")
                print("          (Yüklemek için terminalde: pip install fabric)")
                print(f"\n  [Manuel İşlem] Terminalden çalıştırmak için kopyalayın:")
                print_ssh_usage(selected_path, rip)
        else:
            print("\n  [Bilgi] Otomatik gönderim iptal edildi. Oluşturulan betikleri manuel kullanabilirsiniz.")

    if mode == "disk":
        print("\n  ⚠️ NOT: Kalıcı oto-genişletme servisi kuruldu. Sistem arka planda diski genişletip")
        print("          otomatik olarak yeniden başlatacaktır. Sysupgrade sonrasında da bu işlem otonom gerçekleşir.")


if __name__ == "__main__":
    try:
        run_cli()
    except KeyboardInterrupt:
        print("\n\nİşlem iptal edildi.")
        sys.exit(0)
    except Exception as ex:
        print(f"\nKritik Hata: {ex}")
        sys.exit(1)