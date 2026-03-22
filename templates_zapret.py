# -*- coding: utf-8 -*-
"""Zapret (DPI bypass) shell script şablonları."""

from typing import Final

ZAPRET_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# DOSYA: setup_zapret.sh
# AÇIKLAMA: Zapret (DPI bypass) kurulum ve yapılandırması.
# ==============================================================================

set -e

<<PKG_MANAGER_BLOCK>>

echo ""
echo "================================================================"
echo "  Zapret (DPI Bypass) Kurulumu"
echo "================================================================"
echo ""

# --- FLOW OFFLOADING ---
echo "[1/4] Flow offloading kontrol..."
fo=$(uci -q get firewall.@defaults[0].flow_offloading || echo 0)
foh=$(uci -q get firewall.@defaults[0].flow_offloading_hw || echo 0)
if [ "$fo" = "1" ] || [ "$foh" = "1" ]; then
    uci set firewall.@defaults[0].flow_offloading='0'
    uci set firewall.@defaults[0].flow_offloading_hw='0'
    uci commit firewall
    /etc/init.d/firewall restart
    echo "    Flow offloading kapatıldı (zapret uyumu)"
else
    echo "    Zaten kapalı, OK"
fi

# --- PAKETLER ---
echo "[2/4] Gerekli paketler... ($PKG_MANAGER)"
pkg_update >/dev/null 2>&1 || echo "    UYARI: $PKG_MANAGER update başarısız"
for pkg in kmod-nft-queue kmod-nf-conntrack kmod-nft-nat curl; do
    pkg_install "$pkg" >/dev/null 2>&1 && echo "    $pkg OK" || echo "    $pkg atlandı"
done

# --- ZAPRET KURULUM ---
echo "[3/4] Zapret kuruluyor..."

ZAPRET_OK=0

# Yöntem 1: remittor/zapret-openwrt
if curl -fsSL "https://raw.githubusercontent.com/remittor/zapret-openwrt/zap1/zapret/update-pkg.sh" -o /tmp/zap.sh 2>/dev/null; then
    if sh /tmp/zap.sh -u 1; then
        ZAPRET_OK=1
        echo "    Zapret paketi kuruldu (remittor)"
    fi
    rm -f /tmp/zap.sh
fi

# Yöntem 2: bol-van/zapret (fallback | experimental)
if [ "$ZAPRET_OK" = "0" ]; then
    echo "    Alternatif: bol-van/zapret deneniyor..."
    if [ ! -d /opt/zapret ]; then
        cd /tmp
        wget -q -O zapret.tar.gz "https://github.com/bol-van/zapret/releases/latest/download/zapret-openwrt-embedded.tar.gz" 2>/dev/null || \
        wget -q -O zapret.tar.gz "https://github.com/bol-van/zapret/archive/refs/heads/master.tar.gz" 2>/dev/null || true
        if [ -f zapret.tar.gz ]; then
            tar xzf zapret.tar.gz -C /opt/ 2>/dev/null || true
            [ -d /opt/zapret-master ] && mv /opt/zapret-master /opt/zapret
            rm -f /tmp/zapret.tar.gz
            if [ -d /opt/zapret ]; then
                cd /opt/zapret
                [ -f install_bin.sh ] && ./install_bin.sh 2>/dev/null
                [ -f install_prereq.sh ] && ./install_prereq.sh 2>/dev/null
                ZAPRET_OK=1
            fi
        fi
    else
        ZAPRET_OK=1
        echo "    Zapret zaten /opt/zapret'te mevcut"
    fi
fi

if [ "$ZAPRET_OK" = "0" ]; then
    echo "    UYARI: Zapret kurulamadı. Manuel kurulum:"
    echo "    https://github.com/remittor/zapret-openwrt/wiki"
    exit 0
fi

# --- YAPILANDIRMA ---
echo "[4/4] Zapret yapılandırılıyor..."

if [ -f /opt/zapret/config ]; then
    sed -i 's/^MODE=.*/MODE=nfqws/' /opt/zapret/config
    sed -i 's/^MODE_HTTP=.*/MODE_HTTP=1/' /opt/zapret/config
    sed -i 's/^MODE_HTTPS=.*/MODE_HTTPS=1/' /opt/zapret/config
    sed -i 's/^MODE_QUIC=.*/MODE_QUIC=1/' /opt/zapret/config
    sed -i 's/^MODE_FILTER=.*/MODE_FILTER=hostlist/' /opt/zapret/config
    sed -i 's/^INIT_APPLY_FW=.*/INIT_APPLY_FW=1/' /opt/zapret/config

    grep -q "^NFQWS_OPT_DESYNC=" /opt/zapret/config && \
    sed -i 's|^NFQWS_OPT_DESYNC=.*|NFQWS_OPT_DESYNC="--dpi-desync=fake,disorder2 --dpi-desync-split-pos=1 --dpi-desync-ttl=0 --dpi-desync-fooling=md5sig,badsum --dpi-desync-fake-tls=/opt/zapret/files/fake/tls_clienthello_www_google_com.bin"|' /opt/zapret/config

    grep -q "^NFQWS_OPT_DESYNC_QUIC=" /opt/zapret/config && \
    sed -i 's|^NFQWS_OPT_DESYNC_QUIC=.*|NFQWS_OPT_DESYNC_QUIC="--dpi-desync=fake --dpi-desync-repeats=6"|' /opt/zapret/config
fi

# Host listesi
HOSTLIST="/opt/zapret/ipset/zapret-hosts-user.txt"
if [ -d "/opt/zapret/ipset" ]; then
    [ ! -f "$HOSTLIST" ] && touch "$HOSTLIST"
    for domain in <<ZAPRET_DOMAINS>>; do
        grep -qxF "$domain" "$HOSTLIST" 2>/dev/null || echo "$domain" >> "$HOSTLIST"
    done
    echo "    Host listesi güncellendi"
fi

# TV+ hariç tutma
EXCLUDELIST="/opt/zapret/ipset/zapret-hosts-user-exclude.txt"
if [ -d "/opt/zapret/ipset" ]; then
    [ ! -f "$EXCLUDELIST" ] && touch "$EXCLUDELIST"
    for excl in "*.superonline.net" "*.turkcell.com.tr" "*.tvplus.com.tr" \
                "cpentp.superonline.net" "*.iptv.superonline.net"; do
        grep -qxF "$excl" "$EXCLUDELIST" 2>/dev/null || echo "$excl" >> "$EXCLUDELIST"
    done
    echo "    TV+ domainleri hariç tutuldu"
fi

/etc/init.d/zapret enable 2>/dev/null || true
/etc/init.d/zapret restart 2>/dev/null || true

echo ""
echo "================================================================"
echo "  ZAPRET KURULUMU TAMAMLANDI"
echo "================================================================"
echo "  Mod: nfqws (hostlist) | Flow offloading: KAPALI"
echo "  Strateji optimizasyonu: cd /opt/zapret && ./blockcheck.sh"
echo "  Doğrulama: ps | grep nfqws"
echo "================================================================"
"""

ZAPRET_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# DOSYA: uninstall_zapret.sh - KOMPLE TEMİZLİK
# ==============================================================================

set -u

<<PKG_MANAGER_BLOCK>>

echo "================================================================"
echo "  Zapret - Komple Kaldırma"
echo "================================================================"

# --- 1. SERVİS ---
echo "[1/4] Zapret durduruluyor..."
/etc/init.d/zapret stop 2>/dev/null || true
/etc/init.d/zapret disable 2>/dev/null || true
killall -9 nfqws tpws 2>/dev/null || true

# --- 2. PAKETLER VE DOSYALAR ---
echo "[2/4] Paketler ve dosyalar kaldırılıyor..."

# paket kaldırma ($PKG_MANAGER)
pkg_remove luci-app-zapret zapret 2>/dev/null || true

# Manuel kurulum kalıntıları
[ -f /opt/zapret/uninstall_easy.sh ] && sh /opt/zapret/uninstall_easy.sh 2>/dev/null || true
rm -rf /opt/zapret
rm -f /etc/init.d/zapret
rm -f /etc/hotplug.d/iface/90-zapret
rm -f /etc/config/zapret 2>/dev/null || true

# nftables tabloları
nft delete table inet zapret 2>/dev/null || true
nft delete table ip zapret 2>/dev/null || true

# ipset kalıntıları
rm -f /tmp/zapret*.list 2>/dev/null || true

echo "    Zapret dosyaları silindi."

# --- 3. FIREWALL ---
echo "[3/4] Firewall zapret kalıntıları..."

# UCI'deki zapret ile ilgili firewall kuralları
for idx in $(seq 30 -1 0); do
    name=$(uci -q get "firewall.@rule[$idx].name" 2>/dev/null) || continue
    case "$name" in
        *zapret*|*nfqws*|*tpws*|*ZAPRET*)
            uci -q delete "firewall.@rule[$idx]" 2>/dev/null || true
            echo "    firewall rule ($name) silindi"
            ;;
    esac
done
uci commit firewall 2>/dev/null || true
/etc/init.d/firewall restart 2>/dev/null || true

echo "    Firewall temiz."

# --- 4. BİLGİ ---
echo "[4/4] Tamamlandı."
echo ""
echo "================================================================"
echo "  ZAPRET TAMAMEN KALDIRILDI"
echo "================================================================"
echo "  - nfqws/tpws: durduruldu ve silindi"
echo "  - /opt/zapret: silindi"
echo "  - nftables: zapret tabloları temizlendi"
echo "  - paketler ($PKG_MANAGER): kaldırıldı"
echo ""
echo "  Flow offloading tekrar açılabilir:"
echo "    uci set firewall.@defaults[0].flow_offloading='1'"
echo "    uci commit firewall && /etc/init.d/firewall restart"
echo "================================================================"
"""