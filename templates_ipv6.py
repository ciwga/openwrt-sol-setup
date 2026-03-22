# -*- coding: utf-8 -*-
"""IPv6 enable/disable ayrı shell betiği şablonları.

Ana WAN kurulumundan bağımsız çalışır.
"""

from typing import Final

IPV6_DISABLE_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# disable_ipv6.sh - IPv6 Tamamen Kapatma
# Superonline IPv6 desteklemediği için odhcp6c SOLICIT spam'ini önler.
# ==============================================================================

echo "================================================================"
echo "  IPv6 Kapatılıyor"
echo "================================================================"

# 1. Çalışan odhcp6c process'lerini durdur
echo "[1/6] odhcp6c durduruluyor..."
for pid in $(ps -w 2>/dev/null | grep "[o]dhcp6c" | awk '{print $1}'); do
    kill "$pid" 2>/dev/null && echo "    PID:$pid durduruldu"
done

# 2. wan6 interface sil
echo "[2/6] wan6 siliniyor..."
uci -q delete network.wan6 2>/dev/null && echo "    wan6 silindi" || echo "    wan6 zaten yok"

# 3. WAN ve LAN IPv6 kapat
echo "[3/6] Interface IPv6 kapatılıyor..."
uci set network.wan.ipv6='0'
uci set network.lan.ipv6='0'
uci -q delete network.lan.ip6assign 2>/dev/null
uci -q delete network.lan.delegate 2>/dev/null

# IPTV interface varsa onda da kapat
if uci -q get network.tvplus_iptv >/dev/null 2>&1; then
    uci set network.tvplus_iptv.ipv6='0'
    uci set network.tvplus_iptv.delegate='0'
    echo "    tvplus_iptv ipv6=0"
fi

# 4. DHCPv6/RA kapat
echo "[4/6] DHCPv6/RA kapatılıyor..."
uci -q delete dhcp.lan.dhcpv6 2>/dev/null
uci -q delete dhcp.lan.ra 2>/dev/null
uci -q delete dhcp.lan.ra_management 2>/dev/null
uci set dhcp.lan.ra_default='0'

# odhcpd durdur
/etc/init.d/odhcpd stop 2>/dev/null || true
/etc/init.d/odhcpd disable 2>/dev/null || true
echo "    odhcpd devre dışı"

# 5. Kernel IPv6 disable
echo "[5/6] Kernel IPv6 kapatılıyor..."
cat > /etc/sysctl.d/99-ipv6.conf << 'EOF'
net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1
EOF
sysctl -p /etc/sysctl.d/99-ipv6.conf 2>/dev/null || true

# 6. Firewall'dan wan6 çıkar
echo "[6/6] Firewall temizleniyor..."
IDX=0
while uci -q get "firewall.@zone[$IDX]" >/dev/null 2>&1; do
    ZN=$(uci -q get "firewall.@zone[$IDX].name")
    if [ "$ZN" = "wan" ]; then
        uci -q del_list "firewall.@zone[$IDX].network=wan6" 2>/dev/null
    fi
    IDX=$((IDX+1))
done

# Commit ve restart
uci commit network
uci commit dhcp
uci commit firewall

/etc/init.d/dnsmasq restart 2>/dev/null || true
/etc/init.d/firewall restart 2>/dev/null || true

# Son kez odhcp6c temizle
sleep 2
for pid in $(ps -w 2>/dev/null | grep "[o]dhcp6c" | awk '{print $1}'); do
    kill -9 "$pid" 2>/dev/null
done

# Doğrulama
echo ""
echo "--- Doğrulama ---"
echo -n "  odhcp6c: "
ps -w 2>/dev/null | grep -q "[o]dhcp6c" && echo "HALA ÇALIŞIYOR!" || echo "YOK (OK)"

echo -n "  wan6: "
uci -q get network.wan6 >/dev/null 2>&1 && echo "VAR!" || echo "SİLİNDİ (OK)"

echo -n "  kernel IPv6: "
V=$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null)
[ "$V" = "1" ] && echo "KAPALI (OK)" || echo "AÇIK!"

echo -n "  odhcpd: "
/etc/init.d/odhcpd enabled 2>/dev/null && echo "AKTİF!" || echo "DEVRE DIŞI (OK)"

echo ""
echo "================================================================"
echo "  IPv6 TAMAMEN KAPATILDI"
echo "  odhcp6c SOLICIT spam artık olmayacak."
echo "================================================================"
"""

IPV6_ENABLE_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# enable_ipv6.sh - IPv6 Aktifleştirme (DHCPv6 + SLAAC)
# ISP IPv6 destekliyorsa kullanın.
# ==============================================================================

echo "================================================================"
echo "  IPv6 Aktifleştiriliyor"
echo "================================================================"

# 1. Kernel IPv6 enable
echo "[1/5] Kernel IPv6 açılıyor..."
rm -f /etc/sysctl.d/99-ipv6.conf 2>/dev/null
sysctl -w net.ipv6.conf.all.disable_ipv6=0 2>/dev/null || true
sysctl -w net.ipv6.conf.default.disable_ipv6=0 2>/dev/null || true

# 2. wan6 interface oluştur
echo "[2/5] wan6 interface oluşturuluyor..."
uci -q delete network.wan6 2>/dev/null
uci set network.wan6=interface
uci set network.wan6.proto='dhcpv6'
uci set network.wan6.device='@wan'
uci set network.wan6.reqaddress='try'
uci set network.wan6.reqprefix='auto'

# WAN ve LAN IPv6 aç
uci set network.wan.ipv6='1'
uci set network.lan.ipv6='1'
uci set network.lan.ip6assign='60'
uci set network.lan.delegate='1'

# 3. DHCPv6/RA aç
echo "[3/5] DHCPv6 + RA aktif..."
uci set dhcp.lan.dhcpv6='server'
uci set dhcp.lan.ra='server'
uci set dhcp.lan.ra_default='1'
uci set dhcp.lan.ra_management='1'

# odhcpd başlat
/etc/init.d/odhcpd enable 2>/dev/null || true
/etc/init.d/odhcpd start 2>/dev/null || true
echo "    odhcpd aktif"

# 4. Firewall'a wan6 ekle
echo "[4/5] Firewall wan6 ekleniyor..."
IDX=0
while uci -q get "firewall.@zone[$IDX]" >/dev/null 2>&1; do
    ZN=$(uci -q get "firewall.@zone[$IDX].name")
    if [ "$ZN" = "wan" ]; then
        CUR=$(uci -q get "firewall.@zone[$IDX].network" 2>/dev/null)
        echo "$CUR" | grep -q "wan6" || uci add_list "firewall.@zone[$IDX].network=wan6"
    fi
    IDX=$((IDX+1))
done

# 5. Commit ve restart
echo "[5/5] Servisler yeniden başlatılıyor..."
uci commit network
uci commit dhcp
uci commit firewall

/etc/init.d/network restart 2>/dev/null || true
echo "    30 saniye bekleniyor..."
sleep 30
/etc/init.d/dnsmasq restart 2>/dev/null || true
/etc/init.d/firewall restart 2>/dev/null || true

# Doğrulama
echo ""
echo "--- Doğrulama ---"
echo -n "  wan6: "
uci -q get network.wan6.proto 2>/dev/null || echo "YOK!"

echo -n "  IPv6 WAN: "
W6=$(ip -6 addr show pppoe-wan 2>/dev/null | grep "inet6.*scope global" | head -1 | awk '{print $2}')
[ -n "$W6" ] && echo "$W6" || echo "Adres yok (ISP desteklemiyor olabilir)"

echo -n "  IPv6 LAN: "
L6=$(ip -6 addr show br-lan 2>/dev/null | grep "inet6.*scope global" | head -1 | awk '{print $2}')
[ -n "$L6" ] && echo "$L6" || echo "Adres yok"

echo -n "  odhcpd: "
/etc/init.d/odhcpd enabled 2>/dev/null && echo "AKTİF (OK)" || echo "DEVRE DIŞI!"

echo ""
echo "================================================================"
echo "  IPv6 AKTİF"
echo "  ISP desteklemiyorsa adres alamayabilirsiniz."
echo "  Test: ping6 google.com"
echo "================================================================"
"""