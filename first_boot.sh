#!/bin/bash
# FonoScreen — first_boot.sh
# Se ejecuta UNA SOLA VEZ en el primer arranque del Pi.
# Lee los archivos de configuración desde /home/pi/fonoscreen-server/config/
# NO sobreescribe archivos que ya existen en el proyecto.
# Compatible con Pi 3 B+, Pi 4 y Pi 5.

set -e
LOG="/home/pi/first_boot.log"
exec > >(tee -a "$LOG") 2>&1

echo "========================================"
echo " FonoScreen first boot: $(date)"
echo "========================================"

PROJECT="/home/pi/fonoscreen-server"
CONFIG="$PROJECT/config"

# ── Detectar modelo ───────────────────────────────────────────────────────────
PI_MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo "Unknown")
echo "==> Modelo: $PI_MODEL"

# ── Leer SSID del network-config del Imager ───────────────────────────────────
WIFI_SSID=""
NETWORK_CONFIG="/boot/firmware/network-config"
[ -f "/boot/network-config" ] && NETWORK_CONFIG="/boot/network-config"

if [ -f "$NETWORK_CONFIG" ]; then
    # Extrae el SSID (la línea con comillas después de "access-points:")
    WIFI_SSID=$(grep -A1 "access-points:" "$NETWORK_CONFIG" | tail -1 | tr -d ' "' | tr -d ':')
    echo "==> Red WiFi detectada del Imager: $WIFI_SSID"
else
    echo "==> No se encontró network-config, SSID quedará como placeholder"
fi

# ── 1. Instalar dependencias ──────────────────────────────────────────────────
echo "==> Instalando dependencias..."
apt-get update -qq
apt-get install -y python3-venv python3-pip sox alsa-utils hostapd dnsmasq

# ── 2. Crear venv ─────────────────────────────────────────────────────────────
echo "==> Creando venv..."
cd "$PROJECT"
rm -rf venv
python3 -m venv venv
venv/bin/pip install --quiet -r requirements.txt
mkdir -p logs exports
touch logs/server.log
chown -R pi:pi "$PROJECT"

# ── 3. Instalar archivos de configuración desde config/ ───────────────────────
echo "==> Instalando archivos de configuración..."

# hostapd
if [ -f "$CONFIG/hostapd.conf" ]; then
    cp "$CONFIG/hostapd.conf" /etc/hostapd/hostapd.conf
    echo "OK: hostapd.conf"
else
    echo "ERROR: no se encontró $CONFIG/hostapd.conf"
    exit 1
fi

# dnsmasq
if [ -f "$CONFIG/dnsmasq.conf" ]; then
    mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
    cp "$CONFIG/dnsmasq.conf" /etc/dnsmasq.conf
    echo "OK: dnsmasq.conf"
else
    echo "ERROR: no se encontró $CONFIG/dnsmasq.conf"
    exit 1
fi

# Scripts de switch
if [ -f "$CONFIG/modo-hotspot" ]; then
    cp "$CONFIG/modo-hotspot" /usr/local/bin/modo-hotspot
    chmod +x /usr/local/bin/modo-hotspot
    echo "OK: modo-hotspot"
else
    echo "ERROR: no se encontró $CONFIG/modo-hotspot"
    exit 1
fi

if [ -f "$CONFIG/modo-dev" ]; then
    cp "$CONFIG/modo-dev" /usr/local/bin/modo-dev
    # Reemplazar SSID automáticamente si se detectó del Imager
    if [ -n "$WIFI_SSID" ]; then
        sed -i "s/SSID_AQUI/$WIFI_SSID/g" /usr/local/bin/modo-dev
        echo "OK: modo-dev (SSID=$WIFI_SSID)"
    else
        echo "OK: modo-dev (SSID no detectado, editar manualmente)"
    fi
    chmod +x /usr/local/bin/modo-dev
else
    echo "ERROR: no se encontró $CONFIG/modo-dev"
    exit 1
fi

# ── 4. Aliases ────────────────────────────────────────────────────────────────
if ! grep -q "FonoScreen aliases" /home/pi/.bashrc; then
    cat >> /home/pi/.bashrc << 'EOF'

# FonoScreen aliases
alias hotspot='sudo /usr/local/bin/modo-hotspot'
alias devmode='sudo /usr/local/bin/modo-dev'
EOF
    echo "OK: aliases"
fi

# ── 5. Sudoers ────────────────────────────────────────────────────────────────
echo "pi ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/fonoscreen
echo "OK: sudoers"

# ── 6. Servicios systemd ──────────────────────────────────────────────────────
cp "$CONFIG/fonoscreen.service" /etc/systemd/system/fonoscreen.service
cp "$CONFIG/fonoscreen-hotspot.service" /etc/systemd/system/fonoscreen-hotspot.service
systemctl daemon-reload
systemctl enable fonoscreen
systemctl enable fonoscreen-hotspot
echo "OK: servicios systemd"

# ── 7. Deshabilitar este servicio ─────────────────────────────────────────────
systemctl disable first-boot.service 2>/dev/null || true
rm -f /etc/systemd/system/first-boot.service

# ── 8. Activar hotspot y reiniciar ────────────────────────────────────────────
echo "==> Activando hotspot..."
/usr/local/bin/modo-hotspot

echo "========================================"
echo " first_boot.sh completado: $(date)"
echo " Reiniciando en 5 segundos..."
echo "========================================"
sleep 5
reboot
