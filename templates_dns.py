# -*- coding: utf-8 -*-
"""DNS Zinciri shell script şablonları.

MİMARİ:
  AdGuard Home(:53) -> https-dns-proxy(:5053/:5054) -> DoH (Cloudflare/Google)
  dnsmasq(:5353) -> sadece DHCP servisi (DNS yönlendirme YOK)

  KRİTİK: https-dns-proxy force_dns='0' OLMALI
    force_dns=1 -> nftables port 53 redirect -> ISP DNS erişimi engellenir
"""

from typing import Final

DNS_CHAIN_SETUP_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# setup_dns_chain.sh
# AdGuard(:53) -> DoH(:<<HDNSP_PORT>>) | dnsmasq(:<<AGH_DNS_PORT>> DHCP-only)
# Split-DNS: AdGuard upstream [/superonline.net/] -> ISP DNS
# Per-client: AdGuard panelinde her cihaz görünür
# ==============================================================================

set -e

LAN_IP="<<LAN_IP>>"
AGH_DNS_PORT=<<AGH_DNS_PORT>>
AGH_WEB_PORT=<<AGH_WEB_PORT>>
HDNSP_PORT=<<HDNSP_PORT>>
HDNSP_PORT2=$((HDNSP_PORT + 1))

<<PKG_MANAGER_BLOCK>>

echo ""
echo "================================================================"
echo "  DNS Zinciri Kurulumu"
echo "  AdGuard(:53) -> DoH(:$HDNSP_PORT) | dnsmasq(:$AGH_DNS_PORT DHCP)"
echo "================================================================"

# --- 1. YEDEK ---
echo "[1/7] Yedekleme..."
BACKUP_DIR="/root/dns-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
for f in /etc/config/dhcp /etc/config/firewall /etc/config/https-dns-proxy; do
    [ -f "$f" ] && cp -a "$f" "$BACKUP_DIR/"
done
echo "    Yedek: $BACKUP_DIR"

# --- 2. PAKETLER ---
echo "[2/7] Paketler... ($PKG_MANAGER)"
pkg_update >/dev/null 2>&1 || true
for pkg in curl wget-ssl ca-bundle ca-certificates https-dns-proxy luci-app-https-dns-proxy; do
    pkg_install "$pkg" >/dev/null 2>&1 && echo "    $pkg OK" || echo "    $pkg atlandı"
done

# --- 3. HTTPS-DNS-PROXY ---
echo "[3/7] HTTPS-DNS-Proxy..."

while uci -q delete https-dns-proxy.@https-dns-proxy[0] 2>/dev/null; do :; done

uci set https-dns-proxy.cf="https-dns-proxy"
uci set https-dns-proxy.cf.bootstrap_dns="1.1.1.1,1.0.0.1"
uci set https-dns-proxy.cf.resolver_url="https://cloudflare-dns.com/dns-query"
uci set https-dns-proxy.cf.listen_addr="127.0.0.1"
uci set https-dns-proxy.cf.listen_port="$HDNSP_PORT"

uci set https-dns-proxy.goog="https-dns-proxy"
uci set https-dns-proxy.goog.bootstrap_dns="8.8.8.8,8.8.4.4"
uci set https-dns-proxy.goog.resolver_url="https://dns.google/dns-query"
uci set https-dns-proxy.goog.listen_addr="127.0.0.1"
uci set https-dns-proxy.goog.listen_port="$HDNSP_PORT2"

# *** KRİTİK: force_dns KAPATILIYOR ***
# force_dns=1 -> nftables "udp dport 53 redirect" kuralı koyar
# Bu kural router'dan çıkan DNS sorgularını da yakalar!
# AdGuard'ın ISP DNS'e (213.74.0.1:53) split-DNS sorguları
# redirect olur -> timeout -> TV+ bozulur
uci set https-dns-proxy.config="main"
uci set https-dns-proxy.config.dnsmasq_config_update="*"
uci set https-dns-proxy.config.force_dns='0'
uci -q delete https-dns-proxy.config.force_dns_port 2>/dev/null || true
uci -q delete https-dns-proxy.config.force_dns_src_interface 2>/dev/null || true

uci commit https-dns-proxy

# Servisi TAMAMEN durdur, firewall temizle, sonra başlat
/etc/init.d/https-dns-proxy stop 2>/dev/null || true
killall -9 https-dns-proxy 2>/dev/null || true
sleep 1

# Firewall restart - https-dns-proxy durdurulduğu için yeni kural eklenmez
/etc/init.d/firewall restart 2>/dev/null || true
sleep 1

# Şimdi servisi başlat (force_dns=0 ile)
/etc/init.d/https-dns-proxy enable 2>/dev/null || true
/etc/init.d/https-dns-proxy start 2>/dev/null || true
sleep 2

# Servis başladıktan sonra TEKRAR firewall restart
# (https-dns-proxy procd üzerinden firewall'a kural eklerse temizlenir)
/etc/init.d/firewall restart 2>/dev/null || true
sleep 1

# Son kontrol: hala redirect varsa nft ile zorla sil
REDIR=$(nft list ruleset 2>/dev/null | grep -c "dport 53.*redirect" 2>/dev/null) || true
REDIR=${REDIR:-0}
if [ "${REDIR}" != "0" ]; then
    echo "    Redirect kuralları hala var ($REDIR adet), zorla siliniyor..."
    # DNAT zincirindeki redirect kurallarını tek tek sil
    for HANDLE in $(nft -a list chain inet fw4 dstnat 2>/dev/null | grep "dport 53.*redirect" | awk '{print $NF}'); do
        nft delete rule inet fw4 dstnat handle "$HANDLE" 2>/dev/null || true
    done
    # 853 redirect (DoT engelleme) de silinebilir
    for HANDLE in $(nft -a list chain inet fw4 dstnat 2>/dev/null | grep "dport 853" | awk '{print $NF}'); do
        nft delete rule inet fw4 dstnat handle "$HANDLE" 2>/dev/null || true
    done
    echo "    Redirect kuralları nft ile silindi."
fi
echo "    DoH OK, force_dns=0"

# --- 4. ADGUARD HOME - PORT 53 ---
echo "[4/7] AdGuard Home (port 53 - istemci görünürlüğü)..."

AGH_CONF_DIR="/etc/adguardhome"
AGH_CONF="$AGH_CONF_DIR/config.yaml"
AGH_WORK_DIR="/var/adguardhome"

if ! pkg_is_installed "adguardhome"; then
    echo "    Kuruluyor ($PKG_MANAGER)..."
    if ! pkg_install adguardhome >/dev/null 2>&1; then
        echo "    HATA: adguardhome paketi kurulamadı!"
        exit 1
    fi
    echo "    $PKG_MANAGER ile kuruldu"
else
    echo "    Zaten yüklü"
fi

/etc/init.d/adguardhome stop 2>/dev/null || true
killall -9 AdGuardHome adguardhome 2>/dev/null || true

mkdir -p "$AGH_CONF_DIR" "$AGH_WORK_DIR"

# ISP DNS'leri split-DNS upstream olarak hazırla
ISP_DNS="<<ISP_DNS>>"
ISP_DNS1=$(echo "$ISP_DNS" | cut -d',' -f1 | tr -d ' ')
ISP_DNS2=$(echo "$ISP_DNS" | cut -d',' -f2 -s | tr -d ' ')

# YAML yapılandırma
# AdGuard port 53'te DİNLİYOR -> istemciler doğrudan bağlanıyor -> per-client görünürlük
# Split-DNS: [/superonline.net/] formatında ISP DNS'e yönlendirme
# dnsmasq port 5353'e taşınıyor (sadece DHCP + tag-based DNS bypass)
cat > "$AGH_CONF" << AGHEOF
schema_version: 29
http:
  address: 0.0.0.0:${AGH_WEB_PORT}
  session_ttl: 720h
users: []
language: tr
dns:
  bind_hosts:
    - 0.0.0.0
  port: 53
  ratelimit: 0
  upstream_dns:
    - '[/superonline.net/]${ISP_DNS1}'
    - '[/superonline.com/]${ISP_DNS1}'
    - '[/superonlinetv.com/]${ISP_DNS1}'
    - '[/turkcell.com.tr/]${ISP_DNS1}'
    - '[/tvplus.com.tr/]${ISP_DNS1}'
    - '[/superonline.net/]${ISP_DNS2}'
    - '[/superonline.com/]${ISP_DNS2}'
    - '[/superonlinetv.com/]${ISP_DNS2}'
    - '[/turkcell.com.tr/]${ISP_DNS2}'
    - '[/tvplus.com.tr/]${ISP_DNS2}'
    - '[/lan/]127.0.0.1:${AGH_DNS_PORT}'
    - 127.0.0.1:${HDNSP_PORT}
    - 127.0.0.1:${HDNSP_PORT2}
  bootstrap_dns:
    - 1.1.1.1
    - 8.8.8.8
  fallback_dns:
    - 1.1.1.1
    - 8.8.8.8
  upstream_mode: parallel
  cache_size: 4194304
  cache_optimistic: true
  enable_dnssec: true
clients:
  runtime_sources:
    whois: true
    arp: true
    rdns: true
    dhcp: true
    hosts: true
  persistent: []
tls:
  enabled: false
querylog:
  interval: 24h
  enabled: true
  file_enabled: true
statistics:
  interval: 24h
  enabled: true
filters:
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt
    name: AdGuard DNS filter
    id: 1
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_2.txt
    name: AdAway Default Blocklist
    id: 2
dhcp:
  enabled: false
filtering:
  filtering_enabled: true
  protection_enabled: true
AGHEOF

if id -u adguardhome >/dev/null 2>&1; then
    chown -R adguardhome:adguardhome "$AGH_CONF_DIR" "$AGH_WORK_DIR" 2>/dev/null || true
fi

cat > /etc/config/adguardhome << UCIEOF
config adguardhome 'config'
    option enabled '1'
    option configpath '$AGH_CONF'
    option config '$AGH_CONF'
    option workdir '$AGH_WORK_DIR'
UCIEOF

/etc/init.d/adguardhome enable 2>/dev/null || true
echo "    AGH: DNS=:53 (per-client!) | Web=http://$LAN_IP:$AGH_WEB_PORT"
echo "    Split-DNS: *.superonline.net -> $ISP_DNS1 (AdGuard içinde)"

# --- 5. DNSMASQ (port 5353, DHCP-only) ---
echo "[5/7] dnsmasq -> port $AGH_DNS_PORT (DHCP servisi)..."

# dnsmasq port 53'ü AdGuard'a bırakır
uci set dhcp.@dnsmasq[0].port="$AGH_DNS_PORT"
uci set dhcp.@dnsmasq[0].noresolv='1'
uci set dhcp.@dnsmasq[0].cachesize='0'

# dnsmasq'ın upstream DNS'i yok - sadece DHCP servisi yapıyor
# (eski split-DNS kurallarını temizle, artık AdGuard yapıyor)
uci -q delete dhcp.@dnsmasq[0].server 2>/dev/null || true

uci set dhcp.@dnsmasq[0].rebind_protection='0'

# DHCP Option 6: Tüm cihazlara router IP'yi DNS olarak ver
# Bu sefer router IP = AdGuard (:53) -> per-client görünürlük!
uci -q delete dhcp.lan.dhcp_option 2>/dev/null || true
uci add_list dhcp.lan.dhcp_option="6,$LAN_IP"

echo "    dnsmasq: port $AGH_DNS_PORT (DHCP-only)"

# --- 6. TV+ DHCP BYPASS ---
echo "[6/7] TV+ DNS bypass..."

TVPLUS_STB_MAC="<<TVPLUS_STB_MAC>>"
TVPLUS_STB_IP="<<TVPLUS_STB_IP>>"

# Temizlik
uci -q delete dhcp.tvplus_stb 2>/dev/null || true
uci -q delete dhcp.@dnsmasq[0].confdir 2>/dev/null || true
rm -f /etc/dnsmasq.d/tvplus-dns.conf 2>/dev/null || true
for idx in $(seq 20 -1 0); do
    name=$(uci -q get dhcp.@host[$idx].name 2>/dev/null) || continue
    case "$name" in tvplus*|TV_Plus*) uci -q delete dhcp.@host[$idx] 2>/dev/null || true ;; esac
done

ISP_DNS_CLEAN=$(echo "$ISP_DNS" | tr -d ' ')

if [ -n "$TVPLUS_STB_MAC" ] && [ -n "$ISP_DNS" ]; then
    uci set dhcp.tvplus_stb=host
    uci set dhcp.tvplus_stb.name='tvplus-stb'
    uci set dhcp.tvplus_stb.mac="$TVPLUS_STB_MAC"
    [ -n "$TVPLUS_STB_IP" ] && uci set dhcp.tvplus_stb.ip="$TVPLUS_STB_IP"
    uci set dhcp.tvplus_stb.tag='tvplus'
    mkdir -p /etc/dnsmasq.d
    echo "dhcp-option=tag:tvplus,6,$ISP_DNS_CLEAN" > /etc/dnsmasq.d/tvplus-dns.conf
    uci set dhcp.@dnsmasq[0].confdir='/etc/dnsmasq.d'
    echo "    TV+ ($TVPLUS_STB_MAC) -> ISP DNS ($ISP_DNS_CLEAN)"
else
    echo "    TV+ MAC yok, DHCP bypass atlandı. Split-DNS yeterli olabilir."
fi

uci commit dhcp

# --- 7. SERVİSLER ---
echo "[7/7] Servisler başlatılıyor..."

# 1) DoH proxy
/etc/init.d/https-dns-proxy restart 2>/dev/null || true
sleep 2

# 2) dnsmasq ÖNCE (port 5353'e taşınır, port 53'ü serbest bırakır)
/etc/init.d/dnsmasq stop 2>/dev/null || true
killall -9 dnsmasq 2>/dev/null || true
sleep 1
/etc/init.d/dnsmasq start 2>/dev/null || true
sleep 2

# 3) AdGuard Home (port 53'ü alır)
/etc/init.d/adguardhome restart 2>/dev/null || true
sleep 3

# 4) Firewall
/etc/init.d/firewall restart 2>/dev/null || true
sleep 1

# 5) Redirect temizliği
for HANDLE in $(nft -a list chain inet fw4 dstnat 2>/dev/null | grep "dport 53.*redirect" | awk '{print $NF}'); do
    nft delete rule inet fw4 dstnat handle "$HANDLE" 2>/dev/null || true
done
for HANDLE in $(nft -a list chain inet fw4 dstnat 2>/dev/null | grep "dport 853" | awk '{print $NF}'); do
    nft delete rule inet fw4 dstnat handle "$HANDLE" 2>/dev/null || true
done

# DOĞRULAMA
echo ""
echo "--- Doğrulama ---"

REDIR=$(nft list ruleset 2>/dev/null | grep -c "dport 53.*redirect" 2>/dev/null) || true
REDIR=${REDIR:-0}
[ "$REDIR" = "0" ] && echo "  [OK] Port 53 redirect yok" || echo "  [!] $REDIR redirect kuralı var!"

# Port 53'te kim var?
P53=$(netstat -tlnp 2>/dev/null | grep ":53 " | head -1 | awk '{print $NF}')
if echo "$P53" | grep -qi "adguard"; then
    echo "  [OK] Port 53: AdGuard Home (per-client görünürlük)"
elif echo "$P53" | grep -qi "dnsmasq"; then
    echo "  [!] Port 53: dnsmasq (AdGuard başlamadı!)"
else
    echo "  [?] Port 53: $P53"
fi

if [ -n "$ISP_DNS1" ]; then
    R=$(nslookup cpentp.superonline.net "$ISP_DNS1" 2>&1 | grep -i "address" | tail -1)
    [ -n "$R" ] && echo "  [OK] ISP DNS ($ISP_DNS1): $R" || echo "  [!] ISP DNS bağlantı hatası"
fi

R=$(nslookup cpentp.superonline.net 127.0.0.1 2>&1 | grep -i "address" | tail -1)
[ -n "$R" ] && echo "  [OK] Split-DNS (AGH:53): $R" || echo "  [!] Split-DNS çalışmadı"

R=$(nslookup google.com 127.0.0.1 2>&1 | grep -i "address" | tail -1)
[ -n "$R" ] && echo "  [OK] Genel DNS: $R" || echo "  [!] Genel DNS bozuk!"

echo ""
echo "================================================================"
echo "  DNS ZİNCİRİ TAMAMLANDI (v3)"
echo "  AdGuard(:53) -> DoH(:$HDNSP_PORT) | dnsmasq(:$AGH_DNS_PORT DHCP-only)"
echo "  Split-DNS: *.superonline.net -> ISP DNS (AdGuard upstream)"
echo "  Per-client: AdGuard panelinde her cihaz görünür!"
echo "  force_dns: KAPALI"
echo "  AdGuard: http://$LAN_IP:$AGH_WEB_PORT"
echo ""
echo "  *** TV+ KUTUSUNU YENİDEN BAŞLATIN! ***"
echo "================================================================"
"""

DNS_CHAIN_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# uninstall_dns_chain.sh (v3) - KOMPLE TEMİZLİK
# AdGuard Home + HTTPS-DNS-Proxy + dnsmasq ayarları + lease + konfigürasyonlar
# ==============================================================================

set -u

<<PKG_MANAGER_BLOCK>>

echo "================================================================"
echo "  DNS Zinciri - Komple Kaldırma"
echo "================================================================"

# --- 1. ADGUARD HOME ---
echo "[1/6] AdGuard Home tamamen kaldırılıyor..."
/etc/init.d/adguardhome stop 2>/dev/null || true
killall -9 AdGuardHome adguardhome 2>/dev/null || true
/etc/init.d/adguardhome disable 2>/dev/null || true

# paket kaldırma
pkg_remove luci-app-adguardhome adguardhome 2>/dev/null || true

# Konfig dosyaları
rm -f /etc/config/adguardhome
rm -rf /etc/adguardhome
rm -rf /var/adguardhome

# Binary kurulum kalıntıları (eğer önce binary ile kurulduysa)
rm -rf /opt/AdGuardHome 2>/dev/null || true
rm -f /etc/init.d/adguardhome 2>/dev/null || true

echo "    AdGuard Home tamamen silindi."

# --- 2. HTTPS-DNS-PROXY ---
echo "[2/6] HTTPS-DNS-Proxy tamamen kaldırılıyor..."
/etc/init.d/https-dns-proxy stop 2>/dev/null || true
killall -9 https-dns-proxy 2>/dev/null || true
/etc/init.d/https-dns-proxy disable 2>/dev/null || true

# UCI konfigürasyonu tamamen temizle
uci -q delete https-dns-proxy.config.force_dns 2>/dev/null || true
uci -q delete https-dns-proxy.config.force_dns_port 2>/dev/null || true
uci -q delete https-dns-proxy.config.force_dns_src_interface 2>/dev/null || true
uci -q delete https-dns-proxy.config.dnsmasq_config_update 2>/dev/null || true
while uci -q delete https-dns-proxy.@https-dns-proxy[0] 2>/dev/null; do :; done
uci -q delete https-dns-proxy.config 2>/dev/null || true
uci -q delete https-dns-proxy.cf 2>/dev/null || true
uci -q delete https-dns-proxy.goog 2>/dev/null || true
uci commit https-dns-proxy 2>/dev/null || true

# paket kaldırma
pkg_remove luci-app-https-dns-proxy https-dns-proxy 2>/dev/null || true

# Konfig kalıntıları
rm -f /etc/config/https-dns-proxy 2>/dev/null || true

echo "    HTTPS-DNS-Proxy tamamen silindi."

# --- 3. DNSMASQ VARSAYILANA DÖNDÜR ---
echo "[3/6] dnsmasq varsayılanına döndürülüyor..."

# Port (varsayılan 53'e dön)
uci -q delete dhcp.@dnsmasq[0].port 2>/dev/null || true

# noresolv kaldır (WAN DNS tekrar kullanılsın)
uci -q delete dhcp.@dnsmasq[0].noresolv 2>/dev/null || true

# Cache varsayılana
uci set dhcp.@dnsmasq[0].cachesize='150'

# Tüm server kurallarını temizle (split-DNS dahil)
uci -q delete dhcp.@dnsmasq[0].server 2>/dev/null || true

# Rebind koruması aç
uci set dhcp.@dnsmasq[0].rebind_protection='1'

# Rebind domain istisnalarını temizle
uci -q del_list dhcp.@dnsmasq[0].rebind_domain='/superonline.net/' 2>/dev/null || true
uci -q del_list dhcp.@dnsmasq[0].rebind_domain='/superonline.com/' 2>/dev/null || true
uci -q del_list dhcp.@dnsmasq[0].rebind_domain='/superonlinetv.com/' 2>/dev/null || true

# DHCP option temizle (DNS yönlendirme)
uci -q delete dhcp.lan.dhcp_option 2>/dev/null || true

# confdir temizle
uci -q delete dhcp.@dnsmasq[0].confdir 2>/dev/null || true

echo "    dnsmasq varsayılanına döndü."

# --- 4. TV+ DHCP / STATIC LEASE TEMİZLİĞİ ---
echo "[4/6] TV+ DHCP lease ve static host temizliği..."

# UCI named host temizle
uci -q delete dhcp.tvplus_stb 2>/dev/null || true
uci -q delete dhcp.tvplus 2>/dev/null || true
uci -q delete dhcp.tvplus_dns 2>/dev/null || true

# Anonim host tanımlarını temizle (tvplus ile ilgili tüm satırlar)
for idx in $(seq 30 -1 0); do
    name=$(uci -q get "dhcp.@host[$idx].name" 2>/dev/null) || continue
    case "$name" in
        tvplus*|TV_Plus*|tvplus-stb*|TVPLUS*)
            uci -q delete "dhcp.@host[$idx]" 2>/dev/null || true
            echo "    dhcp.@host[$idx] ($name) silindi"
            ;;
    esac
done

# Tag tanımlarını temizle
for idx in $(seq 10 -1 0); do
    uci -q get "dhcp.@tag[$idx]" >/dev/null 2>&1 || continue
    uci -q delete "dhcp.@tag[$idx]" 2>/dev/null || true
done

# dnsmasq.d konfig dosyaları
rm -f /etc/dnsmasq.d/tvplus-dns.conf 2>/dev/null || true
rm -f /etc/dnsmasq.d/tvplus*.conf 2>/dev/null || true
rmdir /etc/dnsmasq.d 2>/dev/null || true

# /tmp/dhcp.leases içerisindeki tvplus ile ilgili satırları temizle
if [ -f /tmp/dhcp.leases ]; then
    sed -i '/tvplus/Id' /tmp/dhcp.leases 2>/dev/null || true
    sed -i '/TV_Plus/Id' /tmp/dhcp.leases 2>/dev/null || true
    sed -i '/tvplus-stb/Id' /tmp/dhcp.leases 2>/dev/null || true
    echo "    DHCP lease dosyası temizlendi"
fi

uci commit dhcp

echo "    TV+ DHCP kalıntıları tamamen temizlendi."

# --- 5. FIREWALL TEMİZLİĞİ ---
echo "[5/6] Firewall redirect ve eski kurallar temizleniyor..."

# https-dns-proxy'nin bıraktığı redirect kurallarını temizle
/etc/init.d/firewall restart 2>/dev/null || true
sleep 1

# nftables redirect doğrulaması
REDIR=$(nft list ruleset 2>/dev/null | grep -c "dport 53.*redirect" 2>/dev/null) || true
REDIR=${REDIR:-0}
if [ "$REDIR" -gt 0 ] 2>/dev/null; then
    echo "    $REDIR redirect kuralı kaldı, zorla temizleniyor..."
    nft flush chain inet fw4 dstnat 2>/dev/null || true
    /etc/init.d/firewall restart 2>/dev/null || true
fi

echo "    Firewall temiz."

# --- 6. SERVİSLERİ YENİDEN BAŞLAT ---
echo "[6/6] Servisler yeniden başlatılıyor..."
killall -9 dnsmasq 2>/dev/null || true
sleep 1
/etc/init.d/dnsmasq restart 2>/dev/null || true

echo ""
echo "================================================================"
echo "  DNS ZİNCİRİ TAMAMEN KALDIRILDI"
echo "================================================================"
echo "  - AdGuard Home: silindi (paket + konfig + data)"
echo "  - HTTPS-DNS-Proxy: silindi (paket + konfig + redirect)"
echo "  - dnsmasq: varsayılan (port 53, WAN DNS)"
echo "  - TV+ static lease: temizlendi"
echo "  - DHCP leases: temizlendi"
echo "  - Firewall redirect: temizlendi"
echo ""
echo "  *** TV+ KUTUSUNU YENİDEN BAŞLATIN! ***"
echo "================================================================"
"""