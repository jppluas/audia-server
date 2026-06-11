# FonoScreen — Kiosk Server

Sistema de cribado fonológico automatizado para niños de 3 a 5 años.
ESPOL · Ingeniería en Ciencias de la Computación · Materia Integradora

---

## Estructura del proyecto

```
fonoscreen-server/
├── app.py                  # Servidor Flask — toda la infraestructura
├── requirements.txt        # Flask==3.1.3
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
│   ├── register.html       # Registro del niño antes de la prueba
│   ├── session.html        # Pantalla en curso — polling al estado global
│   ├── results.html        # Resultados y descarga de informes
│   └── device.html         # Panel de dispositivo (volumen, mic, apagado)
├── static/
│   ├── css/base.css        # Estilos mobile-first
│   └── js/utils.js         # Utilidades JS: toast, confirm, api()
├── backups/                # Backups del sistema (git-ignored)
├── exports/                # PDFs generados (git-ignored)
└── logs/
    └── server.log
```

---

## Desarrollo en laptop (Debian 12)

```bash
cd ~/fonoscreen-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
# Abrir http://localhost:5000
```

Desde el celular (misma red): `http://<IP-de-la-laptop>:5000`

En laptop, `IS_PI = False`. Esto significa:
- El volumen, tono, grabación de micrófono y apagado se **simulan** (responden ok sin ejecutar nada real).
- El endpoint `/dev/simulate` está activo para simular el pipeline manualmente.
- El servidor corre en modo debug con recarga automática.

> **Importante:** el venv tiene rutas absolutas. Si mueves o renombras la
> carpeta, bórralo y créalo de nuevo:
> ```bash
> rm -rf venv
> python3 -m venv venv
> source venv/bin/activate
> pip install -r requirements.txt
> ```

> **Importante:** verificar siempre que solo hay un proceso corriendo antes de
> probar. Dos servidores activos al mismo tiempo causan comportamiento
> impredecible porque el navegador puede estar hablando con el proceso viejo.
> ```bash
> pkill -f "python app.py"
> sleep 1
> ps aux | grep "python app.py"  # verificar que no queda ninguno
> python app.py
> ```

> **Importante:** probar en ventana incógnito (`Ctrl+Shift+N`). Las extensiones
> de Chrome pueden interceptar eventos de click y hacer que los botones no
> respondan aunque el código esté correcto.

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
1. Instala dependencias del sistema (`sox`, `alsa-utils`, `hostapd`, `dnsmasq`)
2. Crea el venv ARM e instala Flask
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

Si el arranque automático no funciona, este es el proceso paso a paso:

```bash
# 1. Instalar dependencias de audio y red
sudo apt install -y sox alsa-utils hostapd dnsmasq

# 2. Clonar el proyecto
git clone <repo> ~/fonoscreen-server
cd ~/fonoscreen-server

# 3. Crear el venv ARM
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 4. Copiar archivos de configuración
sudo cp config/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp config/dnsmasq.conf /etc/dnsmasq.conf
sudo cp config/modo-hotspot /usr/local/bin/modo-hotspot
sudo cp config/modo-dev /usr/local/bin/modo-dev
sudo chmod +x /usr/local/bin/modo-hotspot /usr/local/bin/modo-dev
sudo cp config/fonoscreen.service /etc/systemd/system/
sudo cp config/fonoscreen-hotspot.service /etc/systemd/system/

# 5. Habilitar servicios
sudo systemctl daemon-reload
sudo systemctl enable fonoscreen fonoscreen-hotspot

# 6. Activar hotspot
sudo /usr/local/bin/modo-hotspot
```

Ver los logs del servicio:
```bash
journalctl -u fonoscreen -f
# o directamente:
tail -f ~/fonoscreen-server/logs/server.log
```

---

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
        "name":   str,
        "dob":    str,      # "YYYY-MM-DD"
        "gender": str,      # "F" | "M" | "O"
        "notes":  str,
    },
    "started_at":   str,    # ISO datetime

    # --- Daniel actualiza estos campos durante el pipeline ---
    "status":           str,    # ver tabla de estados abajo
    "current_item":     int,    # ítem actual, empieza en 0, sube hasta total_items
    "total_items":      int,    # total de palabras a evaluar (defínelo al inicio)
    "current_word":     str,    # palabra objetivo que ve el docente, ej. "pelota"
    "analysis_progress":int,    # cuántos ítems ya analizados (durante "analyzing")
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
    "level": str,           # texto descriptivo del nivel, ej. "Desarrollo típico"
    "details": [
        {
            "phoneme": str,     # fonema evaluado, ej. "/r/"
            "score":   int,     # puntuación 0-100
            "flag":    bool,    # True = requiere atención
        },
        # ... un objeto por fonema evaluado
    ],
}
```

### Conectar el pipeline

En `app.py`, buscar el bloque `# TODO` (~línea 125):

```python
import threading
from pipeline import run_pipeline
threading.Thread(target=run_pipeline, args=(session_id,), daemon=True).start()
```

### Estructura básica de `run_pipeline`

```python
# pipeline.py
import app
import time

def esperar_si_pausado():
    """Bloquea el hilo del pipeline mientras el docente tiene pausada la prueba."""
    while app._session_state.get("status") == "paused":
        time.sleep(0.5)

def run_pipeline(session_id):
    state = app._session_state

    WORDS = ["pelota", "casa", "árbol", ...]  # tu lista real
    state["total_items"] = len(WORDS)

    for i, word in enumerate(WORDS):

        # Verificar cancelación al inicio de cada ítem
        if not state["active"]:
            return

        esperar_si_pausado()

        # 1. Reproducir estímulo
        state.update({"status": "playing", "current_word": word, "current_item": i})
        reproducir_audio(word)

        esperar_si_pausado()

        # 2. Grabar respuesta
        state["status"] = "recording"
        audio = grabar()

        # 3. Verificar que el niño habló (Silero VAD)
        if not voz_detectada(audio):
            state.update({"status": "no_voice", "no_voice_detected": True})
            continue  # reintentar este ítem

        state["no_voice_detected"] = False
        guardar_audio(session_id, i, audio)

    # Fase de análisis (XLS-R + Phonemizer + NW)
    state.update({"status": "analyzing", "analysis_progress": 0})
    resultados = []
    for i, word in enumerate(WORDS):
        if not state["active"]:
            return
        resultados.append(analizar(session_id, i, word))
        state["analysis_progress"] = i + 1

    # Generar reporte (Gemma via Ollama)
    state["status"] = "generating_report"
    reporte = generar_reporte(resultados)

    # Terminar — la UI redirige automáticamente a /resultado
    state["results"] = {
        "score": reporte["score"],
        "level": reporte["level"],
        "details": reporte["details"],
    }
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

El pipeline no necesita hacer nada especial para reanudar: solo llamar
`esperar_si_pausado()` en los puntos donde no debe ejecutarse mientras está pausado.

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
# Mientras la sesión está en curso, pausar:
curl -s -X POST http://localhost:5000/api/session/pause \
  -H "Content-Type: application/json"

# Reanudar desde la UI o directamente:
curl -s -X POST http://localhost:5000/api/session/resume \
  -H "Content-Type: application/json"
```

> El endpoint `/dev/simulate` está **deshabilitado en Pi** (devuelve 403).

---

## Endpoints HTTP

| método | ruta | descripción |
|---|---|---|
| GET | `/` | Redirige según estado: registro, sesión o resultado |
| GET | `/registro` | Formulario de registro del niño |
| GET | `/sesion` | Pantalla de sesión en curso |
| GET | `/resultado` | Pantalla de resultados |
| GET | `/dispositivo` | Panel de administración del dispositivo |
| POST | `/api/session/start` | Inicia sesión. Body: `{name, dob, gender, notes}` |
| GET | `/api/session/status` | Devuelve `_session_state` completo como JSON |
| POST | `/api/session/pause` | Pone `status = "paused"` |
| POST | `/api/session/resume` | Reanuda desde pausa. Pone `status = "playing"` o `"idle"` |
| POST | `/api/session/reset` | Cancela la sesión y limpia el estado |
| GET | `/api/report/tecnico` | Descarga el PDF del informe técnico |
| GET | `/api/report/representantes` | Descarga el PDF del informe para representantes |
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

## TODOs pendientes

- `app.py` ~línea 125: descomentar lanzamiento del pipeline en hilo
- `api_report()`: reemplazar placeholder por PDF real (weasyprint o reportlab)
- Base de datos SQLite para persistir sesiones y grabaciones entre reinicios
- Panel de dispositivo: campo para cambiar SSID/contraseña del modo dev sin editar archivos
