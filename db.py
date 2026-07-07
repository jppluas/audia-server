"""
Audia — db.py
Capa de persistencia SQLite.

Tablas:
  sessions        — una fila por sesión (niño, anamnesis, PFFB, nivel, estado)
  items           — una fila por palabra evaluada (20 por sesión)
  phoneme_summary — una fila por fonema evaluado (10 por sesión)
  reports         — una fila por sesión (textos Gemma)

Nomenclatura de audios: recordings/<session_id>/<session_id>_<palabra>.wav
  Ej: recordings/A1B2C3D4/A1B2C3D4_mama.wav

has_audio se calcula dinámicamente desde disco — no se guarda en BD.

Uso desde app.py:
  import db
  db.init()
  db.create_session(session_id, child_data, started_at)
  db.close_session(session_id, pffb, level)

Uso desde pipeline.py (Daniel):
  import db
  db.save_item(session_id, item_data)
  db.save_phoneme_summary(session_id, phoneme_data)
  db.save_report(session_id, report_data)
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent / "audia.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    """Crea las tablas si no existen. Llamar una vez al arrancar Flask."""
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            child_dob           TEXT NOT NULL,
            child_gender        TEXT NOT NULL,
            child_age_months    INTEGER,
            notes               TEXT,
            anamnesis_otitis          INTEGER DEFAULT 0,
            anamnesis_hearing_dx      TEXT,
            anamnesis_home_language   TEXT,
            anamnesis_family_history  INTEGER DEFAULT 0,
            anamnesis_prior_therapy   INTEGER DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'active',
            pffb                REAL,
            level               TEXT,
            started_at          TEXT NOT NULL,
            finished_at         TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL REFERENCES sessions(session_id),
            item_index      INTEGER NOT NULL,
            phoneme         TEXT NOT NULL,
            word_expected   TEXT NOT NULL,
            word_produced   TEXT,
            audio_path      TEXT,
            result          TEXT NOT NULL DEFAULT 'pending',
            error_type      TEXT,
            pff             REAL,
            alignment_json  TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS phoneme_summary (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL REFERENCES sessions(session_id),
            phoneme             TEXT NOT NULL,
            pff                 REAL NOT NULL,
            level               TEXT NOT NULL,
            error_predominant   TEXT,
            UNIQUE(session_id, phoneme)
        );

        CREATE TABLE IF NOT EXISTS reports (
            session_id          TEXT PRIMARY KEY REFERENCES sessions(session_id),
            nota_clinica        TEXT,
            nota_representantes TEXT,
            generated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_items_session    ON items(session_id);
        CREATE INDEX IF NOT EXISTS idx_phoneme_session  ON phoneme_summary(session_id);
        """)
        # Migración: quitar columnas de versiones anteriores si existen
        # (audio_deleted, pdf_tecnico, pdf_representantes ya no se usan)
        # SQLite no permite DROP COLUMN antes de 3.35 — ignoramos silenciosamente


# ─── sessions ─────────────────────────────────────────────────────────────────

def create_session(session_id: str, child: dict, started_at: str):
    """
    Crea una fila en sessions al iniciar la evaluación.
    child = {"dob", "gender", "notes",
             "anamnesis_otitis", "anamnesis_hearing_dx",
             "anamnesis_home_language", "anamnesis_family_history",
             "anamnesis_family_who", "anamnesis_prior_therapy"}
    """
    age_months = None
    try:
        from datetime import date
        dob = date.fromisoformat(child["dob"])
        today = date.today()
        age_months = (today.year - dob.year) * 12 + (today.month - dob.month)
    except Exception:
        pass

    anamnesis_parts = []
    if child.get("anamnesis_otitis"):
        anamnesis_parts.append("Historial de otitis: sí")
    if child.get("anamnesis_hearing_dx"):
        anamnesis_parts.append(f"Diagnóstico auditivo: {child['anamnesis_hearing_dx']}")
    if child.get("anamnesis_home_language") and child["anamnesis_home_language"] not in ("español", "Español"):
        anamnesis_parts.append(f"Idioma en el hogar: {child['anamnesis_home_language']}")
    if child.get("anamnesis_family_history"):
        quien = child.get("anamnesis_family_who") or "no especificado"
        anamnesis_parts.append(f"Antecedentes familiares: sí ({quien})")
    if child.get("anamnesis_prior_therapy"):
        anamnesis_parts.append("Terapia de lenguaje previa: sí")
    if child.get("notes"):
        anamnesis_parts.append(f"Obs: {child['notes']}")
    notes_combined = " | ".join(anamnesis_parts) if anamnesis_parts else child.get("notes", "")

    with _connect() as conn:
        conn.execute("""
            INSERT INTO sessions
                (session_id, child_dob, child_gender, child_age_months,
                 notes, anamnesis_otitis, anamnesis_hearing_dx, anamnesis_home_language,
                 anamnesis_family_history, anamnesis_prior_therapy, started_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (
            session_id,
            child.get("dob", ""),
            child.get("gender", ""),
            age_months,
            notes_combined,
            int(child.get("anamnesis_otitis", 0) or 0),
            child.get("anamnesis_hearing_dx"),
            child.get("anamnesis_home_language", "Español"),
            int(child.get("anamnesis_family_history", 0) or 0),
            int(child.get("anamnesis_prior_therapy", 0) or 0),
            started_at,
        ))


def close_session(session_id: str, pffb: float, level: str):
    with _connect() as conn:
        conn.execute("""
            UPDATE sessions SET status='done', pffb=?, level=?, finished_at=?
            WHERE session_id=?
        """, (pffb, level, datetime.now().isoformat(), session_id))


def purge_incomplete_sessions():
    """
    Elimina sesiones 'active' o 'cancelled' de la BD junto con sus audios.
    Se llama al arrancar Flask — estas sesiones son basura de reinicios anteriores.
    """
    import shutil
    with _connect() as conn:
        rows = conn.execute(
            "SELECT session_id FROM sessions WHERE status IN ('active', 'cancelled')"
        ).fetchall()
        for r in rows:
            sid = r["session_id"]
            # Borrar audios si existen
            audio_dir = get_recordings_dir(sid)
            if audio_dir.exists():
                shutil.rmtree(audio_dir, ignore_errors=True)
            # Borrar de BD en cascada
            conn.execute("DELETE FROM reports           WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM phoneme_summary   WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM items             WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM sessions          WHERE session_id=?", (sid,))
        if rows:
            import logging
            logging.getLogger("audia").info(
                "Purged %d incomplete session(s) on startup.", len(rows)
            )


def delete_session(session_id: str):
    """Elimina completamente una sesión: BD + audios en disco."""
    import shutil
    audio_dir = get_recordings_dir(session_id)
    if audio_dir.exists():
        shutil.rmtree(audio_dir, ignore_errors=True)
    with _connect() as conn:
        conn.execute("DELETE FROM reports           WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM phoneme_summary   WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM items             WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions          WHERE session_id=?", (session_id,))


def get_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None


def list_sessions(limit: int = 50) -> list[dict]:
    """Lista las últimas sesiones finalizadas. has_audio se calcula desde disco."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT session_id, child_dob, child_gender,
                   child_age_months, status, pffb, level, started_at, finished_at
            FROM sessions WHERE status = 'done'
            ORDER BY started_at DESC LIMIT ?
        """, (limit,)).fetchall()
        sessions = []
        for r in rows:
            d = dict(r)
            d["has_audio"] = _has_audio(d["session_id"])
            sessions.append(d)
        return sessions


# ─── items ────────────────────────────────────────────────────────────────────

def save_item(session_id: str, item: dict):
    """
    item = {
        "item_index": int,
        "phoneme": str,
        "word_expected": str,
        "word_produced": str | None,
        "audio_path": str | None,   # relativo a recordings/
        "result": str,              # correct | error | not_evaluable
        "error_type": str | None,
        "pff": float | None,
        "alignment": list | None,
    }
    """
    alignment_json = json.dumps(item.get("alignment"), ensure_ascii=False) \
        if item.get("alignment") is not None else None

    with _connect() as conn:
        conn.execute("""
            INSERT INTO items
                (session_id, item_index, phoneme, word_expected, word_produced,
                 audio_path, result, error_type, pff, alignment_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, (
            session_id,
            item["item_index"],
            item["phoneme"],
            item["word_expected"],
            item.get("word_produced"),
            item.get("audio_path"),
            item.get("result", "pending"),
            item.get("error_type"),
            item.get("pff"),
            alignment_json,
        ))


def get_items(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE session_id=? ORDER BY item_index", (session_id,)
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            if d.get("alignment_json"):
                try:
                    d["alignment"] = json.loads(d["alignment_json"])
                except Exception:
                    d["alignment"] = None
            else:
                d["alignment"] = None
            items.append(d)
        return items


# ─── phoneme_summary ──────────────────────────────────────────────────────────

def save_phoneme_summary(session_id: str, phoneme_data: dict):
    with _connect() as conn:
        conn.execute("""
            INSERT INTO phoneme_summary (session_id, phoneme, pff, level, error_predominant)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, phoneme) DO UPDATE SET
                pff=excluded.pff, level=excluded.level,
                error_predominant=excluded.error_predominant
        """, (
            session_id,
            phoneme_data["phoneme"],
            phoneme_data["pff"],
            phoneme_data["level"],
            phoneme_data.get("error_predominant", "Ninguno"),
        ))


def get_phoneme_summary(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM phoneme_summary WHERE session_id=? ORDER BY phoneme", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── reports ──────────────────────────────────────────────────────────────────

def save_report(session_id: str, report: dict):
    """
    report = {
        "nota_clinica": str,
        "nota_representantes": str,
    }
    Los PDFs ya no se guardan en BD — se generan en memoria al exportar.
    """
    with _connect() as conn:
        conn.execute("""
            INSERT INTO reports (session_id, nota_clinica, nota_representantes)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                nota_clinica=excluded.nota_clinica,
                nota_representantes=excluded.nota_representantes,
                generated_at=datetime('now')
        """, (
            session_id,
            report.get("nota_clinica"),
            report.get("nota_representantes"),
        ))


def get_report(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None


# ─── audios — solo disco, sin BD ──────────────────────────────────────────────

# Peor caso: 44.1kHz estéreo, 8s × 20 ítems
SESSION_AUDIO_MB  = 28
MIN_FREE_SESSIONS = 10
RECORDINGS_DIR    = Path(__file__).resolve().parent / "recordings"


def get_recordings_dir(session_id: str) -> Path:
    return RECORDINGS_DIR / session_id


def _normalize_word(word: str) -> str:
    """Quita tildes y pasa a minúsculas para nombres de archivo seguros."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def audio_filename(session_id: str, word: str) -> str:
    """Nomenclatura estándar: <session_id>_<palabra_normalizada>.wav
    Ej: A1B2C3D4_mama.wav, A1B2C3D4_cafe.wav
    """
    return f"{session_id}_{_normalize_word(word)}.wav"


def _has_audio(session_id: str) -> bool:
    """True si la carpeta existe y contiene al menos un WAV."""
    folder = get_recordings_dir(session_id)
    return folder.exists() and any(folder.glob("*.wav"))


def get_audio_path(session_id: str, word: str) -> Path | None:
    """Devuelve la ruta al WAV de una palabra, o None si no existe."""
    path = get_recordings_dir(session_id) / audio_filename(session_id, word)
    return path if path.exists() else None


def get_audio_size_mb(session_id: str) -> float:
    folder = get_recordings_dir(session_id)
    if not folder.exists():
        return 0.0
    total = sum(f.stat().st_size for f in folder.glob("*.wav"))
    return round(total / (1024 * 1024), 2)


def delete_audio_files(session_id: str) -> bool:
    """Elimina la carpeta de grabaciones. Devuelve True si había archivos."""
    import shutil
    folder = get_recordings_dir(session_id)
    existed = folder.exists() and any(folder.glob("*.wav"))
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return existed


def get_disk_free_mb() -> float:
    import shutil
    usage = shutil.disk_usage(Path(__file__).resolve().parent)
    return round(usage.free / (1024 * 1024), 1)


def get_sessions_remaining() -> int:
    try:
        return int(get_disk_free_mb() // SESSION_AUDIO_MB)
    except Exception:
        return -1


def has_enough_space() -> bool:
    remaining = get_sessions_remaining()
    return remaining < 0 or remaining >= MIN_FREE_SESSIONS


# ─── exportación completa ─────────────────────────────────────────────────────

def export_session(session_id: str) -> dict | None:
    session = get_session(session_id)
    if not session:
        return None
    session["has_audio"] = _has_audio(session_id)
    return {
        "session":         session,
        "items":           get_items(session_id),
        "phoneme_summary": get_phoneme_summary(session_id),
        "report":          get_report(session_id),
    }


# ─── seed de prueba ───────────────────────────────────────────────────────────

def seed_test_session() -> str:
    """
    Sesión de prueba basada en la batería fonológica real de Audia.
    Palabras, fonemas y resultados son coherentes con la evaluación manual
    de los audios de prueba (bien%, silencio, tipo de error).
    Devuelve el session_id.
    """
    import uuid

    sid = str(uuid.uuid4())[:8].upper()
    started = datetime.now().isoformat()

    create_session(sid, {
        "dob":                      "2021-03-15",
        "gender":                   "M",
        "notes":                    "Sesión de prueba generada desde el panel de historial.",
        "anamnesis_otitis":         1,
        "anamnesis_hearing_dx":     "Hipoacusia conductiva leve",
        "anamnesis_home_language":  "Español",
        "anamnesis_family_history": 1,
        "anamnesis_family_who":     "Padre",
        "anamnesis_prior_therapy":  0,
    }, started)

    # Batería: (fonema, palabra_esperada, resultado, tipo_error, pff, transcripcion)
    # pff individual: 100=correct, 85=error leve, 50=error, 0=not_evaluable
    BATTERY = [
        # /m/ — nasal bilabial
        ("/m/", "mamá",   "correct",       None,           100.0, "mama"),
        ("/m/", "cama",   "error",         "Sustitución",   85.0, "kana"),
        # /p/ — oclusiva bilabial sorda
        ("/p/", "papá",   "correct",       None,           100.0, "papa"),
        ("/p/", "sopa",   "error",         "Omisión",       50.0, "soa"),
        # /b/ — oclusiva bilabial sonora
        ("/b/", "boca",   "error",         "Sustitución",   50.0, "poka"),
        ("/b/", "abeja",  "error",         "Sustitución",   85.0, "abecha"),
        # /t/ — oclusiva dental sorda
        ("/t/", "taza",   "error",         "Sustitución",   50.0, "dasa"),
        ("/t/", "gato",   "error",         "Sustitución",   85.0, "gado"),
        # /d/ — oclusiva dental sonora
        ("/d/", "dedo",   "error",         "Omisión",       50.0, "eeo"),
        ("/d/", "helado", "error",         "Sustitución",   85.0, "helato"),
        # /k/ — oclusiva velar sorda
        ("/k/", "casa",   "error",         "Sustitución",   50.0, "tasa"),
        ("/k/", "vaca",   "error",         "Sustitución",   85.0, "baka"),
        # /g/ — oclusiva velar sonora
        ("/g/", "gato",   "error",         "Sustitución",   85.0, "dato"),
        ("/g/", "agua",   "correct",       None,           100.0, "agua"),
        # /f/ — fricativa labiodental
        ("/f/", "foco",   "error",         "Sustitución",   85.0, "poko"),
        ("/f/", "café",   "error",         "Sustitución",   85.0, "cape"),
        # /n/ — nasal alveolar
        ("/n/", "nariz",  "not_evaluable", None,             0.0, None),
        ("/n/", "mano",   "error",         "Sustitución",   85.0, "mano"),
        # /l/ — lateral alveolar
        ("/l/", "luna",   "error",         "Omisión",       50.0, "una"),
        ("/l/", "pelota", "not_evaluable", None,             0.0, None),
    ]

    for i, (phoneme, word_expected, result, error_type, pff, word_produced) \
            in enumerate(BATTERY):
        audio_path = f"{sid}/{audio_filename(sid, word_expected)}" \
            if result != "not_evaluable" else None
        save_item(sid, {
            "item_index":    i,
            "phoneme":       phoneme,
            "word_expected": word_expected,
            "word_produced": word_produced,
            "audio_path":    audio_path,
            "result":        result,
            "error_type":    error_type,
            "pff":           pff,
            "alignment":     None,
        })

    # PFF por fonema: promedio de los dos ítems de cada fonema
    PHONEMES = [
        ("/m/", round((100 + 85)  / 2, 1), "Normal", "Sustitución"),
        ("/p/", round((100 + 50)  / 2, 1), "Normal", "Omisión"),
        ("/b/", round((50  + 85)  / 2, 1), "Bajo",   "Sustitución"),
        ("/t/", round((50  + 85)  / 2, 1), "Bajo",   "Sustitución"),
        ("/d/", round((50  + 85)  / 2, 1), "Bajo",   "Sustitución"),
        ("/k/", round((50  + 85)  / 2, 1), "Bajo",   "Sustitución"),
        ("/g/", round((85  + 100) / 2, 1), "Normal", "Sustitución"),
        ("/f/", round((85  + 85)  / 2, 1), "Normal", "Sustitución"),
        ("/n/", round((0   + 85)  / 2, 1), "Bajo",   "Omisión"),
        ("/l/", round((50  + 0)   / 2, 1), "Bajo",   "Omisión"),
    ]
    for phoneme, pff, level, error_predominant in PHONEMES:
        save_phoneme_summary(sid, {
            "phoneme":           phoneme,
            "pff":               pff,
            "level":             level,
            "error_predominant": error_predominant,
        })

    pffb = round(sum(p[1] for p in PHONEMES) / len(PHONEMES), 1)
    # Nivel según PFFB
    level = "Normal" if pffb > 75 else "Seguimiento activo" if pffb >= 50 else "Atención requerida"
    close_session(sid, pffb, level)

    save_report(sid, {
        "nota_clinica": (
            f"John Doe presenta un PFFB de {pffb}%, con dificultades en fonemas oclusivos "
            "(/b/, /t/, /d/, /k/) y laterales (/l/), donde se observan patrones de sustitución "
            "y omisión que requieren atención. Los fonemas nasales (/m/, /n/) muestran rendimiento "
            "variable. Se recomienda evaluación fonoaudiológica completa para determinar plan de intervención."
        ),
        "nota_representantes": (
            "Evaluamos cómo su niño pronuncia los sonidos del español. "
            "Encontramos algunas dificultades en varios sonidos, especialmente al pronunciar "
            "ciertos sonidos en el medio de las palabras. "
            "Se recomienda consultar con un especialista de lenguaje para una evaluación más detallada."
        ),
    })

    return sid
