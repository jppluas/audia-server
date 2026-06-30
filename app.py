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
    send_from_directory, send_file, redirect, url_for, abort
)

import db
from report_html import generate_report_html

# ─── Configuración ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
LOGS_DIR    = BASE_DIR / "logs"
RECORDINGS_DIR = BASE_DIR / "recordings"
EXPORTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
RECORDINGS_DIR.mkdir(exist_ok=True)

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

# Inicializar la base de datos (crea tablas si no existen)
db.init()

# Limpiar sesiones huérfanas de arranques anteriores
# Cualquier sesión 'active' o 'cancelled' en BD es basura — el servidor acaba de iniciar
db.purge_incomplete_sessions()

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
    global _session_state
    state = get_state()
    if state.get("status") in ("done", "error"):
        _session_state = {
            "active": False, "session_id": None, "child": {},
            "current_item": 0, "total_items": 20, "status": "idle",
            "results": None, "started_at": None,
        }
    elif state["active"] and state["status"] not in ("done", "error"):
        return redirect(url_for("session_view"))
    return render_template("register.html", state=get_state())


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    """Registra al niño e inicia una nueva sesión."""
    global _session_state

    if _session_state["active"]:
        return jsonify({"ok": False, "error": "Ya hay una sesión activa."}), 409

    # Verificar espacio en disco antes de iniciar
    if not db.has_enough_space():
        remaining = db.get_sessions_remaining()
        return jsonify({
            "ok": False,
            "error": f"Espacio insuficiente. Solo quedan {remaining} sesión(es) disponibles en disco. "
                     f"Libere espacio borrando audios desde el historial antes de continuar.",
            "low_space": True,
            "sessions_remaining": remaining,
        }), 507

    data = request.get_json(silent=True) or {}
    required = ["dob", "gender"]
    for field in required:
        if not data.get(field):
            return jsonify({"ok": False, "error": f"Campo requerido: {field}"}), 400

    session_id = str(uuid.uuid4())[:8].upper()
    _session_state = {
        "active": True,
        "session_id": session_id,
        "child": {
            "dob":    data["dob"],
            "gender": data["gender"],
            "notes":  data.get("notes", "").strip(),
            "anamnesis_otitis":         data.get("anamnesis_otitis", 0),
            "anamnesis_hearing_dx":     data.get("anamnesis_hearing_dx"),
            "anamnesis_home_language":  data.get("anamnesis_home_language", "español"),
            "anamnesis_family_history": data.get("anamnesis_family_history", 0),
            "anamnesis_family_who":     data.get("anamnesis_family_who"),
            "anamnesis_prior_therapy":  data.get("anamnesis_prior_therapy", 0),
        },
        "current_item": 0,
        "total_items": 20,
        "status": "idle",
        "current_word": None,
        "analysis_progress": 0,
        "no_voice_detected": False,
        "results": None,
        "started_at": datetime.now().isoformat(),
    }

    log.info("Sesión iniciada: %s", session_id)

    db.create_session(session_id, _session_state["child"], _session_state["started_at"])

    from pipeline import run_pipeline
    import threading
    threading.Thread(target=run_pipeline, args=(session_id, _session_state), daemon=True).start()

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
    """Cancela la sesión actual — borra BD y audios si no está finalizada."""
    global _session_state
    old_id = _session_state.get("session_id")
    status = _session_state.get("status")

    # Si la sesión no está finalizada, borrar completamente
    if old_id and _session_state.get("active") and status != "done":
        try:
            db.delete_session(old_id)
        except Exception as e:
            log.warning("No se pudo borrar sesión cancelada: %s", e)

    # Siempre resetear el estado en memoria
    _session_state = {
        "active": False, "session_id": None, "child": {},
        "current_item": 0, "total_items": 20, "status": "idle",
        "results": None, "started_at": None,
    }
    log.info("Sesión %s reseteada (status previo: %s).", old_id, status)
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
    sessions_remaining = db.get_sessions_remaining()
    low_space = sessions_remaining >= 0 and sessions_remaining < db.MIN_FREE_SESSIONS
    return render_template("device.html",
                           uptime=uptime_str,
                           disk=disk_info,
                           is_pi=IS_PI,
                           sessions_remaining=sessions_remaining,
                           low_space=low_space,
                           min_free_sessions=db.MIN_FREE_SESSIONS)


@app.route("/api/device/volume", methods=["POST"])
def api_set_volume():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level is None or not (0 <= int(level) <= 100):
        return jsonify({"ok": False, "error": "Nivel inválido (0-100)."}), 400
    level = int(level)
    try:
        # wpctl funciona con PipeWire en Pi y laptop
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"],
            capture_output=True, check=True
        )
        log.info("Volumen ajustado a %d%%", level)
        return jsonify({"ok": True, "level": level})
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning("wpctl falló: %s", e)
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/device/volume", methods=["GET"])
def api_get_volume():
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True, text=True, check=True
        )
        # Output: "Volume: 0.80"
        import re
        match = re.search(r"[\d.]+", result.stdout)
        level = int(float(match.group()) * 100) if match else 80
        return jsonify({"ok": True, "level": level})
    except Exception as e:
        log.warning("No se pudo leer volumen: %s", e)
        return jsonify({"ok": True, "level": 80, "simulated": True})


@app.route("/api/device/mic/volume", methods=["GET"])
def api_get_mic_volume():
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            capture_output=True, text=True, check=True
        )
        import re
        match = re.search(r"[\d.]+", result.stdout)
        level = int(float(match.group()) * 100) if match else 80
        return jsonify({"ok": True, "level": level})
    except Exception as e:
        log.warning("No se pudo leer volumen de micrófono: %s", e)
        return jsonify({"ok": True, "level": 80, "simulated": True})


@app.route("/api/device/mic/volume", methods=["POST"])
def api_set_mic_volume():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level is None or not (0 <= int(level) <= 100):
        return jsonify({"ok": False, "error": "Nivel inválido (0-100)."}), 400
    level = int(level)
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{level}%"],
            capture_output=True, check=True
        )
        log.info("Volumen de micrófono ajustado a %d%%", level)
        return jsonify({"ok": True, "level": level})
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning("wpctl mic falló: %s", e)
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/device/tone", methods=["POST"])
def api_tone():
    """Reproduce un tono de prueba — usa pw-play con PipeWire."""
    try:
        import struct, math
        sample_rate = 44100
        n_samples = int(sample_rate * 1.5)
        freq = 1000
        tone_file = "/tmp/fonoscreen_tone.wav"
        with open(tone_file, "wb") as f:
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
        subprocess.run(["pw-play", tone_file],
                       capture_output=True, check=True, timeout=5)
        return jsonify({"ok": True})
    except Exception as e:
        log.warning("Tono falló: %s", e)
        return jsonify({"ok": False, "error": str(e)})


# Globals para grabación de prueba
_mic_process = None
_mic_stream   = None
_mic_frames   = []
MIC_TEST_FILE = "/tmp/fonoscreen_mic_test.wav"


@app.route("/api/device/mic/start", methods=["POST"])
def api_mic_start():
    """Inicia grabación de prueba con pw-record (PipeWire)."""
    global _mic_process
    if _mic_process:
        try:
            _mic_process.terminate()
        except Exception:
            pass
    try:
        _mic_process = subprocess.Popen(
            ["pw-record", MIC_TEST_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log.info("Grabación iniciada con pw-record, PID %s", _mic_process.pid)
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "pw-record no disponible."})


@app.route("/api/device/mic/stop", methods=["POST"])
def api_mic_stop():
    """Detiene la grabación en curso."""
    global _mic_process
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
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/device/mic/play", methods=["POST"])
def api_mic_play():
    """Reproduce el archivo grabado con pw-play (PipeWire)."""
    try:
        if not Path(MIC_TEST_FILE).exists():
            return jsonify({"ok": False, "error": "No hay grabación disponible."})
        subprocess.run(
            ["pw-play", MIC_TEST_FILE],
            capture_output=True, check=True, timeout=30
        )
        return jsonify({"ok": True})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
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


# ── Historial y pruebas de BD ─────────────────────────────────────────────────

@app.route("/historial")
def historial():
    """Pantalla de historial de sesiones — lectura y pruebas de la BD."""
    sessions = db.list_sessions(limit=50)
    return render_template("historial.html", sessions=sessions)


@app.route("/api/historial/sessions")
def api_historial_sessions():
    """Lista las últimas 50 sesiones."""
    return jsonify({"ok": True, "sessions": db.list_sessions(50)})


@app.route("/api/historial/session/<session_id>")
def api_historial_session(session_id):
    """Devuelve la exportación completa de una sesión (todas las tablas)."""
    data = db.export_session(session_id)
    if not data:
        return jsonify({"ok": False, "error": "Sesión no encontrada."}), 404
    return jsonify({"ok": True, **data})


@app.route("/api/historial/seed", methods=["POST"])
def api_historial_seed():
    """Inserta una sesión de prueba completa. Solo disponible en desarrollo."""
    if not app.debug:
        abort(403)
    try:
        sid = db.seed_test_session()
        return jsonify({"ok": True, "session_id": sid})
    except Exception as e:
        log.warning("seed_test_session falló: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/historial/session/<session_id>", methods=["DELETE"])
def api_historial_delete(session_id):
    """Elimina completamente una sesión: BD + audios."""
    try:
        import shutil
        # Borrar audios
        audio_folder = RECORDINGS_DIR / session_id
        if audio_folder.exists():
            shutil.rmtree(audio_folder, ignore_errors=True)
        # Borrar de la BD
        with db._connect() as conn:
            conn.execute("DELETE FROM reports WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM phoneme_summary WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM items WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        log.info("Sesión %s eliminada completamente.", session_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/historial/session/<session_id>/delete-audio", methods=["POST"])
def api_historial_delete_audio(session_id):
    """Elimina solo los audios de una sesión, conserva el resultado en BD."""
    try:
        existed = db.delete_audio_files(session_id)
        log.info("Audios de sesión %s eliminados (existían: %s).", session_id, existed)
        return jsonify({"ok": True, "had_audio": existed})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/historial/session/<session_id>/audio/<word>")
def api_historial_audio(session_id, word):
    """Sirve el WAV de una palabra para reproducción inline en el historial."""
    # Normalizar por si la URL llega con o sin tilde
    audio_path = db.get_audio_path(session_id, word)
    if not audio_path:
        # Intentar también con la palabra ya normalizada (por si el cliente envió con tilde)
        audio_path = db.get_audio_path(session_id, db._normalize_word(word))
    if not audio_path:
        abort(404)
    return send_file(audio_path, mimetype="audio/wav")


@app.route("/api/historial/session/<session_id>/export-zip")
def api_historial_export_zip(session_id):
    """
    Exporta la sesión completa como ZIP:
      - fonoscreen_<id>.json        — datos completos
      - informe_<nombre>_<id>.pdf   — generado en memoria con weasyprint
      - audios/<id>_<palabra>.wav   — si existen en disco
    Nada se escribe en disco en el servidor.
    """
    import zipfile
    import io

    data = db.export_session(session_id)
    if not data:
        return jsonify({"ok": False, "error": "Sesión no encontrada."}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # 1. JSON
        zf.writestr(
            f"fonoscreen_{session_id}.json",
            json.dumps(data, indent=2, ensure_ascii=False)
        )

        # 2. PDF generado en memoria con weasyprint
        try:
            from weasyprint import HTML as WP_HTML
            html_str = generate_report_html(data)
            pdf_bytes = WP_HTML(string=html_str).write_pdf()
            zf.writestr(f"informe_{session_id}.pdf", pdf_bytes)
        except Exception as e:
            log.warning("weasyprint falló al generar PDF para ZIP: %s", e)
            zf.writestr(
                "informe_ERROR.txt",
                f"No se pudo generar el PDF: {e}\n"
                f"Instalar dependencias: sudo apt install -y "
                f"libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 "
                f"libharfbuzz-subset0 libffi-dev libjpeg-dev libopenjp2-7-dev"
            )

        # 3. Audios si existen
        audio_folder = RECORDINGS_DIR / session_id
        if audio_folder.exists():
            for wav in sorted(audio_folder.glob("*.wav")):
                zf.write(wav, f"audios/{wav.name}")

    buf.seek(0)
    filename = f"fonoscreen_{session_id}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename
    )


@app.route("/api/historial/session/<session_id>/report-html")
def api_historial_report_html(session_id):
    """Devuelve el HTML del informe. ?tipo=representantes muestra solo nota para padres."""
    data = db.export_session(session_id)
    if not data:
        return jsonify({"ok": False, "error": "Sesión no encontrada."}), 404
    tipo = request.args.get("tipo", "clinico")
    html = generate_report_html(data, tipo=tipo)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/device/space")
def api_device_space():
    """Devuelve espacio libre y sesiones restantes estimadas."""
    remaining = db.get_sessions_remaining()
    return jsonify({
        "ok": True,
        "free_mb": db.get_disk_free_mb(),
        "sessions_remaining": remaining,
        "low_space": remaining >= 0 and remaining < db.MIN_FREE_SESSIONS,
        "min_free_sessions": db.MIN_FREE_SESSIONS,
        "session_size_mb": db.SESSION_AUDIO_MB,
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
