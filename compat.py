# -*- coding: utf-8 -*-
"""Shell script uyumluluk sabitleri ve donanımsal onarım servisleri.

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

Özellikler:
    USB_FIX_SERVICE (Final[str]): USB Ethernet denetleyicileri için donanımsal güç sıfırlama init betiği.
    OPENWRT_GUARD (Final[str]): Betiklerin yerel Linux platformlarında yanlışlıkla çalıştırılmasını önleyen koruma katmanı.
    PKG_MANAGER_BLOCK (Final[str]): OpenWrt sürümleri arasında paket yöneticisi (opkg/apk) soyutlama katmanı.
    USB_FIX_SETUP_TEMPLATE (Final[str]): USB Fix kurulumunu gerçekleştiren bağımsız kabuk betiği şablonu.
    USB_FIX_UNINSTALL_TEMPLATE (Final[str]): USB Fix bileşenlerini ve Raspberry Pi yamalarını temizleyen kabuk betiği şablonu.
"""

from typing import Final

# ==============================================================================
# USB ETHERNET (Realtek r8152 ailesi) BOOT FIX SERVİSİ
# ==============================================================================
USB_FIX_SERVICE: Final[str] = """\
#!/bin/sh /etc/rc.common
# =============================================================================
# usb-lan-fix — Anakart USB Güç Kesintisi
# Otomatik üretildi: OpenWrt Ağ Yöneticisi
# =============================================================================
START=19
STOP=10

start() {
    logger -t usb-lan-fix " [+] xHCI Donanım Reset başlatıldı."

    CAN_RESET=0
    ROOT_FS=$(mount | awk '$3 == "/" {print $1}')
    case "$ROOT_FS" in
        *mmcblk*|*nvme*|*mtdblock*|*ubifs*) 
            CAN_RESET=1 
            ;;
        /dev/root)
            if grep -q -e "root=PARTUUID" -e "root=/dev/mmc" -e "root=/dev/nvme" /proc/cmdline; then
                CAN_RESET=1
            fi
            ;;
    esac

    if [ "$CAN_RESET" -eq 1 ]; then
        logger -t usb-lan-fix " [+] RootFS SD/NVMe üzerinde. Anakart USB gücü kesiliyor..."

        PLATFORM_DEVS=""
        PCI_DEVS=""

        for hcd in /sys/bus/platform/drivers/xhci-hcd/*; do
            if [ -d "$hcd" ]; then
                dev_id=$(basename "$hcd")
                if [ "$dev_id" != "module" ] && [ "$dev_id" != "bind" ] && [ "$dev_id" != "unbind" ]; then
                    PLATFORM_DEVS="$PLATFORM_DEVS $dev_id"
                fi
            fi
        done

        for hcd in /sys/bus/pci/drivers/xhci_hcd/0000:*; do
            if [ -d "$hcd" ]; then
                dev_id=$(basename "$hcd")
                PCI_DEVS="$PCI_DEVS $dev_id"
            fi
        done

        for dev_id in $PLATFORM_DEVS; do
            logger -t usb-lan-fix " [+] Platform xHCI Koparılıyor: $dev_id"
            echo "$dev_id" > /sys/bus/platform/drivers/xhci-hcd/unbind 2>/dev/null || true
        done
        for dev_id in $PCI_DEVS; do
            logger -t usb-lan-fix " [+] PCI xHCI Koparılıyor: $dev_id"
            echo "$dev_id" > /sys/bus/pci/drivers/xhci_hcd/unbind 2>/dev/null || true
        done

        sleep 2

        for dev_id in $PLATFORM_DEVS; do
            logger -t usb-lan-fix " [+] Platform xHCI Bağlanıyor: $dev_id"
            echo "$dev_id" > /sys/bus/platform/drivers/xhci-hcd/bind 2>/dev/null || true
        done
        for dev_id in $PCI_DEVS; do
            logger -t usb-lan-fix " [+] PCI xHCI Bağlanıyor: $dev_id"
            echo "$dev_id" > /sys/bus/pci/drivers/xhci_hcd/bind 2>/dev/null || true
        done

        logger -t usb-lan-fix " [+] Anakart USB portlarına güç başarıyla geri verildi. Donanım uyanacak."
    else
        logger -t usb-lan-fix " [-] RİSKLİ: USB üzerinden boot edilmiş olabilir. Donanım reseti iptal edildi."
    fi
}

stop() {
    : ;
}
"""

# ==============================================================================
# OPENWRT ÇALIŞMA ORTAMI KORUMASI
# ==============================================================================
OPENWRT_GUARD: Final[str] = """\
# --- OpenWrt Ortam Kontrolü ---
if ! command -v uci >/dev/null 2>&1; then
    echo '------------------------------------------------------------'
    echo '  HATA: Bu betik yalnızca OpenWrt router üzerinde çalışır.'
    echo '  Lütfen betiği yerel makinenizde çalıştırmayın.'
    echo ''
    echo '  Doğru kullanım (SSH ile gönderin):'
    echo '    cat BETİK.sh | ssh root@192.168.1.1 ash'
    echo '------------------------------------------------------------'
    exit 1
fi"""

# ==============================================================================
# PAKET YÖNETİCİSİ UYUMLULUK KATMANI
# ==============================================================================
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

# ==============================================================================
# BAĞIMSIZ USB FIX KURULUM VE KALDIRMA ŞABLONLARI
# ==============================================================================
USB_FIX_SETUP_TEMPLATE: Final[str] = f"""#!/bin/sh
# ==============================================================================
# setup_usb_fix.sh - USB Ethernet xHCI Donanımsal Reset Kurulumu
# ==============================================================================

set -e

<<PKG_MANAGER_BLOCK>>

echo "================================================================"
echo "  USB Ethernet (r8152) ANAKART GÜÇ KESİNTİSİ Fix Kurulumu"
echo "================================================================"

echo "[1/4] Raspberry Pi 5 USB Akım Limiti Kontrolü..."
BOOT_CONF=""
if [ -f /boot/config.txt ]; then
    BOOT_CONF="/boot/config.txt"
elif [ -f /boot/firmware/config.txt ]; then
    BOOT_CONF="/boot/firmware/config.txt"
fi

if [ -n "$BOOT_CONF" ]; then
    mount -o remount,rw /boot 2>/dev/null || true
    mount -o remount,rw /boot/firmware 2>/dev/null || true
    
    if ! grep -q "usb_max_current_enable=1" "$BOOT_CONF"; then
        echo "" >> "$BOOT_CONF"
        echo "# OpenWrt USB Fix: RPi5 USB port akım limitini 600mA'den 1600mA'e çıkarır" >> "$BOOT_CONF"
        echo "usb_max_current_enable=1" >> "$BOOT_CONF"
        echo "  [+] usb_max_current_enable=1 eklendi! (USB portlarına 1.6A tam güç verildi)"
    else
        echo "  [+] Akım limiti zaten kaldırılmış (1.6A aktif durumda)."
    fi
else
    echo "  [-] /boot/config.txt bulunamadı, akım limiti yaması atlandı."
fi

echo "[2/4] /etc/init.d/usb-lan-fix servisi oluşturuluyor..."
cat << 'EOF_USBFIX' > /etc/init.d/usb-lan-fix
{USB_FIX_SERVICE}
EOF_USBFIX

echo "[3/4] İzinler ayarlanıyor ve başlangıç servisi etkinleştiriliyor..."
chmod +x /etc/init.d/usb-lan-fix
/etc/init.d/usb-lan-fix enable

echo "[4/4] Servis şu an anında tetikleniyor..."
/etc/init.d/usb-lan-fix start

echo "================================================================"
echo "  KURULUM TAMAMLANDI!"
echo "  Sistem açılışında ağ servisleri devreye girmeden hemen önce"
echo "  USB kontrolcüsünün (xHCI) elektriği kesilip geri verilecektir."
echo "  NOT: Akım limiti değişikliğinin (1.6A) aktif olması için"
echo "  cihazınızı YENİDEN BAŞLATMANIZ (Reboot) gerekmektedir."
echo "================================================================"
"""

USB_FIX_UNINSTALL_TEMPLATE: Final[str] = """#!/bin/sh
# ==============================================================================
# uninstall_usb_fix.sh - USB Ethernet xHCI Donanımsal Reset Kaldırma
# ==============================================================================

echo "================================================================"
echo "  USB Ethernet Boot Fix Kaldırılıyor..."
echo "================================================================"
if [ -f "/etc/init.d/usb-lan-fix" ]; then
    /etc/init.d/usb-lan-fix disable >/dev/null 2>&1 || true
    rm -f /etc/init.d/usb-lan-fix
    echo "  > Servis başarıyla sistemden silindi."
else
    echo "  > Servis zaten kurulu değil."
fi

BOOT_CONF=""
if [ -f /boot/config.txt ]; then
    BOOT_CONF="/boot/config.txt"
elif [ -f /boot/firmware/config.txt ]; then
    BOOT_CONF="/boot/firmware/config.txt"
fi

if [ -n "$BOOT_CONF" ]; then
    mount -o remount,rw /boot 2>/dev/null || true
    mount -o remount,rw /boot/firmware 2>/dev/null || true
    sed -i '/usb_max_current_enable=1/d' "$BOOT_CONF"
    sed -i '/OpenWrt USB Fix/d' "$BOOT_CONF"
    echo "  > usb_max_current_enable (1.6A) yaması config.txt dosyasından kaldırıldı."
fi

echo "================================================================"
"""