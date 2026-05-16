# -*- coding: utf-8 -*-
"""
Raspberry Pi 5 özel araçlar.

İki bağımsız modül:
  1. Disk Genişletme - SD kart/SSD üzerindeki root bölümünü tam kapasiteye genişletir
  2. Argon ONE V3 Fan Kontrol - LuCI arayüzünden fan hız kontrolü sağlar

Not: Disk genişletme tüm OpenWrt cihazlarda çalışır.
     Fan kontrol sadece Argon ONE V3 kasası olan Raspberry Pi 5 içindir.
"""

from typing import Final

DISK_EXPAND_TEMPLATE: Final[str] = r"""#!/bin/sh
# ==============================================================================
# expand_disk.sh - Otomatik ve Kalıcı Disk Genişletme (OpenWrt)
#
# SD kart veya SSD üzerindeki root bölümünü tam kapasiteye genişletir.
# Attended Sysupgrade sonrasında boyutun küçülmesini engellemek için
# kalıcı bir oto-genişletme servisi kurar.
# ==============================================================================

set -e

<<PKG_MANAGER_BLOCK>>

echo ""
echo "================================================================"
echo "  Kalıcı Otonom Disk Genişletme Kurulumu"
echo "================================================================"

# --- Güncelleme sonrası eski bootloop yapan hatalı betikleri silme ---
rm -f /etc/uci-defaults/70-rootpt-resize 2>/dev/null || true
rm -f /etc/uci-defaults/80-rootfs-resize 2>/dev/null || true
sed -i '/70-rootpt-resize/d' /etc/sysupgrade.conf 2>/dev/null || true
sed -i '/80-rootfs-resize/d' /etc/sysupgrade.conf 2>/dev/null || true

# Önceki denemelerden kalan başarı bayraklarını temizle
rm -f /etc/.disk_* 2>/dev/null || true

echo "[1/4] Gerekli disk araçları kuruluyor... ($PKG_MANAGER)"
pkg_update >/dev/null 2>&1 || true
for pkg in parted losetup resize2fs blkid e2fsprogs; do
    pkg_install "$pkg" >/dev/null 2>&1 && echo "    $pkg OK" || echo "    $pkg atlandı"
done

echo "[2/4] Kalıcı oto-genişletme betiği oluşturuluyor..."

cat << 'EOF_EXPAND' > /etc/auto_expand.sh
#!/bin/sh

# ==============================================================================
# SYSUPGRADE TESPİTİ VE ONARIMI
# ==============================================================================
ROOT_BLK_SYS="$(readlink -f /sys/dev/block/"$(awk -e '$9=="/dev/root"{print $3}' /proc/self/mountinfo 2>/dev/null)" 2>/dev/null)"
if [ -n "$ROOT_BLK_SYS" ]; then
    PART_NAME="$(basename "$ROOT_BLK_SYS")"
    if [ -f "/sys/class/block/$PART_NAME/size" ]; then
        PART_SECTORS=$(cat "/sys/class/block/$PART_NAME/size" 2>/dev/null || echo "0")
        if [ "$PART_SECTORS" -gt 0 ] && [ "$PART_SECTORS" -lt 1000000 ]; then
            rm -f /etc/.disk_expanded
            rm -f /etc/.disk_part_done
            rm -f /etc/.disk_fs_done
        fi
    fi
fi

[ -f /etc/.disk_expanded ] && exit 0

# Sysupgrade sonrası silinen paketleri internet gelince geri kur
if ! command -v parted >/dev/null || ! command -v resize2fs >/dev/null || ! command -v losetup >/dev/null; then
    logger -t disk_expander "Sysupgrade durumu tespit edildi. Paketler icin internet bekleniyor..."
    for i in $(seq 1 36); do
        if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
            logger -t disk_expander "Internet mevcut. Eksik paketler kuruluyor..."
            if command -v apk >/dev/null; then
                apk update && apk add parted losetup e2fsprogs blkid || true
            else
                opkg update && opkg install parted losetup resize2fs blkid || true
            fi
            break
        fi
        sleep 5
    done
    if ! command -v parted >/dev/null || ! command -v resize2fs >/dev/null; then
        logger -t disk_expander "HATA: Paketler kurulamadi."
        exit 0
    fi
fi

ROOT_DEV="/dev/$(basename "$ROOT_BLK_SYS")"
ROOT_DISK="/dev/$(basename "$(dirname "$ROOT_BLK_SYS")")"
ROOT_PART="${ROOT_DEV##*[^0-9]}"

# Adım 1: Partition Genişletme
if [ ! -f /etc/.disk_part_done ]; then
    logger -t disk_expander "Adım 1: Disk bölümü %100 kapasiteye genişletiliyor..."
    parted -f -s "${ROOT_DISK}" resizepart "${ROOT_PART}" 100%

    if [ -e /boot/cmdline.txt ]; then
        NEW_UUID=$(blkid -s PARTUUID -o value "${ROOT_DEV}")
        if [ -n "$NEW_UUID" ]; then
            sed -i "s/PARTUUID=[^ ]*/PARTUUID=${NEW_UUID}/" /boot/cmdline.txt
        fi
    fi

    touch /etc/.disk_part_done
    sync
    reboot
    exit 0
fi

# Adım 2: Dosya Sistemi Genişletme (Loopback Trick)
if [ ! -f /etc/.disk_fs_done ]; then
    logger -t disk_expander "Adım 2: Dosya sistemi (RootFS) sınırları genişletiliyor..."

    LOOP_DEV="$(awk -e '$5=="/overlay"{print $9}' /proc/self/mountinfo 2>/dev/null)"
    if [ -z "${LOOP_DEV}" ]; then
        LOOP_DEV="$(losetup -f 2>/dev/null)"
        losetup "${LOOP_DEV}" "${ROOT_DEV}" 2>/dev/null || true
    fi
    
    if [ -n "${LOOP_DEV}" ]; then
        resize2fs -f "${LOOP_DEV}"
    else
        # Loopback oluşturulamazsa fallback
        resize2fs -f "${ROOT_DEV}" || true
    fi

    touch /etc/.disk_fs_done
    touch /etc/.disk_expanded
    logger -t disk_expander "Disk genişletme başarıyla tamamlandı!"
    sync
    reboot
    exit 0
fi

exit 0
EOF_EXPAND

chmod +x /etc/auto_expand.sh

echo "[3/4] /etc/rc.local açılış tetikleyicisi ayarlanıyor..."
if ! grep -q "auto_expand.sh" /etc/rc.local 2>/dev/null; then
    sed -i '/^exit 0/i \/etc\/auto_expand.sh &' /etc/rc.local
fi

echo "[4/4] Sysupgrade (Güncelleme) korumasına ekleniyor..."
if ! grep -q "/etc/auto_expand.sh" /etc/sysupgrade.conf 2>/dev/null; then
    echo "/etc/auto_expand.sh" >> /etc/sysupgrade.conf
fi

echo ""
echo "================================================================"
echo "  KURULUM TAMAMLANDI!"
echo "  Sistem şimdi diskinizi genişletmek için otonom süreci başlatıyor."
echo "================================================================"

/etc/auto_expand.sh &
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
echo "  Genişletme Durumu (Gerçek Donanım):"
ROOT_DEV=""
BOOT_DEV=$(df /boot 2>/dev/null | awk 'NR==2 {print $1}')
if [ -n "$BOOT_DEV" ]; then
    ROOT_DISK=$(echo "$BOOT_DEV" | sed -E 's/p?1$//')
    if [ -b "${ROOT_DISK}p2" ]; then ROOT_DEV="${ROOT_DISK}p2"
    elif [ -b "${ROOT_DISK}2" ]; then ROOT_DEV="${ROOT_DISK}2"
    fi
fi

if [ -n "$ROOT_DEV" ]; then
    PART_SIZE=$(cat "/sys/class/block/$(basename "$ROOT_DEV")/size" 2>/dev/null || echo 0)
    PART_GB=$((PART_SIZE * 512 / 1000000000))
    if [ "$PART_GB" -gt 2 ]; then
        echo "    Bölüm (Donanım): GENİŞLETİLDİ (~${PART_GB} GB)"
    else
        echo "    Bölüm (Donanım): GENİŞLETİLMEDİ (~${PART_GB} GB)"
    fi
    
    FS_KB=$(df -k / | awk 'NR==2 {print $2}' 2>/dev/null || echo 0)
    FS_GB=$((FS_KB / 1000000))
    if [ "$FS_GB" -gt 2 ]; then
        echo "    Dosya sistemi:   GENİŞLETİLDİ (~${FS_GB} GB)"
    else
        echo "    Dosya sistemi:   GENİŞLETİLMEDİ (~${FS_GB} GB)"
    fi
else
    echo "    Durum: Bilinmiyor"
fi

echo ""
echo "================================================================"
"""