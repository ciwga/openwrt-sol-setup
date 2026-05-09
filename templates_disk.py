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

echo "[1/4] Gerekli disk araçları kuruluyor... ($PKG_MANAGER)"
pkg_update >/dev/null 2>&1 || true
for pkg in parted losetup resize2fs blkid; do
    pkg_install "$pkg" >/dev/null 2>&1 && echo "    $pkg OK" || echo "    $pkg atlandı"
done

echo "[2/4] Kalıcı oto-genişletme betiği oluşturuluyor..."

cat << 'EOF_EXPAND' > /etc/auto_expand.sh
#!/bin/sh

[ -f /etc/.disk_expanded ] && exit 0

if ! command -v parted >/dev/null || ! command -v resize2fs >/dev/null; then
    logger -t disk_expander "Uyarı: parted veya resize2fs bulunamadı, genişletme iptal edildi."
    exit 0
fi

# Disk aygıtlarını dinamik ve evrensel olarak belirle (SD, USB, NVMe)
ROOT_BLK_SYS="$(readlink -f /sys/dev/block/"$(awk -e '$9=="/dev/root"{print $3}' /proc/self/mountinfo)")"
ROOT_DEV="/dev/$(basename "$ROOT_BLK_SYS")"
ROOT_DISK="/dev/$(basename "$(dirname "$ROOT_BLK_SYS")")"
ROOT_PART="${ROOT_DEV##*[^0-9]}"

if [ ! -f /etc/.disk_part_done ]; then
    logger -t disk_expander "Adım 1: Disk bölümü %100 kapasiteye genişletiliyor..."
    parted -f -s "${ROOT_DISK}" resizepart "${ROOT_PART}" 100%

    if [ -e /boot/cmdline.txt ]; then
        # UUID hesabını ROOT_DEV üzerinden al
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

if [ ! -f /etc/.disk_fs_done ]; then
    logger -t disk_expander "Adım 2: Dosya sistemi (RootFS) sınırları genişletiliyor..."

    # Kernel Panic koruması
    if df -T / | grep -q -i ext4; then
        resize2fs -f "${ROOT_DEV}"
    else
        # Sadece SquashFS varsa loop device devreye sokulur
        LOOP_DEV="$(awk -e '$5=="/overlay"{print $9}' /proc/self/mountinfo)"
        if [ -z "${LOOP_DEV}" ] && command -v losetup >/dev/null; then
            LOOP_DEV="$(losetup -f)"
            losetup "${LOOP_DEV}" "${ROOT_DEV}"
        fi
        if [ -n "${LOOP_DEV}" ]; then
            resize2fs -f "${LOOP_DEV}"
        fi
    fi

    touch /etc/.disk_fs_done
    touch /etc/.disk_expanded
    logger -t disk_expander "Disk genişletme başarıyla tamamlandı!"
    sync
    reboot
    exit 0
fi
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
echo ""
echo "  ÖNEMLİ BİLGİ: Bundan sonra 'Attended Sysupgrade' ile"
echo "  güncelleme yaptığınızda, cihaz açılışta boyutun küçüldüğünü"
echo "  kendi kendine fark edecek ve OTONOM olarak arka planda genişletecektir."
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
echo "  Genişletme Durumu:"
[ -e /etc/.disk_part_done ] && echo "    Bölüm:       GENİŞLETİLDİ" || echo "    Bölüm:       GENİŞLETİLMEDİ"
[ -e /etc/.disk_fs_done ] && echo "    Dosya sistemi: GENİŞLETİLDİ" || echo "    Dosya sistemi: GENİŞLETİLMEDİ"

echo ""
echo "================================================================"
"""