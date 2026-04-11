# -*- coding: utf-8 -*-
"""
OpenWrt Ağ Yöneticisi - Metin Şablonları (Templates) Modülü.

Bu modül, oluşturulacak shell scriptleri için gerekli olan metin şablonlarını
(string templates) barındırır.
"""

from typing import Final

# ==============================================================================
# BÖLÜM 1: TV+ IPTV L2 BRIDGE ŞABLONU (EN STABİL YÖNTEM)
# ==============================================================================
TVPLUS_L2_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# DOSYA ADI: setup_tvplus_l2.sh
# MOD: L2 KÖPRÜ (Katman 2 Bridge) - SIFIR GECİKME, SIFIR FIREWALL
# ==============================================================================

set -e
set -u

<<PKG_MANAGER_BLOCK>>

echo "=================================================================================="
echo "🚀 SUPERONLINE TV+ KURULUMU (L2 KÖPRÜ MODU) BAŞLATILIYOR..."
echo "=================================================================================="

# ==============================================================================
# BÖLÜM 0: SİSTEM SAATİ VE NTP AYARLARI
# ==============================================================================
echo "🕒 [1/4] Sistem saati ve NTP ayarlanıyor..."
uci set system.@system[0].zonename='<<TIMEZONE>>'
uci set system.@system[0].timezone='<<TIMEZONE_CODE>>'
uci delete system.ntp.server >/dev/null 2>&1 || true
uci add_list system.ntp.server='<<NTP_SERVER>>'
uci set system.ntp.enable_server='1'
uci commit system
/etc/init.d/system restart
/etc/init.d/sysntpd restart

# ==============================================================================
# BÖLÜM 1: USB ETHERNET FIX (Varsa)
# ==============================================================================
echo "🔌 [2/4] USB Ethernet durumları kontrol ediliyor..."
cat << 'EOF_USBFIX' > /etc/init.d/usb-lan-fix
<<USB_FIX_SERVICE>>
EOF_USBFIX
chmod +x /etc/init.d/usb-lan-fix
/etc/init.d/usb-lan-fix enable

# ==============================================================================
# BÖLÜM 2: L2 KÖPRÜ KURULUMU (LAYER 2 BRIDGE)
# ==============================================================================
echo "🌉 [3/4] L2 Ağ Köprüsü (Bridge) Oluşturuluyor..."

# 1. WAN Cihazı Tespiti
DETECTED_DEV=$(uci -q get network.wan.device)
if [ -z "$DETECTED_DEV" ]; then
    DETECTED_DEV=$(uci -q get network.wan.ifname)
fi
if [ -z "$DETECTED_DEV" ]; then
    WAN_PHY_DEV="<<WAN_INTERFACE>>"
else
    if echo "$DETECTED_DEV" | grep -q "br-"; then
        WAN_PHY_DEV="<<WAN_INTERFACE>>"
    else
        WAN_PHY_DEV="$DETECTED_DEV"
    fi
fi
WAN_PHY_DEV=${WAN_PHY_DEV%%.*}
VLAN_ID="<<VLAN_ID>>"
VLAN_DEV="${WAN_PHY_DEV}.${VLAN_ID}"
TV_PORT="<<TV_ETH2_PORT>>"

echo "    > ISP VLAN ($VLAN_DEV) ile TV Portu ($TV_PORT) doğrudan birleştiriliyor..."

# Eski ayarları, proxy'yi ve kuralları temizle
/etc/init.d/igmpproxy stop >/dev/null 2>&1 || true
/etc/init.d/igmpproxy disable >/dev/null 2>&1 || true
echo "" > /etc/config/igmpproxy

# br-lan'dan TV portunu çıkar
LAN_DEV_IDX=0
while uci -q get "network.@device[$LAN_DEV_IDX]" >/dev/null 2>&1; do
    DEV_NAME=$(uci -q get "network.@device[$LAN_DEV_IDX].name" 2>/dev/null)
    if [ "$DEV_NAME" = "br-lan" ]; then
        uci -q del_list "network.@device[$LAN_DEV_IDX].ports"="$TV_PORT" 2>/dev/null || true
        break
    fi
    LAN_DEV_IDX=$((LAN_DEV_IDX+1))
done

# VLAN Cihazı Tanımlama
uci delete network.vlan$VLAN_ID 2>/dev/null || true
uci set network.vlan$VLAN_ID=device
uci set network.vlan$VLAN_ID.type='8021q'
uci set network.vlan$VLAN_ID.ifname="$WAN_PHY_DEV"
uci set network.vlan$VLAN_ID.vid="$VLAN_ID"
uci set network.vlan$VLAN_ID.name="$VLAN_DEV"

# MAC Klonlama (Sadece L2 Bridge'de VLAN için)
MAC_ADDR="<<MAC_ADDRESS>>"
if [ -n "$MAC_ADDR" ]; then
    uci set network.vlan$VLAN_ID.macaddr="$MAC_ADDR"
    echo "    > VLAN $VLAN_ID MAC Adresi Klonlandı: $MAC_ADDR"
fi

# L2 Bridge Cihazı
uci delete network.br_iptv 2>/dev/null || true
uci set network.br_iptv=device
uci set network.br_iptv.type='bridge'
uci set network.br_iptv.name='br-iptv'
uci add_list network.br_iptv.ports="$VLAN_DEV"
uci add_list network.br_iptv.ports="$TV_PORT"
# Multicast paketlerin donanımda kaybolmaması için Snooping KAPALI
uci set network.br_iptv.igmp_snooping='0'

# L2 Arayüzü (Köprüyü çalışır durumda tutmak için isimsiz arayüz)
uci delete network.<<IPTV_INTERFACE>> 2>/dev/null || true
uci set network.<<IPTV_INTERFACE>>=interface
uci set network.<<IPTV_INTERFACE>>.device='br-iptv'
uci set network.<<IPTV_INTERFACE>>.proto='none'
uci set network.<<IPTV_INTERFACE>>.auto='1'

# L2 Bridge'de IP, DHCP, Firewall veya Routing YOKTUR. Cihaz izoledir.

# ==============================================================================
# BÖLÜM 3: KAYDET VE UYGULA
# ==============================================================================
echo "💾 [4/4] Ayarlar Kaydediliyor..."
uci commit network
/etc/init.d/network restart

echo "=================================================================================="
echo "✅ L2 KÖPRÜ KURULUMU BAŞARIYLA TAMAMLANDI!"
echo "   -> TV kutusunun fişini çekip takın."
echo "   -> IP adresini OpenWrt'den değil, doğrudan Superonline'dan alacaktır."
echo "   -> Firewall, yönlendirme, rp_filter ve proxy tamamen devre dışı bırakıldı."
echo "=================================================================================="
"""

# ==============================================================================
# BÖLÜM 2: TV+ IPTV PROXY ŞABLONU (YEDEK / STANDART YÖNTEM)
# ==============================================================================
TVPLUS_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# DOSYA ADI: setup_tvplus.sh
# MOD: IGMP PROXY
# ==============================================================================

set -e
set -u

<<PKG_MANAGER_BLOCK>>

echo "=================================================================================="
echo "🚀 SUPERONLINE TV+ KURULUMU (PROXY MODU) BAŞLATILIYOR..."
echo "=================================================================================="

echo "🕒 [1/7] Sistem saati ve NTP ayarlanıyor..."
uci set system.@system[0].zonename='<<TIMEZONE>>'
uci set system.@system[0].timezone='<<TIMEZONE_CODE>>'
uci delete system.ntp.server >/dev/null 2>&1 || true
uci add_list system.ntp.server='<<NTP_SERVER>>'
uci set system.ntp.enable_server='1'
uci commit system
/etc/init.d/system restart
/etc/init.d/sysntpd restart

echo "📦 [2/7] Paketler kuruluyor (igmpproxy, ip-full)..."
pkg_update >/dev/null 2>&1 || true
for PKG in igmpproxy ip-full; do
    pkg_install "$PKG" >/dev/null 2>&1 || true
done

echo "🔌 [3/7] USB Ethernet (r8152 ailesi) boot fix güncelleniyor..."
cat << 'EOF_USBFIX' > /etc/init.d/usb-lan-fix
<<USB_FIX_SERVICE>>
EOF_USBFIX
chmod +x /etc/init.d/usb-lan-fix
/etc/init.d/usb-lan-fix enable

echo "📺 [4/7] IPTV Arayüzü (<<IPTV_INTERFACE>>) oluşturuluyor..."
DETECTED_DEV=$(uci -q get network.wan.device || uci -q get network.wan.ifname)
WAN_PHY_DEV=${DETECTED_DEV%%.*}
[ -z "$WAN_PHY_DEV" ] && WAN_PHY_DEV="<<WAN_INTERFACE>>"

uci delete network.<<IPTV_INTERFACE>>_dev 2>/dev/null || true
uci delete network.<<IPTV_INTERFACE>> 2>/dev/null || true

VLAN_ID="<<VLAN_ID>>"
VLAN_DEV="${WAN_PHY_DEV}.${VLAN_ID}"

uci set network.<<IPTV_INTERFACE>>_dev=device
uci set network.<<IPTV_INTERFACE>>_dev.name="$VLAN_DEV"
MAC_ADDR="<<MAC_ADDRESS>>"
if [ -n "$MAC_ADDR" ]; then
    uci set network.<<IPTV_INTERFACE>>_dev.macaddr="$MAC_ADDR"
fi
uci set network.<<IPTV_INTERFACE>>_dev.type='8021q'
uci set network.<<IPTV_INTERFACE>>_dev.ifname="$WAN_PHY_DEV"
uci set network.<<IPTV_INTERFACE>>_dev.vid="$VLAN_ID"
uci set network.<<IPTV_INTERFACE>>_dev.igmpversion='<<IGMP_VERSION>>'

uci set network.<<IPTV_INTERFACE>>=interface
uci set network.<<IPTV_INTERFACE>>.proto='dhcp'
uci set network.<<IPTV_INTERFACE>>.device="$VLAN_DEV"
uci set network.<<IPTV_INTERFACE>>.defaultroute='0'
uci set network.<<IPTV_INTERFACE>>.peerdns='0'
uci set network.<<IPTV_INTERFACE>>.metric='20'
if [ -n "$MAC_ADDR" ]; then
    uci set network.<<IPTV_INTERFACE>>.macaddr="$MAC_ADDR"
fi
uci set network.<<IPTV_INTERFACE>>.vendorid='<<VENDOR_ID>>'
uci set network.<<IPTV_INTERFACE>>.clientid='<<CLIENT_ID>>'
uci add_list network.<<IPTV_INTERFACE>>.sendopts='12:<<HOST_NAME_HEX>>'

echo "🔥 [5/7] Firewall (<<TV_ZONE_NAME>>) ayarları..."
uci delete firewall.<<TV_ZONE_NAME>> 2>/dev/null || true
uci set firewall.<<TV_ZONE_NAME>>=zone
uci set firewall.<<TV_ZONE_NAME>>.name='<<TV_ZONE_NAME>>'
uci set firewall.<<TV_ZONE_NAME>>.network='<<IPTV_INTERFACE>>'
uci set firewall.<<TV_ZONE_NAME>>.input='ACCEPT'
uci set firewall.<<TV_ZONE_NAME>>.output='ACCEPT'
uci set firewall.<<TV_ZONE_NAME>>.forward='REJECT'
uci set firewall.<<TV_ZONE_NAME>>.masq='1'

uci delete firewall.lan_to_tv_forwarding 2>/dev/null || true
uci set firewall.lan_to_tv_forwarding=forwarding
uci set firewall.lan_to_tv_forwarding.src='<<LAN_ZONE>>'
uci set firewall.lan_to_tv_forwarding.dest='<<TV_ZONE_NAME>>'

uci delete firewall.tv_igmp_rule 2>/dev/null || true
uci set firewall.tv_igmp_rule=rule
uci set firewall.tv_igmp_rule.name='Allow-IGMP-TV'
uci set firewall.tv_igmp_rule.src='<<TV_ZONE_NAME>>'
uci set firewall.tv_igmp_rule.dest='<<LAN_ZONE>>'
uci set firewall.tv_igmp_rule.proto='igmp'
uci set firewall.tv_igmp_rule.dest_ip='224.0.0.0/4'
uci set firewall.tv_igmp_rule.target='ACCEPT'

uci delete firewall.tv_udp_rule 2>/dev/null || true
uci set firewall.tv_udp_rule=rule
uci set firewall.tv_udp_rule.name='Allow-UDP-TV-Multicast'
uci set firewall.tv_udp_rule.src='<<TV_ZONE_NAME>>'
uci set firewall.tv_udp_rule.dest='<<LAN_ZONE>>'
uci set firewall.tv_udp_rule.proto='udp'
uci set firewall.tv_udp_rule.dest_ip='224.0.0.0/4'
uci set firewall.tv_udp_rule.target='ACCEPT'

echo "📺 [6/7] IGMP Proxy ve Rota dosyası yazılıyor..."
cat <<EOF > /etc/config/igmpproxy
config igmpproxy
    option quickleave 0
config phyint
    option network <<IPTV_INTERFACE>>
    option zone <<TV_ZONE_NAME>>
    option direction upstream
    list altnet 0.0.0.0/0
config phyint
    option network <<LAN_INTERFACE>>
    option zone <<LAN_ZONE>>
    option direction downstream
    option igmp_version <<IGMP_VERSION>>
EOF

cat << 'EOF_HOTPLUG' > /etc/hotplug.d/iface/99-tvplus-calc
#!/bin/sh
[ "$INTERFACE" = "<<IPTV_INTERFACE>>" ] || return 0
[ "$ACTION" = "ifup" ] || return 0
if [ -z "$DEVICE" ]; then return 1; fi

sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null 2>&1
for f in /proc/sys/net/ipv4/conf/*/rp_filter; do echo 0 > "$f" 2>/dev/null; done

OPTION3_GW=$(ubus call network.interface.<<IPTV_INTERFACE>> status 2>/dev/null | awk '/"nexthop":/ {print $2}' | tr -d ',"' | head -n 1)
if [ -n "$OPTION3_GW" ]; then
    ip route replace 172.31.128.0/19 via $OPTION3_GW dev $DEVICE
    ip route replace 10.31.0.0/16 via $OPTION3_GW dev $DEVICE
    ip route replace 176.235.12.0/24 via $OPTION3_GW dev $DEVICE
fi
EOF_HOTPLUG
chmod +x /etc/hotplug.d/iface/99-tvplus-calc

<<TV_ETH2_BLOCK>>

echo "💾 [7/7] Kaydediliyor..."
uci commit
/etc/init.d/network restart
/etc/init.d/firewall restart
/etc/init.d/igmpproxy restart
echo "✅ PROXY KURULUMU TAMAMLANDI."
"""

# ==============================================================================
# BÖLÜM 3: KALDIRMA VE TEMİZLİK (HER İKİ MOD İÇİN ORTAK)
# ==============================================================================
TVPLUS_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# DOSYA ADI: uninstall_tvplus.sh
# AÇIKLAMA: Proxy veya L2 Bridge mimarisinin izlerini tamamen siler.
# ==============================================================================

set -u

echo "=================================================================================="
echo "🗑️ SUPERONLINE TV+ KALDIRMA İŞLEMİ BAŞLATILIYOR..."
echo "=================================================================================="

echo "🧹 [1/3] Hotplug ve IGMP Proxy siliniyor..."
rm -f /etc/hotplug.d/iface/99-tvplus-calc
/etc/init.d/igmpproxy stop >/dev/null 2>&1 || true
/etc/init.d/igmpproxy disable >/dev/null 2>&1 || true
echo "" > /etc/config/igmpproxy

echo "🔥 [2/3] Firewall kuralları ve Ağ Arayüzleri siliniyor..."
# Proxy Firewall Kalıntıları
uci -q delete firewall.tv_igmp_rule
uci -q delete firewall.tv_udp_rule
uci -q delete firewall.lan_to_tv_forwarding
uci -q delete firewall.<<TV_ZONE_NAME>>

# Proxy Ağ Arayüzleri
uci -q delete network.<<IPTV_INTERFACE>>
uci -q delete network.<<IPTV_INTERFACE>>_dev

# L2 Bridge Kalıntıları (vlan ve br-iptv)
uci -q delete network.vlan<<VLAN_ID>> 2>/dev/null || true
uci -q delete network.br_iptv 2>/dev/null || true

# TV izole subnet kalıntıları (Proxy eth2 modu için)
uci -q delete network.br_tv        2>/dev/null || true
uci -q delete network.tv_lan       2>/dev/null || true
uci -q delete dhcp.tv_lan          2>/dev/null || true
uci -q delete firewall.tv_lan_zone 2>/dev/null || true
uci -q delete firewall.tv_lan_to_wan  2>/dev/null || true
uci -q delete firewall.tv_lan_to_iptv 2>/dev/null || true
uci -q delete firewall.tv_lan_igmp_rule 2>/dev/null || true
uci -q delete firewall.tv_lan_udp_rule 2>/dev/null || true

for domain in superonline.net superonline.com superonlinetv.com ims.superonline.com; do
    uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
done

echo "💾 [3/3] Değişiklikler uygulanıyor..."
uci commit
/etc/init.d/network restart
/etc/init.d/firewall restart
/etc/init.d/dnsmasq restart

echo "✅ KALDIRMA İŞLEMİ BAŞARIYLA TAMAMLANDI."
"""