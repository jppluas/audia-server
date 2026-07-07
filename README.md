# Audia — Kiosk Server

Sistema de cribado fonológico automatizado para niños de 3 a 5 años.
ESPOL · Ingeniería en Ciencias de la Computación · Materia Integradora

---

## Estructura del proyecto

```
audia-server/
├── app.py                  # Servidor Flask — infraestructura completa
├── db.py                   # Capa de persistencia SQLite
├── pipeline.py             # Flujo de evaluación: grabación, IA, guardado
├── motor_ia.py             # Silero VAD + wav2vec2 XLS-R + Phonemizer + NW
├── report_html.py          # Fuente única del HTML del informe (PDF y pantalla)
├── requirements.txt        # Dependencias Python
├── first_boot.sh           # Script de primer arranque del Pi
├── first-boot.service      # Servicio systemd que lanza first_boot.sh
├── backup_config.sh        # Script para hacer backup de la configuración
├── config/                 # Archivos de configuración del sistema (fuente única)
│   ├── hostapd.conf
│   ├── dnsmasq.conf
│   ├── modo-hotspot        # Script de switch a modo hotspot
│   ├── modo-dev            # Script de switch a modo desarrollo
│   ├── audia.service
│   └── audia-hotspot.service
├── templates/
│   ├── base.html           # Layout compartido (header, footer)
│   ├── register.html       # Registro del niño + anamnesis (sin nombre)
│   ├── session.html        # Pantalla en curso — polling al estado global
│   ├── results.html        # Resultado global + fonemas + ir al historial
│   ├── device.html         # Panel de dispositivo (volumen, mic, apagado)
│   └── historial.html      # Historial de sesiones + gestión de audios
├── static/
│   ├── css/base.css        # Estilos mobile-first
│   └── js/utils.js         # Utilidades JS: toast, confirm, api()
├── audios/                 # Estímulos WAV de la batería (git-ignored)
│   └── mama.wav, taza.wav, gato.wav ... (20 archivos, nombre sin tildes)
├── recordings/             # Respuestas grabadas por sesión (git-ignored)
│   └── <session_id>/
│       └── <session_id>_<palabra>.wav
├── backups/                # Backups del sistema (git-ignored)
├── exports/                # Reservado (git-ignored)
├── audia.db                # Base de datos SQLite (git-ignored)
└── logs/
    └── server.log
```

---

## Desarrollo en laptop (Debian 12)

### Dependencias de sistema (solo una vez)

```bash
# weasyprint
sudo apt install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev

# pipeline de IA
sudo apt install -y espeak-ng sox libportaudio2

# audio real en laptop (para prueba de micrófono y pipeline)
sudo apt install -y pulseaudio alsa-utils
sudo usermod -aG audio $USER
pulseaudio --start
```

### Arrancar el servidor

```bash
cd ~/audia-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 python app.py
# Abrir http://localhost:5000
```

Desde el celular (misma red): `http://<IP-de-la-laptop>:5000`

En laptop, `IS_PI = False`. El servidor usa `wpctl`/`pw-play`/`pw-record` para
audio igual que en el Pi (vía PipeWire/PulseAudio). El micrófono y el tono
funcionan realmente — no se simulan.

El endpoint `/dev/simulate` está activo para simular el pipeline manualmente
sin necesidad de que el pipeline de IA esté corriendo.

> **Importante:** el venv tiene rutas absolutas. Si mueves o renombras la
> carpeta, bórralo y créalo de nuevo:
> ```bash
> rm -rf venv && python3 -m venv venv
> source venv/bin/activate && pip install -r requirements.txt
> ```

> **Importante:** verificar que solo hay un proceso corriendo:
> ```bash
> pkill -f "python app.py" && sleep 1 && python app.py
> ```

> **Importante:** probar en ventana incógnito (`Ctrl+Shift+N`) para evitar
> interferencia de extensiones del navegador.

---

## Configurar una Raspberry Pi nueva (primer uso)

Este es el proceso completo desde cero para cualquier Pi (3 B+, 4 o 5).

### Paso 1: Flashear la microSD con Raspberry Pi Imager

En Raspberry Pi Imager configurar:
- **OS:** Raspberry Pi OS Lite (64-bit)
- **Hostname:** `audia`
- **SSH:** activado, autenticación por contraseña
- **Usuario:** `pi`, contraseña la que prefieras
- **Wi-Fi:** nombre y contraseña de la red donde se va a hacer el primer arranque
- **Zona horaria:** `America/Guayaquil`
- **Teclado:** `es`

> La red Wi-Fi configurada aquí es la que el Pi usará para conectarse a internet
> en el primer arranque y descargar dependencias. El `first_boot.sh` la leerá
> automáticamente para configurar el modo desarrollo.

### Paso 2: Copiar el proyecto a la microSD

Con la SD montada en la laptop (usar `rsync` para excluir venv y cachés):

```bash
sudo mkdir -p /media/$USER/rootfs/home/pi

sudo rsync -av \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.db' \
    --exclude='.git/' \
    --exclude='recordings/' \
    --exclude='exports/' \
    --exclude='logs/' \
    ~/audia-server/ \
    /media/$USER/rootfs/home/pi/audia-server/

sudo chown -R 1000:1000 /media/$USER/rootfs/home/pi/audia-server

# Copiar el servicio de primer arranque
sudo cp /media/$USER/rootfs/home/pi/audia-server/first-boot.service \
    /media/$USER/rootfs/etc/systemd/system/

# Habilitar el servicio (crear symlink)
sudo ln -sf /etc/systemd/system/first-boot.service \
    /media/$USER/rootfs/etc/systemd/system/multi-user.target.wants/first-boot.service
```

### Paso 3: Desmontar y arrancar el Pi

```bash
sudo umount /media/$USER/bootfs
sudo umount /media/$USER/rootfs
```

Insertar la SD en el Pi y encender. El `first_boot.sh` corre automáticamente en
9 pasos:

1. Instala dependencias del sistema (`sox`, `espeak-ng`, `libportaudio2`, `hostapd`, `dnsmasq`, librerías de weasyprint)
2. Instala PipeWire y `pipewire-alsa` — habilita servicios de usuario con linger
3. Configura Bluetooth (regla udev, variables de entorno para Flask)
4. Crea el venv ARM e instala dependencias Python (Flask, weasyprint, sounddevice, torch, transformers, phonemizer)
5. Copia archivos de `config/` a sus rutas del sistema
6. Configura sudoers y aliases
7. Habilita los servicios systemd (`audia`, `audia-hotspot`)
8. Descarga modelos de IA (Silero VAD y wav2vec2 XLS-R) — requiere internet, verifica caché antes de descargar
9. Activa el hotspot y reinicia

> **Importante:** el paso 8 requiere internet. El Pi debe tener conectividad
> configurada desde el Imager. Los modelos (~1.5GB en total) se descargan una
> sola vez y quedan en caché local para todos los arranques posteriores.

El proceso tarda 20-40 minutos dependiendo de la velocidad de internet. El Pi
se reinicia solo al terminar. El log completo queda en `/home/pi/first_boot.log`.

### Paso 4: Verificar

Después del reinicio, buscar la red `Audia` en el celular, conectarse con
la contraseña `audia2025` y abrir `http://192.168.4.1:5000`.

Para ver el log del primer arranque:
```bash
# Conectarse en modo dev primero (ver sección abajo), luego:
cat ~/audia-server/first_boot.log
```

---

## Setup manual del Pi (alternativa si first_boot.sh falla)

```bash
# 1. Dependencias del sistema
sudo apt install -y sox alsa-utils hostapd dnsmasq espeak-ng \
    libportaudio2 \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev

# 2. PipeWire para audio
sudo apt install -y pipewire pipewire-pulse pipewire-alsa wireplumber libspa-0.2-bluetooth
loginctl enable-linger pi
sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 \
    systemctl --user enable pipewire pipewire-pulse wireplumber

# 3. Fix Bluetooth soft block
sudo rfkill unblock bluetooth
echo 'SUBSYSTEM=="rfkill", ATTR{type}=="bluetooth", ATTR{state}="1"' \
    | sudo tee /etc/udev/rules.d/50-bluetooth.rules

# 4. Variables de entorno para Flask
sudo mkdir -p /etc/systemd/system/audia.service.d
sudo tee /etc/systemd/system/audia.service.d/pipewire.conf << 'EOF'
[Service]
Environment="PIPEWIRE_RUNTIME_DIR=/run/user/1000"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Environment="TRANSFORMERS_OFFLINE=1"
Environment="HF_DATASETS_OFFLINE=1"
EOF

# 5. Clonar el proyecto y crear venv
git clone <repo> ~/audia-server
cd ~/audia-server
python3 -m venv venv

# Paquetes pequeños primero
venv/bin/pip install Flask weasyprint sounddevice soundfile requests phonemizer

# torch separado con directorio temporal en disco (evita llenar /tmp en RAM)
mkdir -p ~/.pip-tmp
TMPDIR=~/.pip-tmp venv/bin/pip install --cache-dir ~/.pip-cache \
    torch torchaudio transformers
rm -rf ~/.pip-tmp ~/.pip-cache

# 6. Descargar modelos (con internet activo, antes de activar hotspot)
venv/bin/python3 -c "import torch; torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)"
venv/bin/python3 -c "
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
Wav2Vec2Processor.from_pretrained('facebook/wav2vec2-large-xlsr-53-spanish')
Wav2Vec2ForCTC.from_pretrained('facebook/wav2vec2-large-xlsr-53-spanish')
"

# 7. Copiar archivos de configuración
sudo cp config/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp config/dnsmasq.conf /etc/dnsmasq.conf
sudo cp config/modo-hotspot /usr/local/bin/modo-hotspot
sudo cp config/modo-dev /usr/local/bin/modo-dev
sudo chmod +x /usr/local/bin/modo-hotspot /usr/local/bin/modo-dev
sudo cp config/audia.service /etc/systemd/system/
sudo cp config/audia-hotspot.service /etc/systemd/system/

# 8. Habilitar servicios y activar hotspot
sudo systemctl daemon-reload
sudo systemctl enable audia audia-hotspot
sudo /usr/local/bin/modo-hotspot
```

Ver los logs del servicio:
```bash
journalctl -u audia -f
# o directamente:
tail -f ~/audia-server/logs/server.log
```

---

## Audio en el Pi

Audia usa PipeWire para gestionar el audio. Los controles usan `wpctl` y
`pw-play`/`pw-record`, que funcionan tanto en el Pi como en laptop con
PipeWire/PulseAudio.

El hardware de audio definitivo será un módulo USB-C con parlante y micrófono
dedicados. Durante las pruebas se usan auriculares Bluetooth Sony WH-1000XM4.

### Conectar auriculares Bluetooth (para pruebas)

```bash
# PipeWire debe estar corriendo antes de conectar
systemctl --user start pipewire pipewire-pulse wireplumber
sleep 5

# Emparejar (solo la primera vez)
bluetoothctl
  power on
  agent on
  default-agent
  scan on
  # Esperar que aparezca el MAC del dispositivo
  pair XX:XX:XX:XX:XX:XX
  trust XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  exit

# Verificar que PipeWire los detectó
wpctl status
```

### Comportamiento de audio con Bluetooth

Los auriculares operan en dos perfiles:
- **A2DP** — alta calidad, solo reproducción. Activo cuando se reproducen estímulos.
- **HFP** — baja calidad, entrada + salida. Se activa automáticamente al grabar.

El switch entre perfiles toma 2-3 segundos. El evaluador debe esperar ese tiempo
antes de pedirle al niño que hable.

### Si los auriculares no conectan después de reiniciar

```bash
sudo rfkill unblock bluetooth
systemctl --user start pipewire.socket pipewire-pulse.socket wireplumber
sleep 5
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

Si falla con `br-connection-profile-unavailable`, reiniciar bluetooth después
de que PipeWire esté corriendo:

```bash
sudo systemctl restart bluetooth
sleep 3
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

### Verificar volumen y dispositivo por defecto

```bash
wpctl status              # ver sinks y sources activos
wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.8
wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.8
```

---

## Uso diario

### Modo producción (por defecto al encender)

El Pi genera la red `Audia` automáticamente. Cualquier dispositivo se
conecta con `audia2025` y abre `http://192.168.4.1:5000`.

### Activar modo desarrollo (SSH)

```bash
devmode
```

La conexión WiFi puede tardar 3-5 minutos después de ejecutar `devmode` —
NetworkManager necesita negociar con el router después de liberar la interfaz.
El SSH puede aparecer como colgado durante ese tiempo; esperar sin interrumpir.

Para encontrar la IP del Pi en la red:
```bash
# Desde el Pi:
ip addr show wlan0

# Desde la laptop:
nmap -sn 192.168.100.0/24  # ajustar subred según tu router
```

Conectar por SSH:
```bash
ssh pi@<IP-del-pi>
```

Al reiniciar el Pi, vuelve automáticamente al modo hotspot.

### Volver al modo hotspot

```bash
hotspot
```

### Cambiar la red Wi-Fi del modo desarrollo

```bash
sudo nano /usr/local/bin/modo-dev
```

Y también actualizar la fuente en el proyecto:

```bash
nano ~/audia-server/config/modo-dev
```

El script usa `nmcli connection up` con el primer perfil WiFi guardado —
detecta el nombre del perfil dinámicamente sin hardcodearlo.

---

## Backup de la configuración

```bash
bash ~/audia-server/backup_config.sh
```

El backup queda en `~/audia-server/backups/backup-<fecha>/`. Para copiarlo a la laptop:
```bash
scp -r pi@<IP-del-pi>:~/audia-server/backups/ ~/audia-server/backups/
```

---

## Modificar la configuración del sistema

Los archivos en `config/` son la fuente única de verdad. Los del sistema son
copias. Siempre editar en `config/` primero y luego copiar:

```bash
# Ejemplo: actualizar modo-hotspot
sudo cp ~/audia-server/config/modo-hotspot /usr/local/bin/modo-hotspot

# Ejemplo: actualizar audia.service
sudo cp ~/audia-server/config/audia.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart audia
```

---

## Detección automática de entorno

```python
IS_PI = Path("/proc/device-tree/model").exists()
```

Este archivo solo existe en Raspberry Pi. El mismo código funciona en laptop
y en Pi sin cambios.

---

## Base de datos SQLite

La BD `audia.db` se crea automáticamente en la raíz del proyecto al
arrancar Flask por primera vez.

### Tablas

| tabla | descripción |
|---|---|
| `sessions` | Una fila por sesión: fecha de nacimiento, género, anamnesis, PFFB, nivel, estado. Sin nombre del niño (anonimizado). Solo sesiones con `status='done'` aparecen en el historial. |
| `items` | Una fila por palabra evaluada (20 por sesión): transcripción, resultado, tipo de error, alineación NW |
| `phoneme_summary` | Una fila por fonema por sesión: PFF%, nivel, error predominante |
| `reports` | Una fila por sesión: nota clínica y nota para representantes generadas automáticamente por el pipeline |

Al arrancar el servidor se purgan automáticamente las sesiones con
`status='active'` o `'cancelled'` — son basura de reinicios anteriores.

### Funciones principales (para el pipeline de Daniel)

```python
import db

# Al terminar cada ítem
db.save_item(session_id, {
    "item_index":    i,             # 0-19
    "phoneme":       "/r/",
    "word_expected": "carro",
    "word_produced": "cayo",
    "audio_path":    f"{session_id}/{session_id}_carro.wav",
    "result":        "error",       # correct | error | not_evaluable
    "error_type":    "Sustitución", # Sustitución | Omisión | Inserción | Variante dialectal
    "pff":           50.0,
    "alignment":     [...],
})

# Al terminar el análisis fonémico
db.save_phoneme_summary(session_id, {
    "phoneme":           "/r/",
    "pff":               62.5,
    "level":             "Bajo",
    "error_predominant": "Sustitución",
})

# Al terminar la generación del reporte
db.save_report(session_id, {
    "nota_clinica":        "...",
    "nota_representantes": "...",
})

# Al terminar toda la sesión
db.close_session(session_id, pffb=68.2, level="Seguimiento activo")
```

### Nomenclatura de audios

```
recordings/<session_id>/<session_id>_<palabra_normalizada>.wav
```

La normalización quita tildes y pasa a minúsculas: `mamá` → `mama`, `café` → `cafe`.

```python
audio_path = f"{session_id}/{db.audio_filename(session_id, word_expected)}"
```

### Exportación de sesión

```python
data = db.export_session(session_id)
# data = { "session": {...}, "items": [...], "phoneme_summary": [...], "report": {...} }
```

### Espacio en disco

- Peor caso por sesión: **28 MB** (44.1kHz estéreo, 8s × 20 ítems)
- Mínimo requerido: **10 sesiones disponibles** (280 MB libres)

Si hay menos espacio, el inicio de sesión devuelve error 507 y muestra banner rojo.

---

## Informe de evaluación

```python
from report_html import generate_report_html
data = db.export_session(session_id)

html = generate_report_html(data, tipo="clinico")
html = generate_report_html(data, tipo="representantes")

from weasyprint import HTML
pdf_bytes = HTML(string=html).write_pdf()
```

**Informe clínico** contiene:
1. Identificación (fecha de nacimiento, edad, género, fecha de evaluación)
2. Anamnesis
3. Resultado global (PFFB redondeado a 2 decimales, nivel, interpretación)
4. Desempeño por fonema (PFF%, nivel, error predominante)
5. Detalle por palabra (palabra esperada, producción, resultado, tipo de error)
6. Nota clínica (generada automáticamente por el pipeline según los errores detectados)

**Informe para representantes** contiene:
1. Identificación
2. Anamnesis
3. Resultado global
4. Desempeño por fonema (solo nivel, sin PFF% ni error predominante)
5. Detalle por palabra (sin tipo de error)
6. Nota con consejos prácticos por fonema en lenguaje accesible

Tiempo de generación del PDF estimado:
- Pi 4: 1-3 segundos
- Pi 5: menos de 1 segundo

---

## Integración del pipeline (para Daniel)

El pipeline modifica `_session_state` en `app.py` directamente desde su hilo.
**Daniel no hace peticiones HTTP. Solo modifica `_session_state` directamente
desde el hilo del pipeline.**
La UI hace polling cada 1.5s y reacciona automáticamente.

### Estructura completa del estado

```python
_session_state = {
    # --- Manejado por la infraestructura (no tocar desde el pipeline) ---
    "active":       bool,
    "session_id":   str,
    "child": {
        "dob":    str,      # "YYYY-MM-DD"
        "gender": str,      # "F" | "M" | "O"
        "notes":  str,
        "anamnesis_otitis":         int,
        "anamnesis_hearing_dx":     str | None,
        "anamnesis_home_language":  str,
        "anamnesis_family_history": int,
        "anamnesis_family_who":     str | None,
        "anamnesis_prior_therapy":  int,
    },
    "started_at":   str,

    # --- Daniel actualiza estos campos durante el pipeline ---
    "status":            str,
    "current_item":      int,
    "total_items":       int,
    "current_word":      str,
    "analysis_progress": int,
    "analysis_total":    int,
    "no_voice_detected": bool,
    "results":           dict,
}
```

### Estados posibles

| status | qué ve el evaluador | cuándo usarlo |
|---|---|---|
| `idle` | Preparando evaluación | al iniciar, antes del primer ítem |
| `playing` | Reproduciendo estímulo | mientras se reproduce el audio |
| `recording` | Grabando respuesta | mientras se graba |
| `no_voice` | No se detectó respuesta | cuando Silero VAD devuelve silencio |
| `analyzing` | Analizando grabaciones | XLS-R + NW corriendo |
| `generating_report` | Preparando informe | mientras se genera el reporte |
| `paused` | Evaluación pausada | cuando el evaluador presiona Pausar |
| `done` | Evaluación completada | al terminar, la UI redirige a resultados |

### Estructura de `results`

```python
_session_state["results"] = {
    "score": float,   # PFFB global, 2 decimales
    "level": str,     # "Normal" | "Seguimiento activo" | "Atención requerida"
}
```

---

## Simular el pipeline en laptop

```bash
BASE="http://localhost:5000/dev/simulate"

curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"playing"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"recording"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"no_voice"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"progress"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"analyzing"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"analysis_progress"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"generating_report"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"done"}'
```

> El endpoint `/dev/simulate` está **deshabilitado en Pi** (devuelve 403).

---

## Endpoints HTTP

| método | ruta | descripción |
|---|---|---|
| GET | `/` | Redirige según estado: registro, sesión o resultado |
| GET | `/registro` | Formulario de registro del niño + anamnesis |
| GET | `/sesion` | Pantalla de sesión en curso |
| GET | `/resultado` | Pantalla de resultados |
| GET | `/dispositivo` | Panel de administración del dispositivo |
| GET | `/historial` | Historial de sesiones y gestión de audios |
| POST | `/api/session/start` | Inicia sesión. Body: `{dob, gender, notes, anamnesis_*}` |
| GET | `/api/session/status` | Devuelve `_session_state` completo como JSON |
| POST | `/api/session/pause` | Pone `status = "paused"` |
| POST | `/api/session/resume` | Reanuda desde pausa |
| POST | `/api/session/reset` | Cancela la sesión y limpia el estado |
| GET | `/api/device/volume` | Devuelve el nivel de volumen actual |
| POST | `/api/device/volume` | Ajusta volumen. Body: `{level: 0-100}` |
| POST | `/api/device/tone` | Reproduce tono de prueba |
| POST | `/api/device/mic/start` | Inicia grabación de prueba |
| POST | `/api/device/mic/stop` | Detiene la grabación de prueba |
| POST | `/api/device/mic/play` | Reproduce la grabación de prueba |
| POST | `/api/device/shutdown` | Apaga el dispositivo |
| POST | `/api/device/reboot` | Reinicia el dispositivo |
| GET | `/api/device/status` | Uptime, disco, hora del servidor |
| GET | `/api/device/space` | Espacio libre y sesiones restantes estimadas |
| GET | `/api/historial/sessions` | Lista las últimas 50 sesiones |
| GET | `/api/historial/session/<id>` | Exportación completa de una sesión (JSON) |
| DELETE | `/api/historial/session/<id>` | Elimina sesión completa (BD + audios) |
| POST | `/api/historial/session/<id>/delete-audio` | Elimina solo los audios |
| GET | `/api/historial/session/<id>/audio/<word>` | Sirve el WAV de una palabra |
| GET | `/api/historial/session/<id>/export-zip` | ZIP con JSON + PDF + audios |
| GET | `/api/historial/session/<id>/report-html` | HTML del informe |
| POST | `/dev/simulate` | Simula estados del pipeline (solo debug) |

---

## Variables de entorno

| variable | default | descripción |
|---|---|---|
| `PORT` | `5000` | Puerto del servidor |
| `FLASK_ENV` | `development` | Poner `production` en Pi |
| `TRANSFORMERS_OFFLINE` | — | Poner `1` para forzar uso de caché local de modelos |
| `HF_DATASETS_OFFLINE` | — | Poner `1` para forzar uso de caché local de datasets |

En el Pi estas variables están configuradas en
`/etc/systemd/system/audia.service.d/pipewire.conf`.

---

## Troubleshooting

### El servidor arranca pero la UI no carga los templates

**Síntoma:** `jinja2.exceptions.TemplateNotFound: register.html`

```bash
mkdir -p templates static/css static/js
mv *.html templates/
mv base.css static/css/
mv utils.js static/js/
```

---

### `bash: /home/pi/audia-server/venv/bin/python: No existe el fichero`

El venv tiene rutas absolutas y no es portable:

```bash
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### Hay dos servidores corriendo al mismo tiempo

```bash
pkill -f "python app.py"
sleep 1
ps aux | grep "python app.py"
python app.py
```

---

### Un botón no responde al hacer click

Abrir en ventana incógnito (`Ctrl+Shift+N`). Si funciona ahí, el problema es
una extensión del navegador interceptando eventos de click.

---

### Un endpoint devuelve HTML en vez de JSON (`Unexpected token '<'`)

Flask está devolviendo una página de error. Revisar la terminal del servidor
para ver el error real. Verificar en Network que el status code no sea 404 o 500.

---

### `OSError: PortAudio library not found`

```bash
sudo apt install -y libportaudio2
```

---

### Los modelos de IA fallan sin internet en modo hotspot

Las variables de entorno offline no están configuradas. Al correr manualmente:

```bash
TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 python app.py
```

En el servicio systemd, verificar que existen en
`/etc/systemd/system/audia.service.d/pipewire.conf`.

---

### El modo desarrollo tarda en conectar (3-5 minutos)

Normal — NetworkManager necesita tiempo para negociar la conexión con el router
después de liberar la interfaz wlan0. El SSH puede aparecer colgado; esperar
sin interrumpir.

---

### `pip install` falla con errores de permisos

Siempre activar el venv antes de instalar:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

---

### weasyprint falla al generar el PDF

```bash
sudo apt install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev
source venv/bin/activate
python3 -c "from weasyprint import HTML; print('OK')"
```

---

### El servicio falla con `status=217/USER`

```bash
sudo nano /etc/systemd/system/audia.service
# Verificar User=pi y WorkingDirectory=/home/pi/audia-server
sudo systemctl daemon-reload && sudo systemctl restart audia
```

---

### La red Audia no aparece después de reiniciar

```bash
sudo systemctl status audia-hotspot
sudo /usr/local/bin/modo-hotspot
```

---

### La red Audia aparece pero no asigna IP

```bash
sudo ip addr add 192.168.4.1/24 dev wlan0
sudo systemctl restart dnsmasq
```

---

### NetworkManager pisa la IP del hotspot

```bash
cat /etc/NetworkManager/conf.d/unmanaged.conf
# Si no existe:
sudo /usr/local/bin/modo-hotspot
```

---

### hostapd falla con "Unit is masked"

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo /usr/local/bin/modo-hotspot
```

---

### El audio de prueba no se puede reproducir en el historial

```bash
ls recordings/<SESSION_ID>/
# Formato correcto: <SESSION_ID>_<palabra_sin_tilde>.wav
```

---

## TODOs pendientes

- `pipeline.py` — completar `BATERIA` con las 20 palabras reales
- `motor_ia.py` — agregar umbral de similitud mínima para marcar `not_evaluable` cuando el niño dice algo completamente diferente a la palabra esperada
- Hardware de audio definitivo — reemplazar Bluetooth por módulo USB-C con parlante y micrófono dedicados
- Panel de dispositivo — campo para cambiar SSID/contraseña del modo dev desde la interfaz
