# -*- coding: utf-8 -*-
"""Tailscale VPN shell script şablonları."""

from typing import Final

TAILSCALE_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# setup_tailscale.sh - Tailscale VPN Kurulumu
# Subnet router + Exit node + WoL
# ==============================================================================

set -e
set -u

LAN_SUBNET="<<LAN_SUBNET>>"
TAILSCALE_AUTH_KEY="<<TAILSCALE_AUTH_KEY>>"
ADVERTISE_EXIT_NODE="<<ADVERTISE_EXIT_NODE>>"
ACCEPT_DNS="<<ACCEPT_DNS>>"
TAILNET_NAME="<<TAILNET_NAME>>"
WOL_ENABLED="<<WOL_ENABLED>>"

<<PKG_MANAGER_BLOCK>>

echo ""
echo "================================================================"
echo "  Tailscale VPN Kurulumu"
echo "================================================================"

# --- 1. PAKETLER ---
echo "[1/5] Paketler... ($PKG_MANAGER)"

pkg_update >/dev/null 2>&1 || true

# nftables altyapısı kullanan güncel OpenWrt sürümlerinde 
# tailscaled servisinin çökmesini önlemek için 'ip6tables-nft' paketi listeye eklendi.
for pkg in tailscale iptables-nft ip6tables-nft etherwake; do
    if pkg_is_installed "$pkg"; then
        echo "    $pkg OK"
    else
        if pkg_install "$pkg" >/dev/null 2>&1; then
            echo "    $pkg kuruldu"
        else
            echo "    $pkg KURULAMADI (devam ediliyor)"
        fi
    fi
done

# --- 2. ÇEKİRDEK (KERNEL) YAPILANDIRMASI ---
echo "[2/5] Çekirdek ayarları (IP Yönlendirme)..."

# Tailscale'in subnet advertise edebilmesi için (IP yönlendirmesi),
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf
echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.d/99-tailscale.conf
sysctl -p /etc/sysctl.d/99-tailscale.conf 2>/dev/null || true


# --- 3. NETWORK VE FIREWALL ÖN YAPILANDIRMASI ---
# Tailscale servisi başlamadan önce network ve firewall 
# kuralları tanımlanmalı ve uygulanmalıdır. Böylece tailscale0 arayüzü
# dinamik olarak oluştuğu anda OpenWrt onu doğru bölgeye (zone) dahil edebilir.
echo "[3/5] Network ve Firewall ayarları hazırlanıyor..."

# 3.1 Network arayüzü tanımlama
uci -q delete network.tailscale 2>/dev/null || true
uci set network.tailscale=interface
uci set network.tailscale.proto='none'
uci set network.tailscale.device='tailscale0'
uci commit network
/etc/init.d/network reload 2>/dev/null || true
sleep 2

# 3.2 Firewall arayüzü için zone oluştur
uci -q delete firewall.tailscale_zone 2>/dev/null || true
uci set firewall.tailscale_zone=zone
uci set firewall.tailscale_zone.name='tailscale'
uci set firewall.tailscale_zone.network='tailscale'
uci add_list firewall.tailscale_zone.device='tailscale0'

# Arayüz içi trafik kuralları
uci set firewall.tailscale_zone.input='ACCEPT'
uci set firewall.tailscale_zone.output='ACCEPT'
# Bağlantı kopmalarını (erişilememezliği) engellemek için
# REJECT olan forward ayarı ACCEPT olarak değiştirildi.
uci set firewall.tailscale_zone.forward='ACCEPT'
uci set firewall.tailscale_zone.masq='1'

# Tailscale -> LAN yönlendirme
uci -q delete firewall.ts_to_lan 2>/dev/null || true
uci set firewall.ts_to_lan=forwarding
uci set firewall.ts_to_lan.src='tailscale'
uci set firewall.ts_to_lan.dest='lan'
uci set firewall.ts_to_lan.mtu_fix='1'

# LAN -> Tailscale yönlendirme
uci -q delete firewall.lan_to_ts 2>/dev/null || true
uci set firewall.lan_to_ts=forwarding
uci set firewall.lan_to_ts.src='lan'
uci set firewall.lan_to_ts.dest='tailscale'
uci set firewall.lan_to_ts.mtu_fix='1'
 
# Tailscale -> WAN
if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    uci -q delete firewall.ts_to_wan 2>/dev/null || true
    uci set firewall.ts_to_wan=forwarding
    uci set firewall.ts_to_wan.src='tailscale'
    uci set firewall.ts_to_wan.dest='wan'
    uci set firewall.ts_to_wan.mtu_fix='1'
fi

# 3.3 Firewall Trafik Kuralları (Traffic Rules)
# Sadece arayüz yönlendirmeleri (forwarding) bazen nftables
# tarafından yoksayılabilir.

# Kural 1: WAN üzerinden Tailscale iletişim portuna (UDP 41641) izin ver. (P2P doğrudan bağlantı için şart)
uci -q delete firewall.tailscale_wan_udp 2>/dev/null || true
uci set firewall.tailscale_wan_udp=rule
uci set firewall.tailscale_wan_udp.name='Allow-Tailscale-WAN-UDP'
uci set firewall.tailscale_wan_udp.src='wan'
uci set firewall.tailscale_wan_udp.dest_port='41641'
uci set firewall.tailscale_wan_udp.proto='udp'
uci set firewall.tailscale_wan_udp.target='ACCEPT'

# Kural 2: Tailscale'den LAN'a gelen tüm trafiğe açıkça izin ver (Drop sorunlarını önler)
uci -q delete firewall.tailscale_in 2>/dev/null || true
uci set firewall.tailscale_in=rule
uci set firewall.tailscale_in.name='Allow-Tailscale-To-LAN'
uci set firewall.tailscale_in.src='tailscale'
uci set firewall.tailscale_in.dest='lan'
uci set firewall.tailscale_in.target='ACCEPT'

# Kural 3: LAN'dan Tailscale'e giden tüm trafiğe açıkça izin ver
uci -q delete firewall.tailscale_out 2>/dev/null || true
uci set firewall.tailscale_out=rule
uci set firewall.tailscale_out.name='Allow-LAN-To-Tailscale'
uci set firewall.tailscale_out.src='lan'
uci set firewall.tailscale_out.dest='tailscale'
uci set firewall.tailscale_out.target='ACCEPT'

uci commit firewall
/etc/init.d/firewall restart 2>/dev/null || true
echo "    Network ve Firewall OK (Traffic Rules eklendi)"


# --- 4. DNSMASQ BYPASS ---
echo "[4/5] dnsmasq ayarları..."
for domain in tailscale.com ts.net tailscaled.net; do
    uci -q del_list dhcp.@dnsmasq[0].server="/$domain/213.74.0.1" 2>/dev/null || true
    uci add_list dhcp.@dnsmasq[0].server="/$domain/213.74.0.1"
done
uci commit dhcp
/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
echo "    ✅ Tailscale domain'leri (dnsmasq) ISP DNS'e yönlendirildi."


# --- 5. TAILSCALE SERVİSİ VE GİRİŞ ---
echo "[5/5] Tailscale servisi başlatılıyor..."

/etc/init.d/tailscale enable 2>/dev/null || true
/etc/init.d/tailscale start 2>/dev/null || true
sleep 3

# tailscaled servisinin arka planda çalışıp çalışmadığını doğrula
if ! pidof tailscaled >/dev/null 2>&1; then
    echo "    HATA: tailscaled başlatılamadı!"
    /etc/init.d/tailscale start
    sleep 5
fi

# Auth key ile otomatik login işlemleri
export TS_AUTHKEY="$TAILSCALE_AUTH_KEY"
TS_ARGS="--auth-key=$TS_AUTHKEY --reset"
TS_ARGS="$TS_ARGS --advertise-routes=$LAN_SUBNET"
TS_ARGS="$TS_ARGS --accept-routes"
TS_ARGS="$TS_ARGS --snat-subnet-routes=true"

# =================================================================================
# DNS LOOP engellemesi ve Dinamik Kabul (Accept DNS)
# =================================================================================
if [ "$ACCEPT_DNS" = "hayır" ]; then
    TS_ARGS="$TS_ARGS --accept-dns=false"
    echo "    Tailscale DNS: KAPALI (Router'ın kendi DNS ayarları DNS Loop koruması için korundu)"
    
    if [ -n "$TAILNET_NAME" ]; then
        uci -q del_list dhcp.@dnsmasq[0].server="/$TAILNET_NAME/100.100.100.100" 2>/dev/null || true
        uci add_list dhcp.@dnsmasq[0].server="/$TAILNET_NAME/100.100.100.100"
        uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$TAILNET_NAME" 2>/dev/null || true
        uci add_list dhcp.@dnsmasq[0].rebind_domain="$TAILNET_NAME"
        uci commit dhcp
        /etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
        echo "    MagicDNS: $TAILNET_NAME -> 100.100.100.100 (dnsmasq bypass aktif)"
    else
        echo "    MagicDNS: tailnet adi belirtilmedi, hostname cozumu devre disi."
    fi
else
    # Eğer kullanıcı Accept DNS'i evet seçerse, Tailscale'in DNS'ini kabul et
    echo "    Tailscale DNS: AKTİF (MagicDNS Tailscale tarafından yönetilecek)"
    echo "    ⚠️ BİLGİ: Accept DNS 'evet' seçildi. Eğer AdGuard kullanıyorsanız,"
    echo "    DNS Loop riskine karşı lütfen kurulum sonundaki ayarları unutmayın!"
fi

if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    TS_ARGS="$TS_ARGS --advertise-exit-node"
    echo "    Exit node: AKTİF"
fi

echo "    Tailscale ağına bağlanılıyor..."
tailscale up $TS_ARGS 2>&1
TS_UP_EXIT=$?

# Hassas veriyi (Auth Key) bellekten ve çevresel değişkenlerden derhal temizle
unset TS_AUTHKEY

if [ $TS_UP_EXIT -ne 0 ]; then
    echo "    HATA: Tailscale login basarisiz!"
    echo "    Auth key gecerli mi? https://login.tailscale.com/admin/settings/keys"
    exit 1
fi

sleep 2
echo "    Tailscale bağlandı"

# --- 5.1: TAILSCALE GÜNCELLEME VE BINARY HATASI DÜZELTMESİ ---
echo "    Tailscale otomatik güncellemeleri OpenWrt kararlılığı için kapatılıyor..."
tailscale set --auto-update=false 2>/dev/null || true

if [ ! -f /usr/bin/tailscale ] && [ -f /usr/sbin/tailscale ]; then
    ln -s /usr/sbin/tailscale /usr/bin/tailscale 2>/dev/null || true
    echo "    ✅ /usr/bin/tailscale sembolik bağı oluşturuldu."
fi


# --- DOĞRULAMA ---
echo ""
echo "--- Doğrulama ---"

TS_STATUS=$(tailscale status 2>&1 | head -5)
TS_IP=$(tailscale ip -4 2>/dev/null)

echo -n "  Tailscale durumu: "
if tailscale status >/dev/null 2>&1; then
    echo "BAĞLI"
else
    echo "BAĞLANTI YOK"
fi

[ -n "$TS_IP" ] && echo "  Tailscale IP: $TS_IP"
echo "  Subnet: $LAN_SUBNET"

if [ "$WOL_ENABLED" = "evet" ]; then
    echo -n "  etherwake: "
    command -v etherwake >/dev/null 2>&1 && echo "OK" || echo "YOK (kurulum basarisiz)"
fi

echo ""
echo "    =================================================================="
echo "    ⚠️ DİKKAT: ADGUARD HOME KULLANICILARI İÇİN ÖNEMLİ ADIM ⚠️"
echo "    Eğer sistemde AdGuard Home kurulu ise, Tailscale bağlantısının"
echo "    bloklanmaması ve stabil çalışması için AdGuard Web Arayüzünde:"
echo "    Filtrelemeler -> Özel Filtreleme Kuralları alanına"
echo "    aşağıdaki 3 satırı manuel olarak kopyalayıp yapıştırın ve kaydedin:"
echo ""
echo "    @@||tailscale.com^\$important"
echo "    @@||ts.net^\$important"
echo "    @@||tailscaled.net^\$important"
echo "    =================================================================="

echo ""
echo "================================================================"
echo "  TAILSCALE KURULUMU TAMAMLANDI"
echo "================================================================"
echo ""
echo "  Tailscale IP: $TS_IP"
echo "  Subnet: $LAN_SUBNET"
echo "  Admin: https://login.tailscale.com/admin/machines"
echo ""
echo "  ÖNEMLİ: Cihazınızda sorunsuz bağlantı için şu ayarları yapın:"
echo "  1. Tailscale Admin Panel: Subnet routes'u ONAYLA (Edit route settings)"
if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    echo "  2. Tailscale Admin Panel: Exit node'u ONAYLA"
fi
echo "  3. Ağınızın DNS sunucusunu kullanmak için;"
echo "     Tailscale Admin Panel -> DNS -> Global nameservers -> Add nameserver -> Custom seçin,"
echo "     $TS_IP adresini girip ekleyin ve 'Override local DNS' seçeneğini işaretleyin."
echo ""

if [ "$WOL_ENABLED" = "evet" ]; then
    echo "  WoL kullanimi: ssh root@$(tailscale ip -4) \"etherwake -i br-lan MAC_ADRESI\""
fi
echo "================================================================"
"""

TAILSCALE_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh

# ==============================================================================
# uninstall_tailscale.sh - Tailscale Komple Kaldırma
# ==============================================================================

set -e
set -u 

<<PKG_MANAGER_BLOCK>>

echo "================================================================"
echo "  Tailscale Kaldırma"
echo "================================================================"

# Tailscale logout ve durdur
echo "[1/4] Tailscale durduruluyor..."
tailscale logout 2>/dev/null || true
tailscale down 2>/dev/null || true
/etc/init.d/tailscale stop 2>/dev/null || true
/etc/init.d/tailscale disable 2>/dev/null || true
killall -9 tailscaled 2>/dev/null || true

# Paket kaldırma
echo "[2/4] Paketler kaldırılıyor... ($PKG_MANAGER)"
pkg_remove tailscale etherwake 2>/dev/null || true

# Sembolik bağ temizliği
rm -f /usr/bin/tailscale 2>/dev/null || true

# MagicDNS ve dnsmasq temizliği
echo "[2.5/4] MagicDNS dnsmasq kayıtları temizleniyor..."
for entry in $(uci -q get dhcp.@dnsmasq[0].server 2>/dev/null); do
    echo "$entry" | grep -q "ts.net" &&         uci -q del_list dhcp.@dnsmasq[0].server="$entry" 2>/dev/null || true
done
for entry in $(uci -q get dhcp.@dnsmasq[0].rebind_domain 2>/dev/null); do
    echo "$entry" | grep -q "ts.net" &&         uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$entry" 2>/dev/null || true
done
uci commit dhcp 2>/dev/null || true

# Firewall temizliği
echo "[3/4] Firewall temizleniyor..."
uci -q delete firewall.tailscale_zone 2>/dev/null || true
uci -q delete firewall.ts_to_lan 2>/dev/null || true
uci -q delete firewall.lan_to_ts 2>/dev/null || true
uci -q delete firewall.ts_to_wan 2>/dev/null || true

# Trafik Kurallarını Temizleme
uci -q delete firewall.tailscale_wan_udp 2>/dev/null || true
uci -q delete firewall.tailscale_in 2>/dev/null || true
uci -q delete firewall.tailscale_out 2>/dev/null || true

uci commit firewall 2>/dev/null || true

# Network temizliği
echo "[4/4] Network temizleniyor..."
uci -q delete network.tailscale 2>/dev/null || true
uci commit network 2>/dev/null || true

# Tailscale dnsmasq kayıtları temizliği
for domain in tailscale.com ts.net tailscaled.net; do
    uci -q del_list dhcp.@dnsmasq[0].server="/$domain/213.74.0.1" 2>/dev/null || true
done
uci commit dhcp 2>/dev/null || true

# Dosya temizliği (Artık verilerin güvenli imhası)
rm -rf /var/lib/tailscale 2>/dev/null || true
rm -rf /etc/tailscale 2>/dev/null || true
rm -f /etc/sysctl.d/99-tailscale.conf 2>/dev/null || true

/etc/init.d/firewall restart 2>/dev/null || true
/etc/init.d/network reload 2>/dev/null || true

echo ""
echo "================================================================"
echo "  Tailscale kaldırıldı."
echo "  Admin panelinden cihazı da silin:"
echo "  https://login.tailscale.com/admin/machines"
echo "================================================================"
"""