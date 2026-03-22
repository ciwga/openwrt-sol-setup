# -*- coding: utf-8 -*-
"""Shell script uyumluluk sabitleri.

OpenWrt 25.12 ile birlikte paket yöneticisi opkg'den apk'ya geçti.
Üretilen shell scriptleri bağımsız (tek dosya) çalışmak zorunda olduğundan
bu bloğu her script'e gömmek gerekir — ama kaynak burada tek yerde tutulur.

Kullanım (template dosyalarında):
    from compat import PKG_MANAGER_BLOCK

    BENIM_TEMPLATE = r\"\"\"#!/bin/sh
    set -e
    {PKG_MANAGER_BLOCK}
    ...
    \"\"\".replace("{PKG_MANAGER_BLOCK}", PKG_MANAGER_BLOCK)

    Ya da manager.py'de toplu replace yapılıyorsa placeholder yeterli:
    # Script içinde: <<PKG_MANAGER_BLOCK>>
"""

from typing import Final

# ==============================================================================
# USB ETHERnet (Realtek r8152 ailesi) BOOT FIX SERVİSİ
# ==============================================================================
#
# Sorun:
#   Realtek RTL8152/8153/8156/8156B/8157 yongalı USB Ethernet adaptörler
#   OpenWrt'te yeniden başlatma sonrasında "uykuya dalabilir": arayüz kernel'e
#   kayıtlıdır ama paket gönderip alamaz duruma gelir.
#
# Çözüm:
#   init.d servisi boot tamamlandıktan sonra (START=99) Realtek r8152 ailesine
#   ait tüm arayüzleri iki yöntemle tespit eder:
#     1. sysfs driver adı kalıbı: r815*  (r8152, r8153, r8156 vb.)
#     2. USB Vendor ID: 0x0bda (Realtek) — driver symlink görünmese de yakalar
#   Eşleşen her arayüze down → kısa bekleme → up döngüsü uygular.
#
# Kapsanan çipler:
#   RTL8152B, RTL8153, RTL8153A, RTL8153B, RTL8156, RTL8156B, RTL8157
#   (Hepsi Linux'ta r8152.ko modülünü kullanır.)
#
# Çoklu adaptör güvenliği:
#   Adaptörler arasında 2 saniyelik bekleme USB veri yolu (bus) çakışmasını
#   önler.
#
USB_FIX_SERVICE: Final[str] = """\
#!/bin/sh /etc/rc.common
# =============================================================================
# usb-lan-fix — Realtek USB Ethernet otomatik arayüz uyandırıcı
# Otomatik üretildi: OpenWrt Ağ Yöneticisi
#
# Kapsanan çipler (tümü r8152 kernel modülünü kullanır):
#   RTL8152B, RTL8153, RTL8153A/B, RTL8156, RTL8156B, RTL8157
#
# Tespit yöntemi (çift katmanlı, hangisi tutarsa):
#   1. sysfs driver adı: r815* kalıbı (r8152, r8153, r8156 vb.)
#   2. USB Vendor ID : 0x0bda (Realtek) — driver adı görünmese bile yakalar
#
# Sabit arayüz adı gerektirmez; kaç adaptör takılırsa otomatik bulur.
# =============================================================================
START=99
STOP=10

# Verilen arayüzün Realtek r8152 ailesinden olup olmadığını kontrol eder.
# Çıkış kodu 0 = eşleşme var, 1 = eşleşme yok.
_is_r8152_family() {
    local iface="$1"
    local drv_link="/sys/class/net/$iface/device/driver"

    # Yöntem 1 — sysfs driver symlink adı: r815* kalıbı
    # RTL8152→r8152, RTL8153→r8152 ya da r8153, RTL8156B→r8152
    if [ -L "$drv_link" ]; then
        drv=$(readlink "$drv_link" 2>/dev/null | sed 's|.*/||')
        case "$drv" in
            r815*)
                return 0
                ;;
        esac
    fi

    # Yöntem 2 — USB Vendor ID: 0x0bda = Realtek Semiconductor Corp.
    # Driver symlink oluşmadan önce ya da farklı kernel patchlerinde güvenilir.
    local vendor_file="/sys/class/net/$iface/device/../idVendor"
    if [ -f "$vendor_file" ]; then
        vendor=$(cat "$vendor_file" 2>/dev/null | tr '[:upper:]' '[:lower:]')
        [ "$vendor" = "0bda" ] && return 0
    fi

    return 1
}

start() {
    logger -t usb-lan-fix "Realtek r8152 ailesi USB adaptörler taranıyor..."
    FOUND=0
    for iface in $(ls /sys/class/net/ 2>/dev/null); do
        if _is_r8152_family "$iface"; then
            FOUND=$((FOUND + 1))
            # Birden fazla adaptörde USB veri yolu çakışmasını önlemek için
            # ilk adaptörden sonra kısa bekleme uygula
            [ $FOUND -gt 1 ] && sleep 2
            drv=$(readlink "/sys/class/net/$iface/device/driver" 2>/dev/null | sed 's|.*/||')
            logger -t usb-lan-fix "  [$FOUND] $iface (drv=${drv:-bilinmiyor}) down/up döngüsü..."
            ip link set dev "$iface" down 2>/dev/null || true
            sleep 1
            ip link set dev "$iface" up   2>/dev/null || true
            logger -t usb-lan-fix "  [$FOUND] $iface aktif."
        fi
    done
    if [ "$FOUND" -eq 0 ]; then
        logger -t usb-lan-fix "r8152 ailesi adaptör bulunamadı — atlandı."
    else
        logger -t usb-lan-fix "$FOUND adet Realtek USB adaptör resetlendi."
    fi
}

stop() { : ; }
"""

# ==============================================================================
# OPENWRT ÇALIŞMA ORTAMI KORUMASI
# ==============================================================================
# Tüm üretilen betiklerin başına eklenir.
# Betik yanlışlıkla yerel makinede çalıştırılırsa anlamlı hata mesajı
# basar ve çıkar — uci/opkg bulunamadı hatası yerine.
OPENWRT_GUARD: Final[str] = """\
# --- OpenWrt Ortam Kontrolü ---
if ! command -v uci >/dev/null 2>&1; then
    echo '------------------------------------------------------------'
    echo '  HATA: Bu betik yalnizca OpenWrt router uzerinde calisir.'
    echo '  Lutfen betigi yerel makinenizde calistirmayin.'
    echo ''
    echo '  Dogru kullanim (SSH ile gonderin):'
    echo '    cat BETIK.sh | ssh root@192.168.1.1 ash'
    echo '------------------------------------------------------------'
    exit 1
fi"""

# Shell bloğu — her üretilen .sh dosyasına gömülür.
# Değiştirilmesi gereken tek yer burasıdır.
PKG_MANAGER_BLOCK: Final[str] = """\
# --- PAKET YÖNETİCİSİ UYUMLULUK KATMANI ---
# OpenWrt < 25.12: opkg | OpenWrt >= 25.12: apk
_owrt_ver() { grep DISTRIB_RELEASE /etc/openwrt_release 2>/dev/null | cut -d'=' -f2 | tr -d "\\\"'" | cut -d'.' -f1; }
if command -v apk >/dev/null 2>&1 && [ "$(_owrt_ver)" -ge 25 ] 2>/dev/null; then
    PKG_MANAGER="apk"
    pkg_update()       { apk update "$@"; }
    pkg_install()      { apk add "$@"; }
    pkg_remove()       { apk del "$@"; }
    pkg_is_installed() { apk info --installed "$1" >/dev/null 2>&1; }
else
    PKG_MANAGER="opkg"
    pkg_update()       { opkg update "$@"; }
    pkg_install()      { opkg install "$@"; }
    pkg_remove()       { opkg remove "$@"; }
    pkg_is_installed() { opkg list-installed 2>/dev/null | awk '{print $1}' | grep -q "^${1}$"; }
fi"""
