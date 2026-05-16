# -*- coding: utf-8 -*-
"""
Konfigürasyon yönetimi ve iş mantığı.
"""

import re
import binascii
from typing import Dict, Any, Final, List

from compat import PKG_MANAGER_BLOCK, USB_FIX_SERVICE, OPENWRT_GUARD
from templates_tvplus import TVPLUS_SETUP_TEMPLATE, TVPLUS_L2_SETUP_TEMPLATE, TVPLUS_UNINSTALL_TEMPLATE
from templates_dns import DNS_CHAIN_SETUP_TEMPLATE, DNS_CHAIN_UNINSTALL_TEMPLATE
from templates_zapret import ZAPRET_SETUP_TEMPLATE, ZAPRET_UNINSTALL_TEMPLATE
from templates_tailscale import TAILSCALE_SETUP_TEMPLATE, TAILSCALE_UNINSTALL_TEMPLATE
from templates_wan import WAN_SETUP_TEMPLATE, WAN_UNINSTALL_TEMPLATE
from templates_ipv6 import IPV6_DISABLE_TEMPLATE, IPV6_ENABLE_TEMPLATE
from templates_disk import DISK_EXPAND_TEMPLATE, DISK_STATUS_TEMPLATE, ARGON_FAN_TEMPLATE, ARGON_FAN_UNINSTALL_TEMPLATE

# Girdilerin doğrulanması için derlenmiş düzenli ifadeler
REGEX_VLAN: Final[re.Pattern] = re.compile(r"^\d+$")
REGEX_SAFE_INPUT: Final[re.Pattern] = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]*$")
REGEX_MAC: Final[re.Pattern] = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")
REGEX_CLIENT_ID: Final[re.Pattern] = re.compile(r"^[0-9A-Fa-f:\-]+$")
REGEX_IP: Final[re.Pattern] = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$")
REGEX_PORT: Final[re.Pattern] = re.compile(r"^\d+$")

# Zapret modülü için varsayılan alan adları
DEFAULT_ZAPRET_DOMAINS: Final[List[str]] = [
    "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
    "ggpht.com", "gstatic.com", "googleapis.com", "googleusercontent.com",
    "discord.com", "discord.gg", "discordapp.com", "xcancel.com",
    "protonvpn.com", ".proton.me", "proton.me", "protonweb.com", ".mullvad.net", 
    "mullvad.net", "pastebin.com", "4shared.com", "wikileaks.org", "pages.dev", 
    "google.com", "cloudflare.com", "x.com", "twitter.com", 
    "twimg.com", "t.co", "kick.com", "ttvnw.net", "twitch.tv", 
    "torproject.org", "cloudflare-dns.com", "dns.google", "one.one.one.one",
    "dns.quad9.net", "adguard-dns.io"
]

# Boş bırakılabilir alanların listesi
OPTIONAL_FIELDS: Final[set] = {
    "mac_address", "client_id", "host_name", "zapret_domains", "tv_eth2_port", "iptv_mode", "wan_vlan_id", "tailnet_name", "wol_enabled",
    "tvplus_stb_mac", "tvplus_stb_ip", "isp_dns",
    "tailscale_auth_key", "lan_subnet",
    "pppoe_user", "pppoe_pass", "custom_dns", "usb_eth", "wan_mac_address",
}


class Manager:
    """Tüm bileşenlerin yapılandırma ve script üretim yöneticisi."""

    def __init__(self) -> None:
        """Sınıf başlatıldığında tüm modüllerin varsayılan konfigürasyonlarını ayarlar."""
        self.tvplus_defaults: Dict[str, Any] = {
            "vlan_id": "103",
            "wan_interface": "eth1",
            "lan_interface": "lan",
            "lan_zone": "lan",
            "iptv_interface": "tvplus_iptv",
            "tv_zone_name": "tvplus_iptv_zone",
            "igmp_version": "2",
            "timezone": "Europe/Istanbul",
            "timezone_code": "TRT-3",
            "ntp_server": "cpentp.superonline.net",
            "mac_address": "",
            "client_id": "",
            "vendor_id": "dslforum.org",
            "host_name": "",
            "iptv_ipv6": "hayır",
            "mtu_value": "otomatik",
            "auto_multicast": "evet",
            "iptv_mode": "bridge",          # Default L2 Bridge, en stabil yöntem
            "tv_eth2_port": "",             # Özel port varsa bridge aktifleşir
        }
        self.dns_defaults: Dict[str, Any] = {
            "lan_ip": "192.168.1.1",
            "agh_dns_port": "5353",
            "agh_web_port": "3000",
            "hdnsp_port": "5053",
            "tvplus_stb_mac": "",
            "tvplus_stb_ip": "",
            "isp_dns": "213.74.0.1,213.74.1.1",
        }
        self.zapret_defaults: Dict[str, Any] = {
            "zapret_domains": " ".join(DEFAULT_ZAPRET_DOMAINS),
        }
        self.tailscale_defaults: Dict[str, Any] = {
            "tailscale_auth_key": "",
            "lan_subnet": "192.168.1.0/24",
            "advertise_exit_node": "evet",
            "accept_dns": "hayır",
            "tailnet_name": "",
            "wol_enabled": "hayır",
        }
        self.wan6_defaults: Dict[str, Any] = {
            "ipv6_mode": "kapalı",
        }
        self.wan_defaults: Dict[str, Any] = {
            "pppoe_user": "",
            "pppoe_pass": "",
            "wan_phys": "eth1",
            "wan_vlan_id": "",
            "wan_mac_address": "", # ISP'nin tanıdığı orijinal modem MAC klonlaması
            "custom_dns": "",
            "timezone": "Europe/Istanbul",
            "timezone_code": "TRT-3",
            "usb_eth": "yok",
        }
        
        # Tüm varsayılan ayarları tek bir sözlükte birleştir
        self.defaults: Dict[str, Any] = {
            **self.tvplus_defaults, **self.dns_defaults,
            **self.zapret_defaults, **self.tailscale_defaults,
            **self.wan6_defaults, **self.wan_defaults,
        }

    def validate_input(self, key: str, value: str) -> str:
        """
        Kullanıcı girdisini belirtilen tipe göre doğrular. Güvenlik ve mantıksal kontroller yapar.
        """
        value = value.strip()
        if not value and key not in OPTIONAL_FIELDS:
            raise ValueError(f"'{key}' alanı boş bırakılamaz.")

        if key == "vlan_id":
            if not REGEX_VLAN.match(value):
                raise ValueError("VLAN ID sadece sayısal değer alabilir.")
            if not (1 <= int(value) <= 4094):
                raise ValueError("VLAN ID 1-4094 arasında olmalıdır.")
            return value

        if key == "igmp_version":
            if value not in ("2", "3"):
                raise ValueError("IGMP sadece '2' veya '3' olabilir.")
            return value

        if key == "auto_multicast":
            if value not in ("evet", "hayır"):
                raise ValueError("Lütfen 'evet' veya 'hayır' giriniz.")
            return value

        if key == "iptv_mode":
            if value.lower() not in ("proxy", "bridge", "köprü"):
                raise ValueError("IPTV modu 'proxy' veya 'bridge' olabilir.")
            return "bridge" if value.lower() == "köprü" else value.lower()

        if key in ("mac_address", "tvplus_stb_mac", "wan_mac_address"):
            if not value:
                return ""
            if not REGEX_MAC.match(value):
                raise ValueError("Geçerli MAC: AA:BB:CC:DD:EE:FF")
            return value.lower()

        if key == "client_id":
            if not value:
                return ""
            if not REGEX_CLIENT_ID.match(value):
                raise ValueError("Client ID hex/MAC formatında olmalıdır.")
            return value.replace(":", "").replace("-", "").lower()

        if key in ("vendor_id", "host_name"):
            if not value:
                return ""
            if not re.match(r"^[a-zA-Z0-9_\-\.:]+$", value):
                raise ValueError(f"'{key}' alanında geçersiz karakterler var.")
            return value

        if key in ("lan_ip", "tvplus_stb_ip"):
            if not value:
                return ""
            if not REGEX_IP.match(value):
                raise ValueError("Geçerli IP örneği: 192.168.1.1")
            return value

        if key in ("agh_dns_port", "agh_web_port", "hdnsp_port"):
            if not REGEX_PORT.match(value):
                raise ValueError("Port numarası sadece sayı olabilir.")
            port = int(value)
            if not (1024 <= port <= 65535):
                raise ValueError("Port 1024-65535 arasında olmalıdır.")
            return value

        if key == "isp_dns":
            if not value:
                return ""
            for ip in value.split(","):
                ip = ip.strip()
                if ip and not REGEX_IP.match(ip):
                    raise ValueError(f"Geçersiz DNS IP: {ip}")
            return value

        if key in ("zapret_domains", "usb_eth", "iptv_phy_port", "bridge_name", "bridge_iface"):
            return value

        if not REGEX_SAFE_INPUT.match(value):
            raise ValueError(f"'{key}' alanında geçersiz karakterler var.")
        return value

    def check_conflicts(self, config: Dict[str, str]) -> None:
        """Kullanıcının girdiği yapılandırmada çakışma (conflict) kontrolü yapar."""
        iptv = config.get("iptv_interface", "")
        lan = config.get("lan_interface", "")
        lz = config.get("lan_zone", "")
        tz = config.get("tv_zone_name", "")

        if iptv and lan and iptv == lan:
            raise ValueError("IPTV arayüz ismi LAN ile aynı olamaz!")
        if iptv == "wan":
            raise ValueError("IPTV için 'wan' ismi kullanılamaz.")
        if lz and tz and lz == tz:
            raise ValueError("LAN ve TV zone isimleri aynı olamaz!")

        ports = []
        for pk in ("agh_dns_port", "agh_web_port", "hdnsp_port"):
            pv = config.get(pk, "")
            if pv:
                if pv in ports:
                    raise ValueError(f"Port çakışması: {pv}")
                ports.append(pv)

    # --- TV+ İşlemleri ---
    def generate_tvplus_setup(self, config: Dict[str, str]) -> str:
        """TV+ Kurulum shell betiğini oluşturur."""
        iptv_mode = config.get("iptv_mode", "bridge").strip().lower()
        tv_eth2 = config.get("tv_eth2_port", "").strip()

        # Eğer bridge modu seçildiyse L2 Bridge şablonunu kullan
        if iptv_mode in ("bridge", "köprü"):
            if not tv_eth2:
                raise ValueError("L2 Bridge modu için fiziksel bir TV portu (örn: eth2) belirtilmelidir!")
            script = TVPLUS_L2_SETUP_TEMPLATE
        else:
            # Proxy modu
            script = TVPLUS_SETUP_TEMPLATE

        # Hostname hex encode
        raw = config.get("host_name", "")
        hostname_hex = binascii.hexlify(raw.encode("utf-8")).decode("utf-8") if raw else ""
        script = script.replace("<<HOST_NAME_HEX>>", hostname_hex)
        script = script.replace("<<USB_FIX_SERVICE>>", USB_FIX_SERVICE)

        # Proxy modunda eth2 subnet izolasyonu istenmişse
        if iptv_mode not in ("bridge", "köprü"):
            if tv_eth2:
                eth2_block = self._render_eth2_block(tv_eth2, config)
            else:
                eth2_block = '    echo "    > Ayrı TV portu belirtilmedi — TV br-lan üzerinden proxy edilecek."'
            script = script.replace("<<TV_ETH2_BLOCK>>", eth2_block)

        # Değişkenleri yerleştir
        for key, val in config.items():
            script = script.replace(f"<<{key.upper()}>>", str(val))

        return self._render(script)

    def _render_eth2_block(self, eth2_port: str, config: Dict[str, str]) -> str:
        """TV için izole subnet bloğu üretir (Yalnızca proxy modu için)."""
        tv_zone = config.get("tv_zone_name", "tvplus_iptv_zone")
        return f"""    # --- İzole TV Subnet ({eth2_port}) ---
    echo "    > {eth2_port} bulundu — TV izole subnet (192.168.2.0/24) kuruluyor..."

    # br-lan'dan çıkar
    LAN_DEV_IDX=0
    while uci -q get "network.@device[$LAN_DEV_IDX]" >/dev/null 2>&1; do
        DEV_NAME=$(uci -q get "network.@device[$LAN_DEV_IDX].name" 2>/dev/null)
        if [ "$DEV_NAME" = "br-lan" ]; then
            uci -q del_list "network.@device[$LAN_DEV_IDX].ports"="{eth2_port}" 2>/dev/null || true
            break
        fi
        LAN_DEV_IDX=$((LAN_DEV_IDX+1))
    done

    uci delete network.br_tv 2>/dev/null || true
    uci set network.br_tv=device
    uci set network.br_tv.name='br-tv'
    uci set network.br_tv.type='bridge'
    uci add_list network.br_tv.ports='{eth2_port}'
    uci set network.br_tv.igmp_snooping='1'

    uci delete network.tv_lan 2>/dev/null || true
    uci set network.tv_lan=interface
    uci set network.tv_lan.device='br-tv'
    uci set network.tv_lan.proto='static'
    uci set network.tv_lan.ipaddr='192.168.2.1'
    uci set network.tv_lan.netmask='255.255.255.0'

    uci delete dhcp.tv_lan 2>/dev/null || true
    uci set dhcp.tv_lan=dhcp
    uci set dhcp.tv_lan.interface='tv_lan'
    uci set dhcp.tv_lan.start='100'
    uci set dhcp.tv_lan.limit='50'
    uci set dhcp.tv_lan.leasetime='12h'

    uci delete firewall.tv_lan_zone 2>/dev/null || true
    uci set firewall.tv_lan_zone=zone
    uci set firewall.tv_lan_zone.name='tv_lan'
    uci set firewall.tv_lan_zone.network='tv_lan'
    uci set firewall.tv_lan_zone.input='ACCEPT'
    uci set firewall.tv_lan_zone.output='ACCEPT'
    uci set firewall.tv_lan_zone.forward='REJECT'
    uci set firewall.tv_lan_zone.masq='1'

    uci delete firewall.tv_lan_to_wan 2>/dev/null || true
    uci set firewall.tv_lan_to_wan=forwarding
    uci set firewall.tv_lan_to_wan.src='tv_lan'
    uci set firewall.tv_lan_to_wan.dest='wan'

    uci delete firewall.tv_lan_to_iptv 2>/dev/null || true
    uci set firewall.tv_lan_to_iptv=forwarding
    uci set firewall.tv_lan_to_iptv.src='tv_lan'
    uci set firewall.tv_lan_to_iptv.dest='{tv_zone}'

    uci delete firewall.tv_lan_igmp_rule 2>/dev/null || true
    uci set firewall.tv_lan_igmp_rule=rule
    uci set firewall.tv_lan_igmp_rule.name='Allow-IGMP-TV-Iso'
    uci set firewall.tv_lan_igmp_rule.src='{tv_zone}'
    uci set firewall.tv_lan_igmp_rule.dest='tv_lan'
    uci set firewall.tv_lan_igmp_rule.proto='igmp'
    uci set firewall.tv_lan_igmp_rule.dest_ip='224.0.0.0/4'
    uci set firewall.tv_lan_igmp_rule.target='ACCEPT'

    uci delete firewall.tv_lan_udp_rule 2>/dev/null || true
    uci set firewall.tv_lan_udp_rule=rule
    uci set firewall.tv_lan_udp_rule.name='Allow-UDP-TV-Iso'
    uci set firewall.tv_lan_udp_rule.src='{tv_zone}'
    uci set firewall.tv_lan_udp_rule.dest='tv_lan'
    uci set firewall.tv_lan_udp_rule.proto='udp'
    uci set firewall.tv_lan_udp_rule.dest_ip='224.0.0.0/4'
    uci set firewall.tv_lan_udp_rule.target='ACCEPT'

    DS_IDX=0
    while uci -q get "igmpproxy.@phyint[$DS_IDX]" >/dev/null 2>&1; do
        if [ "$(uci -q get igmpproxy.@phyint[$DS_IDX].direction 2>/dev/null)" = "downstream" ]; then
            uci set igmpproxy.@phyint[$DS_IDX].network='tv_lan'
            uci set igmpproxy.@phyint[$DS_IDX].zone='tv_lan'
            break
        fi
        DS_IDX=$((DS_IDX+1))
    done

    for domain in superonline.net superonline.com superonlinetv.com ims.superonline.com; do
        uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
        uci add_list dhcp.@dnsmasq[0].rebind_domain="$domain"
    done
"""

    def generate_tvplus_uninstall(self, config: Dict[str, str]) -> str:
        """TV+ Kaldırma shell betiğini oluşturur."""
        script = TVPLUS_UNINSTALL_TEMPLATE
        script = script.replace("<<IPTV_INTERFACE>>", config.get("iptv_interface", "tvplus_iptv"))
        script = script.replace("<<TV_ZONE_NAME>>", config.get("tv_zone_name", "tvplus_iptv_zone"))
        script = script.replace("<<VLAN_ID>>", config.get("vlan_id", "103"))
        return self._render(script)

    def generate_dns_setup(self, config: Dict[str, str]) -> str:
        """DNS Zinciri Kurulum shell betiğini oluşturur."""
        script = DNS_CHAIN_SETUP_TEMPLATE
        for ph, key in [("<<LAN_IP>>", "lan_ip"), ("<<AGH_DNS_PORT>>", "agh_dns_port"),
                        ("<<AGH_WEB_PORT>>", "agh_web_port"), ("<<HDNSP_PORT>>", "hdnsp_port"),
                        ("<<TVPLUS_STB_MAC>>", "tvplus_stb_mac"),
                        ("<<TVPLUS_STB_IP>>", "tvplus_stb_ip"), ("<<ISP_DNS>>", "isp_dns")]:
            script = script.replace(ph, config.get(key, ""))
        return self._render(script)

    def generate_dns_uninstall(self, config: Dict[str, str]) -> str:
        """DNS Zinciri Kaldırma shell betiğini döndürür."""
        return self._render(DNS_CHAIN_UNINSTALL_TEMPLATE)

    # --- Zapret İşlemleri ---
    def generate_zapret_setup(self, config: Dict[str, str]) -> str:
        """Zapret DPI Bypass kurulum betiğini oluşturur."""
        script = ZAPRET_SETUP_TEMPLATE
        script = script.replace("<<ZAPRET_DOMAINS>>",
                                config.get("zapret_domains", " ".join(DEFAULT_ZAPRET_DOMAINS)))
        return self._render(script)

    def generate_zapret_uninstall(self, config: Dict[str, str]) -> str:
        """Zapret kaldırma betiğini döndürür."""
        return self._render(ZAPRET_UNINSTALL_TEMPLATE)

    # --- Tailscale İşlemleri ---
    def generate_tailscale_setup(self, config: Dict[str, str]) -> str:
        """Tailscale VPN kurulum betiğini oluşturur."""
        script = TAILSCALE_SETUP_TEMPLATE
        for ph, key in [("<<LAN_SUBNET>>", "lan_subnet"),
                        ("<<TAILSCALE_AUTH_KEY>>", "tailscale_auth_key"),
                        ("<<ADVERTISE_EXIT_NODE>>", "advertise_exit_node"),
                        ("<<ACCEPT_DNS>>", "accept_dns"),
                        ("<<TAILNET_NAME>>", "tailnet_name"),
                        ("<<WOL_ENABLED>>", "wol_enabled"),
                        ("<<AGH_WEB_PORT>>", "agh_web_port")]:
            script = script.replace(ph, config.get(key, ""))
        return self._render(script)

    def generate_tailscale_uninstall(self, config: Dict[str, str]) -> str:
        """Tailscale VPN kaldırma betiğini döndürür."""
        return self._render(TAILSCALE_UNINSTALL_TEMPLATE)

    # --- WAN (PPPoE) İşlemleri ---
    def generate_wan_setup(self, config: Dict[str, str]) -> str:
        """WAN PPPoE kurulum betiğini oluşturur."""
        script = WAN_SETUP_TEMPLATE
        for ph, key in [("<<PPPOE_USER>>", "pppoe_user"), ("<<PPPOE_PASS>>", "pppoe_pass"),
                        ("<<LAN_IP>>", "lan_ip"), ("<<IPV6_MODE>>", "ipv6_mode"),
                        ("<<WAN_PHYS>>", "wan_phys"), ("<<WAN_VLAN_ID>>", "wan_vlan_id"),
                        ("<<WAN_MAC_ADDRESS>>", "wan_mac_address"),
                        ("<<CUSTOM_DNS>>", "custom_dns"),
                        ("<<TIMEZONE>>", "timezone"), ("<<TIMEZONE_CODE>>", "timezone_code"),
                        ("<<USB_ETH>>", "usb_eth")]:
            script = script.replace(ph, config.get(key, ""))

        usb_eth = config.get("usb_eth", "yok")
        if usb_eth and usb_eth != "yok":
            usb_fix_block = f"""\
    echo "    > r8152 boot fix servisi kuruluyor..."
    echo "    > (Tüm r8152 adaptörler otomatik tespit edilir — {usb_eth} dahil)"
    cat << 'EOF_USBFIX' > /etc/init.d/usb-lan-fix
{USB_FIX_SERVICE}
EOF_USBFIX
    chmod +x /etc/init.d/usb-lan-fix
    /etc/init.d/usb-lan-fix enable
    echo "    > /etc/init.d/usb-lan-fix oluşturuldu ve etkinleştirildi."
    echo "    > Boot'ta r8152 olan tüm arayüzler resetlenecek."
"""
        else:
            usb_fix_block = '    echo "    > USB Ethernet fix belirtilmedi, atlandı."'

        script = script.replace("<<USB_FIX_BLOCK>>", usb_fix_block)
        return self._render(script)

    def generate_wan_uninstall(self, config: Dict[str, str]) -> str:
        """WAN PPPoE kaldırma betiğini döndürür."""
        script = WAN_UNINSTALL_TEMPLATE
        # VLAN device temizliği — sadece wan_vlan_id varsa eklenir
        wan_vlan = config.get("wan_vlan_id", "").strip()
        vlan_cleanup = "uci -q delete network.wan_vlan_dev 2>/dev/null || true\n" if wan_vlan and wan_vlan != "0" else ""
        script = script.replace("<<WAN_VLAN_CLEANUP>>", vlan_cleanup)
        return self._render(script)

    # --- IPv6 İşlemleri ---
    def generate_ipv6_disable(self, config: Dict[str, str]) -> str:
        """IPv6 tamamen kapatma betiğini döndürür."""
        return self._render(IPV6_DISABLE_TEMPLATE)

    def generate_ipv6_enable(self, config: Dict[str, str]) -> str:
        """IPv6 tamamen açma betiğini döndürür."""
        return self._render(IPV6_ENABLE_TEMPLATE)

    # --- Disk İşlemleri ---
    def generate_disk_expand(self, config: Dict[str, str]) -> str:
        """Disk genişletme betiğini döndürür."""
        return self._render(DISK_EXPAND_TEMPLATE)

    def generate_disk_status(self, config: Dict[str, str]) -> str:
        """Disk durumunu gösteren betiği döndürür."""
        return self._render(DISK_STATUS_TEMPLATE)

    # --- Argon ONE V3 Fan İşlemleri ---
    def generate_argon_fan_setup(self, config: Dict[str, str]) -> str:
        """Argon Fan Kurulum betiğini döndürür."""
        return self._render(ARGON_FAN_TEMPLATE)

    def generate_argon_fan_uninstall(self, config: Dict[str, str]) -> str:
        """Argon Fan Kaldırma betiğini döndürür."""
        return self._render(ARGON_FAN_UNINSTALL_TEMPLATE)

    # --- Birleşik Kurulum ---
    def generate_full_setup(self, config: Dict[str, str]) -> str:
        """Tüm modülleri içeren kapsamlı kurulum betiğini oluşturur."""
        parts = ["#!/bin/sh",
                 "# Komple Kurulum: WAN + TV+ + DNS Zinciri + Zapret + Tailscale",
                 "set -e", "",
                 'echo "=== KOMPLE KURULUM BAŞLIYOR ==="', ""]
        parts.append('echo "--- ADIM 1/5: WAN (PPPoE + IPv6) ---"')
        parts.append(self._strip_header(self.generate_wan_setup(config)))
        parts.append('echo "--- ADIM 2/5: TV+ IPTV ---"')
        parts.append(self._strip_header(self.generate_tvplus_setup(config)))
        parts.append('echo "--- ADIM 3/5: DNS Zinciri ---"')
        parts.append(self._strip_header(self.generate_dns_setup(config)))
        parts.append('echo "--- ADIM 4/5: Zapret ---"')
        parts.append(self._strip_header(self.generate_zapret_setup(config)))
        parts.append('echo "--- ADIM 5/5: Tailscale VPN ---"')
        parts.append(self._strip_header(self.generate_tailscale_setup(config)))
        parts.append('echo "=== KOMPLE KURULUM TAMAMLANDI ==="')
        return "\n".join(parts)

    def generate_full_uninstall(self, config: Dict[str, str]) -> str:
        """Tüm modülleri kaldıran birleşik betiği oluşturur."""
        parts = ["#!/bin/sh", "# Komple Kaldırma", "",
                 "set -u", "",
                 'echo "=== KOMPLE KALDIRMA ==="']
        parts.append(self._strip_header(self.generate_tailscale_uninstall(config)))
        parts.append(self._strip_header(self.generate_zapret_uninstall(config)))
        parts.append(self._strip_header(self.generate_dns_uninstall(config)))
        parts.append(self._strip_header(self.generate_tvplus_uninstall(config)))
        parts.append(self._strip_header(self.generate_wan_uninstall(config)))
        parts.append('echo "=== KOMPLE KALDIRMA TAMAMLANDI ==="')
        return "\n".join(parts)

    @staticmethod
    def _render(script: str) -> str:
        """Yer tutucuları (placeholder) gerçek kodla değiştirir."""
        script = script.replace("<<PKG_MANAGER_BLOCK>>", PKG_MANAGER_BLOCK)
        script = script.replace("<<OPENWRT_GUARD>>", OPENWRT_GUARD)
        return script

    @staticmethod
    def _strip_header(script: str) -> str:
        """Birleşmiş betiklerde gereksiz başlıkları (shebang) temizler."""
        lines = script.split("\n")
        body = []
        in_header = True
        for line in lines:
            s = line.strip()
            if in_header:
                if s.startswith("#!/") or s.startswith("# == ") or s.startswith("# DOSYA") or \
                   s.startswith("# ACIKLAMA") or s.startswith("# MOD:") or \
                   s.startswith("# KONFIG") or s.startswith("# MIMARI") or s.startswith("# DNS") or \
                   s == "set -e" or s == "set -u" or s == "#" or s == "":
                    continue
                in_header = False
            body.append(line)
        return "\n".join(body)