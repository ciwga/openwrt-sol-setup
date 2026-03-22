# -*- coding: utf-8 -*-
"""Raspberry Pi 5 özel araçlar.

İki bağımsız modül:
  1. Disk Genişletme - SD kart/SSD üzerindeki root bölümünü tam kapasiteye genişletir
  2. Argon ONE V3 Fan Kontrol - LuCI arayüzünden fan hız kontrolü sağlar

Not: Disk genişletme tüm OpenWrt cihazlarda çalışır.
     Fan kontrol sadece Argon ONE V3 kasası olan Raspberry Pi 5 içindir.
"""

from typing import Final

DISK_EXPAND_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# expand_disk.sh - Disk Genişletme (OpenWrt)
#
# SD kart veya SSD üzerindeki root bölümünü tam kapasiteye genişletir.
# Kaynak: https://openwrt.org/docs/guide-user/advanced/expand_root
#
# UYARI: İşlem 2 yeniden başlatma gerektirir!
#   1. reboot: Bölüm (partition) genişletilir  → otomatik reboot
#   2. reboot: Dosya sistemi (filesystem) genişletilir → otomatik reboot
#   Her iki adım uci-defaults mekanizmasıyla otomatik çalışır.
# ==============================================================================

set -e

<<PKG_MANAGER_BLOCK>>

echo ""
echo "================================================================"
echo "  Disk Genişletme"
echo "================================================================"

# Zaten tamamlanmış mı?
if [ -e /etc/rootfs-resize ]; then
    echo ""
    df -h / | awk 'NR==2{printf "  Zaten genişletilmiş: Toplam %s | Kullanılan %s | Boş %s\n", $2, $3, $4}'
    echo "================================================================"
    exit 0
fi

# Mevcut durum
echo ""
df -h / | awk 'NR==2{printf "  Mevcut: Toplam %s | Kullanılan %s | Boş %s\n", $2, $3, $4}'
echo ""

# --- 1. PAKETLER ---
echo "[1/3] Paketler kuruluyor... ($PKG_MANAGER)"
pkg_update >/dev/null 2>&1 || { echo "HATA: $PKG_MANAGER update başarısız!"; exit 1; }
for pkg in parted losetup resize2fs blkid; do
    pkg_install "$pkg" >/dev/null 2>&1 && echo "    $pkg OK" || echo "    $pkg atlandı (zaten mevcut olabilir)"
done

# --- 2. STARTUP BETİKLERİ ---
echo "[2/3] Startup betikleri yazılıyor..."

cat << "PTEOF" > /etc/uci-defaults/70-rootpt-resize
if [ ! -e /etc/rootpt-resize ] \
&& type parted > /dev/null \
&& lock -n /var/lock/root-resize
then
ROOT_BLK="$(readlink -f /sys/dev/block/"$(awk -e \
'$9=="/dev/root"{print $3}' /proc/self/mountinfo)")"
ROOT_DISK="/dev/$(basename "${ROOT_BLK%/*}")"
ROOT_PART="${ROOT_BLK##*[^0-9]}"
parted -f -s "${ROOT_DISK}" \
resizepart "${ROOT_PART}" 100%
mount_root done
touch /etc/rootpt-resize

if [ -e /boot/cmdline.txt ]
then
NEW_UUID=`blkid ${ROOT_DISK}p${ROOT_PART} | sed -n 's/.*PARTUUID="\([^"]*\)".*/\1/p'`
sed -i "s/PARTUUID=[^ ]*/PARTUUID=${NEW_UUID}/" /boot/cmdline.txt
fi

reboot
fi
exit 1
PTEOF

cat << "FSEOF" > /etc/uci-defaults/80-rootfs-resize
if [ ! -e /etc/rootfs-resize ] \
&& [ -e /etc/rootpt-resize ] \
&& type losetup > /dev/null \
&& type resize2fs > /dev/null \
&& lock -n /var/lock/root-resize
then
ROOT_BLK="$(readlink -f /sys/dev/block/"$(awk -e \
'$9=="/dev/root"{print $3}' /proc/self/mountinfo)")"
ROOT_DEV="/dev/${ROOT_BLK##*/}"
LOOP_DEV="$(awk -e '$5=="/overlay"{print $9}' \
/proc/self/mountinfo)"
if [ -z "${LOOP_DEV}" ]
then
LOOP_DEV="$(losetup -f)"
losetup "${LOOP_DEV}" "${ROOT_DEV}"
fi
resize2fs -f "${LOOP_DEV}"
mount_root done
touch /etc/rootfs-resize
reboot
fi
exit 1
FSEOF

# sysupgrade sonrasında betikler korunsun
grep -q "70-rootpt-resize" /etc/sysupgrade.conf 2>/dev/null || \
cat << "SUEOF" >> /etc/sysupgrade.conf
/etc/uci-defaults/70-rootpt-resize
/etc/uci-defaults/80-rootfs-resize
SUEOF

echo "    70-rootpt-resize → OK"
echo "    80-rootfs-resize → OK"
echo "    sysupgrade.conf  → OK"

# --- 3. BAŞLAT ---
echo "[3/3] Bölüm genişletiliyor ve yeniden başlatılıyor..."
echo ""
echo "  Sistem şimdi yeniden başlayacak (1. reboot: bölüm genişletme)."
echo "  Ardından otomatik olarak tekrar başlayacak (2. reboot: dosya sistemi)."
echo "  Tamamlandıktan sonra 'df -h /' ile kontrol edin."
echo "================================================================"

sh /etc/uci-defaults/70-rootpt-resize
"""

ARGON_FAN_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# setup_argon_fan.sh - Argon ONE V3 Fan Kontrol (Raspberry Pi 5)
#
# LuCI arayüzünden fan hız kontrolü sağlar.
# SADECE Argon ONE V3 kasası olan Raspberry Pi 5 için geçerlidir.
# Kasa yoksa bu betiği çalıştırmayın, işe yaramaz.
#
# Kaynak: https://github.com/ciwga/luci-app-argononev3-fancontrol
# ==============================================================================

echo ""
echo "================================================================"
echo "  Argon ONE V3 Fan Kontrol Kurulumu"
echo "  Sadece Raspberry Pi 5 + Argon ONE V3 kasası için"
echo "================================================================"

# Raspberry Pi 5 mi kontrol et
MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
if ! echo "$MODEL" | grep -qi "raspberry pi 5"; then
    echo ""
    echo "  HATA: Bu cihaz Raspberry Pi 5 değil!"
    echo "  Model: $MODEL"
    echo "  Argon ONE V3 fan kontrol sadece RPi5 için çalışır."
    echo "================================================================"
    exit 1
fi

echo ""
echo "  Cihaz: $MODEL"
echo "  Argon ONE V3 fan kontrol yükleniyor..."
echo ""

# Kurulum betiğini indir ve çalıştır
wget -qO - https://raw.githubusercontent.com/ciwga/luci-app-argononev3-fancontrol/main/install.sh | sh

if [ $? -eq 0 ]; then
    echo ""
    echo "================================================================"
    echo "  Argon ONE V3 Fan Kontrol KURULDU"
    echo ""
    echo "  LuCI arayüzünden erişim:"
    echo "    Sistem > Argon ONE V3 Fan Kontrol"
    echo ""
    echo "  Varsayılan fan profili otomatik etkinleştirildi."
    echo "================================================================"
else
    echo ""
    echo "  HATA: Kurulum başarısız!"
    echo "  İnternet bağlantınızı kontrol edin."
    echo "  Manuel kurulum:"
    echo "    wget -qO - https://raw.githubusercontent.com/ciwga/luci-app-argononev3-fancontrol/main/install.sh | sh"
    echo "================================================================"
    exit 1
fi
"""

ARGON_FAN_UNINSTALL_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# uninstall_argon_fan.sh - Argon ONE V3 Fan Kontrol Kaldırma
# ==============================================================================

echo "================================================================"
echo "  Argon ONE V3 Fan Kontrol Kaldırılıyor"
echo "================================================================"

<<PKG_MANAGER_BLOCK>>

pkg_remove luci-app-argononev3-fancontrol 2>/dev/null || true
pkg_remove argononev3-fancontrol 2>/dev/null || true

echo ""
echo "  Fan kontrol kaldırıldı."
echo "================================================================"
"""

DISK_STATUS_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# disk_status.sh - Disk Durum Raporu
# ==============================================================================

echo "================================================================"
echo "  Disk Durumu"
echo "================================================================"
echo ""

# Root dosya sistemi
echo "  Root Dosya Sistemi:"
df -h / | awk 'NR==2{printf "    Toplam: %s | Kullanılan: %s (%s) | Boş: %s\n", $2, $3, $5, $4}'

# Overlay
echo ""
echo "  Overlay:"
df -h /overlay 2>/dev/null | awk 'NR==2{printf "    Toplam: %s | Kullanılan: %s (%s) | Boş: %s\n", $2, $3, $5, $4}' || echo "    Overlay bulunamadı"

# Blok aygıtlar
echo ""
echo "  Blok Aygıtlar:"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>/dev/null || df -h

# Genişletme durumu
echo ""
echo "  Genişletme Durumu:"
[ -e /etc/rootpt-resize ] && echo "    Bölüm:       GENİŞLETİLDİ" || echo "    Bölüm:       GENİŞLETİLMEDİ"
[ -e /etc/rootfs-resize ] && echo "    Dosya sistemi: GENİŞLETİLDİ" || echo "    Dosya sistemi: GENİŞLETİLMEDİ"

echo ""
echo "================================================================"
"""
