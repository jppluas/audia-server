# FonoScreen — Kiosk Server

Sistema de cribado fonológico automatizado para niños de 3 a 5 años.
ESPOL · Ingeniería en Ciencias de la Computación · Materia Integradora

---

## Estructura del proyecto

```
fonoscreen-server/
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
│   ├── fonoscreen.service
│   └── fonoscreen-hotspot.service
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
├── fonoscreen.db           # Base de datos SQLite (git-ignored)
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
sudo apt install -y espeak-ng sox

# audio real en laptop (para prueba de micrófono y pipeline)
sudo apt install -y pulseaudio alsa-utils
sudo usermod -aG audio $USER
pulseaudio --start
```

### Arrancar el servidor

```bash
cd ~/fonoscreen-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
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
- **Hostname:** `fonoscreen`
- **SSH:** activado, autenticación por contraseña
- **Usuario:** `pi`, contraseña la que prefieras
- **Wi-Fi:** nombre y contraseña de la red donde se va a hacer el primer arranque
- **Zona horaria:** `America/Guayaquil`
- **Teclado:** `es`

> La red Wi-Fi configurada aquí es la que el Pi usará para conectarse a internet
> en el primer arranque y descargar dependencias. El `first_boot.sh` la leerá
> automáticamente para configurar el modo desarrollo.

### Paso 2: Editar `config/modo-dev` antes de copiar

Abrir `config/modo-dev` y reemplazar `CONTRASENA_AQUI` con la contraseña real
de tu red Wi-Fi. El SSID se detecta automáticamente del Imager, pero la
contraseña no está disponible (está hasheada). Si prefieres, puedes dejarlo
con el placeholder y editarlo después en el Pi.

### Paso 3: Copiar el proyecto a la microSD

Con la SD montada en la laptop:

```bash
# Verificar que está montada
ls /media/$USER/rootfs/home/pi/

# Copiar el proyecto completo
sudo cp -r ~/fonoscreen-server /media/$USER/rootfs/home/pi/
sudo chown -R 1000:1000 /media/$USER/rootfs/home/pi/fonoscreen-server

# Eliminar el venv de laptop (no sirve en ARM)
sudo rm -rf /media/$USER/rootfs/home/pi/fonoscreen-server/venv

# Copiar el servicio de primer arranque
sudo cp /media/$USER/rootfs/home/pi/fonoscreen-server/first-boot.service \
    /media/$USER/rootfs/etc/systemd/system/

# Habilitar el servicio (crear symlink)
sudo ln -sf /etc/systemd/system/first-boot.service \
    /media/$USER/rootfs/etc/systemd/system/multi-user.target.wants/first-boot.service
```

### Paso 4: Desmontar y arrancar el Pi

```bash
sudo umount /media/$USER/bootfs
sudo umount /media/$USER/rootfs
```

Insertar la SD en el Pi y encender. El `first_boot.sh` corre automáticamente:
1. Instala dependencias del sistema (`sox`, `alsa-utils`, `hostapd`, `dnsmasq`, librerías de weasyprint)
2. Crea el venv ARM e instala Flask y weasyprint
3. Copia los archivos de `config/` a sus rutas del sistema
4. Configura sudoers y aliases
5. Habilita los servicios systemd
6. Activa el hotspot
7. Reinicia

El proceso tarda 5-10 minutos dependiendo de la velocidad de internet. El Pi
se reinicia solo al terminar.

### Paso 5: Verificar

Después del reinicio, buscar la red `FonoScreen` en el celular, conectarse con
la contraseña `fonoscreen2025` y abrir `http://192.168.4.1:5000`.

Para ver el log del primer arranque:
```bash
# Conectarse en modo dev primero (ver sección abajo), luego:
cat ~/first_boot.log
```

---

## Setup manual del Pi (alternativa si first_boot.sh falla)

```bash
# 1. Dependencias del sistema
sudo apt install -y sox alsa-utils hostapd dnsmasq espeak-ng \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev

# 2. PipeWire para audio Bluetooth
sudo apt install -y pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth
systemctl --user enable pipewire pipewire-pulse wireplumber
systemctl --user start pipewire pipewire-pulse wireplumber

# 3. Fix Bluetooth soft block
sudo rfkill unblock bluetooth
echo 'SUBSYSTEM=="rfkill", ATTR{type}=="bluetooth", ATTR{state}="1"' \
    | sudo tee /etc/udev/rules.d/50-bluetooth.rules

# 4. Variables de entorno PipeWire para el servicio Flask
sudo mkdir -p /etc/systemd/system/fonoscreen.service.d
sudo tee /etc/systemd/system/fonoscreen.service.d/pipewire.conf << 'EOF'
[Service]
Environment="PIPEWIRE_RUNTIME_DIR=/run/user/1000"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
EOF

# 5. Clonar el proyecto y crear venv
git clone <repo> ~/fonoscreen-server
cd ~/fonoscreen-server
python3 -m venv venv

# Paquetes pequeños primero
venv/bin/pip install Flask weasyprint sounddevice soundfile requests phonemizer

# torch separado con directorio temporal en disco (evita llenar /tmp en RAM)
mkdir -p ~/.pip-tmp
TMPDIR=~/.pip-tmp venv/bin/pip install --cache-dir ~/.pip-cache \
    torch torchaudio transformers
rm -rf ~/.pip-tmp ~/.pip-cache

# 6. Copiar archivos de configuración
sudo cp config/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp config/dnsmasq.conf /etc/dnsmasq.conf
sudo cp config/modo-hotspot /usr/local/bin/modo-hotspot
sudo cp config/modo-dev /usr/local/bin/modo-dev
sudo chmod +x /usr/local/bin/modo-hotspot /usr/local/bin/modo-dev
sudo cp config/fonoscreen.service /etc/systemd/system/
sudo cp config/fonoscreen-hotspot.service /etc/systemd/system/

# 7. Habilitar servicios y activar hotspot
sudo systemctl daemon-reload
sudo systemctl enable fonoscreen fonoscreen-hotspot
sudo /usr/local/bin/modo-hotspot
```

Ver los logs del servicio:
```bash
journalctl -u fonoscreen -f
# o directamente:
tail -f ~/fonoscreen-server/logs/server.log
```

---

## Audio Bluetooth en el Pi

FonoScreen usa PipeWire para gestionar el audio. Los controles usan `wpctl` y
`pw-play`/`pw-record`, que funcionan tanto en el Pi como en laptop con
PipeWire/PulseAudio.

### Conectar auriculares Bluetooth

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
después de que aparezca "Ahora repite la palabra" antes de pedirle al niño que hable.

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



## Uso diario

### Modo producción (por defecto al encender)

El Pi genera la red `FonoScreen` automáticamente. Cualquier dispositivo se
conecta con `fonoscreen2025` y abre `http://192.168.4.1:5000`.

### Activar modo desarrollo (SSH)

Desde la terminal del Pi o desde el botón en el panel de dispositivo de la app:

```bash
devmode
```

Esperar 2-5 minutos (normal en Pi 3 B+) y conectar por SSH:

```bash
TERM=xterm-256color ssh pi@<IP-del-pi>
```

Para encontrar la IP del Pi en la red:
```bash
nmap -sn 192.168.100.0/24  # ajustar subred según tu router
```

Al reiniciar el Pi, vuelve automáticamente al modo hotspot.

### Volver al modo hotspot

```bash
hotspot
```

### Cambiar la red Wi-Fi del modo desarrollo

Si vas a usar el Pi en una red diferente, editar el script:

```bash
sudo nano /usr/local/bin/modo-dev
# Cambiar SSID_AQUI y CONTRASENA_AQUI
```

Y también actualizar la fuente en el proyecto para que el cambio quede en git:

```bash
nano ~/fonoscreen-server/config/modo-dev
```

---

## Backup de la configuración

Para hacer backup de todos los archivos del sistema desde el Pi:

```bash
bash ~/fonoscreen-server/backup_config.sh
```

El backup queda en `~/fonoscreen-server/backups/backup-<fecha>/`.

Para copiarlo a la laptop:
```bash
# Desde la laptop:
scp -r pi@<IP-del-pi>:~/fonoscreen-server/backups/ ~/fonoscreen-server/backups/
```

El backup incluye: `modo-hotspot`, `modo-dev`, `fonoscreen.service`,
`fonoscreen-hotspot.service`, `hostapd.conf`, `dnsmasq.conf`, `sudoers`,
`.bashrc`, y un snapshot del estado del sistema.

---

## Modificar la configuración del sistema

Si cambias algún archivo en `config/`, debes copiarlo manualmente al sistema:

```bash
# Ejemplo: actualizar modo-hotspot
sudo cp ~/fonoscreen-server/config/modo-hotspot /usr/local/bin/modo-hotspot

# Ejemplo: actualizar fonoscreen.service
sudo cp ~/fonoscreen-server/config/fonoscreen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart fonoscreen
```

Los archivos en `config/` son la fuente única de verdad. Los del sistema son
copias. Siempre editar en `config/` primero y luego copiar.

---

## Detección automática de entorno

```python
IS_PI = Path("/proc/device-tree/model").exists()
```

Este archivo solo existe en Raspberry Pi. No hay que configurar nada:
el mismo código funciona en laptop y en Pi sin cambios.

---

## Base de datos SQLite

La BD `fonoscreen.db` se crea automáticamente en la raíz del proyecto al
arrancar Flask por primera vez. No hay que crearla manualmente.

### Tablas

| tabla | descripción |
|---|---|
| `sessions` | Una fila por sesión: fecha de nacimiento, género, anamnesis, PFFB, nivel, estado. Sin nombre del niño (anonimizado). Solo sesiones con `status='done'` aparecen en el historial. |
| `items` | Una fila por palabra evaluada (20 por sesión): transcripción, resultado, tipo de error, alineación NW |
| `phoneme_summary` | Una fila por fonema por sesión: PFF%, nivel, error predominante |
| `reports` | Una fila por sesión: nota clínica y nota para representantes generadas automáticamente por el pipeline |

### Funciones principales (para el pipeline de Daniel)

```python
import db

# Al terminar cada ítem
db.save_item(session_id, {
    "item_index":    i,             # 0-19
    "phoneme":       "/r/",
    "word_expected": "carro",
    "word_produced": "cayo",        # transcripción del niño
    "audio_path":    f"{session_id}/{session_id}_carro.wav",
    "result":        "error",       # correct | error | not_evaluable
    "error_type":    "Sustitución", # Sustitución | Omisión | Inserción | Variante dialectal
    "pff":           50.0,
    "alignment":     [...],         # lista de dicts posición a posición (NW)
})

# Al terminar el análisis fonémico
db.save_phoneme_summary(session_id, {
    "phoneme":           "/r/",
    "pff":               62.5,
    "level":             "Bajo",        # Normal | Bajo
    "error_predominant": "Sustitución",
})

# Al terminar la generación del reporte (Gemma)
db.save_report(session_id, {
    "nota_clinica":        "...",  # texto para el especialista
    "nota_representantes": "...",  # texto en lenguaje simple
})

# Al terminar toda la sesión
db.close_session(session_id, pffb=68.2, level="Seguimiento activo")
```

### Nomenclatura de audios

Los archivos WAV se guardan en `recordings/<session_id>/` con el nombre:

```
<session_id>_<palabra_normalizada>.wav
```

La normalización quita tildes y pasa a minúsculas:
`mamá` → `mama`, `café` → `cafe`, `nariz` → `nariz`.

Ejemplos:
```
recordings/A1B2C3D4/A1B2C3D4_mama.wav
recordings/A1B2C3D4/A1B2C3D4_carro.wav
recordings/A1B2C3D4/A1B2C3D4_cafe.wav
```

El pipeline guarda la ruta relativa en `items.audio_path`:
```python
audio_path = f"{session_id}/{db.audio_filename(session_id, word_expected)}"
```

### Exportación de sesión

Para exportar todos los datos de una sesión como dict:

```python
data = db.export_session(session_id)
# data = {
#   "session": {...},
#   "items": [...],
#   "phoneme_summary": [...],
#   "report": {...},
# }
```

Desde la interfaz, el historial permite:
- **Exportar ZIP**: JSON + PDF generado con weasyprint + audios WAV (si existen)
- **Exportar JSON**: solo los datos estructurados
- **Exportar PDF**: abre el informe en ventana nueva y llama `window.print()`

### Espacio en disco

El sistema verifica espacio antes de iniciar cada sesión. Parámetros:

- Peor caso por sesión: **28 MB** (44.1kHz estéreo, 8s × 20 ítems)
- Mínimo requerido: **10 sesiones disponibles** (280 MB libres)

Si hay menos espacio, el inicio de sesión devuelve error 507 y la pantalla
de registro muestra un banner rojo. El panel de dispositivo muestra el número
de sesiones restantes estimadas en tiempo real.

### Gestión de audios desde el historial

Cada sesión en el historial muestra si tiene audios disponibles. Las acciones
posibles (todas con confirmación de irreversibilidad):

| acción | qué hace |
|---|---|
| Borrar audios | Elimina `recordings/<session_id>/`. Resultado en BD intacto. |
| Borrar sesión completa | Elimina audios + todos los registros de BD. |
| Exportar ZIP | Genera PDF en memoria + empaqueta JSON + audios + PDF en un ZIP. |

---

## Informe de evaluación

El HTML del informe vive en `report_html.py` — es la fuente única de verdad
para el PDF y para la vista en pantalla. Si se cambia el diseño del informe,
cambia en ambos lados automáticamente.

```python
from report_html import generate_report_html
data = db.export_session(session_id)

# Informe clínico (completo, para el especialista)
html = generate_report_html(data, tipo="clinico")

# Informe para representantes (simplificado, para padres)
html = generate_report_html(data, tipo="representantes")

# Para PDF:
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
6. Nota para representantes (consejos prácticos por fonema en lenguaje simple)

Las notas se generan en `pipeline.py` mediante `_generar_nota_clinica()` y
`_generar_nota_representantes()`, usando una base de conocimiento por fonema
con observaciones clínicas específicas para cada tipo de error (omisión/sustitución).

Tiempo de generación del PDF estimado:
- Pi 3 B+: 3-8 segundos
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
    "active":       bool,   # True cuando hay sesión en curso
    "session_id":   str,    # ID de 8 caracteres, ej. "A1B2C3D4"
    "child": {
        "dob":    str,      # "YYYY-MM-DD"
        "gender": str,      # "F" | "M" | "O"
        "notes":  str,
        # anamnesis estructurada
        "anamnesis_otitis":         int,  # 0 | 1
        "anamnesis_hearing_dx":     str | None,
        "anamnesis_home_language":  str,
        "anamnesis_family_history": int,  # 0 | 1
        "anamnesis_family_who":     str | None,
        "anamnesis_prior_therapy":  int,  # 0 | 1
    },
    "started_at":   str,    # ISO datetime

    # --- Daniel actualiza estos campos durante el pipeline ---
    "status":           str,    # ver tabla de estados abajo
    "current_item":     int,    # ítem actual, empieza en 0
    "total_items":      int,    # total de palabras a evaluar
    "current_word":     str,    # palabra objetivo, ej. "pelota"
    "analysis_progress":int,    # ítems ya analizados (durante "analyzing")
    "no_voice_detected":bool,   # True cuando Silero VAD no detectó voz
    "results":          dict,   # resultado final (ver estructura abajo)
}
```

### Estados posibles

| status | qué ve el docente | cuándo usarlo |
|---|---|---|
| `idle` | Preparando evaluación | al iniciar, antes del primer ítem |
| `playing` | Escucha con atención | mientras se reproduce el estímulo de audio |
| `recording` | Ahora repite la palabra | mientras `arecord` está grabando |
| `no_voice` | No se escuchó respuesta | cuando Silero VAD devuelve silencio |
| `analyzing` | Analizando grabaciones | fase post-grabación, XLS-R + NW corriendo |
| `generating_report` | Preparando informe | mientras Gemma genera el reporte |
| `paused` | Evaluación pausada | cuando el docente presiona Pausar |
| `done` | ¡Evaluación completada! | al terminar, la UI redirige a resultados |

### Estructura de `results`

```python
_session_state["results"] = {
    "score": int,           # puntuación global 0-100
    "level": str,           # texto descriptivo del nivel
    "details": [
        {
            "phoneme": str,     # fonema evaluado, ej. "/r/"
            "score":   int,     # puntuación 0-100
            "flag":    bool,    # True = requiere atención
        },
    ],
}
```

### Conectar el pipeline

En `app.py`, buscar el bloque `# TODO` (~línea 154):

```python
import threading
from pipeline import run_pipeline
threading.Thread(target=run_pipeline, args=(session_id,), daemon=True).start()
```

### Estructura básica de `run_pipeline`

```python
# pipeline.py
import app, db, time

def esperar_si_pausado():
    """Bloquea el hilo del pipeline mientras el docente tiene pausada la prueba."""
    while app._session_state.get("status") == "paused":
        time.sleep(0.5)

def run_pipeline(session_id):
    state = app._session_state

    WORDS = ["mamá", "cama", "papá", ...]  # batería real
    state["total_items"] = len(WORDS)

    for i, word in enumerate(WORDS):
        if not state["active"]:
            return
        esperar_si_pausado()

        # 1. Reproducir estímulo
        state.update({"status": "playing", "current_word": word, "current_item": i})
        reproducir_audio(word)
        esperar_si_pausado()

        # 2. Grabar respuesta
        state["status"] = "recording"
        audio_path = db.get_recordings_dir(session_id) / db.audio_filename(session_id, word)
        audio = grabar(audio_path)

        # 3. Verificar voz (Silero VAD)
        if not voz_detectada(audio):
            state.update({"status": "no_voice", "no_voice_detected": True})
            continue

        state["no_voice_detected"] = False

    # Fase de análisis (XLS-R + Phonemizer + NW)
    state.update({"status": "analyzing", "analysis_progress": 0})
    for i, word in enumerate(WORDS):
        if not state["active"]:
            return
        resultado = analizar(session_id, i, word)
        db.save_item(session_id, resultado)
        state["analysis_progress"] = i + 1

    # Guardar resumen por fonema
    for fonema_data in calcular_resumen_fonemas():
        db.save_phoneme_summary(session_id, fonema_data)

    # Generar reporte (Gemma via Ollama)
    state["status"] = "generating_report"
    reporte = generar_reporte_gemma(session_id)
    db.save_report(session_id, reporte)

    # Terminar — la UI redirige automáticamente a /resultado
    pffb = calcular_pffb()
    level = calcular_nivel(pffb)
    db.close_session(session_id, pffb, level)
    state["results"] = {"score": pffb, "level": level, "details": [...]}
    state["status"] = "done"
```

### Cómo funciona la pausa y reanudación

Cuando el docente presiona "Pausar":
- La infraestructura pone `state["status"] = "paused"`
- El pipeline llama a `esperar_si_pausado()` que bloquea el hilo hasta que cambie

Cuando el docente presiona "Continuar":
- La infraestructura llama a `/api/session/resume`
- Ese endpoint pone `state["status"] = "playing"` (o `"idle"` si no había palabra activa)
- El pipeline que estaba bloqueado en `esperar_si_pausado()` detecta el cambio y continúa

---

## Simular el pipeline en laptop

Con el servidor corriendo en modo debug, desde otra terminal:

```bash
BASE="http://localhost:5000/dev/simulate"

# Flujo completo:
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"playing"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"recording"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"no_voice"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"progress"}'           # repetir 20 veces
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"analyzing"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"analysis_progress"}'  # repetir 20 veces
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"generating_report"}'
curl -s -X POST $BASE -H "Content-Type: application/json" -d '{"action":"done"}'
```

Cada comando responde con el estado completo en JSON.
La pantalla de sesión reacciona en máximo 1.5 segundos sin recargar.

Para probar pausa y reanudación:
```bash
curl -s -X POST http://localhost:5000/api/session/pause \
  -H "Content-Type: application/json"

curl -s -X POST http://localhost:5000/api/session/resume \
  -H "Content-Type: application/json"
```

> El endpoint `/dev/simulate` está **deshabilitado en Pi** (devuelve 403).

---

## Probar la base de datos (sesión de prueba)

Con el servidor corriendo en modo debug, el historial muestra un botón
"➕ Insertar sesión de prueba". Al presionarlo se crea una sesión completa
de **John Doe** con la batería fonológica real de FonoScreen, resultados
coherentes con la evaluación manual de los audios, y notas clínicas de ejemplo.

Para probar también la reproducción de audios, crear los WAVs de prueba
manualmente después de insertar la sesión. El historial muestra el session ID:

```bash
# Reemplazar SESSION_ID con el ID que aparece en el historial
mkdir -p recordings/SESSION_ID
cd recordings/SESSION_ID

for word in mama cama papa sopa boca abeja taza gato dedo helado \
            casa vaca agua foco cafe nariz mano luna pelota; do
    sox -n "SESSION_ID_${word}.wav" synth 1.5 sine 440
done
```

Después de crear los archivos, recargar el historial. El botón ▶ aparece
en cada fila de la tabla de palabras. Si los audios no existen, la columna
muestra `—` y el botón de "Borrar audios" no aparece.

Para probar el flujo completo de gestión:
1. Insertar sesión de prueba → anotar el ID
2. Crear los WAVs de prueba con el comando de arriba
3. Abrir la sesión en el historial → verificar que ▶ funciona
4. Exportar ZIP → verificar que incluye JSON, PDF y audios
5. Presionar "Borrar audios" → confirmar → verificar que ▶ desaparece
6. Exportar ZIP nuevamente → verificar que sale sin audios
7. Presionar "Borrar sesión completa" → confirmar → verificar que desaparece del historial

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
| POST | `/api/session/start` | Inicia sesión. Body: `{name, dob, gender, notes, anamnesis_*}` |
| GET | `/api/session/status` | Devuelve `_session_state` completo como JSON |
| POST | `/api/session/pause` | Pone `status = "paused"` |
| POST | `/api/session/resume` | Reanuda desde pausa |
| POST | `/api/session/reset` | Cancela la sesión y limpia el estado |
| GET | `/api/report/tecnico` | PDF del informe técnico (placeholder hasta pipeline) |
| GET | `/api/report/representantes` | PDF para representantes (placeholder hasta pipeline) |
| GET | `/api/device/volume` | Devuelve el nivel de volumen actual |
| POST | `/api/device/volume` | Ajusta volumen. Body: `{level: 0-100}` |
| POST | `/api/device/tone` | Reproduce tono de prueba por el parlante |
| POST | `/api/device/mic/start` | Inicia grabación de prueba (indefinida hasta /stop) |
| POST | `/api/device/mic/stop` | Detiene la grabación de prueba |
| POST | `/api/device/mic/play` | Reproduce la grabación de prueba por el parlante |
| POST | `/api/device/devmode` | Activa modo desarrollo (solo Pi) |
| POST | `/api/device/shutdown` | Apaga el dispositivo (`sudo shutdown now`) |
| POST | `/api/device/reboot` | Reinicia el dispositivo (`sudo reboot`) |
| GET | `/api/device/status` | Uptime, disco, hora del servidor |
| GET | `/api/device/space` | Espacio libre y sesiones restantes estimadas |
| GET | `/api/historial/sessions` | Lista las últimas 50 sesiones |
| GET | `/api/historial/session/<id>` | Exportación completa de una sesión (JSON) |
| DELETE | `/api/historial/session/<id>` | Elimina sesión completa (BD + audios) |
| POST | `/api/historial/session/<id>/delete-audio` | Elimina solo los audios |
| GET | `/api/historial/session/<id>/audio/<word>` | Sirve el WAV de una palabra |
| GET | `/api/historial/session/<id>/export-zip` | ZIP con JSON + PDF + audios |
| GET | `/api/historial/session/<id>/report-html` | HTML del informe (fuente del PDF) |
| POST | `/api/historial/seed` | Inserta sesión de prueba (solo debug) |
| POST | `/dev/simulate` | Simula estados del pipeline (solo debug, deshabilitado en Pi) |

---

## Variables de entorno

| variable | default | descripción |
|---|---|---|
| `PORT` | `5000` | Puerto del servidor. Usar `80` en Pi para acceso directo |
| `FLASK_ENV` | `development` | Poner `production` en Pi para deshabilitar debug |
| `FONOSCREEN_SECRET` | `dev-secret-fonoscreen` | Clave secreta de Flask. Cambiar en producción |

Ejemplo para Pi en `fonoscreen.service`:
```ini
Environment="FLASK_ENV=production"
Environment="PORT=80"
Environment="FONOSCREEN_SECRET=una-clave-larga-y-segura"
```

---

## Troubleshooting

### El servidor arranca pero la UI no carga los templates

**Síntoma:** `jinja2.exceptions.TemplateNotFound: register.html`

**Causa:** los archivos HTML no están en la carpeta `templates/`.

**Solución:**
```bash
mkdir -p templates static/css static/js
mv *.html templates/
mv base.css static/css/
mv utils.js static/js/
```

---

### `bash: /home/jp/fonoscreen/venv/bin/python: No existe el fichero`

**Causa:** los venvs tienen rutas absolutas hardcodeadas y no son portables.

**Solución:**
```bash
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### Hay dos servidores corriendo al mismo tiempo

**Síntoma:** los cambios en el código no se reflejan en el navegador aunque
el servidor se haya reiniciado. O el navegador responde con datos de una
sesión que ya fue cancelada.

**Causa:** un proceso viejo de Flask quedó corriendo en segundo plano.

**Solución:**
```bash
pkill -f "python app.py"
sleep 1
ps aux | grep "python app.py"  # verificar que no queda ninguno
python app.py
```

---

### Un botón no responde al hacer click

**Síntoma:** se presiona un botón y no pasa nada. No aparece nada en Network
ni en Console del navegador.

**Causa más común:** una extensión del navegador está interceptando los
eventos de click.

**Solución:** abrir en ventana incógnito (`Ctrl+Shift+N`) donde las extensiones
están deshabilitadas. Si funciona ahí, el problema es la extensión.

Para identificar cuál extensión es el problema, ejecutar en la consola:
```javascript
document.querySelectorAll('script').forEach((s, i) =>
  console.log(i, s.src || s.textContent.slice(0, 60))
)
```
Si aparecen scripts de `chrome-extension://` antes de los scripts del proyecto,
ahí está el conflicto.

---

### Un endpoint devuelve HTML en vez de JSON (`Unexpected token '<'`)

**Síntoma:** en la consola del navegador aparece
`SyntaxError: Unexpected token '<', "<!doctype "... is not valid JSON`

**Causa:** Flask está devolviendo una página de error HTML (404 o 500) porque
la ruta no existe o hay un error en el servidor.

**Solución:** revisar la terminal donde corre el servidor para ver el error
real. También verificar en Network que el status code no sea 404 o 500.

Si es 404, el endpoint no existe en el `app.py` que está corriendo. Verificar:
```bash
grep "nombre_del_endpoint" ~/fonoscreen-server/app.py
```

---

### La pausa funciona pero el botón Continuar no hace nada

**Causa:** el `app.py` no tiene el endpoint `/api/session/resume`. Ocurre
cuando se está usando una versión vieja del archivo.

**Verificar:**
```bash
grep "session/resume" ~/fonoscreen-server/app.py
```

Si no devuelve nada, actualizar `app.py` con la versión más reciente.

---

### `pip install` falla con errores de permisos o rutas

**Causa:** se está corriendo `pip` sin tener el venv activado, instalando en
el Python del sistema.

**Solución:** siempre activar el venv antes de instalar:
```bash
source venv/bin/activate
# verificar que el prompt muestra (venv) al inicio
pip install -r requirements.txt
```

---

### weasyprint falla al generar el PDF

**Síntoma:** el ZIP se descarga pero contiene `informe_ERROR.txt` en vez del PDF.

**Causa:** faltan las librerías de sistema de weasyprint.

**Solución:**
```bash
sudo apt install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev
```

Verificar que weasyprint funciona:
```bash
source venv/bin/activate
python3 -c "from weasyprint import HTML; print('OK')"
```

---

### El servicio falla con `status=217/USER`

```bash
sudo nano /etc/systemd/system/fonoscreen.service
# Verificar User=pi y WorkingDirectory=/home/pi/fonoscreen-server
sudo systemctl daemon-reload && sudo systemctl restart fonoscreen
```

---

### El servicio falla con `status=209/STDOUT`

Cambiar en el `.service`:
```
StandardOutput=journal
StandardError=journal
```

---

### La red FonoScreen no aparece después de reiniciar

```bash
sudo systemctl status fonoscreen-hotspot
sudo /usr/local/bin/modo-hotspot
```

---

### La red FonoScreen aparece pero no asigna IP

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

### El modo desarrollo tarda en estar disponible por SSH

Normal en Pi 3 B+, esperar hasta 5 minutos. Si después de 5 minutos no conecta:

```bash
# Desde el monitor del Pi:
sudo ip addr del 192.168.4.1/24 dev wlan0 2>/dev/null
sudo systemctl restart ssh
```

---

### hostapd falla con "Unit is masked"

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo /usr/local/bin/modo-hotspot
```

---

### SSH conecta pero el Pi no es accesible por red

La IP `192.168.4.1` todavía está en `wlan0`:
```bash
sudo ip addr del 192.168.4.1/24 dev wlan0
```

---

### El audio de prueba no se puede reproducir en el historial

**Síntoma:** el botón ▶ aparece pero al presionarlo dice "No se pudo reproducir el audio."

**Causa más probable:** el archivo WAV no existe en disco con el nombre correcto.

**Verificar:**
```bash
ls recordings/<SESSION_ID>/
# Los archivos deben tener el formato: <SESSION_ID>_<palabra_sin_tilde>.wav
# Ejemplo correcto: A1B2C3D4_mama.wav, A1B2C3D4_cafe.wav
# Ejemplo incorrecto: A1B2C3D4_mamá.wav, item_00.wav
```

Si los archivos tienen tildes en el nombre, renombrarlos:
```bash
cd recordings/<SESSION_ID>
for f in *_*.wav; do
    # Renombrar manualmente si es necesario
    mv "$f" "$(echo $f | iconv -f utf-8 -t ascii//TRANSLIT)"
done
```

---

## TODOs pendientes

- `pipeline.py`: completar `BATERIA` con las 20 palabras reales (actualmente 3 para pruebas)
- `motor_ia.py`: agregar umbral de similitud mínima para marcar `not_evaluable` cuando el niño dice algo completamente diferente a la palabra esperada
- Bluetooth: conexión automática confiable de auriculares en cada arranque del Pi sin intervención manual
- Panel de dispositivo: campo para cambiar SSID/contraseña del modo dev sin editar archivos
- `pipeline.py`: actualizar `analysis_progress` durante la fase de análisis para que la barra de progreso se mueva
