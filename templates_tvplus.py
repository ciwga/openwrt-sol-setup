# -*- coding: utf-8 -*-
"""
OpenWrt Ağ Yöneticisi - Metin Şablonları (Templates) Modülü.

Bu modül, oluşturulacak shell scriptleri için gerekli olan metin şablonlarını
(string templates) barındırır.
"""

from typing import Final

# ==============================================================================
# BÖLÜM 1: TV+ IPTV KURULUM VE KALDIRMA ŞABLONLARI
# ==============================================================================

TVPLUS_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# DOSYA ADI: setup_tvplus.sh
#
# KONFIGURASYON:
#   - VLAN ID: <<VLAN_ID>>
#   - WAN Interface: <<WAN_INTERFACE>>
#   - LAN Interface: <<LAN_INTERFACE>>
#   - IPTV Interface Name: <<IPTV_INTERFACE>>
#   - TV Zone Name: <<TV_ZONE_NAME>>
#   - IGMP Version: <<IGMP_VERSION>>
#   - IPv6: <<IPTV_IPV6>>
#   - MTU: <<MTU_VALUE>>
#   - Dinamik Multicast: <<AUTO_MULTICAST>>
# ==============================================================================

set -e
set -u

<<PKG_MANAGER_BLOCK>>

echo "=================================================================================="
echo "🚀 SUPERONLINE TV+ KURULUMU BAŞLATILIYOR..."
echo "=================================================================================="

# ==============================================================================
# BÖLÜM 0: SİSTEM SAATİ VE NTP AYARLARI
# ==============================================================================
echo "🕒 [0/7] Sistem saati ve NTP ayarlanıyor..."
uci set system.@system[0].zonename='<<TIMEZONE>>'
uci set system.@system[0].timezone='<<TIMEZONE_CODE>>'
uci delete system.ntp.server >/dev/null 2>&1 || true
uci add_list system.ntp.server='<<NTP_SERVER>>'
uci set system.ntp.enable_server='1'
uci commit system
/etc/init.d/system restart
/etc/init.d/sysntpd restart

# Saat kontrolü (SSL ve Sertifika hatalarını önlemek için)
CURRENT_YEAR=$(date +%Y)
if [ "$CURRENT_YEAR" -lt 2026 ]; then
    echo "    ⚠️ UYARI: Sistem saati güncel değil. HTTP üzerinden eşitleniyor..."
    HTTP_DATE=$(wget -qS --spider http://google.com 2>&1 | grep -i "^  Date:" | sed 's/  Date: //g')
    if [ -n "$HTTP_DATE" ]; then
        date -s "$HTTP_DATE" >/dev/null 2>&1 || echo "    ⚠️ Saat ayarlanamadı."
    fi
fi

# ==============================================================================
# BÖLÜM 1: GEREKLİ PAKETLERİN KURULUMU
# ==============================================================================
echo "📦 [1/7] Gerekli paketler kontrol ediliyor..."
pkg_update >/dev/null 2>&1 || echo "    ⚠️ Paket listesi güncellenemedi. ($PKG_MANAGER)"
PACKAGES="igmpproxy ip-full"
for PKG in $PACKAGES; do
    if pkg_is_installed "$PKG"; then
        echo "    > $PKG zaten kurulu."
    else
        echo "    > $PKG kuruluyor..."
        pkg_install "$PKG" >/dev/null 2>&1
    fi
done

# ==============================================================================
# BÖLÜM 1.5: USB ETHERNET (r8152 / RTL8156B) BOOT FIX
# ==============================================================================
# WAN kurulumu daha önce yapıldıysa bu servis zaten mevcuttur; üzerine yazar
# (idempotent). Tvplus bağımsız kurulursa eth1 + eth2 her ikisini de kapsar.
echo "🔌 [1.5/7] USB Ethernet (r8152 ailesi) boot fix güncelleniyor..."
cat << 'EOF_USBFIX' > /etc/init.d/usb-lan-fix
<<USB_FIX_SERVICE>>
EOF_USBFIX
chmod +x /etc/init.d/usb-lan-fix
/etc/init.d/usb-lan-fix enable
echo "    > usb-lan-fix: tüm r8152/RTL8156B adaptörler otomatik tespit edilecek."

# ==============================================================================
# BÖLÜM 2: PERFORMANS VE IGMP SNOOPING (DEVICE SEVİYESİ)
# ==============================================================================
echo "⚙️ [2/7] Flow Offloading ve IGMP Snooping ayarlanıyor..."
uci set firewall.@defaults[0].flow_offloading='0'
uci set firewall.@defaults[0].flow_offloading_hw='0'

# br-lan device seviyesinde snooping (LuCI > Devices > br-lan > Configure'da görünür)
BR_DEV=""
IDX=0
while uci -q get "network.@device[$IDX]" >/dev/null 2>&1; do
    DEV_NAME=$(uci -q get "network.@device[$IDX].name")
    if [ "$DEV_NAME" = "br-lan" ]; then
        BR_DEV="network.@device[$IDX]"
        break
    fi
    IDX=$((IDX+1))
done

if [ -n "$BR_DEV" ]; then
    uci set "${BR_DEV}.igmp_snooping=1"
    uci set "${BR_DEV}.multicast_querier=1"
    echo "    > br-lan device: igmp_snooping=1, multicast_querier=1"
else
    echo "    ⚠️ UYARI: br-lan device bulunamadı, arayüz seviyesinde ayarlanıyor."
fi

# Fallback: Arayüz seviyesinde IGMP Snooping ayarı (Eski OpenWrt sürümleri için)
if uci get network.<<LAN_INTERFACE>> >/dev/null 2>&1; then
    uci set network.<<LAN_INTERFACE>>.igmp_snooping='1'
    uci set network.<<LAN_INTERFACE>>.multicast_to_unicast='1' 2>/dev/null || true
fi

# ==============================================================================
# BÖLÜM 3: ARAYÜZ, VLAN VE DHCP YAPILANDIRMASI
# ==============================================================================
echo "📺 [3/7] IPTV Arayüzü (<<IPTV_INTERFACE>>) oluşturuluyor..."

# 3.1. WAN Fiziksel Cihaz Tespiti
DETECTED_DEV=$(uci -q get network.wan.device)
if [ -z "$DETECTED_DEV" ]; then
    DETECTED_DEV=$(uci -q get network.wan.ifname)
fi

if [ -z "$DETECTED_DEV" ]; then
    echo "    ℹ️ Otomatik WAN tespiti yapılamadı."
    WAN_PHY_DEV="<<WAN_INTERFACE>>"
else
    if echo "$DETECTED_DEV" | grep -q "br-"; then
        echo "    ⚠️ Tespit edilen arayüz bir Köprü (Bridge): $DETECTED_DEV"
        echo "    ⚠️ Stabilite için kullanıcının belirttiği fiziksel arayüz kullanılacak: <<WAN_INTERFACE>>"
        WAN_PHY_DEV="<<WAN_INTERFACE>>"
    else
        WAN_PHY_DEV="$DETECTED_DEV"
        echo "    ✅ WAN Cihazı Otomatik Tespit Edildi: $WAN_PHY_DEV"
    fi
fi

# 3.2. Arayüz Temizliği ve VLAN Hazırlığı
WAN_PHY_DEV=${WAN_PHY_DEV%%.*}
echo "    👉 Hedef Fiziksel Arayüz: $WAN_PHY_DEV"

uci delete network.<<IPTV_INTERFACE>>_dev 2>/dev/null || true
uci delete network.<<IPTV_INTERFACE>> 2>/dev/null || true

VLAN_ID="<<VLAN_ID>>"
VLAN_DEV="${WAN_PHY_DEV}.${VLAN_ID}"

# 3.3. Device (Cihaz) Tanımı ve Dinamik MTU Ayarı
uci set network.<<IPTV_INTERFACE>>_dev=device
uci set network.<<IPTV_INTERFACE>>_dev.name="$VLAN_DEV"
uci set network.<<IPTV_INTERFACE>>_dev.macaddr='<<MAC_ADDRESS>>'
uci set network.<<IPTV_INTERFACE>>_dev.type='8021q'
uci set network.<<IPTV_INTERFACE>>_dev.ifname="$WAN_PHY_DEV"
uci set network.<<IPTV_INTERFACE>>_dev.vid="$VLAN_ID"
uci set network.<<IPTV_INTERFACE>>_dev.igmpversion='<<IGMP_VERSION>>'

MTU_VALUE="<<MTU_VALUE>>"
if [ -n "$MTU_VALUE" ] && [ "$MTU_VALUE" != "otomatik" ]; then
    uci set network.<<IPTV_INTERFACE>>_dev.mtu="$MTU_VALUE"
    echo "    > MTU değeri özel ayarlandı: $MTU_VALUE"
fi

# 3.4. Interface (Arayüz) Tanımı ve Dinamik IPv6 Ayarı
uci set network.<<IPTV_INTERFACE>>=interface
uci set network.<<IPTV_INTERFACE>>.proto='dhcp'
uci set network.<<IPTV_INTERFACE>>.device="$VLAN_DEV"
uci set network.<<IPTV_INTERFACE>>.defaultroute='0'
uci set network.<<IPTV_INTERFACE>>.peerdns='0'
uci set network.<<IPTV_INTERFACE>>.metric='20'

IPTV_IPV6="<<IPTV_IPV6>>"
if [ "$IPTV_IPV6" = "evet" ]; then
    uci set network.<<IPTV_INTERFACE>>.ipv6='auto'
    echo "    > IPTV IPv6 Protokolü: AKTİF"
else
    uci set network.<<IPTV_INTERFACE>>.ipv6='0'
    echo "    > IPTV IPv6 Protokolü: KAPALI"
fi

# 3.5. DHCP Seçenekleri (Options), MAC ve Client ID
echo "    > DHCP Kimlikleri yazılıyor (MAC, Vendor ID, Client ID, Hostname Hex)..."
uci set network.<<IPTV_INTERFACE>>.macaddr='<<MAC_ADDRESS>>'
uci set network.<<IPTV_INTERFACE>>.vendorid='<<VENDOR_ID>>'

# Client ID (Option 61)
uci set network.<<IPTV_INTERFACE>>.clientid='<<CLIENT_ID>>'

# Hostname (Option 12)
uci delete network.<<IPTV_INTERFACE>>.hostname 2>/dev/null || true
uci delete network.<<IPTV_INTERFACE>>.sendopts 2>/dev/null || true
uci add_list network.<<IPTV_INTERFACE>>.sendopts='12:<<HOST_NAME_HEX>>'

# Option 55 (Reqopts)
uci delete network.<<IPTV_INTERFACE>>.reqopts 2>/dev/null || true
uci add_list network.<<IPTV_INTERFACE>>.reqopts='1'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='3'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='6'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='51'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='54'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='43'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='121'
uci add_list network.<<IPTV_INTERFACE>>.reqopts='120'

# ==============================================================================
# BÖLÜM 4: FIREWALL ZONE VE KURALLAR (UDP DAHİL)
# ==============================================================================
echo "🔥 [4/7] Firewall (<<TV_ZONE_NAME>>) ve DNS Rebind ayarları..."

# Zone Tanımlama
uci delete firewall.<<TV_ZONE_NAME>> 2>/dev/null || true
uci set firewall.<<TV_ZONE_NAME>>=zone
uci set firewall.<<TV_ZONE_NAME>>.name='<<TV_ZONE_NAME>>'
uci set firewall.<<TV_ZONE_NAME>>.network='<<IPTV_INTERFACE>>'
uci set firewall.<<TV_ZONE_NAME>>.input='ACCEPT'
uci set firewall.<<TV_ZONE_NAME>>.output='ACCEPT'
uci set firewall.<<TV_ZONE_NAME>>.forward='REJECT'
uci set firewall.<<TV_ZONE_NAME>>.masq='1'
uci set firewall.<<TV_ZONE_NAME>>.mtu_fix='1'

# IPv6 Kapalıysa Firewall Ailesini Katı Olarak IPv4'e Zorla
if [ "<<IPTV_IPV6>>" != "evet" ]; then
    uci set firewall.<<TV_ZONE_NAME>>.family='ipv4'
    echo "    > TV Zone Firewall Ailesi: Sadece IPv4 (IPv6 Kapalı)"
fi

# LAN -> TV Forwarding Kuralı
uci delete firewall.lan_to_tv_forwarding 2>/dev/null || true
uci set firewall.lan_to_tv_forwarding=forwarding
uci set firewall.lan_to_tv_forwarding.src='<<LAN_ZONE>>'
uci set firewall.lan_to_tv_forwarding.dest='<<TV_ZONE_NAME>>'

# IGMP İzin Kuralı
uci delete firewall.tv_igmp_rule 2>/dev/null || true
uci set firewall.tv_igmp_rule=rule
uci set firewall.tv_igmp_rule.name='Allow-IGMP-TV'
uci set firewall.tv_igmp_rule.src='<<TV_ZONE_NAME>>'
uci set firewall.tv_igmp_rule.dest='<<LAN_ZONE>>'
uci set firewall.tv_igmp_rule.proto='igmp'
uci set firewall.tv_igmp_rule.dest_ip='224.0.0.0/4'
uci set firewall.tv_igmp_rule.target='ACCEPT'

# UDP Multicast İzin Kuralı
uci delete firewall.tv_udp_rule 2>/dev/null || true
uci set firewall.tv_udp_rule=rule
uci set firewall.tv_udp_rule.name='Allow-UDP-TV-Multicast'
uci set firewall.tv_udp_rule.src='<<TV_ZONE_NAME>>'
uci set firewall.tv_udp_rule.dest='<<LAN_ZONE>>'
uci set firewall.tv_udp_rule.proto='udp'
uci set firewall.tv_udp_rule.dest_ip='224.0.0.0/4'
uci set firewall.tv_udp_rule.target='ACCEPT'

# Varsa hatalı slash içeren varyasyonları güvenle temizle
for domain in superonline.net/ superonline.com/ superonlinetv.com/; do
    uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
done

# DNS Rebind Koruması
for domain in superonline.net superonline.com superonlinetv.com ims.superonline.com; do
    uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
    uci add_list dhcp.@dnsmasq[0].rebind_domain="$domain"
done

# ==============================================================================
# BÖLÜM 5: IGMP PROXY YAPILANDIRMASI
# ==============================================================================
echo "📺 [5/7] IGMP Proxy dosyası yazılıyor..."
cat <<EOF > /etc/config/igmpproxy
config igmpproxy
    option quickleave 0
    # disableall: lokal multicast (224.0.0.0/24) ve SSDP/UPnP (239.x) upstream'e iletilmez
    option disableall 0
config phyint
    option network <<IPTV_INTERFACE>>
    option zone <<TV_ZONE_NAME>>
    option direction upstream
    list altnet 225.0.0.0/8
    list altnet 233.0.0.0/8
    list altnet 10.31.0.0/16
config phyint
    option network <<LAN_INTERFACE>>
    option zone <<LAN_ZONE>>
    option direction downstream
    option igmp_version <<IGMP_VERSION>>
EOF

# ==============================================================================
# BÖLÜM 6: ROTA VE HOTPLUG (DİNAMİK QoS VE ROTA ATAMALARI)
# ==============================================================================
echo "📝 [6/7] Hotplug scripti oluşturuluyor (Rotasyon ve Arayüz QoS)..."
uci commit network

cat << 'EOF_HOTPLUG' > /etc/hotplug.d/iface/99-tvplus-calc
#!/bin/sh
# Auto-generated by setup_tvplus.sh

[ "$INTERFACE" = "<<IPTV_INTERFACE>>" ] || return 0
[ "$ACTION" = "ifup" ] || return 0

logger -t IPTV_LOG "IPTV (<<IPTV_INTERFACE>>) aktif. Rotalar ve Arayüz QoS hesaplanıyor..."

if [ -z "$DEVICE" ]; then return 1; fi

CIDR_DATA=""
ATTEMPT=1
while [ $ATTEMPT -le 5 ]; do
    CIDR_DATA=$(ip -4 -o addr show dev $DEVICE | awk '{print $4}' | head -1)
    if [ -n "$CIDR_DATA" ]; then break; fi
    sleep 2
    ATTEMPT=$((ATTEMPT + 1))
done

if [ -z "$CIDR_DATA" ]; then
    logger -t IPTV_LOG "HATA: $DEVICE üzerinde IP adresi alınamadı."
    return 1
fi

# Gateway Hesaplama (Fallback mekanizması)
CALCULATED_GW=$(echo "$CIDR_DATA" | awk -F'[./]' '{
    ip1=$1; ip2=$2; ip3=$3; ip4=$4; mask=$5
    ip_int = (ip1 * 16777216) + (ip2 * 65536) + (ip3 * 256) + ip4
    host_bits = 32 - mask
    divisor = 2 ^ host_bits
    net_int = int(ip_int / divisor) * divisor
    gw_int = net_int + 1
    o1 = int(gw_int / 16777216)
    gw_int = gw_int % 16777216
    o2 = int(gw_int / 65536)
    gw_int = gw_int % 65536
    o3 = int(gw_int / 256)
    o4 = gw_int % 256
    print o1"."o2"."o3"."o4
}')

# Option 3 (Gateway) varsa ubus üzerinden alınacak
OPTION3_GW=$(ubus call network.interface.<<IPTV_INTERFACE>> status 2>/dev/null | awk '/"nexthop":/ {print $2}' | tr -d ',"' | head -n 1)

ACTIVE_GW=""
if [ -n "$OPTION3_GW" ]; then
    logger -t IPTV_LOG "Option 3 Gateway bulundu: $OPTION3_GW"
    ACTIVE_GW="$OPTION3_GW"
elif [ -n "$CALCULATED_GW" ]; then
    logger -t IPTV_LOG "Option 3 bulunamadı. Hesaplanan Fallback Gateway kullanılıyor: $CALCULATED_GW"
    ACTIVE_GW="$CALCULATED_GW"
else
    logger -t IPTV_LOG "HATA: Gateway bulunamadı veya hesaplanamadı."
    return 1
fi

if [ -n "$ACTIVE_GW" ]; then
    logger -t IPTV_LOG "Aktif Gateway: $ACTIVE_GW. Rotalar ekleniyor..."

    # Statik rotalar — bilinen Superonline TV blokları
    ip route replace 172.31.128.0/19 via $ACTIVE_GW dev $DEVICE
    ip route replace 176.43.0.0/24 via $ACTIVE_GW dev $DEVICE
    ip route replace 10.31.0.0/16 via $ACTIVE_GW dev $DEVICE

    # 176.235.0.0/16 tamamı PPPoE'ye (CDN, Play Store vs.)
    # Sadece TV'nin kullandığı NTP bloğu IPTV'ye istisna olarak eklenir.
    WAN_GW=$(ip route show default dev pppoe-wan 2>/dev/null | awk '{print $3}' | head -1)
    if [ -n "$WAN_GW" ]; then
        ip route replace 176.235.0.0/16 via $WAN_GW dev pppoe-wan
        logger -t IPTV_LOG "176.235.0.0/16 PPPoE'ye yönlendirildi (CDN default)"
    fi
    # 176.235.7.0/24 → Superonline NTP sunucuları, TV kutusu saat senkronizasyonu için kullanır.
    # Daha spesifik rota olduğu için /16'yı ezer, IPTV üzerinden gider.
    ip route replace 176.235.7.0/24 via $ACTIVE_GW dev $DEVICE
    logger -t IPTV_LOG "176.235.7.0/24 NTP istisna rotası eklendi (eth1.103)"
else
    logger -t IPTV_LOG "HATA: Rotalar uygulanamadı."
fi

# Dinamik Arayüz QoS (L2 Önceliği - 802.1p VLAN Priority 4) Doğrudan arayüz üzerinde uygulanır.
ip link set "$DEVICE" type vlan egress-qos-map 0:4 1:4 2:4 3:4 4:4 5:4 6:4 7:4 2>/dev/null || true
logger -t IPTV_LOG "$DEVICE için Egress QoS ataması yapıldı."

# --- Dinamik Altnet (Multicast Kaynak) Tespiti ---
if [ "<<AUTO_MULTICAST>>" = "evet" ]; then
    logger -t IPTV_LOG "Dinamik Multicast (Altnet) tespiti yapılıyor..."

    # Her ifup'ta listeyi sıfırdan yaz — üst üste birikmesini önler
    uci -q delete igmpproxy.@phyint[0].altnet 2>/dev/null || true

    # Sabit temel altnetler (TV yayın grupları)
    uci add_list igmpproxy.@phyint[0].altnet='225.0.0.0/8'
    uci add_list igmpproxy.@phyint[0].altnet='233.0.0.0/8'
    uci add_list igmpproxy.@phyint[0].altnet='169.254.0.0/16'
    uci add_list igmpproxy.@phyint[0].altnet='176.235.0.0/16'

    # DHCP'den gelen spesifik rotaları dinamik ekle (Option 121 dahil)
    DETECTED_SUBNETS=$(ip -4 route show dev "$DEVICE" | awk '{print $1}' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$')
    for SUBNET in $DETECTED_SUBNETS; do
        # Sadece RFC1918 veya ISP blokları — geniş /8 blokları atla
        PREFIX=$(echo "$SUBNET" | cut -d'/' -f2)
        [ "$PREFIX" -le 8 ] && continue  # /8 veya daha geniş → atla
        uci add_list igmpproxy.@phyint[0].altnet="$SUBNET"
        logger -t IPTV_LOG "Dinamik Altnet eklendi: $SUBNET"
    done

    uci commit igmpproxy
    /etc/init.d/igmpproxy reload 2>/dev/null || /etc/init.d/igmpproxy restart
    logger -t IPTV_LOG "IGMP Proxy altnet listesi yenilendi."
fi

EOF_HOTPLUG
chmod +x /etc/hotplug.d/iface/99-tvplus-calc

# ==============================================================================
# BÖLÜM 6.5: İKİNCİ USB ADAPTÖR (ETH2) — İZOLE TV SUBNET (OPSİYONEL)
# ==============================================================================
echo "🔌 [6.5/7] TV izolasyon ayarı..."
<<TV_ETH2_BLOCK>>

# ==============================================================================
# BÖLÜM 7: KAYDET VE YENİDEN BAŞLAT
# ==============================================================================
echo "💾 [7/7] Kaydediliyor ve servisler yeniden başlatılıyor..."
uci commit network
uci commit firewall
uci commit system
uci commit dhcp
/etc/init.d/network restart
/etc/init.d/firewall restart
/etc/init.d/dnsmasq restart
/etc/init.d/igmpproxy enable
/etc/init.d/igmpproxy restart
echo "✅ KURULUM BAŞARIYLA TAMAMLANDI."
"""

TVPLUS_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# DOSYA ADI: uninstall_tvplus.sh
# AÇIKLAMA:
#   Bu betik, setup_tvplus.sh tarafından yapılan değişiklikleri
#   geri alır (Hotplug, Firewall, UDP kuralları, Network, IGMP Proxy).
# ==============================================================================

set -u

echo "=================================================================================="
echo "🗑️ SUPERONLINE TV+ KALDIRMA İŞLEMİ BAŞLATILIYOR..."
echo "=================================================================================="

# --- 1. HOTPLUG TEMİZLİĞİ ---
echo "🧹 [1/5] Hotplug scripti siliniyor..."
if [ -f "/etc/hotplug.d/iface/99-tvplus-calc" ]; then
    rm -f /etc/hotplug.d/iface/99-tvplus-calc
    echo "    ✅ /etc/hotplug.d/iface/99-tvplus-calc silindi."
else
    echo "    ℹ️ Hotplug scripti zaten yok."
fi

# --- 2. IGMP PROXY ---
echo "🛑 [2/5] IGMP Proxy devre dışı bırakılıyor..."
/etc/init.d/igmpproxy stop >/dev/null 2>&1 || true
/etc/init.d/igmpproxy disable >/dev/null 2>&1 || true

# IGMP Proxy dosyası tamamen boşaltılır, böylece dinamik eklenen altnetler de sıfırlanır
echo "" > /etc/config/igmpproxy
echo "    ✅ IGMP Proxy konfigürasyonu ve dinamik altnetler temizlendi."

# --- 3. FIREWALL AYARLARI ---
echo "🔥 [3/5] Firewall kuralları ve Zone (<<TV_ZONE_NAME>>) siliniyor..."

# Kural ve Forwarding silme
uci -q delete firewall.tv_igmp_rule
uci -q delete firewall.tv_udp_rule
uci -q delete firewall.lan_to_tv_forwarding

# Zone silme
uci -q delete firewall.<<TV_ZONE_NAME>>

echo "    ✅ Firewall ayarları (IGMP, UDP, Forwarding) kaldırıldı."

# --- 4. NETWORK VE ARAYÜZLER ---
echo "🌐 [4/5] Ağ arayüzleri (<<IPTV_INTERFACE>>) siliniyor..."

# Interface silme
uci -q delete network.<<IPTV_INTERFACE>>

# Device (VLAN) silme - Modern DSA
uci -q delete network.<<IPTV_INTERFACE>>_dev

# TV izole subnet temizliği (eth2 ile kurulduysa)
uci -q delete network.br_tv        2>/dev/null || true
uci -q delete network.tv_lan       2>/dev/null || true
uci -q delete dhcp.tv_lan          2>/dev/null || true
uci -q delete firewall.tv_lan_zone 2>/dev/null || true
uci -q delete firewall.tv_lan_to_wan  2>/dev/null || true
uci -q delete firewall.tv_lan_to_iptv 2>/dev/null || true
# br-tv'yi br-lan'a geri eklemek için: LuCI > Network > Devices > br-lan > Ports
echo "    ✅ TV izole subnet (tv_lan/br-tv) temizlendi (varsa)." 

# DNS Rebind temizliği (Her iki format için de döngü uygulanarak güvenli temizlik)
for domain in superonline.net superonline.com superonlinetv.com ims.superonline.com; do
    uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
done
for domain in superonline.net/ superonline.com/ superonlinetv.com/; do
    uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$domain" 2>/dev/null || true
done

echo "    ✅ Ağ ve DNS ayarları temizlendi."

# --- 5. KAYDET VE UYGULA ---
echo "💾 [5/5] Değişiklikler uygulanıyor..."
uci commit network
uci commit firewall
uci commit dhcp
uci commit system

echo "🔄 Servisler yeniden başlatılıyor..."
/etc/init.d/network restart
/etc/init.d/firewall restart
/etc/init.d/dnsmasq restart

echo "✅ KALDIRMA İŞLEMİ BAŞARIYLA TAMAMLANDI."
echo "   Cihazınız eski haline döndürüldü."
"""
