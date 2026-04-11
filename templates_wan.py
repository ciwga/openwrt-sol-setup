# -*- coding: utf-8 -*-
"""PPPoE WAN + IPv6 shell script şablonları.

Fabrika sıfırlaması sonrası ilk kurulum.
PPPoE bağlantısı + IPv6 (otomatik/açık/kapalı) + temel sistem ayarları.
Ayrıca USB-Ethernet (r8152 / RTL8156B) boot asılı kalma sorunu için fix içerir.

Kullanıcıdan alınan bilgiler:
  - PPPoE kullanıcı adı ve şifre
  - IPv6 modu (otomatik/açık/kapalı)
  - LAN IP (varsayılan 192.168.1.1)
  - Zaman dilimi
  - DNS tercihi (ISP / manuel)
  - USB Ethernet arayüzü (varsa r8152 fix için) (örn: eth1)
  - Orijinal Modem WAN MAC Adresi (opsiyonel)
"""

from typing import Final

WAN_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# setup_wan.sh - PPPoE WAN + IPv6 Kurulumu ve USB Fix
# Fabrika sıfırlaması sonrası ilk adım
# ==============================================================================

set -e
set -u

PPPOE_USER="<<PPPOE_USER>>"
PPPOE_PASS="<<PPPOE_PASS>>"
LAN_IP="<<LAN_IP>>"
IPV6_MODE="<<IPV6_MODE>>"
WAN_PHYS="<<WAN_PHYS>>"
WAN_VLAN_ID="<<WAN_VLAN_ID>>"
WAN_MAC_ADDRESS="<<WAN_MAC_ADDRESS>>"
CUSTOM_DNS="<<CUSTOM_DNS>>"
USB_ETH="<<USB_ETH>>"

echo ""
echo "================================================================"
echo "  PPPoE WAN + IPv6 Kurulumu"
echo "  Fabrika sıfırlaması sonrası ilk adım"
echo "================================================================"

# --- 1. YEDEK ---
echo "[1/8] Yedekleme..."
BACKUP_DIR="/root/wan-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
for f in /etc/config/network /etc/config/dhcp /etc/config/firewall /etc/config/system; do
    [ -f "$f" ] && cp -a "$f" "$BACKUP_DIR/"
done
echo "    Yedek: $BACKUP_DIR"

# --- 2. SİSTEM AYARLARI ---
echo "[2/8] Sistem ayarları..."

# Zaman dilimi
uci set system.@system[0].timezone='<<TIMEZONE_CODE>>'
uci set system.@system[0].zonename='<<TIMEZONE>>'
uci commit system

# NTP
uci -q delete system.ntp.server 2>/dev/null || true
uci add_list system.ntp.server='0.openwrt.pool.ntp.org'
uci add_list system.ntp.server='1.openwrt.pool.ntp.org'
uci add_list system.ntp.server='2.openwrt.pool.ntp.org'
uci add_list system.ntp.server='3.openwrt.pool.ntp.org'
uci set system.ntp.enabled='1'
uci commit system
echo "    Zaman dilimi: <<TIMEZONE>>"

# --- 3. WAN PPPoE ---
echo "[3/8] PPPoE WAN..."

# Mevcut WAN'i temizle
uci -q delete network.wan 2>/dev/null || true
uci -q delete network.wan6 2>/dev/null || true

# Dinamik MAC Klonlama (Fiziksel Cihaz Seviyesinde)
if [ -n "$WAN_MAC_ADDRESS" ]; then
    uci -q delete network.wan_phy_dev 2>/dev/null || true
    uci set network.wan_phy_dev=device
    uci set network.wan_phy_dev.name="$WAN_PHYS"
    uci set network.wan_phy_dev.macaddr="$WAN_MAC_ADDRESS"
    echo "    WAN Fiziksel MAC Klonlandı: $WAN_MAC_ADDRESS"
fi

# WAN VLAN (opsiyonel — Türk Telekom için VLAN 35, Superonline için boş. Bölgeye göre değişebilir.)
if [ -n "$WAN_VLAN_ID" ] && [ "$WAN_VLAN_ID" != "0" ]; then
    WAN_DEV_NAME="${WAN_PHYS}.${WAN_VLAN_ID}"
    uci delete network.wan_vlan_dev 2>/dev/null || true
    uci set network.wan_vlan_dev=device
    uci set network.wan_vlan_dev.name="$WAN_DEV_NAME"
    uci set network.wan_vlan_dev.type='8021q'
    uci set network.wan_vlan_dev.ifname="$WAN_PHYS"
    uci set network.wan_vlan_dev.vid="$WAN_VLAN_ID"
    [ -n "$WAN_MAC_ADDRESS" ] && uci set network.wan_vlan_dev.macaddr="$WAN_MAC_ADDRESS"
    echo "    WAN: $WAN_DEV_NAME (VLAN $WAN_VLAN_ID)"
else
    WAN_DEV_NAME="$WAN_PHYS"
    echo "    WAN: $WAN_DEV_NAME (VLAN yok)"
fi

# PPPoE interface oluştur
uci set network.wan=interface
uci set network.wan.proto='pppoe'
uci set network.wan.device="$WAN_DEV_NAME"
uci set network.wan.username="$PPPOE_USER"
uci set network.wan.password="$PPPOE_PASS"
uci set network.wan.keepalive='5 3'
uci set network.wan.mtu='1492'
uci set network.wan.ipv6='auto'
[ -n "$WAN_MAC_ADDRESS" ] && uci set network.wan.macaddr="$WAN_MAC_ADDRESS"

# DNS ayarı
if [ -n "$CUSTOM_DNS" ]; then
    uci set network.wan.peerdns='0'
    uci -q delete network.wan.dns 2>/dev/null || true
    for dns in $(echo "$CUSTOM_DNS" | tr ',' ' '); do
        uci add_list network.wan.dns="$dns"
    done
    echo "    DNS: $CUSTOM_DNS"
else
    uci set network.wan.peerdns='1'
    echo "    DNS: ISP (otomatik)"
fi

echo "    PPPoE: $PPPOE_USER / MTU:1492"

# --- 4. LAN ---
echo "[4/8] LAN..."

uci set network.lan.ipaddr="$LAN_IP"
uci set network.lan.netmask='255.255.255.0'

# DHCP ayarları
uci set dhcp.lan.start='100'
uci set dhcp.lan.limit='150'
uci set dhcp.lan.leasetime='12h'

echo "    LAN: $LAN_IP/24"

# --- 5. IPv6 ---
echo "[5/8] IPv6 ($IPV6_MODE)..."

if [ "$IPV6_MODE" = "kapalı" ]; then
    # IPv6 tamamen kapat
    uci -q delete network.wan6 2>/dev/null || true
    uci set network.wan.ipv6='0'
    uci set network.lan.ipv6='0'
    uci -q delete network.lan.ip6assign 2>/dev/null || true
    uci -q delete network.lan.delegate 2>/dev/null || true

    # DHCPv6 / RA kapat
    uci -q delete dhcp.lan.dhcpv6 2>/dev/null || true
    uci -q delete dhcp.lan.ra 2>/dev/null || true
    uci set dhcp.lan.ra_default='0'

    # Kernel disable
    cat > /etc/sysctl.d/99-ipv6.conf << 'SYSEOF'
net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1
SYSEOF
    sysctl -p /etc/sysctl.d/99-ipv6.conf 2>/dev/null || true
    # IPv6 kapalı ise odhcpd gereksiz (odhcp6c SOLICIT spam'i önlenir)
    /etc/init.d/odhcpd stop 2>/dev/null || true
    /etc/init.d/odhcpd disable 2>/dev/null || true
    echo "    IPv6: KAPALI (kernel dahil)"

elif [ "$IPV6_MODE" = "açık" ]; then
    # IPv6 aktif (DHCPv6 + SLAAC)
    uci set network.wan6=interface
    uci set network.wan6.proto='dhcpv6'
    uci set network.wan6.device='@wan'
    uci set network.wan6.reqaddress='try'
    uci set network.wan6.reqprefix='auto'

    uci set network.wan.ipv6='1'
    uci set network.lan.ipv6='1'
    uci set network.lan.ip6assign='60'
    uci set network.lan.delegate='1'

    uci set dhcp.lan.dhcpv6='server'
    uci set dhcp.lan.ra='server'
    uci set dhcp.lan.ra_default='1'
    uci set dhcp.lan.ra_management='1'

    # Firewall wan zone'una wan6 ekle
    CURRENT_NET=$(uci -q get firewall.@zone[1].network 2>/dev/null || echo "wan")
    if ! echo "$CURRENT_NET" | grep -q "wan6"; then
        uci add_list firewall.@zone[1].network='wan6'
    fi

    rm -f /etc/sysctl.d/99-ipv6.conf 2>/dev/null || true
    sysctl -w net.ipv6.conf.all.disable_ipv6=0 2>/dev/null || true
    echo "    IPv6: AÇIK (DHCPv6 + SLAAC)"

else
    # Otomatik (varsayılan OpenWrt davranışı)
    uci set network.wan6=interface
    uci set network.wan6.proto='dhcpv6'
    uci set network.wan6.device='@wan'
    uci set network.wan6.reqaddress='try'
    uci set network.wan6.reqprefix='auto'

    uci set network.wan.ipv6='auto'
    uci set network.lan.ipv6='auto'
    uci set network.lan.ip6assign='60'
    uci set network.lan.delegate='1'

    uci set dhcp.lan.dhcpv6='server'
    uci set dhcp.lan.ra='server'
    uci set dhcp.lan.ra_default='1'

    CURRENT_NET=$(uci -q get firewall.@zone[1].network 2>/dev/null || echo "wan")
    if ! echo "$CURRENT_NET" | grep -q "wan6"; then
        uci add_list firewall.@zone[1].network='wan6'
    fi

    rm -f /etc/sysctl.d/99-ipv6.conf 2>/dev/null || true
    echo "    IPv6: OTOMATİK"
fi

# --- 6. FIREWALL ---
echo "[6/8] Firewall..."

# MSS clamping (PPPoE için önemli)
uci set firewall.@defaults[0].synflood_protect='1'
uci set firewall.@defaults[0].input='ACCEPT'
uci set firewall.@defaults[0].output='ACCEPT'
uci set firewall.@defaults[0].forward='REJECT'

# WAN zone
uci set firewall.@zone[1].input='REJECT'
uci set firewall.@zone[1].output='ACCEPT'
uci set firewall.@zone[1].forward='REJECT'
uci set firewall.@zone[1].masq='1'
uci set firewall.@zone[1].mtu_fix='1'

uci commit firewall
echo "    Firewall OK (MSS fix aktif)"

# --- 7. USB ETHERNET FIX (r8152 / RTL8156B) ---
echo "[7/8] USB Ethernet (r8152) Fix..."
<<USB_FIX_BLOCK>>
# --- 8. COMMIT VE RESTART ---
echo "[8/8] Servisler yeniden başlatılıyor..."

uci commit network
uci commit dhcp

/etc/init.d/network restart 2>/dev/null || true
echo "    PPPoE bağlantısı kuruluyor (30 saniye bekleniyor)..."
sleep 30

/etc/init.d/dnsmasq restart 2>/dev/null || true
/etc/init.d/firewall restart 2>/dev/null || true

# odhcp6c process kalmışsa temizle (IPv6 kapalı ise çalışmamalı)
if [ "$IPV6_MODE" = "kapalı" ]; then
    for opid in $(ps -w 2>/dev/null | grep "[o]dhcp6c" | awk '{print $1}'); do
        kill -9 "$opid" 2>/dev/null
    done
fi

# --- DOĞRULAMA ---
echo ""
echo "--- Doğrulama ---"

# PPPoE bağlantı
echo -n "  PPPoE: "
WAN_IP=$(ip addr show pppoe-wan 2>/dev/null | grep "inet " | awk '{print $2}')
if [ -n "$WAN_IP" ]; then
    echo "BAĞLI ($WAN_IP)"
else
    echo "BAĞLANAMADI!"
    echo "    Kullanıcı adı/şifre kontrol edin."
    echo "    'logread | grep pppd' ile hata bakabilirsiniz."
fi

# İnternet
echo -n "  İnternet: "
if ping -c 2 -W 5 1.1.1.1 >/dev/null 2>&1; then
    LATENCY=$(ping -c 2 -W 5 1.1.1.1 2>&1 | tail -1 | cut -d'/' -f5)
    echo "OK (${LATENCY}ms)"
else
    echo "ERİŞİM YOK"
fi

# DNS
echo -n "  DNS: "
if nslookup google.com >/dev/null 2>&1; then
    echo "OK"
else
    echo "ÇÖZÜMLEME YOK"
fi

# IPv6
if [ "$IPV6_MODE" != "kapalı" ]; then
    echo -n "  IPv6: "
    WAN6_IP=$(ip -6 addr show pppoe-wan 2>/dev/null | grep "inet6.*scope global" | head -1 | awk '{print $2}')
    if [ -n "$WAN6_IP" ]; then
        echo "AKTİF ($WAN6_IP)"
    else
        echo "IP yok (ISP desteklemiyor olabilir)"
    fi
fi

# MTU
echo -n "  MTU: "
ip link show pppoe-wan 2>/dev/null | grep -o "mtu [0-9]*" || echo "?"

# DNS sunucuları
echo "  DNS sunucuları:"
cat /tmp/resolv.conf.d/resolv.conf.auto 2>/dev/null | grep nameserver | while read _ ns; do
    echo "    $ns"
done

echo ""
echo "================================================================"
echo "  PPPoE WAN KURULUMU TAMAMLANDI"
echo "================================================================"
echo ""
echo "  WAN IP: $WAN_IP"
echo "  LAN IP: $LAN_IP"
echo "  IPv6:   $IPV6_MODE"
echo ""
echo "================================================================"
"""

WAN_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh

set -e
set -u 
# ==============================================================================
# uninstall_wan.sh - WAN Ayarlarını Fabrika Varsayılanına Dön
# ==============================================================================

echo "================================================================"
echo "  WAN Ayarları Sıfırlanıyor"
echo "================================================================"

echo "[1/4] WAN temizleniyor..."
uci -q delete network.wan 2>/dev/null || true
uci -q delete network.wan6 2>/dev/null || true
uci -q delete network.wan_phy_dev 2>/dev/null || true
<<WAN_VLAN_CLEANUP>>

# Varsayılan WAN (DHCP)
uci set network.wan=interface
uci set network.wan.proto='dhcp'
uci set network.wan.device='eth0'

echo "[2/4] IPv6 varsayılanına dönüyor..."
uci -q delete network.lan.ipv6 2>/dev/null || true
uci -q delete network.lan.ip6assign 2>/dev/null || true
uci -q delete network.lan.delegate 2>/dev/null || true
uci -q delete dhcp.lan.dhcpv6 2>/dev/null || true
uci -q delete dhcp.lan.ra 2>/dev/null || true
uci -q delete dhcp.lan.ra_default 2>/dev/null || true
uci -q delete dhcp.lan.ra_management 2>/dev/null || true
rm -f /etc/sysctl.d/99-ipv6.conf 2>/dev/null || true
sysctl -w net.ipv6.conf.all.disable_ipv6=0 2>/dev/null || true

echo "[3/4] USB Ethernet fix temizleniyor (varsa)..."
if [ -f "/etc/init.d/usb-lan-fix" ]; then
    /etc/init.d/usb-lan-fix disable 2>/dev/null || true
    rm -f /etc/init.d/usb-lan-fix
    echo "    > usb-lan-fix servisi kaldırıldı."
fi

echo "[4/4] Servisler yeniden başlatılıyor..."
uci commit network
uci commit dhcp
/etc/init.d/network restart 2>/dev/null || true
sleep 5

echo ""
echo "================================================================"
echo "  WAN fabrika varsayılanına döndü (DHCP)."
echo "  PPPoE bilgileri silindi."
echo "================================================================"
"""