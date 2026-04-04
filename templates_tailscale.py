# -*- coding: utf-8 -*-
"""Tailscale VPN shell script şablonları.

Özellikler:
  - Tailscale kurulumu (opkg/apk)
  - Subnet router (LAN'a uzaktan erişim)
  - Exit node (uzaktan ağ interneti kullanma)
  - Wake-on-LAN (etherwake ile cihaz açma)
"""

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

# ÖNEMLİ DÜZELTME: nftables altyapısı kullanan güncel OpenWrt sürümlerinde 
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

# --- 2. TAILSCALE SERVİSİ ---
echo "[2/5] Tailscale servisi..."

/etc/init.d/tailscale enable 2>/dev/null || true
/etc/init.d/tailscale start 2>/dev/null || true
sleep 3

# tailscaled servisinin arka planda çalışıp çalışmadığını doğrula
if ! pidof tailscaled >/dev/null 2>&1; then
    echo "    HATA: tailscaled başlatılamadı!"
    /etc/init.d/tailscale start
    sleep 5
fi

echo "    tailscaled çalışıyor"

# --- 3. TAILSCALE GİRİŞ ---
echo "[3/5] Tailscale giriş..."

# Auth key ile otomatik login işlemleri
# Güvenlik notu: TS_AUTHKEY çevresel değişkeni (environment variable) kullanıldıktan hemen sonra temizlenmelidir.
export TS_AUTHKEY="$TAILSCALE_AUTH_KEY"
TS_ARGS="--auth-key=$TS_AUTHKEY"
TS_ARGS="$TS_ARGS --advertise-routes=$LAN_SUBNET"
TS_ARGS="$TS_ARGS --accept-routes"
TS_ARGS="$TS_ARGS --snat-subnet-routes=true"

if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    TS_ARGS="$TS_ARGS --advertise-exit-node"
    echo "    Exit node: AKTİF"
fi

if [ "$ACCEPT_DNS" = "hayır" ]; then
    TS_ARGS="$TS_ARGS --accept-dns=false"
    echo "    Tailscale DNS: KAPALI (mevcut DNS korunuyor)"
    if [ -n "$TAILNET_NAME" ]; then
        uci -q del_list dhcp.@dnsmasq[0].server="/$TAILNET_NAME/100.100.100.100" 2>/dev/null || true
        uci add_list dhcp.@dnsmasq[0].server="/$TAILNET_NAME/100.100.100.100"
        uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$TAILNET_NAME" 2>/dev/null || true
        uci add_list dhcp.@dnsmasq[0].rebind_domain="$TAILNET_NAME"
        uci commit dhcp
        /etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
        echo "    MagicDNS: $TAILNET_NAME -> 100.100.100.100 (dnsmasq)"
    else
        echo "    MagicDNS: tailnet adi belirtilmedi, hostname cozumu devre disi."
    fi
else
    echo "    Tailscale DNS: AKTiF (MagicDNS Tailscale tarafindan yonetilecek)"
fi

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

# --- 3.5: ADGUARD WHITELIST ---
# AdGuard kuruluysa tailscale.com domain'lerini whitelist'e ekle.
# Aksi hâlde AdGuard Tailscale'in log/koordinasyon sunucularını bloklar
# → sertifika hatası → DERP relay bağlantısı kopar → shared cihazlar ulaşamaz.

# Tailscale domain'lerini dnsmasq'a yaz — AdGuard varsa da yoksa da çalışır.
# AdGuard DNS sorgularını dnsmasq'a iletir; server direktifleri önce işlenir.
for domain in tailscale.com ts.net tailscaled.net; do
    uci -q del_list dhcp.@dnsmasq[0].server="/$domain/213.74.0.1" 2>/dev/null || true
    uci add_list dhcp.@dnsmasq[0].server="/$domain/213.74.0.1"
done
uci commit dhcp
/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
echo "    ✅ Tailscale domain'leri ISP DNS'e yönlendirildi."

# --- 4. FIREWALL ---
echo "[4/5] Firewall ayarları..."

# Tailscale arayüzü için zone oluştur
uci -q delete firewall.tailscale_zone 2>/dev/null || true
uci set firewall.tailscale_zone=zone
uci set firewall.tailscale_zone.name='tailscale'

# ÖNEMLİ DÜZELTME: Tailscale ağındaki cihazların (örn. telefonunuz) 
# OpenWrt üzerindeki DNS sunucusuna (AdGuard) erişebilmesi için input 'ACCEPT' olarak değiştirildi.
uci set firewall.tailscale_zone.input='ACCEPT'

uci set firewall.tailscale_zone.output='ACCEPT'
uci set firewall.tailscale_zone.forward='REJECT'
# forward=REJECT — izinler explicit forwarding kurallarıyla verilir (ts_to_lan, ts_to_wan)
uci set firewall.tailscale_zone.masq='1'
uci set firewall.tailscale_zone.network='tailscale'
uci add_list firewall.tailscale_zone.device='tailscale0'

# Tailscale -> LAN yönlendirme
uci -q delete firewall.ts_to_lan 2>/dev/null || true
uci set firewall.ts_to_lan=forwarding
uci set firewall.ts_to_lan.src='tailscale'
uci set firewall.ts_to_lan.dest='lan'

# LAN -> Tailscale yönlendirme
uci -q delete firewall.lan_to_ts 2>/dev/null || true
uci set firewall.lan_to_ts=forwarding
uci set firewall.lan_to_ts.src='lan'
uci set firewall.lan_to_ts.dest='tailscale'
 
# Tailscale -> WAN (exit node için)
if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    uci -q delete firewall.ts_to_wan 2>/dev/null || true
    uci set firewall.ts_to_wan=forwarding
    uci set firewall.ts_to_wan.src='tailscale'
    uci set firewall.ts_to_wan.dest='wan'
fi

# IP yönlendirme (forwarding) - Çekirdek (Kernel) seviyesi yapılandırma
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf
echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.d/99-tailscale.conf
sysctl -p /etc/sysctl.d/99-tailscale.conf 2>/dev/null || true

uci commit firewall
/etc/init.d/firewall restart 2>/dev/null || true

echo "    Firewall OK"

# --- 5. NETWORK ARAYÜZÜ ---
echo "[5/5] Network arayüzü..."

# tailscale0 için interface tanımla
uci -q delete network.tailscale 2>/dev/null || true
uci set network.tailscale=interface
uci set network.tailscale.proto='none'
uci set network.tailscale.device='tailscale0'

uci commit network
/etc/init.d/network reload 2>/dev/null || true
sleep 2

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
echo "================================================================"
echo "  TAILSCALE KURULUMU TAMAMLANDI"
echo "================================================================"
echo ""
echo "  Tailscale IP: $TS_IP"
echo "  Subnet: $LAN_SUBNET"
echo "  Admin: https://login.tailscale.com/admin/machines"
echo ""
echo "  ÖNEMLİ: Tailscale admin panelinden şu ayarları yapın:"
echo "  1. Subnet routes'u ONAYLA (Edit route settings)"
if [ "$ADVERTISE_EXIT_NODE" = "evet" ]; then
    echo "  2. Exit node'u ONAYLA"
fi
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
pkg_remove tailscale 2>/dev/null || true
pkg_remove etherwake 2>/dev/null || true

# MagicDNS temizliği
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
