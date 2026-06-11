"""
FonoScreen - Kiosk server
Sistema de cribado fonológico automatizado para niños 3-5 años
ESPOL · Ingeniería en Ciencias de la Computación

Capa de infraestructura: Flask + interfaz web
El pipeline (XLS-R, Phonemizer, NW, Gemma) se conecta en sprint posterior.
"""

import os
import subprocess
import json
import time
import uuid
import logging
from datetime import datetime, date
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, redirect, url_for, abort
)

# ─── Configuración ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
LOGS_DIR = BASE_DIR / "logs"
EXPORTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=LOGS_DIR / "server.log",
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("fonoscreen")

# Detección de entorno: Pi vs laptop
IS_PI = Path("/proc/device-tree/model").exists()
SERVER_START_TIME = time.time()

app = Flask(__name__)
app.secret_key = os.environ.get("FONOSCREEN_SECRET", "dev-secret-fonoscreen")

# ─── Estado global de sesión ──────────────────────────────────────────────────
# En el Pi un solo evaluador opera el dispositivo; no se necesita BD.
# El estado se resetea al reiniciar el servidor (comportamiento correcto).

_session_state = {
    "active": False,           # ¿hay una prueba en curso?
    "session_id": None,
    "child": {},               # datos del niño registrado
    "current_item": 0,
    "total_items": 20,         # placeholder; el pipeline define el real
    "status": "idle",          # idle | recording | analyzing | done | error
    "results": None,           # resultado del pipeline
    "started_at": None,
}


def get_state():
    return dict(_session_state)


# ─── Rutas principales ────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Pantalla inicial: si no hay sesión activa → registro; si la hay → sesión."""
    state = get_state()
    if state["status"] == "done":
        return redirect(url_for("results"))
    if state["active"]:
        return redirect(url_for("session_view"))
    return redirect(url_for("register"))


# ── Flujo de sesión ───────────────────────────────────────────────────────────

@app.route("/registro")
def register():
    state = get_state()
    if state["active"] and state["status"] not in ("done", "error"):
        return redirect(url_for("session_view"))
    return render_template("register.html", state=state)


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    """Registra al niño e inicia una nueva sesión."""
    global _session_state

    if _session_state["active"]:
        return jsonify({"ok": False, "error": "Ya hay una sesión activa."}), 409

    data = request.get_json(silent=True) or {}
    required = ["name", "dob", "gender"]
    for field in required:
        if not data.get(field):
            return jsonify({"ok": False, "error": f"Campo requerido: {field}"}), 400

    session_id = str(uuid.uuid4())[:8].upper()
    _session_state = {
        "active": True,
        "session_id": session_id,
        "child": {
            "name": data["name"].strip(),
            "dob": data["dob"],
            "gender": data["gender"],
            "notes": data.get("notes", "").strip(),
        },
        "current_item": 0,
        "total_items": 20,
        "status": "idle",
        "current_word": None,       # Daniel: palabra objetivo actual
        "analysis_progress": 0,     # Daniel: ítems analizados post-grabación
        "no_voice_detected": False, # Daniel: Silero VAD no detectó voz
        "results": None,
        "started_at": datetime.now().isoformat(),
    }

    log.info("Sesión iniciada: %s — %s", session_id, data["name"])

    # TODO: aquí se lanza el pipeline en un hilo separado
    # from pipeline import run_pipeline
    # threading.Thread(target=run_pipeline, args=(session_id,), daemon=True).start()

    return jsonify({"ok": True, "session_id": session_id})


@app.route("/sesion")
def session_view():
    state = get_state()
    if not state["active"]:
        return redirect(url_for("register"))
    if state["status"] == "done":
        return redirect(url_for("results"))
    return render_template("session.html", state=state)


@app.route("/api/session/status")
def api_session_status():
    """Polling endpoint para actualizar la UI de sesión."""
    return jsonify(get_state())


@app.route("/api/session/pause", methods=["POST"])
def api_session_pause():
    global _session_state
    if not _session_state["active"]:
        return jsonify({"ok": False, "error": "Sin sesión activa."}), 400
    _session_state["status"] = "paused"
    log.info("Sesión %s pausada.", _session_state["session_id"])
    return jsonify({"ok": True})


@app.route("/api/session/resume", methods=["POST"])
def api_session_resume():
    global _session_state
    if not _session_state["active"]:
        return jsonify({"ok": False, "error": "Sin sesión activa."}), 400
    if _session_state["status"] != "paused":
        return jsonify({"ok": False, "error": "La sesión no está pausada."}), 400
    # Vuelve al estado anterior lógico: si hay palabra activa → playing, si no → idle
    _session_state["status"] = "playing" if _session_state.get("current_word") else "idle"
    log.info("Sesión %s reanudada.", _session_state["session_id"])
    return jsonify({"ok": True})


@app.route("/api/session/reset", methods=["POST"])
def api_session_reset():
    """Cancela la sesión actual y vuelve a registro."""
    global _session_state
    old_id = _session_state.get("session_id")
    _session_state = {
        "active": False, "session_id": None, "child": {},
        "current_item": 0, "total_items": 20, "status": "idle",
        "results": None, "started_at": None,
    }
    log.info("Sesión %s reiniciada/cancelada.", old_id)
    return jsonify({"ok": True})


# ── Resultados ────────────────────────────────────────────────────────────────

@app.route("/resultado")
def results():
    state = get_state()
    if state["status"] != "done":
        return redirect(url_for("index"))
    return render_template("results.html", state=state)


@app.route("/api/report/<report_type>")
def api_report(report_type):
    """Genera/devuelve el informe en PDF. Stub hasta que esté el pipeline."""
    if report_type not in ("tecnico", "representantes"):
        abort(404)
    state = get_state()
    if state["status"] != "done":
        return jsonify({"ok": False, "error": "Sin resultados disponibles."}), 400

    # TODO: generar PDF real con reportlab/weasyprint
    filename = f"informe_{report_type}_{state['session_id']}.pdf"
    filepath = EXPORTS_DIR / filename
    if not filepath.exists():
        # Placeholder hasta que esté el generador de PDFs
        filepath.write_text(f"Informe {report_type} — sesión {state['session_id']}\n(placeholder)")

    return send_from_directory(EXPORTS_DIR, filename, as_attachment=True)


# ── Panel de dispositivo ──────────────────────────────────────────────────────

@app.route("/dispositivo")
def device_panel():
    uptime_seconds = int(time.time() - SERVER_START_TIME)
    hours, rem = divmod(uptime_seconds, 3600)
    mins, secs = divmod(rem, 60)
    uptime_str = f"{hours}h {mins}m {secs}s"

    disk_info = _get_disk_info()
    return render_template("device.html",
                           uptime=uptime_str,
                           disk=disk_info,
                           is_pi=IS_PI)


@app.route("/api/device/volume", methods=["POST"])
def api_set_volume():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level is None or not (0 <= int(level) <= 100):
        return jsonify({"ok": False, "error": "Nivel inválido (0-100)."}), 400
    level = int(level)
    try:
        subprocess.run(
            ["amixer", "sset", "Master", f"{level}%"],
            capture_output=True, check=True
        )
        log.info("Volumen ajustado a %d%%", level)
        return jsonify({"ok": True, "level": level})
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning("amixer no disponible o falló: %s", e)
        # En laptop de desarrollo, simulamos éxito
        return jsonify({"ok": True, "level": level, "simulated": not IS_PI})


@app.route("/api/device/volume", methods=["GET"])
def api_get_volume():
    try:
        result = subprocess.run(
            ["amixer", "sget", "Master"],
            capture_output=True, text=True, check=True
        )
        # Parsear línea: "Mono: Playback 65536 [100%] [on]"
        import re
        match = re.search(r"\[(\d+)%\]", result.stdout)
        level = int(match.group(1)) if match else 80
        return jsonify({"ok": True, "level": level})
    except Exception:
        return jsonify({"ok": True, "level": 80, "simulated": True})


@app.route("/api/device/tone", methods=["POST"])
def api_tone():
    """Reproduce un tono de prueba por el parlante del dispositivo."""
    if not IS_PI:
        return jsonify({"ok": True, "simulated": True})
    try:
        # sox genera el tono directamente: 1 kHz, 1.5 segundos, volumen 70%
        subprocess.run(
            ["sox", "-n", "-d", "synth", "1.5", "sine", "1000", "vol", "0.7"],
            capture_output=True, check=True, timeout=5
        )
        return jsonify({"ok": True})
    except FileNotFoundError:
        # sox no instalado, intentar con aplay + archivo WAV generado con python
        try:
            import struct, math
            sample_rate = 44100
            duration = 1.5
            freq = 1000
            n_samples = int(sample_rate * duration)
            tone_file = "/tmp/fonoscreen_tone.wav"
            with open(tone_file, "wb") as f:
                # WAV header
                data_size = n_samples * 2
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + data_size))
                f.write(b"WAVEfmt ")
                f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                                    sample_rate * 2, 2, 16))
                f.write(b"data")
                f.write(struct.pack("<I", data_size))
                for i in range(n_samples):
                    val = int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sample_rate))
                    f.write(struct.pack("<h", val))
            subprocess.run(["aplay", tone_file],
                           capture_output=True, check=True, timeout=5)
            return jsonify({"ok": True})
        except Exception as e:
            log.warning("Tono falló: %s", e)
            return jsonify({"ok": False, "error": str(e)})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("Tono falló: %s", e)
        return jsonify({"ok": False, "error": str(e)})


# Proceso de grabación en curso (global para poder matarlo desde /stop)
_mic_process = None
MIC_TEST_FILE = "/tmp/fonoscreen_mic_test.wav"


@app.route("/api/device/mic/start", methods=["POST"])
def api_mic_start():
    """Inicia grabación con arecord. El proceso queda corriendo hasta /stop."""
    global _mic_process
    if not IS_PI:
        log.info("Grabación de micrófono simulada (no es Pi).")
        _mic_process = "simulated"
        return jsonify({"ok": True, "simulated": True})
    if _mic_process and _mic_process != "simulated":
        try:
            _mic_process.terminate()
        except Exception:
            pass
    try:
        # Sin -d: graba indefinidamente hasta que lo matemos
        _mic_process = subprocess.Popen(
            ["arecord", "-f", "cd", "-t", "wav", MIC_TEST_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log.info("Grabación iniciada, PID %s", _mic_process.pid)
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "arecord no disponible en este entorno.",
                        "simulated": True})


@app.route("/api/device/mic/stop", methods=["POST"])
def api_mic_stop():
    """Detiene la grabación en curso."""
    global _mic_process
    if _mic_process == "simulated":
        _mic_process = None
        return jsonify({"ok": True, "simulated": True})
    if _mic_process is None:
        return jsonify({"ok": False, "error": "No hay grabación activa."})
    try:
        _mic_process.terminate()
        _mic_process.wait(timeout=3)
        _mic_process = None
        log.info("Grabación detenida.")
        return jsonify({"ok": True})
    except Exception as e:
        _mic_process = None
        log.warning("Error al detener grabación: %s", e)
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/device/mic/play", methods=["POST"])
def api_mic_play():
    """Reproduce el archivo grabado por el parlante del dispositivo."""
    if not IS_PI:
        return jsonify({"ok": True, "simulated": True})
    try:
        subprocess.run(
            ["aplay", MIC_TEST_FILE],
            capture_output=True, check=True, timeout=30
        )
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "aplay no disponible en este entorno.",
                        "simulated": True})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/device/shutdown", methods=["POST"])
def api_shutdown():
    if not IS_PI:
        log.info("Apagado simulado (no es Pi).")
        return jsonify({"ok": True, "simulated": True})
    log.info("Apagando dispositivo.")
    subprocess.Popen(["sudo", "shutdown", "now"])
    return jsonify({"ok": True})


@app.route("/api/device/reboot", methods=["POST"])
def api_reboot():
    if not IS_PI:
        log.info("Reinicio simulado (no es Pi).")
        return jsonify({"ok": True, "simulated": True})
    log.info("Reiniciando dispositivo.")
    subprocess.Popen(["sudo", "reboot"])
    return jsonify({"ok": True})


@app.route("/api/device/devmode", methods=["POST"])
def api_devmode():
    """Activa modo desarrollo: desactiva hotspot y conecta al Wi-Fi de casa."""
    if not IS_PI:
        return jsonify({"ok": True, "simulated": True})
    try:
        subprocess.Popen(["sudo", "/usr/local/bin/modo-dev"])
        log.info("Modo desarrollo activado desde la interfaz.")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    if not IS_PI:
        log.info("Reinicio simulado (no es Pi).")
        return jsonify({"ok": True, "simulated": True})
    log.info("Reiniciando dispositivo.")
    subprocess.Popen(["sudo", "reboot"])
    return jsonify({"ok": True})


@app.route("/api/device/status")
def api_device_status():
    uptime_seconds = int(time.time() - SERVER_START_TIME)
    return jsonify({
        "ok": True,
        "uptime_seconds": uptime_seconds,
        "disk": _get_disk_info(),
        "is_pi": IS_PI,
        "server_time": datetime.now().strftime("%H:%M:%S"),
    })


# ─── Utilidades internas ──────────────────────────────────────────────────────

def _get_disk_info():
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            return {
                "total": parts[1],
                "used": parts[2],
                "free": parts[3],
                "percent": parts[4],
            }
    except Exception:
        pass
    return {"total": "—", "used": "—", "free": "—", "percent": "—"}


# ─── Dev helper: simular avance del pipeline ──────────────────────────────────

@app.route("/dev/simulate", methods=["POST"])
def dev_simulate():
    """Solo disponible en desarrollo. Simula el avance del pipeline."""
    global _session_state
    if not app.debug:
        abort(403)

    action = (request.get_json(silent=True, force=True) or {}).get("action", "")

    WORDS = ["pelota", "casa", "árbol", "zapato", "carro",
             "mesa", "libro", "perro", "gato", "pájaro",
             "flor", "niño", "agua", "luna", "sol",
             "mano", "pie", "nariz", "boca", "ojo"]

    if action == "playing":
        item = _session_state["current_item"]
        _session_state["status"] = "playing"
        _session_state["current_word"] = WORDS[item % len(WORDS)]

    elif action == "recording":
        _session_state["status"] = "recording"

    elif action == "no_voice":
        _session_state["status"] = "no_voice"
        _session_state["no_voice_detected"] = True

    elif action == "progress":
        if _session_state["active"]:
            _session_state["no_voice_detected"] = False
            _session_state["current_item"] = min(
                _session_state["current_item"] + 1,
                _session_state["total_items"]
            )
            item = _session_state["current_item"]
            _session_state["current_word"] = WORDS[item % len(WORDS)]
            _session_state["status"] = "playing"

    elif action == "analyzing":
        _session_state["status"] = "analyzing"
        _session_state["analysis_progress"] = 0
        _session_state["current_word"] = None

    elif action == "analysis_progress":
        _session_state["analysis_progress"] = min(
            (_session_state.get("analysis_progress") or 0) + 1,
            _session_state["total_items"]
        )

    elif action == "generating_report":
        _session_state["status"] = "generating_report"

    elif action == "paused":
        _session_state["status"] = "paused"

    elif action == "done":
        _session_state["status"] = "done"
        _session_state["results"] = {
            "score": 72,
            "level": "Desarrollo típico con áreas de atención",
            "details": [
                {"phoneme": "/r/", "score": 45, "flag": True},
                {"phoneme": "/s/", "score": 88, "flag": False},
                {"phoneme": "/l/", "score": 61, "flag": True},
                {"phoneme": "/t/", "score": 90, "flag": False},
                {"phoneme": "/p/", "score": 78, "flag": False},
            ],
        }

    return jsonify({"ok": True, "state": get_state()})


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"

    log.info("FonoScreen arrancando en %s:%d (debug=%s, pi=%s)", host, port, debug, IS_PI)
    print(f"\n  FonoScreen corriendo en http://{host}:{port}")
    print(f"  Entorno: {'Raspberry Pi' if IS_PI else 'Laptop / desarrollo'}\n")

    app.run(host=host, port=port, debug=debug, use_reloader=debug)
