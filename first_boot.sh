#!/bin/bash
# Audia — first_boot.sh
# Se ejecuta UNA SOLA VEZ en el primer arranque del Pi.
# Compatible con Pi 3 B+, Pi 4 y Pi 5.

set -e
LOG="/home/pi/first_boot.log"
exec > >(tee -a "$LOG") 2>&1

echo "========================================"
echo " Audia first boot: $(date)"
echo "========================================"

PROJECT="/home/pi/audia-server"
CONFIG="$PROJECT/config"

# ── Detectar modelo ───────────────────────────────────────────────────────────
PI_MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo "Unknown")
echo "==> Modelo: $PI_MODEL"

# ── Leer SSID del network-config del Imager ───────────────────────────────────
WIFI_SSID=""
NETWORK_CONFIG="/boot/firmware/network-config"
[ -f "/boot/network-config" ] && NETWORK_CONFIG="/boot/network-config"

if [ -f "$NETWORK_CONFIG" ]; then
    WIFI_SSID=$(grep -A1 "access-points:" "$NETWORK_CONFIG" | tail -1 | tr -d ' "' | tr -d ':')
    echo "==> Red WiFi detectada del Imager: $WIFI_SSID"
else
    echo "==> No se encontró network-config, SSID quedará como placeholder"
fi

# ── 1. Dependencias del sistema ───────────────────────────────────────────────
echo "==> [1/8] Instalando dependencias del sistema..."
apt-get update -qq
apt-get install -y \
    python3-venv python3-pip \
    sox alsa-utils \
    hostapd dnsmasq \
    espeak-ng \
    libportaudio2 \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev
echo "OK: dependencias del sistema"

# ── 2. PipeWire para audio ────────────────────────────────────────────────────
echo "==> [2/8] Instalando PipeWire..."
apt-get install -y pipewire pipewire-pulse pipewire-alsa wireplumber libspa-0.2-bluetooth

# Habilitar linger para que los servicios de usuario de pi arranquen sin sesión
loginctl enable-linger pi

# Habilitar servicios de usuario via systemctl --user corriendo como pi
# (requiere linger habilitado primero)
sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 \
    systemctl --user enable pipewire pipewire-pulse wireplumber 2>/dev/null || true
echo "OK: PipeWire instalado y habilitado"

# ── 3. Fix Bluetooth ──────────────────────────────────────────────────────────
echo "==> [3/8] Configurando Bluetooth..."

# Evitar soft block en cada arranque
echo 'SUBSYSTEM=="rfkill", ATTR{type}=="bluetooth", ATTR{state}="1"' \
    > /etc/udev/rules.d/50-bluetooth.rules
echo "OK: regla udev Bluetooth"

# Variables de entorno para que audia.service acceda a PipeWire de usuario
mkdir -p /etc/systemd/system/audia.service.d
cat > /etc/systemd/system/audia.service.d/pipewire.conf << 'EOF'
[Service]
Environment="PIPEWIRE_RUNTIME_DIR=/run/user/1000"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Environment="TRANSFORMERS_OFFLINE=1"
Environment="HF_DATASETS_OFFLINE=1"
EOF
echo "OK: variables PipeWire y offline en audia.service"

# ── 4. Venv y dependencias Python ─────────────────────────────────────────────
echo "==> [4/8] Creando venv..."
cd "$PROJECT"
rm -rf venv
python3 -m venv venv

venv/bin/pip install --quiet \
    Flask weasyprint sounddevice soundfile requests phonemizer

# torch es grande (~500MB) — usar directorio temporal en disco, no en RAM
echo "==> Instalando torch (puede tardar 10-20 minutos)..."
mkdir -p /home/pi/.pip-tmp
TMPDIR=/home/pi/.pip-tmp venv/bin/pip install \
    --cache-dir /home/pi/.pip-cache \
    torch torchaudio transformers 2>&1 | tail -5
rm -rf /home/pi/.pip-tmp /home/pi/.pip-cache

mkdir -p logs exports recordings
touch logs/server.log
chown -R pi:pi "$PROJECT"
echo "OK: venv y dependencias Python"

# ── 5. Archivos de configuración del sistema ──────────────────────────────────
echo "==> [5/8] Instalando archivos de configuración..."

cp "$CONFIG/hostapd.conf" /etc/hostapd/hostapd.conf
echo "OK: hostapd.conf"

mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cp "$CONFIG/dnsmasq.conf" /etc/dnsmasq.conf
echo "OK: dnsmasq.conf"

cp "$CONFIG/modo-hotspot" /usr/local/bin/modo-hotspot
chmod +x /usr/local/bin/modo-hotspot
echo "OK: modo-hotspot"

cp "$CONFIG/modo-dev" /usr/local/bin/modo-dev
if [ -n "$WIFI_SSID" ]; then
    sed -i "s/SSID_AQUI/$WIFI_SSID/g" /usr/local/bin/modo-dev
    echo "OK: modo-dev (SSID=$WIFI_SSID)"
else
    echo "OK: modo-dev (SSID no detectado — editar /usr/local/bin/modo-dev manualmente)"
fi
chmod +x /usr/local/bin/modo-dev

# ── 6. Aliases y sudoers ──────────────────────────────────────────────────────
echo "==> [6/8] Configurando aliases y sudoers..."

if ! grep -q "Audia aliases" /home/pi/.bashrc; then
    cat >> /home/pi/.bashrc << 'EOF'

# Audia aliases
alias hotspot='sudo /usr/local/bin/modo-hotspot'
alias devmode='sudo /usr/local/bin/modo-dev'
EOF
fi
echo "OK: aliases en .bashrc"

echo "pi ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/audia
echo "OK: sudoers"

# ── 7. Servicios systemd ──────────────────────────────────────────────────────
echo "==> [7/9] Habilitando servicios systemd..."

cp "$CONFIG/audia.service" /etc/systemd/system/audia.service
cp "$CONFIG/audia-hotspot.service" /etc/systemd/system/audia-hotspot.service
systemctl daemon-reload
systemctl enable audia
systemctl enable audia-hotspot
echo "OK: servicios systemd"

# ── 8. Descargar modelos IA (requiere internet — antes de activar hotspot) ────
echo "==> [8/8] Descargando modelos de IA..."

# Verificar si ya están en caché
SILERO_CACHE="/home/pi/.cache/torch/hub/snakers4_silero-vad_master"
XLSR_CACHE="/home/pi/.cache/huggingface/hub/models--facebook--wav2vec2-large-xlsr-53-spanish"

if [ -d "$SILERO_CACHE" ]; then
    echo "OK: Silero VAD ya está en caché"
else
    echo "==> Descargando Silero VAD..."
    sudo -u pi "$PROJECT/venv/bin/python3" -c \
        "import torch; torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)"
    echo "OK: Silero VAD descargado"
fi

if [ -d "$XLSR_CACHE" ]; then
    echo "OK: wav2vec2 XLS-R ya está en caché"
else
    echo "==> Descargando wav2vec2 XLS-R (~1.2GB, puede tardar 10-20 minutos)..."
    sudo -u pi "$PROJECT/venv/bin/python3" -c "
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
Wav2Vec2Processor.from_pretrained('facebook/wav2vec2-large-xlsr-53-spanish')
Wav2Vec2ForCTC.from_pretrained('facebook/wav2vec2-large-xlsr-53-spanish')
print('XLS-R descargado correctamente')
"
    echo "OK: wav2vec2 XLS-R descargado"
fi

# ── 9. Activar hotspot, deshabilitar este servicio y reiniciar ────────────────
echo "==> [9/9] Activando hotspot..."
systemctl disable first-boot.service 2>/dev/null || true
rm -f /etc/systemd/system/first-boot.service

/usr/local/bin/modo-hotspot

# ── Verificación final ────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo " Verificación del sistema"
echo "========================================"

ERRORES=0

# Binarios del sistema
for bin in python3 sox espeak hostapd dnsmasq pw-play pw-record wpctl bluetoothctl; do
    if command -v $bin &>/dev/null; then
        echo "  ✓ $bin"
    else
        echo "  ✗ $bin — NO encontrado"
        ERRORES=$((ERRORES + 1))
    fi
done

# Venv y paquetes Python
echo ""
if [ -f "$PROJECT/venv/bin/python" ]; then
    echo "  ✓ venv existe"
    for pkg in flask weasyprint sounddevice soundfile phonemizer torch transformers; do
        if $PROJECT/venv/bin/python -c "import $pkg" 2>/dev/null; then
            echo "  ✓ Python: $pkg"
        else
            echo "  ✗ Python: $pkg — NO instalado"
            ERRORES=$((ERRORES + 1))
        fi
    done
else
    echo "  ✗ venv — NO existe"
    ERRORES=$((ERRORES + 1))
fi

# Archivos de configuración del sistema
echo ""
for f in /etc/hostapd/hostapd.conf /etc/dnsmasq.conf \
          /usr/local/bin/modo-hotspot /usr/local/bin/modo-dev \
          /etc/systemd/system/audia.service \
          /etc/systemd/system/audia-hotspot.service \
          /etc/systemd/system/audia.service.d/pipewire.conf \
          /etc/udev/rules.d/50-bluetooth.rules; do
    if [ -f "$f" ]; then
        echo "  ✓ $f"
    else
        echo "  ✗ $f — NO existe"
        ERRORES=$((ERRORES + 1))
    fi
done

# Archivos del proyecto
echo ""
for f in app.py db.py pipeline.py motor_ia.py report_html.py requirements.txt; do
    if [ -f "$PROJECT/$f" ]; then
        echo "  ✓ $PROJECT/$f"
    else
        echo "  ✗ $PROJECT/$f — NO existe"
        ERRORES=$((ERRORES + 1))
    fi
done

# Carpetas necesarias
echo ""
for d in audios templates static config recordings logs exports; do
    if [ -d "$PROJECT/$d" ]; then
        echo "  ✓ $PROJECT/$d/"
    else
        echo "  ✗ $PROJECT/$d/ — NO existe"
        ERRORES=$((ERRORES + 1))
    fi
done

# Caché de modelos IA
echo ""
if [ -d "/home/pi/.cache/torch/hub/snakers4_silero-vad_master" ]; then
    echo "  ✓ Caché: Silero VAD"
else
    echo "  ✗ Caché: Silero VAD — NO encontrado"
    ERRORES=$((ERRORES + 1))
fi
if [ -d "/home/pi/.cache/huggingface/hub/models--facebook--wav2vec2-large-xlsr-53-spanish" ]; then
    echo "  ✓ Caché: wav2vec2 XLS-R"
else
    echo "  ✗ Caché: wav2vec2 XLS-R — NO encontrado"
    ERRORES=$((ERRORES + 1))
fi

# Servicios habilitados
echo ""
for svc in audia audia-hotspot bluetooth; do
    if systemctl is-enabled $svc &>/dev/null; then
        echo "  ✓ systemd: $svc habilitado"
    else
        echo "  ✗ systemd: $svc — NO habilitado"
        ERRORES=$((ERRORES + 1))
    fi
done

# Resultado
echo ""
if [ $ERRORES -eq 0 ]; then
    echo "  ✅ Todo correcto — $ERRORES errores"
else
    echo "  ⚠️  Se encontraron $ERRORES problema(s) — revisar el log antes de usar"
fi

echo "========================================"
echo " first_boot.sh completado: $(date)"
echo " Reiniciando en 10 segundos..."
echo "========================================"
sleep 10
reboot
