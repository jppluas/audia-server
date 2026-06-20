import os
import time
import traceback
import soundfile as sf
import sounddevice as sd
from pathlib import Path
import db
from motor_ia import MotorFonologico

motor = MotorFonologico()
BASE_DIR = Path(__file__).resolve().parent
AUDIOS_DIR = BASE_DIR / "audios"

BATERIA = [
    ("/m/", "mamá"), 
    ("/t/", "taza"), 
    ("/g/", "gato")
]

def run_pipeline(session_id, state): 
    try:
        state["total_items"] = len(BATERIA)
        folder_path = db.get_recordings_dir(session_id)
        folder_path.mkdir(parents=True, exist_ok=True)
        resultados_items = []

        for i, (fonema, palabra) in enumerate(BATERIA):
            while state.get("status") == "paused": time.sleep(1)
            
            # CORRECCIÓN: Solo abortar si se canceló explícitamente o si la sesión cambió
            if state.get("status") == "cancelled" or state.get("session_id") != session_id:
                print(f"[{session_id}] Sesión abortada por el usuario.")
                return
            
            state["current_item"] = i + 1
            state["current_word"] = palabra
            state["status"] = "playing"
            
            nombre_limpio = db._normalize_word(palabra)
            ruta_audio = AUDIOS_DIR / f"{nombre_limpio}.wav"
            
            if ruta_audio.exists():
                data, fs = sf.read(str(ruta_audio))
                sd.play(data, fs)
                duracion = len(data) / fs
                pasos = int(duracion * 10) + 5
                for _ in range(pasos):
                    time.sleep(0.1)
                    if state.get("status") == "cancelled" or state.get("session_id") != session_id:
                        sd.stop()
                        return
            else:
                print(f"⚠️ ALERTA: Falta el archivo: {ruta_audio}")
                time.sleep(2)
            
            if state.get("status") == "cancelled" or state.get("session_id") != session_id: return
            
            state["status"] = "recording"
            res, audio_np = motor.capturar_y_evaluar(palabra, fonema)
            
            if state.get("status") == "cancelled" or state.get("session_id") != session_id: return
            
            item_data = {
                "item_index": i, "phoneme": fonema, "word_expected": palabra,
                "word_produced": None, "audio_path": None, "result": "not_evaluable",
                "error_type": None, "pff": 0.0, "alignment": None
            }

            if res is not None:
                filename = db.audio_filename(session_id, palabra)
                sf.write(str(folder_path / filename), audio_np, 16000)
                item_data.update({
                    "word_produced": res["word_produced"], "audio_path": f"{session_id}/{filename}",
                    "result": res["result"], "error_type": res["error_type"],
                    "pff": res["pff"], "alignment": res["alignment"]
                })
                
            resultados_items.append(item_data)
            db.save_item(session_id, item_data)

        if state.get("status") == "cancelled" or state.get("session_id") != session_id: return

        # === FASE FINAL ===
        state["status"] = "analyzing"
        state["current_word"] = None
        
        agrupado = {}
        for item in resultados_items:
            if item["result"] != "not_evaluable":
                agrupado.setdefault(item["phoneme"], []).append(item)
                
        pff_por_fonema = []
        for fon, items in agrupado.items():
            promedio = sum(x["pff"] for x in items) / len(items) if items else 0
            nivel = "Normal" if promedio > 75 else "Seguimiento activo" if promedio >= 50 else "Atención requerida"
            errores = [x["error_type"] for x in items if x["error_type"]]
            predominante = max(set(errores), key=errores.count) if errores else "Ninguno"
            
            db.save_phoneme_summary(session_id, {"phoneme": fon, "pff": promedio, "level": nivel, "error_predominant": predominante})
            pff_por_fonema.append((fon, promedio, predominante))

        pffb_global = sum(p[1] for p in pff_por_fonema) / len(pff_por_fonema) if pff_por_fonema else 0
        nivel_global = "Normal" if pffb_global > 75 else "Seguimiento activo" if pffb_global >= 50 else "Atención requerida"
        
        db.close_session(session_id, pffb_global, nivel_global)

        state["status"] = "generating_report"
        
        nota_c = f"NOTA CLÍNICA AUTOMÁTICA: El paciente finalizó la evaluación con un PFFB global de {pffb_global:.1f}% ({nivel_global}). Se registraron los siguientes desempeños por fonema: {pff_por_fonema}."
        nota_r = f"INFORME PARA PADRES: Su niño(a) completó la prueba interactiva de pronunciación obteniendo un puntaje general de {pffb_global:.1f}%."

        db.save_report(session_id, {"nota_clinica": nota_c, "nota_representantes": nota_r})
        
        state["results"] = {
            "score": round(pffb_global, 1),
            "level": nivel_global
        }
        
        state["status"] = "done"
    except Exception as e:
        print(f"\n❌ ERROR CRÍTICO EN EL PIPELINE: {e}")
        traceback.print_exc()
        state["status"] = "error"
        db.close_session(session_id, 0.0, "Error del Sistema")