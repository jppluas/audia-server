#!/bin/bash
# FonoScreen — backup_config.sh
# Hace backup de todos los archivos de configuración del sistema.
# Guarda el resultado en ~/fonoscreen-server/backups/
# Correr desde el Pi: bash ~/fonoscreen-server/backup_config.sh

DATE=$(date +%Y%m%d_%H%M%S)
PROJECT="/home/pi/fonoscreen-server"
BACKUP_DIR="$PROJECT/backups/backup-$DATE"

mkdir -p "$BACKUP_DIR"

echo "==> Copiando archivos del sistema..."

# Scripts de switch
cp /usr/local/bin/modo-hotspot "$BACKUP_DIR/" 2>/dev/null && echo "OK: modo-hotspot" || echo "FALTA: modo-hotspot"
cp /usr/local/bin/modo-dev "$BACKUP_DIR/" 2>/dev/null && echo "OK: modo-dev" || echo "FALTA: modo-dev"

# Servicios systemd
cp /etc/systemd/system/fonoscreen.service "$BACKUP_DIR/" 2>/dev/null && echo "OK: fonoscreen.service" || echo "FALTA: fonoscreen.service"
cp /etc/systemd/system/fonoscreen-hotspot.service "$BACKUP_DIR/" 2>/dev/null && echo "OK: fonoscreen-hotspot.service" || echo "FALTA: fonoscreen-hotspot.service"

# Configuración de red
cp /etc/hostapd/hostapd.conf "$BACKUP_DIR/" 2>/dev/null && echo "OK: hostapd.conf" || echo "FALTA: hostapd.conf"
cp /etc/dnsmasq.conf "$BACKUP_DIR/" 2>/dev/null && echo "OK: dnsmasq.conf" || echo "FALTA: dnsmasq.conf"
cp /etc/NetworkManager/conf.d/unmanaged.conf "$BACKUP_DIR/" 2>/dev/null && echo "OK: unmanaged.conf" || echo "INFO: unmanaged.conf no existe (normal en modo dev)"
cp /etc/sudoers.d/fonoscreen "$BACKUP_DIR/" 2>/dev/null && echo "OK: sudoers" || echo "FALTA: sudoers"
cp /home/pi/.bashrc "$BACKUP_DIR/" 2>/dev/null && echo "OK: .bashrc" || echo "FALTA: .bashrc"

# Estado del sistema
{
    echo "=== Estado del sistema: $(date) ==="
    echo ""
    echo "--- Modelo del Pi ---"
    cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo "No disponible"
    echo ""
    echo "--- IPs ---"
    ip addr show wlan0
    echo ""
    echo "--- Routing ---"
    ip route show
    echo ""
    echo "--- Servicios ---"
    for s in fonoscreen fonoscreen-hotspot hostapd dnsmasq ssh NetworkManager; do
        echo "$s: $(systemctl is-active $s)"
    done
} > "$BACKUP_DIR/system_state.txt"
echo "OK: system_state.txt"

echo ""
echo "========================================"
echo " Backup guardado en:"
echo " $BACKUP_DIR"
echo ""
echo " Para copiar a tu laptop:"
echo " scp -r pi@<IP-del-pi>:$BACKUP_DIR ~/fonoscreen-server/backups/"
echo "========================================"
